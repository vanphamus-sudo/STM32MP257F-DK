"""Optional router services, guarded configuration changes and local diagnostics.

All mutation entry points are called behind the authenticated server's lock and
the cross-process lock below. The supervisor uses the same lock for recovery.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import cellular_info

STATE = Path('/etc/router-web')
RUNTIME = Path('/tmp/router-features.json')
PACKAGES = ('network', 'firewall', 'dhcp', 'wireless', 'sqm', 'ddns', 'openvpn')
BACKUP_FILES = ('features.json', 'mqtt.json', 'modbus.json', 'serial-tcp.json',
                'openvpn/settings.json', 'openvpn/ca.crt', 'openvpn/client.crt',
                'openvpn/client.key', 'openvpn/ta.key', 'openvpn/client.conf')
DEFAULTS = {
    'watchdog': dict(enabled=False, targets=['1.1.1.1', '8.8.8.8'], interval=60,
                     failures=3, cooldown=300, reset_after=3),
    'failover': dict(enabled=False, primary='ethernet_wan', backup='wan', recoveries=3),
    'allowance': dict(enabled=False, limit_mb=10000, warning_percent=80, billing_day=1,
                      cutoff=False),
    'alerts': dict(enabled=True, mqtt=False, weak_rsrp=-110),
    'signal': dict(enabled=True, interval=300, samples=288),
    'wireguard': dict(enabled=False, private_key='', address='10.77.0.2/24',
                      peer_key='', endpoint='', port=51820,
                      allowed_ips=['10.77.0.0/24'], keepalive=25, access_lan=False),
    'guest': dict(enabled=False, vlan=30, subnet='192.168.30.1/24'),
    'sqm': dict(enabled=False, interface='', download=10000, upload=5000),
    'ipv6': dict(enabled=False),
    'cellular': dict(roaming=False, operator='', bands=['any']),
    'sms': dict(enabled=False, alert_number=''),
    'gnss': dict(enabled=False),
    'passthrough': dict(enabled=False, client_mac=''),
}


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Unique names also protect against unrelated processes writing state files.
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(value if isinstance(value, str) else json.dumps(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked():
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'features.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def read(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def config():
    saved = read(STATE / 'features.json', {})
    return {key: dict(value, **saved.get(key, {})) for key, value in DEFAULTS.items()}


def revision():
    return hashlib.sha256(json.dumps(config(), sort_keys=True).encode()).hexdigest()


def execute(*args, timeout=25):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        # stderr from credential-bearing commands must not reach logs or the UI.
        raise RuntimeError('Command failed: ' + Path(args[0]).name)
    return result.stdout.strip()[:65536]


def modem(backend):
    return backend.values('network')['wan']['device']


def capability(backend):
    import ip_passthrough
    result = dict(wireguard=Path('/lib/netifd/proto/wireguard.sh').exists(),
                  sqm=Path('/etc/init.d/sqm').exists(), ipv6=Path('/etc/init.d/odhcpd').exists(),
                  sms=False, gnss=False, dual_sim=False,
                  esim=False, passthrough=bool(ip_passthrough.available()),
                  hardware_note='Routed IPv4 passthrough supports one Ethernet client with exclusive LTE use. eSIM provisioning remains unavailable.')
    try:
        data = json.loads(execute('mmcli', '-m', modem(backend), '-J')).get('modem', {})
        generic = data.get('generic', {})
        gpp = data.get('3gpp', {})
        result['registered_operator'] = dict(code=gpp.get('operator-code', ''), name=gpp.get('operator-name', ''))
        slots = generic.get('sim-slots', [])
        result['dual_sim'] = len([s for s in slots if s not in ('/', '--')]) > 1
        result['sim_slots'] = slots
        result['supported_bands'] = generic.get('supported-bands', [])
        result['band_options'] = cellular_info.band_options(result['supported_bands'])
        for flag, option, group in [('sms', '--messaging-status', 'messaging'), ('gnss', '--location-status', 'location')]:
            try:
                detail = json.loads(execute('mmcli', '-m', modem(backend), option, '-J')).get('modem', {}).get(group, {})
                result[flag] = bool(detail) if flag == 'sms' else 'gps-raw' in detail.get('capabilities', [])
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                pass
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError):
        result['modem_unavailable'] = True
    return result


def status(backend):
    settings = config()
    settings['wireguard']['private_key_saved'] = bool(settings['wireguard'].pop('private_key'))
    runtime = read(RUNTIME, {})
    capabilities = capability(backend)
    return dict(settings=settings, revision=revision(), capabilities=capabilities,
                cellular_choices=cellular_info.choices(capabilities.get('registered_operator'), settings['cellular']['operator']),
                runtime=runtime, pending=public_pending(),
                events=read(STATE / 'feature-events.json', [])[-100:],
                signal=read(Path('/tmp/router-signal.json'), [])[-settings['signal']['samples']:])


def number(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'Enter an integer from {low} to {high}.')
    return value


def text(value, pattern, message):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(message)
    return value


def key(value):
    try:
        if not isinstance(value, str) or len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('WireGuard keys must be base64 encoded 32-byte keys.') from None
    return value


def validate(section, data, old):
    if section not in DEFAULTS or not isinstance(data, dict) or set(data) != set(DEFAULTS[section]):
        raise ValueError('Supply all settings for the selected feature.')
    data = json.loads(json.dumps(data))
    if section == 'passthrough':
        import ip_passthrough
        return ip_passthrough.validate(data)
    for name, default in DEFAULTS[section].items():
        if isinstance(default, bool) and type(data[name]) is not bool:
            raise ValueError('On/off values must be booleans.')
    if section == 'watchdog':
        if not isinstance(data['targets'], list) or not 2 <= len(data['targets']) <= 4:
            raise ValueError('Supply two to four different public IPv4 health-check addresses.')
        for target in data['targets']:
            if not isinstance(target, str):
                raise ValueError('Enter health-check addresses as text.')
            address = ipaddress.IPv4Address(target)
            if not address.is_global:
                raise ValueError('Health checks must use public IPv4 addresses.')
        if len(set(data['targets'])) != len(data['targets']):
            raise ValueError('Use different health-check addresses.')
        for name, low, high in [('interval', 30, 3600), ('failures', 2, 20),
                                ('cooldown', 120, 86400), ('reset_after', 2, 10)]:
            number(data[name], low, high)
    elif section == 'failover':
        if (data['primary'], data['backup']) != ('ethernet_wan', 'wan'):
            raise ValueError('This router supports Ethernet primary and LTE backup.')
        number(data['recoveries'], 2, 20)
    elif section == 'allowance':
        number(data['limit_mb'], 1, 10000000)
        number(data['warning_percent'], 1, 100)
        number(data['billing_day'], 1, 28)
    elif section == 'alerts':
        number(data['weak_rsrp'], -140, -50)
    elif section == 'signal':
        number(data['interval'], 60, 3600)
        number(data['samples'], 12, 1440)
    elif section == 'wireguard':
        if not data['private_key']:
            data['private_key'] = old['private_key']
        if data['private_key']:
            key(data['private_key'])
        if data['peer_key']:
            key(data['peer_key'])
        ipaddress.ip_interface(data['address'])
        if data['endpoint']:
            text(data['endpoint'], r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', 'Enter an endpoint hostname or IPv4 address.')
        number(data['port'], 1, 65535)
        number(data['keepalive'], 0, 65535)
        if not isinstance(data['allowed_ips'], list) or not 1 <= len(data['allowed_ips']) <= 32:
            raise ValueError('Supply one to 32 peer networks.')
        for network in data['allowed_ips']:
            ipaddress.ip_network(network, strict=False)
        if data['enabled'] and not (data['private_key'] and data['peer_key'] and data['endpoint']):
            raise ValueError('Enter both keys and the peer endpoint.')
    elif section == 'guest':
        number(data['vlan'], 1, 4094)
        interface = ipaddress.IPv4Interface(data['subnet'])
        private = any(interface.ip in ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        if not private or interface.network.prefixlen != 24 or interface.ip in (interface.network.network_address, interface.network.broadcast_address):
            raise ValueError('Use a private guest gateway with a /24 subnet.')
        if any(interface.network.overlaps(ipaddress.ip_network(n)) for n in
               ('192.168.10.0/24', '192.168.20.0/24', '192.168.7.0/24')):
            raise ValueError('Guest subnet must differ from LAN, Wi-Fi and USB management.')
    elif section == 'sqm':
        text(data['interface'], r'[A-Za-z0-9_.:-]{0,15}', 'Enter a Linux WAN interface name.')
        if data['enabled'] and not data['interface']:
            raise ValueError('Select the actual WAN interface for SQM.')
        number(data['download'], 64, 1000000)
        number(data['upload'], 64, 1000000)
    elif section == 'cellular':
        text(data['operator'], r'(?:[0-9]{5,6})?', 'Operator must be blank for automatic or a five/six digit MCC/MNC.')
        if not isinstance(data['bands'], list) or not 1 <= len(data['bands']) <= 64:
            raise ValueError('Supply modem band names, or any.')
        for band in data['bands']:
            text(band, r'(?:any|eutran-[0-9]{1,3})', 'Use any or LTE band names such as eutran-3.')
        if 'any' in data['bands'] and len(data['bands']) != 1:
            raise ValueError('Use any alone.')
    elif section == 'sms':
        text(data['alert_number'], r'(?:\+?[0-9]{5,20})?', 'Enter a telephone number including country code.')
    return data


def uci_section(edits, package, name, kind, options):
    edits.setdefault(package, []).append(('set', package + '.' + name, kind))
    for option, value in options.items():
        namekey = package + '.' + name + '.' + option
        if isinstance(value, list):
            # Sections owned by this feature are removed before recreation.
            edits[package] += [('add_list', namekey, str(v)) for v in value]
        else:
            edits[package].append(('set', namekey, str(value)))


def plan(section, settings, backend):
    """Build narrowly owned UCI edits; preserve unrelated LuCI sections."""
    edits = {}
    if section == 'passthrough':
        import ip_passthrough
        return ip_passthrough.plan(settings, backend)
    if section == 'wireguard':
        d = settings
        uci_section(edits, 'network', 'rf_wg', 'interface', dict(proto='wireguard',
                    private_key=d['private_key'], addresses=[d['address']], disabled=int(not d['enabled'])))
        uci_section(edits, 'network', 'rf_peer', 'wireguard_rf_wg', dict(public_key=d['peer_key'],
                    endpoint_host=d['endpoint'], endpoint_port=d['port'],
                    allowed_ips=d['allowed_ips'], route_allowed_ips='1', persistent_keepalive=d['keepalive']))
        uci_section(edits, 'firewall', 'rf_wg', 'zone', dict(name='rf_wg', network=['rf_wg'],
                    input='REJECT', output='ACCEPT', forward='REJECT', mtu_fix='1'))
        uci_section(edits, 'firewall', 'rf_lan_wg', 'forwarding', dict(src='lan', dest='rf_wg'))
        if d['access_lan']:
            uci_section(edits, 'firewall', 'rf_wg_lan', 'forwarding', dict(src='rf_wg', dest='lan'))
    elif section == 'guest':
        net = backend.values('network')
        eth = net.get('router_ethernet', {})
        if settings['enabled'] and eth.get('mode') != 'both':
            raise ValueError('Configure Ethernet LAN + WAN trunk mode before enabling a guest VLAN.')
        if settings['vlan'] in (int(eth.get('lan_vlan', 10)), int(eth.get('wan_vlan', 20))):
            raise ValueError('Guest VLAN must differ from the Ethernet LAN and WAN VLANs.')
        interface = ipaddress.IPv4Interface(settings['subnet'])
        if settings['enabled']:
            uci_section(edits, 'network', 'rf_guest', 'interface', dict(proto='static',
                        device=eth['device'] + '.' + str(settings['vlan']), ipaddr=str(interface.ip), netmask='255.255.255.0'))
            uci_section(edits, 'dhcp', 'rf_guest', 'dhcp', dict(interface='rf_guest', start='50', limit='150', leasetime='12h'))
            uci_section(edits, 'firewall', 'rf_guest', 'zone', dict(name='rf_guest', network=['rf_guest'],
                        input='REJECT', output='ACCEPT', forward='REJECT'))
            uci_section(edits, 'firewall', 'rf_guest_wan', 'forwarding', dict(src='rf_guest', dest='wan', family='ipv4'))
            for name, port in [('dns', '53'), ('dhcp', '67')]:
                uci_section(edits, 'firewall', 'rf_guest_' + name, 'rule', dict(src='rf_guest',
                            proto='tcp udp' if name == 'dns' else 'udp', dest_port=port, family='ipv4', target='ACCEPT'))
        else:
            edits = {p: [] for p in ('network', 'firewall', 'dhcp')}
    elif section == 'sqm':
        uci_section(edits, 'sqm', 'rf_sqm', 'queue', dict(enabled=int(settings['enabled']),
                    interface=settings['interface'], download=settings['download'], upload=settings['upload'],
                    qdisc='cake', script='piece_of_cake.qos', linklayer='none'))
    elif section == 'ipv6':
        on = settings['enabled']
        edits = {'network': [('set', 'network.wan.iptype', 'ipv4v6' if on else 'ipv4'),
                             ('set', 'network.lan.ip6assign', '64' if on else '0')],
                 'dhcp': [('set', 'dhcp.lan.ra', 'server' if on else 'disabled'),
                          ('set', 'dhcp.lan.dhcpv6', 'server' if on else 'disabled')]}
        edits['firewall'] = [('set', 'firewall.lan_wan.family', 'any' if on else 'ipv4')]
        if on:
            uci_section(edits, 'network', 'rf_wan6', 'interface', dict(proto='dhcpv6', device='@wan', reqprefix='auto'))
            for name, options in {
                'rf_icmp6': dict(proto='icmp', family='ipv6', icmp_type=['destination-unreachable',
                    'packet-too-big', 'time-exceeded', 'bad-header', 'unknown-header-type',
                    'router-advertisement', 'neighbour-solicitation', 'neighbour-advertisement'], limit='1000/sec'),
                'rf_dhcp6': dict(proto='udp', family='ipv6', src_ip='fc00::/6', dest_port='546'),
            }.items():
                uci_section(edits, 'firewall', name, 'rule', dict(src='wan', target='ACCEPT', **options))
            uci_section(edits, 'firewall', 'rf_icmp6_forward', 'rule', dict(src='wan', dest='*',
                        proto='icmp', family='ipv6', icmp_type=['destination-unreachable', 'packet-too-big',
                        'time-exceeded', 'bad-header', 'unknown-header-type'], target='ACCEPT', limit='1000/sec'))
    elif section == 'cellular':
        edits = {'network': [('set', 'network.wan.allow_roaming', str(int(settings['roaming'])))]}
    return edits


OWNED = {
    'passthrough': dict(network=['rf_passthrough'], firewall=['rf_passthrough', 'rf_pass_out', 'rf_pass_in', 'rf_pass_dhcp']),
    'wireguard': dict(network=['rf_wg', 'rf_peer'], firewall=['rf_wg', 'rf_lan_wg', 'rf_wg_lan']),
    'guest': dict(network=['rf_guest'], dhcp=['rf_guest'], firewall=['rf_guest', 'rf_guest_wan', 'rf_guest_dns', 'rf_guest_dhcp']),
    'sqm': dict(sqm=['rf_sqm']),
    'ipv6': dict(network=['rf_wan6'], firewall=['rf_icmp6', 'rf_dhcp6', 'rf_icmp6_forward']),
}


def snapshot(backend):
    files = {}
    for name in PACKAGES:
        path = backend.CONFIG / name
        files['uci/' + name] = path.read_text() if path.exists() else None
    files['state/features.json'] = (STATE / 'features.json').read_text() if (STATE / 'features.json').exists() else None
    return files


def restore_files(files, backend):
    for name, content in files.items():
        kind, leaf = name.split('/', 1)
        path = (backend.CONFIG if kind == 'uci' else STATE) / leaf
        if content is None:
            path.unlink(missing_ok=True)
        else:
            atomic(path, content)


def reload_services():
    for service, action in [('network', 'reload'), ('firewall', 'restart'), ('dnsmasq', 'restart'),
                            ('odhcpd', 'restart'), ('sqm', 'restart')]:
        if Path('/etc/init.d/' + service).exists():
            execute('/etc/init.d/' + service, action)


def public_pending():
    pending = read(STATE / 'feature-pending.json', None)
    return None if not pending else {k: pending[k] for k in ('token', 'deadline', 'section')}


def begin_change(section, backend, files=None):
    if public_pending():
        raise ValueError('Confirm or roll back the previous network change first.')
    if not Path('/etc/init.d/router-features').exists() or not backend.service_active('router-features'):
        raise RuntimeError('Start the router-features supervisor before changing network settings; it provides automatic rollback.')
    pending = dict(token=secrets.token_hex(24), deadline=int(time.time()) + 180,
                   section=section, files=files or snapshot(backend), boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    atomic(STATE / 'feature-pending.json', pending)
    return pending


def rollback(backend):
    pending = read(STATE / 'feature-pending.json', None)
    if not pending:
        return
    import ip_passthrough
    ip_passthrough.cleanup(backend)
    restore_files(pending['files'], backend)
    # Cellular preferences are restored as well as the on-disk configuration.
    if pending['section'] == 'cellular':
        apply_cellular(config()['cellular'], backend)
    reload_services()
    if config()['passthrough']['enabled']:
        ip_passthrough.activate(config()['passthrough'], backend)
    (STATE / 'feature-pending.json').unlink(missing_ok=True)
    event('rollback', 'Network settings restored after an unconfirmed change.')


def confirm(token):
    pending = public_pending()
    if not pending or not isinstance(token, str) or not secrets.compare_digest(pending['token'], token):
        raise ValueError('No matching pending change.')
    if pending['deadline'] <= time.time():
        raise ValueError('Confirmation expired; wait for automatic rollback.')
    if pending['section'] == 'passthrough' and config()['passthrough']['enabled']:
        import ip_passthrough
        if not ip_passthrough.dhcp_pid():
            raise ValueError('Passthrough has not activated. Reload service status; renew the client DHCP lease before confirming.')
    (STATE / 'feature-pending.json').unlink()
    event('configuration', 'Network settings confirmed.')


def apply_cellular(settings, backend):
    device = modem(backend)
    execute('mmcli', '-m', device, '--set-current-bands=' + '|'.join(settings['bands']))
    execute('mmcli', '-m', device, '--3gpp-register-in-operator=' + settings['operator']
            if settings['operator'] else '--3gpp-register-home', timeout=60)


def save(data, backend):
    if public_pending():
        raise ValueError('Confirm or roll back the previous network change first.')
    if set(data) != {'section', 'settings', 'revision'} or data['revision'] != revision():
        raise ValueError('Settings changed. Reload before saving.')
    section = data['section']
    current = config()
    settings = validate(section, data['settings'], current.get(section, {}))
    import ip_passthrough
    if current['passthrough']['enabled'] and section in ('watchdog', 'failover', 'wireguard', 'guest', 'ipv6', 'cellular', 'sqm'):
        raise ValueError('Disable IP passthrough before changing a service that reloads or shares LTE networking.')
    if section == 'passthrough':
        ip_passthrough.preflight(settings, backend, current)
    caps = capability(backend)
    if section in ('wireguard', 'sqm', 'ipv6', 'sms', 'gnss') and settings['enabled'] and not caps.get(section):
        raise ValueError('This feature requires the corresponding OpenWrt packages and modem support.')
    if section == 'cellular' and settings['bands'] != ['any']:
        if not set(settings['bands']).issubset(caps.get('supported_bands', [])):
            raise ValueError('One or more bands are not reported as supported by this modem.')
    if section == 'failover' and settings['enabled'] and 'ethernet_wan' not in backend.values('network'):
        raise ValueError('Configure Ethernet WAN or trunk mode first.')
    edits = plan(section, settings, backend)
    pending = begin_change(section, backend) if edits or section == 'cellular' else None
    try:
        if section == 'passthrough':
            ip_passthrough.cleanup(backend)
        for package, commands in edits.items():
            if not (backend.CONFIG / package).exists():
                atomic(backend.CONFIG / package, '')
            existing = backend.values(package)
            remove = [('delete', package + '.' + name, None)
                      for name in OWNED.get(section, {}).get(package, []) if name in existing]
            if section == 'ipv6' and package == 'network':
                networks = backend.values('firewall')['wan'].get('network', ['wan'])
                if isinstance(networks, str):
                    networks = networks.split()
                networks = [n for n in networks if n != 'rf_wan6']
                if settings['enabled']:
                    networks.append('rf_wan6')
                edits.setdefault('firewall', []).extend([('delete', 'firewall.wan.network', None)] +
                    [('add_list', 'firewall.wan.network', n) for n in networks])
            backend.transaction(package, remove + commands, lambda: None, atomic)
        if section == 'guest':
            # dnsmasq is explicitly bound to interfaces on this project.
            interfaces = backend.values('dhcp')['router_dns'].get('interface', ['lan', 'hotspot'])
            if isinstance(interfaces, str):
                interfaces = interfaces.split()
            interfaces = [i for i in interfaces if i != 'rf_guest']
            if settings['enabled']:
                interfaces.append('rf_guest')
            backend.transaction('dhcp', [('delete', 'dhcp.router_dns.interface', None)] +
                [('add_list', 'dhcp.router_dns.interface', i) for i in interfaces], lambda: None, atomic)
        if section == 'cellular':
            apply_cellular(settings, backend)
        if section == 'gnss':
            execute('mmcli', '-m', modem(backend), '--location-enable-gps-raw' if settings['enabled'] else '--location-disable-gps-raw')
        current[section] = settings
        atomic(STATE / 'features.json', current)
        if edits:
            execute('fw4', 'check')
            reload_services()
        if section == 'passthrough':
            # Apply inside the transaction so activation failures roll back before
            # success is reported. The supervisor also reconciles at boot/reconnect.
            ip_passthrough.activate(settings, backend)
        event('configuration', section + ' settings saved.')
    except Exception:
        if pending:
            rollback(backend)
        raise
    return dict(revision=revision(), pending=public_pending(), message=
                'Applied. Confirm connectivity within three minutes or settings will be restored.' if pending else 'Settings saved.')


def event(kind, message):
    settings = config()['alerts']
    entry = dict(time=int(time.time()), kind=kind, message=message[:300])
    events = read(STATE / 'feature-events.json', [])
    atomic(STATE / 'feature-events.json', (events + [entry])[-200:])
    if settings['enabled'] and settings['mqtt']:
        # Use an existing supported alarm envelope rather than an unknown topic.
        from mqtt_data import atomic_json
        queue = STATE / 'mqtt-state/outbox'
        if sum(1 for _ in queue.glob('*.json')) < 1000:
            # Reuse no IDs that are either queued or awaiting application ACK.
            pending = read(STATE / 'mqtt-state/pending.json', {})
            used = {e.get('data', {}).get('id') for e in pending.values() if e.get('topic') == 'ALARM'}
            for path in queue.glob('*.json'):
                queued = read(path, {})
                if queued.get('topic') == 'ALARM':
                    used.add(queued.get('data', {}).get('id'))
            identifier = next((i for i in range(1, 65536) if i not in used), None)
            if identifier is None:
                return
            atomic_json(queue / (secrets.token_hex(16) + '.json'),
                        dict(topic='ALARM', data=dict(id=identifier, time=str(entry['time']),
                             event=dict(type='system', object=kind, action='notify', data=entry['message']))))
    sms_settings = config()['sms']
    if settings['enabled'] and sms_settings['enabled'] and sms_settings['alert_number'] and kind in ('connectivity', 'data-usage', 'recovery'):
        # Never let a failed SMS stop watchdog or local event recording.
        try:
            import openwrt_backend
            body = re.sub(r'[^A-Za-z0-9 .!?@_:+/()\-]', '', message)[:160]
            sms(dict(action='send', number=sms_settings['alert_number'], text=body), openwrt_backend)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            pass


def billing_cycle(now, day):
    month, year = now.month, now.year
    if now.day < day:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return f'{year:04}-{month:02}-{day:02}'


def allowance_update(settings, counters, saved, now):
    """Account cellular totals, never WAN+SIM totals (they may be identical)."""
    cycle = billing_cycle(now, settings['billing_day'])
    if saved.get('cycle') != cycle:
        saved = dict(cycle=cycle, last=counters, used=0, warned=False)
    previous = saved.get('last', counters)
    delta = sum(max(0, counters[k] - previous.get(k, counters[k])) for k in ('tx', 'rx'))
    saved.update(last=counters, used=saved.get('used', 0) + delta)
    saved['percent'] = round(saved['used'] / (settings['limit_mb'] * 1000000) * 100, 2)
    saved['exceeded'] = saved['percent'] >= 100
    return saved


def diagnose(data, backend):
    if set(data) != {'tool', 'target'} or data['tool'] not in ('ping', 'dns', 'traceroute'):
        raise ValueError('Choose ping, DNS lookup or traceroute.')
    target = text(data['target'], r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', 'Enter an IP address or hostname.')
    command = {'ping': ['ping', '-c', '3', '-W', '2', target],
               'dns': ['nslookup', target], 'traceroute': ['traceroute', '-m', '12', '-w', '1', target]}[data['tool']]
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        return dict(output=result.stdout[:16000], ok=result.returncode == 0)
    except subprocess.TimeoutExpired:
        return dict(output='Diagnostic timed out after 20 seconds.', ok=False)


def support(backend):
    # Allowlist fields instead of attempting to redact arbitrary configuration.
    import version_info
    runtime = read(RUNTIME, {})
    return dict(software=version_info.info(), runtime={k: v for k, v in runtime.items() if k != 'gnss'},
                capabilities=capability(backend), events=read(STATE / 'feature-events.json', []),
                signal=read(Path('/tmp/router-signal.json'), []))


def backup(backend):
    files = snapshot(backend)
    for name in BACKUP_FILES:
        path = STATE / name
        if path.exists():
            files['state/' + name] = path.read_text()
    # Credentials, update trust, A/B paths, outbox and executable files are never imported.
    return dict(format='stm32-router-settings', version=1, files=files, device=device_identity(),
                notice='Contains network, Wi-Fi, VPN and MQTT secrets. Store securely. Same-device restore only.')


def restore(data, backend):
    if set(data) != {'format', 'version', 'files', 'notice', 'device'} or data['format'] != 'stm32-router-settings' or data['version'] != 1:
        raise ValueError('Choose a router settings backup, version 1.')
    if data['device'] != device_identity():
        raise ValueError('Restore this backup on its original board. Hardware-specific network settings are not portable.')
    allowed = {'uci/' + p for p in PACKAGES} | {'state/' + n for n in BACKUP_FILES}
    if not isinstance(data['files'], dict) or not set(data['files']).issubset(allowed):
        raise ValueError('Backup contains unsupported files.')
    if not {'uci/network', 'uci/firewall', 'uci/dhcp', 'uci/wireless'}.issubset(data['files']):
        raise ValueError('Backup is missing required network files.')
    for name, content in data['files'].items():
        if content is not None and (not isinstance(content, str) or len(content.encode()) > 131072 or '\x00' in content):
            raise ValueError('Invalid backup file.')
        if name.startswith('state/') and name.endswith('.json') and content is not None:
            json.loads(content)
    import openvpn_client
    vpn_settings = data['files'].get('state/openvpn/settings.json')
    vpn_config = data['files'].get('state/openvpn/client.conf')
    if vpn_settings is not None:
        vpn_settings = openvpn_client.validate(json.loads(vpn_settings))
    if vpn_config is not None and (vpn_settings is None or vpn_config != openvpn_client.render(vpn_settings)):
        raise ValueError('OpenVPN configuration must match the validated router settings.')
    for kind, filename in openvpn_client.FILES.items():
        content = data['files'].get('state/openvpn/' + filename)
        if content is not None:
            openvpn_client.validate_file(kind, content)
    for leaf, module in [('mqtt.json', 'mqtt_client'), ('modbus.json', 'modbus_settings')]:
        content = data['files'].get('state/' + leaf)
        if content is not None:
            __import__(module).validate(json.loads(content))
    if 'state/features.json' in data['files'] and data['files']['state/features.json'] is not None:
        settings = json.loads(data['files']['state/features.json'])
        if not set(settings).issubset(DEFAULTS):
            raise ValueError('Backup feature schema does not match this release.')
        for section, value in settings.items():
            validate(section, value, DEFAULTS[section])
    # UCI import is configuration data, but firewall includes could execute code.
    for name, content in data['files'].items():
        if name.startswith('uci/') and content:
            if re.search(r'\b(?:include|script|command|exec|plugin|script_security|route_up|ipchange|tls_verify)\b', content, re.I):
                raise ValueError('Backups containing executable UCI options cannot be restored here.')
    previous = {}
    for name in data['files']:
        kind, leaf = name.split('/', 1)
        path = (backend.CONFIG if kind == 'uci' else STATE) / leaf
        previous[name] = path.read_text() if path.exists() else None
    begin_change('restore', backend, previous)
    try:
        import ip_passthrough
        ip_passthrough.cleanup(backend)
        # Parse every UCI file in private staging before installing any file.
        with tempfile.TemporaryDirectory(prefix='router-restore-') as tmp:
            for name, content in data['files'].items():
                if name.startswith('uci/') and content is not None:
                    package = name.split('/')[1]
                    atomic(Path(tmp) / package, content)
                    execute('uci', '-c', tmp, 'show', package)
        restore_files(data['files'], backend)
        restored = config()
        if restored['passthrough']['enabled']:
            ip_passthrough.preflight(restored['passthrough'], backend, restored)
        execute('fw4', 'check')
        reload_services()
        if restored['passthrough']['enabled']:
            ip_passthrough.activate(restored['passthrough'], backend)
    except Exception:
        rollback(backend)
        raise
    return dict(pending=public_pending(), message='Backup restored. Confirm access within three minutes. Restart MQTT and collection services after confirming.')


def device_identity():
    for path in (Path('/proc/device-tree/serial-number'), Path('/etc/machine-id')):
        if path.exists():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    raise RuntimeError('Cannot identify this board for a settings backup.')


def sms(data, backend):
    if not config()['sms']['enabled']:
        raise ValueError('Enable SMS first.')
    device = modem(backend)
    if data.get('action') == 'delete':
        if set(data) != {'action', 'id'} or type(data['id']) is not int or not 0 <= data['id'] <= 2147483647:
            raise ValueError('Choose one valid SMS message to delete.')
        listed = json.loads(execute('mmcli', '-m', device, '--messaging-list-sms', '-J', timeout=8))
        paths = listed.get('modem.messaging.sms', listed.get('modem', {}).get('messaging', {}).get('sms'))
        if not isinstance(paths, list):
            raise RuntimeError('The modem returned an unrecognized SMS list.')
        path = '/org/freedesktop/ModemManager1/SMS/' + str(data['id'])
        if path not in paths:
            raise ValueError('This message is no longer stored on this modem. Refresh the inbox.')
        execute('mmcli', '-m', device, '--messaging-delete-sms=' + path, timeout=15)
        return dict(message='SMS deleted permanently from the modem.')
    if data == {'action': 'list'}:
        listed = json.loads(execute('mmcli', '-m', device, '--messaging-list-sms', '-J', timeout=8))
        # mmcli uses a flat key for this list, unlike its nested modem/detail JSON.
        paths = listed.get('modem.messaging.sms', listed.get('modem', {}).get('messaging', {}).get('sms'))
        if not isinstance(paths, list):
            raise RuntimeError('The modem returned an unrecognized SMS list.')
        paths = [p for p in paths if isinstance(p, str) and re.search(r'/SMS/\d+',p)]
        messages = []
        failed = 0
        deadline = time.monotonic() + 15
        for path in paths[:30]:
            if time.monotonic() >= deadline:
                break
            match = re.search(r'/SMS/(\d+)', path)
            if match:
                try:
                    item = json.loads(execute('mmcli', '-s', match[1], '-J', timeout=5)).get('sms', {})
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    failed += 1
                    continue
                content, properties = item.get('content', {}), item.get('properties', {})
                def clean_sms(value):
                    return '' if value in (None,'--') else str(value)
                messages.append(dict(id=int(match[1]), number=content.get('number', ''),
                                     text=clean_sms(content.get('text')) or ('Binary SMS (text unavailable)' if clean_sms(content.get('data')) else ''),
                                     time=clean_sms(properties.get('timestamp')), state=clean_sms(properties.get('state')) or 'unknown'))
        return dict(messages=messages, total=len(paths), failed=failed,
                    truncated=len(messages)+failed<len(paths), updated_at=int(time.time()))
    if set(data) != {'action', 'number', 'text'} or data['action'] != 'send':
        raise ValueError('Choose list, send or delete.')
    number_ = text(data['number'], r'\+?[0-9]{5,20}', 'Enter a telephone number.')
    body = text(data['text'], r"[A-Za-z0-9 .!?@_:+/()\-]{1,160}", 'Use up to 160 plain SMS characters; quotes, commas and line breaks are unsupported.')
    created = execute('mmcli', '-m', device, '--messaging-create-sms=number=' + number_ + ',text="' + body + '"')
    match = re.search(r'/SMS/(\d+)', created)
    if not match:
        raise RuntimeError('The modem did not return an SMS identifier.')
    execute('mmcli', '-s', match[1], '--send', timeout=60)
    return dict(message='SMS submitted to the modem.')


def action(data, backend):
    if data.get('action') == 'confirm' and set(data) == {'action', 'token'}:
        confirm(data['token'])
        return dict(message='Network settings confirmed.')
    if data == {'action': 'rollback'}:
        rollback(backend)
        return dict(message='Previous settings restored.')
    if data.get('action') == 'sim-slot' and set(data) == {'action', 'slot'}:
        caps = capability(backend)
        number(data['slot'], 1, len(caps.get('sim_slots', [])))
        if not caps['dual_sim']:
            raise ValueError('This modem does not report multiple SIM slots.')
        execute('mmcli', '-m', modem(backend), '--set-primary-sim-slot=' + str(data['slot']))
        event('sim', 'Active SIM slot changed.')
        return dict(message='SIM slot selected. LTE will reconnect.')
    raise ValueError('Unknown router action.')
