"""USB management is always available; optional IPv4 uplink forwarding."""
import hashlib
import re


def revision(platform):
    return hashlib.sha256(b''.join((platform.CONFIG / p).read_bytes()
                                  for p in ('network', 'dhcp', 'firewall'))).hexdigest()


def forwarding(enabled):
    return [('set', 'firewall.management_wan', 'forwarding')] + [
        ('set', 'firewall.management_wan.' + key, value)
        for key, value in dict(src='management', dest='wan', family='ipv4',
                               enabled='1' if enabled else '0').items()]


def status(platform):
    network, firewall = platform.values('network'), platform.values('firewall')
    management = network.get('management', {})
    device = management.get('device', '')
    available = bool(re.fullmatch(r'usb[0-9]+', device))
    options = platform.values('dhcp').get('management', {}).get('dhcp_option', [])
    options = [options] if isinstance(options, str) else options
    enabled = '3,192.168.7.1' in options
    return dict(available=available, enabled=enabled, device=device,
                address=management.get('ipaddr', '192.168.7.1'), revision=revision(platform))


def apply(data, platform, atomic_write):
    if set(data) != {'enabled', 'revision'} or type(data['enabled']) is not bool:
        raise ValueError('Supply USB tethering enabled and the settings revision.')
    current = status(platform)
    if current['revision'] != data['revision']:
        raise RuntimeError('Network settings changed. Reload before saving.')
    network, firewall = platform.values('network'), platform.values('firewall')
    management = network.get('management', {})
    if (not current['available'] or management.get('proto') != 'static'
            or management.get('ipaddr') != '192.168.7.1'
            or management.get('netmask') != '255.255.255.0'
            or management.get('disabled', '0') == '1'):
        raise RuntimeError('Restore USB management with USER1 before changing tethering.')
    if (firewall.get('management', {}).get('name') != 'management'
            or firewall.get('wan', {}).get('name') != 'wan'
            or firewall['wan'].get('masq') != '1'):
        raise RuntimeError('The dedicated USB/WAN firewall zones and WAN NAT are required.')
    # The UI controls only this named forwarding section. Never adopt custom rules.
    existing = firewall.get('management_wan', {})
    if existing and (existing.get('src') != 'management' or existing.get('dest') != 'wan'):
        raise RuntimeError('The USB forwarding section was changed outside these settings.')
    for package in ('network', 'dhcp', 'firewall'):
        if platform.run('uci', 'changes', package):
            raise RuntimeError('Apply or revert pending UCI changes first.')
    dhcp = platform.values('dhcp')
    if ('management' not in dhcp or 'router_dns' not in dhcp
            or dhcp['management'].get('ignore', '0') == '1'
            or dhcp['router_dns'].get('port', '53') == '0'):
        raise RuntimeError('Restore USB DHCP/DNS management services before changing tethering.')
    interfaces = dhcp['router_dns'].get('interface', [])
    interfaces = interfaces.split() if isinstance(interfaces, str) else interfaces
    excluded = dhcp['router_dns'].get('notinterface', [])
    excluded = excluded.split() if isinstance(excluded, str) else excluded
    if (interfaces and 'management' not in interfaces) or 'management' in excluded:
        raise RuntimeError('USB is excluded from DHCP/DNS. Restore management with USER1 first.')
    edits = []
    if existing:
        edits.append(('delete', 'firewall.management_wan', None))
    edits += forwarding(True)
    if 'management_web' in firewall:
        edits.append(('delete', 'firewall.management_web', None))
    edits += [('set', 'firewall.management_web', 'rule')]
    edits += [('set', 'firewall.management_web.' + key, value) for key, value in
              dict(name='USB settings', src='management', proto='tcp', dest_port='8081',
                   family='ipv4', target='ACCEPT').items()]
    if 'management_dns' in firewall:
        edits.append(('delete', 'firewall.management_dns', None))
    edits += [('set', 'firewall.management_dns', 'rule')]
    edits += [('set', 'firewall.management_dns.' + key, value) for key, value in
              dict(name='USB DNS', src='management', proto='tcp udp', dest_port='53',
                   family='ipv4', target='ACCEPT', enabled='1').items()]
    dhcp_edits = []
    if 'dhcp_option' in dhcp['management']:
        dhcp_edits.append(('delete', 'dhcp.management.dhcp_option', None))
    options = ['3,192.168.7.1', '6,192.168.7.1'] if data['enabled'] else ['3', '6']
    dhcp_edits += [('add_list', 'dhcp.management.dhcp_option', value) for value in options]
    originals = {p: (platform.CONFIG / p).read_text() for p in ('dhcp', 'firewall')}
    try:
        platform.transaction('dhcp', dhcp_edits, lambda: None, atomic_write)
        platform.transaction('firewall', edits, lambda: platform.run('fw4', 'check'), atomic_write)
    except Exception:
        for package, original in originals.items():
            if (platform.CONFIG / package).read_text() != original:
                atomic_write(platform.CONFIG / package, original)
        raise
    return status(platform)


def recovery_plans(network, dhcp, firewall):
    """Restore the board's existing USB gadget to management-only defaults."""
    device = network.get('management', {}).get('device', 'usb0')
    if not re.fullmatch(r'usb[0-9]+', device):
        # This hardware profile's gadget is usb0; do not adopt another interface.
        device = 'usb0'
    edits = {p: [] for p in ('network', 'dhcp', 'firewall')}

    def section(package, name, kind, options, lists=None):
        values = dict(network=network, dhcp=dhcp, firewall=firewall)[package]
        if name in values:
            edits[package].append(('delete', package + '.' + name, None))
        edits[package].append(('set', package + '.' + name, kind))
        edits[package] += [('set', package + '.' + name + '.' + k, v) for k, v in options.items()]
        for key, entries in (lists or {}).items():
            edits[package] += [('add_list', package + '.' + name + '.' + key, v) for v in entries]

    section('network', 'management', 'interface', dict(device=device, proto='static',
            ipaddr='192.168.7.1', netmask='255.255.255.0', disabled='0'))
    section('dhcp', 'management', 'dhcp', dict(interface='management', ignore='0',
            start='100', limit='51', leasetime='12h', dhcpv6='disabled', ra='disabled', ndp='disabled'),
            {'dhcp_option': ['3', '6']})  # Suppress default gateway and DNS advertisements.
    interfaces = dhcp['router_dns'].get('interface', [])
    interfaces = interfaces.split() if isinstance(interfaces, str) else interfaces
    if interfaces and 'management' not in interfaces:
        edits['dhcp'].append(('add_list', 'dhcp.router_dns.interface', 'management'))
    excluded = dhcp['router_dns'].get('notinterface', [])
    excluded = excluded.split() if isinstance(excluded, str) else excluded
    if 'management' in excluded:
        edits['dhcp'].append(('delete', 'dhcp.router_dns.notinterface', None))
        edits['dhcp'] += [('add_list', 'dhcp.router_dns.notinterface', value)
                         for value in excluded if value != 'management']
    section('firewall', 'management', 'zone', dict(name='management', input='REJECT',
            output='ACCEPT', forward='REJECT'), {'network': ['management']})
    for name, options in {
        'management_dhcp': dict(proto='udp', src_port='68', dest_port='67'),
        'management_admin': dict(proto='tcp', dest_port='22 80 443 8081'),
        'management_ping': dict(proto='icmp'),
    }.items():
        section('firewall', name, 'rule', dict(name='USB ' + name, src='management',
                family='ipv4', target='ACCEPT') | options)
    if 'management_wan' in firewall:
        edits['firewall'].append(('delete', 'firewall.management_wan', None))
    edits['firewall'] += forwarding(True)
    section('firewall', 'management_dns', 'rule', dict(name='USB DNS', src='management',
            proto='tcp udp', dest_port='53', family='ipv4', target='ACCEPT'))
    return edits
