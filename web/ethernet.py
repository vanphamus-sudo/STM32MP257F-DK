"""Dedicated OpenWrt Ethernet roles, staged for the next reboot."""
import hashlib
import re


def revision(platform):
    return hashlib.sha256(b''.join((platform.CONFIG / p).read_bytes()
                                  for p in ('network', 'firewall'))).hexdigest()


def status(platform):
    network = platform.values('network')
    saved = network.get('router_ethernet', {})
    ports = network['lan_bridge'].get('ports', [])
    if isinstance(ports, str):
        ports = [ports]
    device = saved.get('device') or (ports[0] if len(ports) == 1 else '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,10}', device):
        raise RuntimeError('Cannot identify the dedicated Ethernet device.')
    return dict(mode=saved.get('mode', 'lan'), device=device,
                lan_vlan=int(saved.get('lan_vlan', '10')),
                wan_vlan=int(saved.get('wan_vlan', '20')), revision=revision(platform))


def apply(data, platform, atomic_write):
    if set(data) != {'mode', 'lan_vlan', 'wan_vlan', 'revision'}:
        raise ValueError('Supply Ethernet mode and both VLAN IDs.')
    if data['mode'] not in ('lan', 'wan', 'both'):
        raise ValueError('Choose LAN, WAN or LAN + WAN.')
    for key in ('lan_vlan', 'wan_vlan'):
        if type(data[key]) is not int or not 1 <= data[key] <= 4094:
            raise ValueError('VLAN IDs must be integers from 1 to 4094.')
    if data['lan_vlan'] == data['wan_vlan']:
        raise ValueError('LAN and WAN VLAN IDs must differ.')
    current = status(platform)
    if current['revision'] != data['revision']:
        raise RuntimeError('Network settings changed. Reload before saving.')
    network, firewall = platform.values('network'), platform.values('firewall')
    ports = network['lan_bridge'].get('ports', [])
    if isinstance(ports, str):
        ports = [ports]
    expected = ([] if current['mode'] == 'wan' else
                [current['device'] if current['mode'] == 'lan' else
                 f"{current['device']}.{current['lan_vlan']}"])
    if ports != expected:
        raise RuntimeError('LAN bridge was changed outside these settings. Resolve it in LuCI first.')
    for package in ('network', 'firewall'):
        if platform.run('uci', 'changes', package):
            raise RuntimeError('Apply or revert pending UCI changes first.')
    if firewall.get('wan', {}).get('name') != 'wan':
        raise RuntimeError('The dedicated router WAN firewall zone is missing.')
    # Do not adopt unrelated interfaces created through LuCI.
    if 'ethernet_wan' in network and 'router_ethernet' not in network:
        raise RuntimeError('An existing ethernet_wan interface must be resolved in LuCI first.')
    device, mode = current['device'], data['mode']
    edits = [('set', 'network.router_ethernet', 'router_ethernet')]
    edits += [('set', 'network.router_ethernet.' + k, v) for k, v in
              dict(device=device, mode=mode, lan_vlan=data['lan_vlan'], wan_vlan=data['wan_vlan']).items()]
    if network['lan_bridge'].get('ports'):
        edits.append(('delete', 'network.lan_bridge.ports', None))
    edits.append(('set', 'network.lan_bridge.bridge_empty', '1'))
    if mode != 'wan':
        edits.append(('add_list', 'network.lan_bridge.ports',
                      device if mode == 'lan' else f"{device}.{data['lan_vlan']}"))
    if 'ethernet_wan' in network:
        edits.append(('delete', 'network.ethernet_wan', None))
    if mode != 'lan':
        edits += [('set', 'network.ethernet_wan', 'interface')]
        edits += [('set', 'network.ethernet_wan.' + k, v) for k, v in
                  dict(device=device if mode == 'wan' else f"{device}.{data['wan_vlan']}",
                       proto='dhcp', metric='10', peerdns='0', ipv6='0').items()]
    networks = firewall['wan'].get('network', ['wan'])
    if isinstance(networks, str):
        networks = networks.split()
    networks = [n for n in networks if n != 'ethernet_wan']
    if mode != 'lan':
        networks.append('ethernet_wan')
    fw = [('delete', 'firewall.wan.network', None)] if firewall['wan'].get('network') else []
    fw += [('add_list', 'firewall.wan.network', n) for n in networks]
    # DHCP replies from an upstream DHCP server must reach the WAN client.
    fw += [('set', 'firewall.router_ethernet_dhcp', 'rule')]
    fw += [('set', 'firewall.router_ethernet_dhcp.' + k, v) for k, v in
           dict(name='Ethernet WAN DHCP renewal', src='wan', proto='udp',
                src_port='67', dest_port='68', family='ipv4', target='ACCEPT').items()]
    originals = {p: (platform.CONFIG / p).read_text() for p in ('network', 'firewall')}
    try:
        # Both files are committed without reloading services. Each transaction
        # checks pending edits, retains a backup, and uses atomic replacement.
        platform.transaction('network', edits, lambda: None, atomic_write)
        platform.transaction('firewall', fw, lambda: platform.run('fw4', 'check'), atomic_write)
    except Exception:
        for package, original in originals.items():
            if (platform.CONFIG / package).read_text() != original:
                atomic_write(platform.CONFIG / package, original)
        raise
    return status(platform)
