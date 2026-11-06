"""LAN MAC-to-IPv4 DHCP reservations managed through private UCI transactions."""
import fnmatch
import hashlib
import ipaddress
import json
import re
import time

PREFIX = 'router_lease_'
LAN = ipaddress.ip_network('192.168.10.0/24')
FIELDS = {'id', 'hostname', 'mac', 'ip'}
LIMIT = 100


def revision(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def mac(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', value.replace('-', ':')):
        raise ValueError('Enter a MAC address such as 00:11:22:33:44:55.')
    value = value.replace('-', ':').lower()
    if int(value[:2], 16) & 1 or value == '00:00:00:00:00:00':
        raise ValueError('Use a nonzero unicast device MAC address.')
    return value


def normalize(item):
    if not isinstance(item, dict) or set(item) != FIELDS or any(not isinstance(item[k], str) for k in FIELDS):
        raise ValueError('Supply an identifier, hostname, MAC address and LAN IP for each binding.')
    item = dict(item)
    if not re.fullmatch(r'[a-f0-9]{16}', item['id']):
        raise ValueError('Invalid binding identifier.')
    hostname = item['hostname']
    if hostname and not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', hostname):
        raise ValueError('Optional hostname: 1-63 letters, digits or hyphens; begin and end with a letter or digit.')
    item['hostname'] = hostname.lower()
    item['mac'] = mac(item['mac'])
    try:
        ip = ipaddress.IPv4Address(item['ip'])
    except ValueError:
        raise ValueError('Choose a LAN IP from 192.168.10.2 to 192.168.10.254.') from None
    if ip not in LAN or int(ip) & 255 in (0, 1, 255):
        raise ValueError('Choose a LAN IP from 192.168.10.2 to 192.168.10.254.')
    item['ip'] = str(ip)
    return item


def tokens(value):
    return [part for value in (value if isinstance(value, list) else [value])
            for part in str(value).split()]


def leases(backend):
    result = []
    try:
        lines = backend.LEASES.read_text().splitlines()
    except FileNotFoundError:
        return result
    for line in lines:
        fields = line.split()
        try:
            expiry, hardware, ip, hostname = fields[:4]
            if (int(expiry) == 0 or int(expiry) > time.time()) and ipaddress.IPv4Address(ip) in LAN:
                result.append(dict(mac=mac(hardware), ip=ip, hostname='' if hostname == '*' else hostname))
        except (ValueError, TypeError):
            continue
    return result


def status(backend):
    config = backend.values('dhcp')
    bindings, unmanaged = [], []
    for key, section in config.items():
        if section.get('.type') != 'host':
            continue
        if re.fullmatch(PREFIX+r'[a-f0-9]{16}', key):
            hardware = tokens(section.get('mac', ''))
            bindings.append(dict(id=key.removeprefix(PREFIX), hostname=section.get('name', ''),
                                 mac=' '.join(hardware), ip=section.get('ip', '')))
        else:
            unmanaged.append(dict(hostname=section.get('name', key), mac=' '.join(tokens(section.get('mac', ''))),
                                  ip=' '.join(tokens(section.get('ip', '')))))
    return dict(available=True, revision=revision(config), bindings=bindings, unmanaged=unmanaged,
                leases=leases(backend), lan_enabled=config.get('lan', {}).get('ignore', '0') != '1', limit=LIMIT)


def apply(data, backend, atomic_write):
    if set(data) != {'revision', 'bindings'} or not isinstance(data['bindings'], list) or len(data['bindings']) > LIMIT:
        raise ValueError('Supply the DHCP revision and at most 100 bindings.')
    config = backend.values('dhcp')
    if data['revision'] != revision(config):
        raise RuntimeError('DHCP settings changed. Reload bindings before saving.')
    if config.get('router_dns', {}).get('.type') != 'dnsmasq':
        raise ValueError('The router DNS/DHCP instance is unavailable.')
    items = [normalize(item) for item in data['bindings']]
    for field in ('id', 'mac', 'ip', 'hostname'):
        values = [item[field] for item in items if item[field]]
        if len(values) != len(set(values)):
            raise ValueError('Each binding must have a unique '+field+'.')
    current_leases = leases(backend)
    for item in items:
        for lease in current_leases:
            if lease['ip'] == item['ip'] and lease['mac'] != item['mac']:
                raise ValueError('That LAN IP is currently leased to another MAC. Release its lease or choose another address.')
        for key, section in config.items():
            if section.get('.type') != 'host' or key.startswith(PREFIX):
                continue
            hardware = [m.lower().replace('-', ':') for m in tokens(section.get('mac', ''))]
            if (item['ip'] in tokens(section.get('ip', '')) or
                    any(fnmatch.fnmatchcase(item['mac'], pattern) for pattern in hardware) or
                    (item['hostname'] and item['hostname'] == section.get('name', '').lower())):
                raise ValueError('Binding conflicts with an existing static lease managed in LuCI: '+section.get('name', key))
    # Validate the supplied static-host syntax without binding sockets or issuing leases.
    args = ['dnsmasq', '--test', '--conf-file=/dev/null']
    for item in items:
        args.append('--dhcp-host='+','.join(filter(None, (item['mac'], item['ip'], item['hostname']))))
    backend.run(*args)
    edits = []
    for key, section in config.items():
        if key.startswith(PREFIX):
            if section.get('.type') != 'host' or not re.fullmatch(PREFIX+r'[a-f0-9]{16}', key):
                raise ValueError('An unrecognized binding section needs review in LuCI.')
            edits.append(('delete', 'dhcp.'+key, None))
    for item in items:
        key = 'dhcp.'+PREFIX+item['id']
        edits += [('set', key, 'host'), ('set', key+'.mac', item['mac']), ('set', key+'.ip', item['ip']),
                  ('set', key+'.instance', 'router_dns')]
        if item['hostname']:
            edits.append(('set', key+'.name', item['hostname']))
    backend.transaction('dhcp', edits, backend.restart_dns, atomic_write)
    return status(backend)
