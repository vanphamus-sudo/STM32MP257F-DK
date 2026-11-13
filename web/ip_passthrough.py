"""Exclusive routed IPv4 handoff from a netifd/MBIM uplink to one Ethernet MAC.

The cellular address is removed from the host and routed to the client, so
neither DNAT, SNAT nor a USB-mode change is required. A journal is written before
changing live state. Callers hold router_features.locked().
"""
import ipaddress
import gzip
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import time

import router_features as features

ROOT = Path('/tmp/router-passthrough')
GATEWAY = '192.168.40.1'
NETWORK = ipaddress.IPv4Network('192.168.40.0/24')
NFT_TABLE = 'router_passthrough'
OWNED = dict(network=['rf_passthrough'], firewall=['rf_passthrough', 'rf_pass_out',
              'rf_pass_in', 'rf_pass_dhcp'])


def safe_root(create=False):
    if not ROOT.exists() and not ROOT.is_symlink():
        if not create:
            return False
        ROOT.mkdir(parents=True, mode=0o700)
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise RuntimeError('Passthrough runtime path is not a private directory.')
    metadata = ROOT.stat()
    if os.name == 'posix' and (metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022):
        raise RuntimeError('Passthrough runtime directory has unsafe ownership or permissions.')
    return True


def device(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,15}', value):
        raise ValueError('Passthrough requires a dedicated physical Ethernet device.')
    return value


def validate(data):
    if not isinstance(data, dict) or set(data) != {'enabled', 'client_mac'} or type(data['enabled']) is not bool:
        raise ValueError('Supply passthrough state and the downstream client MAC address.')
    mac = data['client_mac']
    if not isinstance(mac, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', mac):
        if not data['enabled'] and mac == '':
            return dict(enabled=False, client_mac='')
        raise ValueError('Enter the downstream router Ethernet WAN MAC address.')
    if int(mac[:2], 16) & 1 or mac.lower() == '00:00:00:00:00:00':
        raise ValueError('Use a unicast Ethernet MAC address.')
    return dict(enabled=data['enabled'], client_mac=mac.lower())


def available():
    import shutil
    return all(shutil.which(name) for name in ('ip', 'nft', 'dnsmasq', 'conntrack'))


def preflight(settings, backend, all_settings):
    """Refuse combinations that would make an exclusive address handoff unsafe."""
    net, fw = backend.values('network'), backend.values('firewall')
    if not settings['enabled']:
        return
    if not available():
        raise ValueError('Install ip-full, nftables, dnsmasq and conntrack before using passthrough.')
    if net.get('router_ethernet', {}).get('mode', 'lan') != 'lan' or 'ethernet_wan' in net:
        raise ValueError('Set Ethernet to LAN mode before enabling passthrough.')
    ports = net.get('lan_bridge', {}).get('ports', [])
    ports = [ports] if isinstance(ports, str) else ports
    active = net.get('rf_passthrough', {})
    ethernet = net.get('router_ethernet', {}).get('device') or (ports[0] if len(ports) == 1 else active.get('device'))
    device(ethernet)
    if not active and ports != [ethernet]:
        raise ValueError('Passthrough requires one dedicated untagged Ethernet LAN port.')
    management = net.get('management', {})
    if management.get('ipaddr') != '192.168.7.1' or not management.get('device'):
        raise ValueError('Configure and verify USB management at 192.168.7.1 first.')
    usb = backend.ubus('network.interface.management', 'status')
    if not usb.get('up') or not any(a.get('address') == '192.168.7.1' for a in usb.get('ipv4-address', [])):
        raise ValueError('USB management must be up at 192.168.7.1 before passthrough.')
    if any(all_settings[name]['enabled'] for name in ('watchdog', 'failover', 'wireguard', 'guest', 'ipv6')):
        raise ValueError('Disable watchdog, failover, WireGuard, guest VLAN and IPv6 before passthrough.')
    if net.get('wan', {}).get('iptype', 'ipv4') != 'ipv4':
        raise ValueError('Passthrough supports an IPv4-only LTE bearer.')
    if fw.get('wan', {}).get('masq', '0') != ('0' if active else '1'):
        raise ValueError('Restore the dedicated WAN masquerading configuration before passthrough.')
    if any(v.get('.type') in ('redirect', 'nat') and v.get('enabled', '1') != '0' for v in fw.values()):
        raise ValueError('Disable port forwards, DMZ and custom NAT rules before passthrough.')
    if backend.values('openvpn').get('router_vpn', {}).get('enabled', '0') == '1':
        raise ValueError('Disable the router OpenVPN client before passthrough.')
    defaults = [v for v in fw.values() if v.get('.type') == 'defaults'] + [fw.get('defaults', {})]
    if any(v.get('flow_offloading', '0') == '1' or v.get('flow_offloading_hw', '0') == '1' for v in defaults):
        raise ValueError('Disable firewall flow offloading before passthrough so every packet passes the client guard.')
    rules = policy_rules()
    if any((int(r.get('priority', -1)), str(r.get('table'))) not in
           ((0, 'local'), (32766, 'main'), (32767, 'default')) for r in rules):
        raise ValueError('Disable custom IPv4 policy routing and wait for failover rules to clear before passthrough.')
    connected = lease(backend)
    if not connected:
        raise ValueError('Connect LTE before enabling passthrough.')
    # Verify the kernel conntrack interface before touching persistent networking.
    features.execute('conntrack', '-L', '-f', 'ipv4', '--orig-src', connected['address'])
    for name, value in net.items():
        if name == 'rf_passthrough' or not value.get('ipaddr'):
            continue
        addresses = value['ipaddr'] if isinstance(value['ipaddr'], list) else [value['ipaddr']]
        for address in addresses:
            try:
                prefix = address if '/' in address else address + '/' + value.get('netmask', '255.255.255.0')
                if ipaddress.IPv4Interface(prefix).network.overlaps(NETWORK):
                    raise ValueError('192.168.40.0/24 is reserved for the passthrough gateway.')
            except ipaddress.AddressValueError:
                continue


def plan(settings, backend):
    net = backend.values('network')
    current = net.get('rf_passthrough', {})
    ports = net.get('lan_bridge', {}).get('ports', [])
    ports = [ports] if isinstance(ports, str) else ports
    ethernet = device(net.get('router_ethernet', {}).get('device') or
                      current.get('device') or (ports[0] if len(ports) == 1 else None))
    if not settings['enabled'] and not current:
        return {}
    edits = {'network': [], 'firewall': []}
    if ports:
        edits['network'].append(('delete', 'network.lan_bridge.ports', None))
    edits['network'].append(('set', 'network.lan_bridge.bridge_empty', '1'))
    edits['firewall'].append(('set', 'firewall.wan.masq', '0' if settings['enabled'] else '1'))
    # Preserve a physical-device record even if the original LAN had no Ethernet metadata.
    features.uci_section(edits, 'network', 'router_ethernet', 'router_ethernet',
                         dict(device=ethernet, mode='lan', lan_vlan=net.get('router_ethernet', {}).get('lan_vlan', '10'),
                              wan_vlan=net.get('router_ethernet', {}).get('wan_vlan', '20')))
    if not settings['enabled']:
        edits['network'].append(('add_list', 'network.lan_bridge.ports', ethernet))
        return edits
    features.uci_section(edits, 'network', 'rf_passthrough', 'interface', dict(proto='static',
                         device=ethernet, ipaddr=GATEWAY, netmask='255.255.255.0'))
    features.uci_section(edits, 'firewall', 'rf_passthrough', 'zone', dict(name='rf_passthrough',
                         network=['rf_passthrough'], input='REJECT', output='ACCEPT', forward='REJECT'))
    for name, src, dest in [('rf_pass_out', 'rf_passthrough', 'wan'), ('rf_pass_in', 'wan', 'rf_passthrough')]:
        features.uci_section(edits, 'firewall', name, 'forwarding', dict(src=src, dest=dest, family='ipv4'))
    features.uci_section(edits, 'firewall', 'rf_pass_dhcp', 'rule', dict(src='rf_passthrough',
                         proto='udp', src_port='68', dest_port='67', family='ipv4', target='ACCEPT'))
    return edits


def lease(backend):
    status = backend.ubus('network.interface.wan', 'status')
    if not status.get('up'):
        return None
    addresses = status.get('ipv4-address', [])
    if len(addresses) != 1:
        raise ValueError('Passthrough requires exactly one LTE IPv4 address.')
    address = str(ipaddress.IPv4Address(addresses[0]['address']))
    parsed = ipaddress.IPv4Address(address)
    if parsed.is_unspecified or parsed.is_loopback or parsed.is_multicast or parsed.is_link_local:
        raise ValueError('LTE returned an unusable passthrough address.')
    if any(parsed in ipaddress.ip_network(n) for n in ('192.168.7.0/24', '192.168.10.0/24', '192.168.20.0/24', str(NETWORK))):
        raise ValueError('LTE address overlaps a router management network.')
    prefix = addresses[0]['mask']
    if type(prefix) is not int or not 0 <= prefix <= 32:
        raise ValueError('Invalid LTE address prefix.')
    uplink = status.get('l3_device')
    if not isinstance(uplink, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', uplink):
        raise ValueError('Cannot identify the LTE network device.')
    default = next((r for r in status.get('route', []) if r.get('target') == '0.0.0.0' and r.get('mask') == 0), None)
    if default is None:
        raise ValueError('LTE has no IPv4 default route.')
    gateway = str(ipaddress.IPv4Address(default.get('nexthop') or '0.0.0.0'))
    # netifd retains bearer DNS under inactive when peer DNS is disabled for
    # normal router operation. Passthrough must still hand that DNS to its client.
    dns = status.get('inactive', {}).get('dns-server', []) or status.get('dns-server', [])
    dns = [dns] if isinstance(dns, str) else dns
    dns = list(dict.fromkeys(str(ipaddress.IPv4Address(d)) for d in dns if ':' not in d))[:3]
    if not dns:
        raise ValueError('LTE has no carrier-provided IPv4 DNS servers. Reconnect LTE before enabling passthrough.')
    return dict(address=address, prefix=prefix, uplink=uplink, gateway=gateway,
                metric=features.number(int(default.get('metric', 20)), 0, 65535), dns=dns)


def dhcp_config(data, ethernet, mac):
    """Offer /32 plus explicit on-link gateway and default routes (RFC 3442)."""
    address = str(ipaddress.IPv4Address(data['address']))
    ethernet = device(ethernet)
    mac = validate(dict(enabled=True, client_mac=mac))['client_mac']
    return '\n'.join([
        'port=0', 'bind-interfaces', 'interface=' + ethernet, 'except-interface=lo',
        'dhcp-authoritative', 'log-dhcp', 'dhcp-lease-max=1', 'dhcp-ignore=tag:!known',
        'dhcp-host=' + mac + ',' + address + ',2m',
        'shared-network=' + ethernet + ',' + address,
        'dhcp-range=' + address + ',' + address + ',255.255.255.255,2m',
        'dhcp-option=option:netmask,255.255.255.255',
        'dhcp-option=option:router,' + GATEWAY,
        'dhcp-option=option:dns-server,' + ','.join(data['dns']),
        'dhcp-option-force=121,' + GATEWAY + '/32,0.0.0.0,0.0.0.0/0,' + GATEWAY,
        'dhcp-option-force=249,' + GATEWAY + '/32,0.0.0.0,0.0.0.0/0,' + GATEWAY,
        'pid-file=' + str(ROOT / 'dnsmasq.pid'),
        'dhcp-leasefile=' + str(ROOT / 'leases'), ''])


def firewall(data, ethernet, mac, exists=False):
    """Restrict handoff to the selected MAC/IP; protect every management network."""
    ethernet = device(ethernet)
    uplink = data['uplink']
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', uplink):
        raise ValueError('Invalid uplink device.')
    address = str(ipaddress.IPv4Address(data['address']))
    mac = validate(dict(enabled=True, client_mac=mac))['client_mac']
    return (('delete table inet ' + NFT_TABLE + '\n') if exists else '') + f'''table inet {NFT_TABLE} {{
 chain guard {{ type filter hook prerouting priority -310; policy accept;
  iifname "{ethernet}" ether saddr != {mac} drop
  iifname "{ethernet}" meta nfproto ipv6 drop
  iifname "{ethernet}" ip saddr 0.0.0.0 udp sport 68 udp dport 67 accept
  iifname "{ethernet}" ip saddr != {address} drop
 }}
 chain forward {{ type filter hook forward priority -10; policy accept;
  oifname "{uplink}" iifname != "{ethernet}" drop
  iifname "{ethernet}" oifname != "{uplink}" drop
  oifname "{ethernet}" iifname != "{uplink}" drop
  oifname "{ethernet}" ip daddr != {address} drop
 }}
 chain output {{ type filter hook output priority -10; policy accept;
  oifname "{uplink}" drop
 }}
}}
'''


def query(*args):
    return json.loads(features.execute(*args))


def policy_rules():
    try:
        return query('ip', '-j', '-4', 'rule', 'show')
    except RuntimeError:
        # Without IPv4 multiple tables the kernel rejects RTM_GETRULE. Only
        # accept that failure when its own configuration proves rules impossible.
        try:
            config = gzip.decompress(Path('/proc/config.gz').read_bytes()).decode().splitlines()
        except (OSError, EOFError, ValueError, UnicodeError):
            config = []
        if ('# CONFIG_IP_ADVANCED_ROUTER is not set' in config
                or '# CONFIG_IP_MULTIPLE_TABLES is not set' in config):
            return []
        raise


def nft_exists():
    return subprocess.run(['nft', 'list', 'table', 'inet', NFT_TABLE],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0


def nft_apply(script):
    subprocess.run(['nft', '-f', '-'], input=script, text=True, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def dhcp_pid():
    try:
        pid = int((ROOT / 'dnsmasq.pid').read_text().strip())
        args = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
        if pid > 1 and any(arg.endswith(b'/dnsmasq') or arg == b'dnsmasq' for arg in args) and \
                ('--conf-file=' + str(ROOT / 'dnsmasq.conf')).encode() in args:
            return pid
    except (OSError, ValueError):
        pass
    return None


def stop_dhcp():
    pid = dhcp_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if dhcp_pid() is None:
                break
            time.sleep(.05)
        else:
            raise RuntimeError('Passthrough DHCP server did not stop.')
    (ROOT / 'dnsmasq.pid').unlink(missing_ok=True)


def default_route(data):
    command = ['ip', '-4', 'route', 'replace', 'default']
    if data['gateway'] != '0.0.0.0':
        command += ['via', data['gateway'], 'onlink']
    features.execute(*(command + ['dev', data['uplink'], 'metric', str(data['metric'])]))


def clear_connections(address):
    # The address changes owner. Old router/client conntrack tuples must not be
    # delivered to the new owner, including flows formerly masqueraded by fw4.
    address = str(ipaddress.IPv4Address(address))
    for selector in ('--orig-src', '--orig-dst', '--reply-src', '--reply-dst'):
        result = subprocess.run(['conntrack', '-D', '-f', 'ipv4', selector, address],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if result.returncode and not (result.returncode == 1 and '0 flow entries' in result.stderr):
            raise RuntimeError('Cannot clear stale IPv4 connections before address handoff.')


def suspend():
    """Leave a stopped supervisor fail-closed until restart/disable/rollback."""
    if not safe_root():
        return
    journal = features.read(ROOT / 'journal.json', None)
    if journal:
        ethernet, uplink = journal['ethernet'], journal['lease']['uplink']
        prefix = ('delete table inet ' + NFT_TABLE + '\n') if nft_exists() else ''
        nft_apply(prefix + f'''table inet {NFT_TABLE} {{
 chain forward {{ type filter hook forward priority -10; policy accept;
  iifname "{ethernet}" drop
  oifname "{ethernet}" drop
  oifname "{uplink}" drop
 }}
 chain output {{ type filter hook output priority -10; policy accept; oifname "{uplink}" drop; }}
}}
''')
        stop_dhcp()


def cleanup(backend, restore=True):
    if not safe_root():
        return
    journal = features.read(ROOT / 'journal.json', None)
    if not journal:
        return
    stop_dhcp()
    data, ethernet = journal['lease'], journal['ethernet']
    # Delete only the exact route/neighbour owned by this handoff.
    routes = query('ip', '-j', '-4', 'route', 'show', 'exact', data['address'] + '/32')
    if any(r.get('dev') == ethernet and r.get('dst') in (data['address'], data['address'] + '/32') for r in routes):
        features.execute('ip', '-4', 'route', 'del', data['address'] + '/32', 'dev', ethernet, 'metric', '5')
    neighbors = query('ip', '-j', '-4', 'neigh', 'show', 'to', data['address'], 'dev', ethernet)
    if any(n.get('lladdr', '').lower() == journal['mac'] for n in neighbors):
        features.execute('ip', '-4', 'neigh', 'del', data['address'], 'dev', ethernet)
    if restore:
        try:
            current = lease(backend)
        except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError):
            current = None  # Never reassign a stale address during a bearer transition.
        if current and current['address'] == data['address'] and current['uplink'] == data['uplink']:
            features.execute('ip', '-4', 'addr', 'replace', data['address'] + '/' + str(data['prefix']), 'dev', data['uplink'])
            default_route(data)
            try:
                clear_connections(data['address'])
            except (OSError, RuntimeError, subprocess.SubprocessError):
                # A missing/broken conntrack interface must not prevent recovery
                # of Ethernet and USB access after a failed activation.
                logging.getLogger(__name__).warning('Routing restored; stale passthrough connections could not be cleared')
    if nft_exists():
        features.execute('nft', 'delete', 'table', 'inet', NFT_TABLE)
    (ROOT / 'journal.json').unlink()
    (ROOT / 'leases').unlink(missing_ok=True)


def reconcile(settings, backend):
    if not settings['enabled']:
        cleanup(backend)
        return dict(state='disabled')
    safe_root(create=True)
    journal = features.read(ROOT / 'journal.json', None)
    net = backend.values('network')
    section = net.get('rf_passthrough', {})
    ethernet = section.get('device')
    ports = net.get('lan_bridge', {}).get('ports', [])
    ports = [ports] if isinstance(ports, str) else ports
    if not section or ethernet in ports:
        cleanup(backend)
        return dict(state='suspended', reason='Ethernet recovery changed the port configuration. Disable passthrough to restore normal routing.')
    device(ethernet)
    downstream = backend.ubus('network.interface.rf_passthrough', 'status')
    if not downstream.get('up') or downstream.get('l3_device') != ethernet or not any(
            a.get('address') == GATEWAY for a in downstream.get('ipv4-address', [])):
        return dict(state='waiting', reason='Waiting for the dedicated Ethernet gateway.')
    data = lease(backend)
    if data is None:
        cleanup(backend, restore=False)
        return dict(state='waiting', reason='Waiting for an IPv4 LTE connection.')
    if data['uplink'] == ethernet:
        raise ValueError('LTE and downstream Ethernet devices must differ.')
    expected = dict(lease=data, ethernet=ethernet, mac=settings['client_mac'])
    same = journal == expected
    addresses = query('ip', '-j', '-4', 'addr', 'show', 'dev', data['uplink'])
    assigned = [a for interface in addresses for a in interface.get('addr_info', []) if a.get('family') == 'inet']
    if any(a.get('local') != data['address'] for a in assigned):
        raise ValueError('The LTE interface has additional addresses; handoff was not applied.')
    if same and not assigned and dhcp_pid() and nft_exists():
        # Refresh objects lost to link events without reallocating the lease.
        default_route(data)
        features.execute('ip', '-4', 'route', 'replace', data['address'] + '/32', 'dev', ethernet, 'metric', '5')
        features.execute('ip', '-4', 'neigh', 'replace', data['address'], 'lladdr', settings['client_mac'], 'nud', 'permanent', 'dev', ethernet)
        return dict(state='active', address=data['address'], client_mac=settings['client_mac'], interface=ethernet)
    if journal:
        cleanup(backend, restore=False)
    elif nft_exists():
        raise RuntimeError('The reserved passthrough nftables table already exists without an ownership journal.')
    # Never replace a host route installed by another component.
    existing = query('ip', '-j', '-4', 'route', 'show', 'exact', data['address'] + '/32')
    if existing:
        raise RuntimeError('A route to the LTE address already exists in the main table.')
    if query('ip', '-j', '-4', 'neigh', 'show', 'to', data['address'], 'dev', ethernet):
        raise RuntimeError('An Ethernet neighbour entry already owns the LTE address.')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    features.atomic(ROOT / 'dnsmasq.conf', dhcp_config(data, ethernet, settings['client_mac']))
    features.execute('dnsmasq', '--test', '--conf-file=' + str(ROOT / 'dnsmasq.conf'))
    # Durable-before-mutation journal; runtime changes can be undone after a crash.
    features.atomic(ROOT / 'journal.json', expected)
    try:
        nft_apply(firewall(data, ethernet, settings['client_mac']))
        clear_connections(data['address'])
        if assigned:
            features.execute('ip', '-4', 'addr', 'del', data['address'] + '/' + str(data['prefix']), 'dev', data['uplink'])
        default_route(data)
        features.execute('ip', '-4', 'route', 'replace', data['address'] + '/32', 'dev', ethernet, 'metric', '5')
        features.execute('ip', '-4', 'neigh', 'replace', data['address'], 'lladdr', settings['client_mac'], 'nud', 'permanent', 'dev', ethernet)
        features.execute('dnsmasq', '--conf-file=' + str(ROOT / 'dnsmasq.conf'))
        if dhcp_pid() is None:
            raise RuntimeError('Passthrough DHCP server did not start.')
    except Exception:
        cleanup(backend)
        raise
    features.event('passthrough', 'LTE IPv4 address handed to the designated Ethernet client. Renew its DHCP lease.')
    return dict(state='active', address=data['address'], client_mac=settings['client_mac'], interface=ethernet)


def activate(settings, backend):
    """Wait briefly for netifd after a reload, retaining transaction rollback."""
    deadline = time.monotonic() + 10
    result = reconcile(settings, backend)
    while settings['enabled'] and result['state'] == 'waiting' and time.monotonic() < deadline:
        time.sleep(.25)
        result = reconcile(settings, backend)
    if settings['enabled'] and result['state'] != 'active':
        raise ValueError('Connect LTE and verify USB management before enabling passthrough.')
    return result
