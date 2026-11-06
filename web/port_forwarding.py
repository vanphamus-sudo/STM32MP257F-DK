"""Managed IPv4 DNAT rules, applied through the existing UCI transaction."""
import hashlib
import ipaddress
import json
import re

PREFIX = 'router_pf_'
LIMIT = 100
FIELDS = {'id', 'name', 'enabled', 'protocol', 'source_zone', 'external_port',
          'destination_zone', 'destination_ip', 'internal_port', 'source_ip',
          'external_ip', 'reflection'}
NETWORKS = {'lan': ipaddress.ip_network('192.168.10.0/24'),
            'hotspot': ipaddress.ip_network('192.168.20.0/24')}
SOURCES = {'wan', 'router_vpn'}
DMZ_SECTION = 'router_dmz'
DMZ_DEFAULT = dict(enabled=False, destination_zone='lan', destination_ip='')


def destination(zone, value):
    if not isinstance(zone, str) or zone not in NETWORKS:
        raise ValueError('Choose LAN or hotspot as the destination zone.')
    value = address(value)
    if not value or ipaddress.ip_address(value) not in NETWORKS[zone] or int(ipaddress.ip_address(value)) & 255 in (0, 1, 255):
        raise ValueError('Destination must be a client address in the selected LAN or hotspot subnet.')
    return value


def dmz_current(config):
    section = config.get(DMZ_SECTION, {})
    return dict(enabled=section.get('enabled', '0') == '1',
                destination_zone=section.get('dest', 'lan'), destination_ip=section.get('dest_ip', ''))


def normalize_dmz(data, zones):
    if not isinstance(data, dict) or set(data) != set(DMZ_DEFAULT) or type(data['enabled']) is not bool:
        raise ValueError('Supply DMZ enabled, destination zone and destination IPv4 address.')
    data = dict(data)
    if not isinstance(data['destination_zone'], str) or data['destination_zone'] not in NETWORKS or data['destination_zone'] not in zones:
        raise ValueError('Choose an available LAN or hotspot DMZ destination.')
    if not isinstance(data['destination_ip'], str):
        raise ValueError('Enter the DMZ client IPv4 address.')
    if data['enabled'] or data['destination_ip']:
        data['destination_ip'] = destination(data['destination_zone'], data['destination_ip'])
    if data['enabled'] and 'wan' not in zones:
        raise ValueError('DMZ requires the WAN firewall zone.')
    return data


def revision(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def ports(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,5}(?:-[0-9]{1,5})?', value):
        raise ValueError('Use a port from 1 to 65535 or a range such as 8000-8010.')
    bounds = list(map(int, value.split('-')))
    lo, hi = bounds[0], bounds[-1]
    if not 1 <= lo <= hi <= 65535:
        raise ValueError('Port ranges must be ascending and within 1-65535.')
    return lo, hi


def address(value, network=False):
    if not isinstance(value, str):
        raise ValueError('Addresses must be IPv4 text.')
    if not value:
        return ''
    try:
        parsed = ipaddress.IPv4Network(value, strict=False) if network else ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError('Enter a valid IPv4 address' + (' or subnet.' if network else '.')) from None
    if not network and (parsed.is_unspecified or parsed.is_multicast or parsed.is_loopback or parsed.is_link_local or int(parsed) == 0xffffffff):
        raise ValueError('Use a unicast IPv4 address.')
    return str(parsed)


def normalize(rule, sources):
    if not isinstance(rule, dict) or set(rule) != FIELDS:
        raise ValueError('Each rule must contain all supported fields and no unknown fields.')
    rule = dict(rule)
    if any(not isinstance(rule[field], str) for field in FIELDS - {'enabled', 'reflection'}):
        raise ValueError('Rule fields must be text, except enabled and NAT loopback.')
    if not isinstance(rule['id'], str) or not re.fullmatch(r'[a-f0-9]{16}', rule['id']):
        raise ValueError('Invalid rule identifier.')
    if not isinstance(rule['name'], str) or not 1 <= len(rule['name'].strip()) <= 64 or any(ord(c) < 32 or ord(c) == 127 for c in rule['name']):
        raise ValueError('Rule names require 1-64 characters without control characters.')
    rule['name'] = rule['name'].strip()
    if type(rule['enabled']) is not bool or type(rule['reflection']) is not bool:
        raise ValueError('Enabled and NAT loopback must be booleans.')
    if rule['protocol'] not in ('tcp', 'udp', 'tcp udp'):
        raise ValueError('Choose TCP, UDP, or TCP + UDP.')
    if rule['source_zone'] not in sources or rule['destination_zone'] not in NETWORKS:
        raise ValueError('Choose an available incoming zone and LAN or hotspot destination.')
    external, internal = ports(rule['external_port']), ports(rule['internal_port'])
    if external[1]-external[0] != internal[1]-internal[0]:
        raise ValueError('External and internal ranges must contain the same number of ports.')
    rule['destination_ip'] = destination(rule['destination_zone'], rule['destination_ip'])
    rule['source_ip'] = address(rule['source_ip'], network=True)
    rule['external_ip'] = address(rule['external_ip'])
    if rule['reflection'] and rule['source_zone'] != 'wan':
        raise ValueError('NAT loopback is supported for WAN rules only.')
    return rule


def overlap(a, b):
    return (a['source_zone'] == b['source_zone'] and
            bool(set(a['protocol'].split()) & set(b['protocol'].split())) and
            max(ports(a['external_port'])[0], ports(b['external_port'])[0]) <= min(ports(a['external_port'])[1], ports(b['external_port'])[1]) and
            (not a['external_ip'] or not b['external_ip'] or a['external_ip'] == b['external_ip']) and
            ipaddress.ip_network(a['source_ip'] or '0.0.0.0/0').overlaps(ipaddress.ip_network(b['source_ip'] or '0.0.0.0/0')))


def decode(key, section):
    protocol = section.get('proto', 'tcp udp')
    if isinstance(protocol, list):
        protocol = ' '.join(protocol)
    return dict(id=key.removeprefix(PREFIX), name=section.get('name', key),
                enabled=section.get('enabled', '1') != '0', protocol=protocol,
                source_zone=section.get('src', 'wan'), external_port=section.get('src_dport', ''),
                destination_zone=section.get('dest', 'lan'), destination_ip=section.get('dest_ip', ''),
                internal_port=section.get('dest_port', section.get('src_dport', '')),
                source_ip=section.get('src_ip', ''), external_ip=section.get('src_dip', ''),
                reflection=section.get('reflection', '1') == '1')


def status(backend):
    config = backend.values('firewall')
    zones = {s.get('name') for s in config.values() if s.get('.type') == 'zone'}
    sources = sorted(zones & SOURCES)
    rules, unmanaged = [], []
    for key, section in config.items():
        if key == DMZ_SECTION:
            continue
        if section.get('.type') == 'redirect':
            item = decode(key, section)
            if key.startswith(PREFIX) and re.fullmatch(r'[a-f0-9]{16}', item['id']):
                rules.append(item)
            else:
                unmanaged.append(dict(name=item['name'], source_zone=item['source_zone'],
                                      external_port=item['external_port'], enabled=item['enabled']))
    return dict(available=True, revision=revision(config), rules=rules, unmanaged=unmanaged,
                source_zones=sources, destination_zones=sorted(zones & NETWORKS.keys()), limit=LIMIT,
                dmz=dmz_current(config))


def apply(data, backend, atomic_write):
    if set(data) not in ({'revision', 'rules'}, {'revision', 'rules', 'dmz'}) or not isinstance(data['rules'], list) or len(data['rules']) > LIMIT:
        raise ValueError('Supply a revision and at most 100 forwarding rules.')
    config = backend.values('firewall')
    if data['revision'] != revision(config):
        raise RuntimeError('Firewall settings changed. Reload rules before saving.')
    zones = {s.get('name') for s in config.values() if s.get('.type') == 'zone'}
    if DMZ_SECTION in config and config[DMZ_SECTION].get('.type') != 'redirect':
        raise ValueError('An unrecognized DMZ firewall section needs review in LuCI.')
    # Older clients and version 1 imports must not silently remove a DMZ host.
    dmz = normalize_dmz(data.get('dmz', dmz_current(config)), zones)
    if dmz['enabled']:
        for key, section in config.items():
            if (key != DMZ_SECTION and not key.startswith(PREFIX) and section.get('.type') == 'redirect'
                    and section.get('enabled', '1') != '0' and section.get('src') == 'wan'
                    and section.get('family', 'any') != 'ipv6' and not section.get('src_dport')):
                raise ValueError('Review the existing all-port WAN redirect in LuCI before enabling DMZ.')
    rules = [normalize(rule, zones & SOURCES) for rule in data['rules']]
    if len({r['id'] for r in rules}) != len(rules):
        raise ValueError('Rule identifiers must be unique.')
    if any(r['destination_zone'] not in zones for r in rules):
        raise ValueError('The destination firewall zone is unavailable.')
    for i, rule in enumerate(rules):
        if not rule['enabled']:
            continue
        for other in rules[:i]:
            if other['enabled'] and overlap(rule, other):
                raise ValueError('Enabled rules overlap: '+other['name']+' / '+rule['name'])
        # Preserve third-party rules, but refuse ambiguous overlaps with them.
        for key, section in config.items():
            if key == DMZ_SECTION or section.get('.type') != 'redirect' or key.startswith(PREFIX) or section.get('enabled', '1') == '0':
                continue
            if section.get('src') != rule['source_zone'] or section.get('family', 'any') == 'ipv6':
                continue
            other = decode(key, section)
            try:
                if other['protocol'] in ('all', 'any', '*'):
                    other['protocol'] = 'tcp udp'
                if not isinstance(other['protocol'], str) or not set(other['protocol'].split()) <= {'tcp', 'udp'}:
                    raise ValueError('Review the existing redirect protocol in LuCI: '+other['name'])
                other['external_port'] = other['external_port'] or '1-65535'
                if overlap(rule, other):
                    raise ValueError('Rule conflicts with an existing firewall redirect: '+other['name'])
            except (TypeError, ipaddress.AddressValueError):
                raise ValueError('Review the existing redirect in LuCI before adding overlapping rules.') from None
    edits = []
    if DMZ_SECTION in config:
        edits.append(('delete', 'firewall.'+DMZ_SECTION, None))
    for key in config:
        if key.startswith(PREFIX):
            if config[key].get('.type') != 'redirect' or not re.fullmatch(PREFIX+r'[a-f0-9]{16}', key):
                raise ValueError('An unrecognized managed firewall section needs review in LuCI.')
            edits.append(('delete', 'firewall.'+key, None))
    for r in rules:
        key = 'firewall.'+PREFIX+r['id']
        edits.append(('set', key, 'redirect'))
        options = dict(name=r['name'], enabled='1' if r['enabled'] else '0', family='ipv4',
                       target='DNAT', src=r['source_zone'], dest=r['destination_zone'],
                       proto=r['protocol'], src_dport=r['external_port'], dest_ip=r['destination_ip'],
                       dest_port=r['internal_port'], reflection='1' if r['reflection'] else '0')
        if r['source_ip']:
            options['src_ip'] = r['source_ip']
        if r['external_ip']:
            options['src_dip'] = r['external_ip']
        if r['reflection']:
            options['reflection_src'] = 'internal'
        edits.extend(('set', key+'.'+name, value) for name, value in options.items())
    # Recreate last so every specific redirect (managed or third-party) wins.
    # No destination port means transport ports are preserved, for all protocols.
    if dmz['enabled'] or dmz['destination_ip']:
        key = 'firewall.'+DMZ_SECTION
        edits.append(('set', key, 'redirect'))
        options = dict(name='Router DMZ host', enabled='1' if dmz['enabled'] else '0', family='ipv4',
                       target='DNAT', src='wan', dest=dmz['destination_zone'], proto='all',
                       dest_ip=dmz['destination_ip'], reflection='0')
        edits.extend(('set', key+'.'+name, value) for name, value in options.items())
    def activate():
        backend.run('fw4', 'check')
        backend.run('/etc/init.d/firewall', 'reload')
        backend.run('nft', 'list', 'table', 'inet', 'fw4')
    backend.transaction('firewall', edits, activate, atomic_write)
    return status(backend)
