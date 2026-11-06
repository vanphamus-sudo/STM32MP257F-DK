"""One managed OpenVPN client. Certificate contents never leave this module."""
import ipaddress
import json
import re
import subprocess
import tempfile
from pathlib import Path

STATE = Path('/etc/router-web/openvpn')
CONFIG = Path('/etc/config')
FILES = {'ca': 'ca.crt', 'cert': 'client.crt', 'key': 'client.key', 'tls': 'ta.key'}
CONNECTED = Path('/var/run/router-openvpn.connected')
DEFAULTS = dict(enabled=False, remote='3.24.63.90', port=1197, protocol='udp',
                cipher='AES-256-GCM', auth='SHA256', keepalive='10 120',
                nobind=True, tls_mode='none', server_fingerprint='', vpn_subnet='10.87.0.0/24')


def command(*args, input=None):
    return subprocess.run(args, input=input, text=True, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=15).stdout.strip()


def current():
    path = STATE / 'settings.json'
    return DEFAULTS | (json.loads(path.read_text()) if path.exists() else {})


def validate(data):
    if set(data) != set(DEFAULTS):
        raise ValueError('Unexpected OpenVPN settings.')
    result = dict(data)
    if type(data['enabled']) is not bool or type(data['nobind']) is not bool:
        raise ValueError('Enable and nobind must be on or off.')
    remote = data['remote']
    if not isinstance(remote, str) or len(remote) > 253 or not re.fullmatch(
            r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', remote):
        raise ValueError('Enter a valid destination IPv4 address or DNS name.')
    if re.fullmatch(r'[0-9.]+', remote):
        try:
            address = ipaddress.IPv4Address(remote)
            if address.is_unspecified or address.is_multicast or address.is_loopback:
                raise ValueError()
        except ValueError:
            raise ValueError('Enter a usable destination IPv4 address.') from None
    elif any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
             for label in remote.split('.')):
        raise ValueError('Enter a valid DNS name.')
    if type(data['port']) is not int or not 1 <= data['port'] <= 65535:
        raise ValueError('Port must be 1–65535.')
    for field, allowed in [('protocol', ('udp', 'tcp')), ('cipher', ('AES-256-CBC', 'AES-128-CBC', 'AES-256-GCM', 'AES-128-GCM')),
                           ('auth', ('SHA256', 'SHA1', 'SHA512')), ('tls_mode', ('none', 'auth', 'crypt'))]:
        if data[field] not in allowed:
            raise ValueError('Unsupported ' + field + '.')
    if not isinstance(data['keepalive'], str) or not re.fullmatch(r'[0-9]{1,4} [0-9]{1,4}', data['keepalive']):
        raise ValueError('Keepalive must be two seconds values, for example 10 120.')
    ping, timeout = map(int, data['keepalive'].split())
    if not 1 <= ping < timeout <= 3600:
        raise ValueError('Keepalive needs a ping interval below its timeout, at most 3600 seconds.')
    pin = data['server_fingerprint']
    if not isinstance(pin, str) or (pin and not (re.fullmatch(r'[0-9a-fA-F]{64}', pin) or
                                               re.fullmatch(r'(?:[0-9a-fA-F]{2}:){31}[0-9a-fA-F]{2}', pin))):
        raise ValueError('Server fingerprint must be a SHA256 certificate fingerprint.')
    compact = pin.replace(':', '').upper()
    result['server_fingerprint'] = ':'.join(compact[n:n+2] for n in range(0, len(compact), 2))
    try:
        if not isinstance(data['vpn_subnet'], str):
            raise ValueError()
        subnet = ipaddress.IPv4Network(data['vpn_subnet'], strict=True)
        if subnet.prefixlen < 8 or subnet.overlaps(ipaddress.IPv4Network('192.168.7.0/24')) or \
                subnet.overlaps(ipaddress.IPv4Network('192.168.10.0/24')) or \
                subnet.overlaps(ipaddress.IPv4Network('192.168.20.0/24')):
            raise ValueError()
    except ValueError:
        raise ValueError('Enter a VPN IPv4 subnet in CIDR form, without overlapping the router LANs.') from None
    return result


def openssl(*args):
    try:
        return command('openssl', *args)
    except (subprocess.SubprocessError, OSError):
        raise ValueError('Invalid certificate or key; use an unencrypted PEM file.') from None


def validate_file(kind, content):
    if not isinstance(kind, str) or kind not in FILES or not isinstance(content, str) or not 1 <= len(content) <= 16384 or '\x00' in content:
        raise ValueError('Choose a CA, client certificate, private key or TLS key, at most 16 KB.')
    content = content.replace('\r\n', '\n').strip() + '\n'
    if kind == 'tls':
        if not re.fullmatch(r'(?:#[^\n]*\n)*-----BEGIN OpenVPN Static key V1-----\n(?:[0-9a-fA-F]{32}\n){16}-----END OpenVPN Static key V1-----\n', content):
            raise ValueError('Choose an OpenVPN Static key V1 file.')
        return content
    label = 'CERTIFICATE' if kind in ('ca', 'cert') else '(?:RSA |EC )?PRIVATE KEY'
    # Easy-RSA exports can contain a text description before the PEM block.
    blocks = re.findall(r'-----BEGIN (' + label + r')-----\s+[A-Za-z0-9+/=\s]+?-----END \1-----', content)
    match = re.search(r'-----BEGIN (' + label + r')-----\s+[A-Za-z0-9+/=\s]+?-----END \1-----', content)
    if not match or len(blocks) != 1:
        raise ValueError('Choose one unencrypted PEM certificate or key.')
    content = match.group(0) + '\n'
    with tempfile.TemporaryDirectory(prefix='router-cert-') as temporary:
        path = Path(temporary) / 'input.pem'
        path.write_text(content)
        path.chmod(0o600)
        if kind == 'key':
            openssl('pkey', '-in', str(path), '-passin', 'pass:', '-check', '-noout')
        else:
            openssl('x509', '-in', str(path), '-noout', '-checkend', '0')
    return content


def check_material(settings):
    needed = ['cert', 'key'] + ([] if settings['server_fingerprint'] else ['ca'])
    if settings['tls_mode'] != 'none':
        needed.append('tls')
    if any(not (STATE / FILES[kind]).exists() for kind in needed):
        raise ValueError('Import the required certificates and keys before enabling OpenVPN.')
    certificate = openssl('x509', '-in', str(STATE / FILES['cert']), '-pubkey', '-noout')
    key = openssl('pkey', '-in', str(STATE / FILES['key']), '-passin', 'pass:', '-pubout')
    if certificate != key:
        raise ValueError('The client certificate and private key do not match.')
    openssl('x509', '-in', str(STATE / FILES['cert']), '-noout', '-checkend', '0')


def render(settings):
    subnet = ipaddress.IPv4Network(settings['vpn_subnet'])
    lines = ['client', 'dev tun-router', 'dev-type tun', 'proto ' + ('udp4' if settings['protocol'] == 'udp' else 'tcp4-client'),
             f"remote {settings['remote']} {settings['port']}", 'resolv-retry infinite', 'persist-key', 'persist-tun',
             'auth ' + settings['auth'], 'cipher ' + settings['cipher'],
             'data-ciphers AES-256-GCM:AES-128-GCM:' + settings['cipher'],
             'data-ciphers-fallback ' + settings['cipher'], 'allow-compression no', 'keepalive ' + settings['keepalive'],
             'script-security 2', 'up-restart', 'route-nopull', 'verb 3', 'status /var/run/router-openvpn.status 10', 'status-version 2',
             f'route {subnet.network_address} {subnet.netmask} vpn_gateway',
             'cert ' + str(STATE / FILES['cert']), 'key ' + str(STATE / FILES['key'])]
    # Keep LTE as default, and ignore pushed DNS/routes. Only the VPN subnet is reachable.
    # A pin also supports legacy server certificates lacking an EKU; never disable verification.
    if settings['server_fingerprint']:
        lines.append('peer-fingerprint ' + settings['server_fingerprint'])
    else:
        lines += ['ca ' + str(STATE / FILES['ca']), 'remote-cert-tls server']
    if settings['nobind']:
        lines.append('nobind')
    if settings['protocol'] == 'udp':
        lines.append('explicit-exit-notify 1')
    if settings['tls_mode'] != 'none':
        lines.append('tls-' + settings['tls_mode'] + ' ' + str(STATE / FILES['tls']) +
                     (' 1' if settings['tls_mode'] == 'auth' else ''))
    return '\n'.join(lines) + '\n'


def connected_address(pid):
    """Native up/down events distinguish a connection from a persisted TUN."""
    try:
        process, address = CONNECTED.read_text().split()
        if pid and int(process) == pid:
            return str(ipaddress.IPv4Address(address))
    except (OSError, ValueError):
        pass
    return ''


def status(backend):
    if not Path('/etc/init.d/openvpn').exists():
        return dict(available=False)
    result = current()
    certificates = {}
    for kind, filename in FILES.items():
        path = STATE / filename
        item = dict(present=path.exists(), name=filename)
        if item['present'] and kind in ('ca', 'cert'):
            try:
                item['details'] = openssl('x509', '-in', str(path), '-noout', '-subject', '-enddate')
            except ValueError:
                item['details'] = 'Invalid certificate'
        certificates[kind] = item
    instances = backend.ubus('service', 'list', name='openvpn').get('openvpn', {}).get('instances', {})
    running = bool(instances.get('router_vpn', {}).get('running'))
    address = connected_address(instances['router_vpn'].get('pid')) if result['enabled'] and running else ''
    result.update(available=True, certificates=certificates, local_ip=address,
                  state='connected' if address else ('connecting' if running else 'stopped') if result['enabled'] else 'disabled')
    return result


def reload_client():
    # Reload reconciles procd instances and leaves unrelated VPN clients intact.
    subprocess.run(['/etc/init.d/openvpn', 'reload'], check=True, timeout=30,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def import_certificate(data, backend, atomic_write):
    if set(data) != {'kind', 'content'}:
        raise ValueError('Unexpected certificate fields.')
    content = validate_file(data['kind'], data['content'])
    if current()['enabled']:
        raise ValueError('Disable OpenVPN before replacing a certificate or key.')
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE.chmod(0o700)
    atomic_write(STATE / FILES[data['kind']], content)
    return status(backend)


def toggle(data, backend, atomic_write):
    if set(data) != {'enabled'} or type(data['enabled']) is not bool:
        raise ValueError('Enable must be on or off.')
    return apply(current() | {'enabled': data['enabled']}, backend, atomic_write)


def apply(data, backend, atomic_write):
    settings = validate(data)
    if not Path('/etc/init.d/openvpn').exists():
        raise ValueError('Install the OpenWrt OpenVPN package first.')
    if settings['enabled']:
        check_material(settings)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE.chmod(0o700)
    packages = ('openvpn', 'firewall')
    original = {CONFIG / name: (CONFIG / name).read_text() for name in packages}
    for name in ('settings.json', 'client.conf'):
        path = STATE / name
        original[path] = path.read_text() if path.exists() else None
    for package in packages:
        if backend.run('uci', 'changes', package):
            raise ValueError('Apply or revert pending OpenVPN/firewall changes first.')
    # Stage both UCI packages before publishing anything.
    with tempfile.TemporaryDirectory(prefix='router-vpn-') as temporary:
        directory = Path(temporary)
        delta = directory / 'delta'
        delta.mkdir()
        for name in packages:
            atomic_write(directory / name, original[CONFIG / name])
        edits = [('openvpn.router_vpn', 'openvpn'), ('openvpn.router_vpn.enabled', '1' if settings['enabled'] else '0'),
                 ('openvpn.router_vpn.config', str(STATE / 'client.conf')),
                 ('firewall.router_vpn', 'zone'), ('firewall.router_vpn.name', 'router_vpn'),
                 ('firewall.router_vpn.device', 'tun-router'), ('firewall.router_vpn.input', 'REJECT'),
                 ('firewall.router_vpn.output', 'ACCEPT'), ('firewall.router_vpn.forward', 'REJECT'),
                 ('firewall.router_vpn.masq', '1'), ('firewall.router_vpn.mtu_fix', '1'),
                 ('firewall.router_vpn_lan', 'forwarding'), ('firewall.router_vpn_lan.src', 'lan'),
                 ('firewall.router_vpn_lan.dest', 'router_vpn'), ('firewall.router_vpn_lan.family', 'ipv4'),
                 ('firewall.router_vpn_ping', 'rule'), ('firewall.router_vpn_ping.name', 'VPN ping'),
                 ('firewall.router_vpn_ping.src', 'router_vpn'), ('firewall.router_vpn_ping.proto', 'icmp'),
                 ('firewall.router_vpn_ping.icmp_type', 'echo-request'), ('firewall.router_vpn_ping.family', 'ipv4'),
                 ('firewall.router_vpn_ping.target', 'ACCEPT')]
        for name in ('openvpn.router_vpn', 'firewall.router_vpn', 'firewall.router_vpn_lan', 'firewall.router_vpn_ping'):
            package, section = name.split('.')
            if section in backend.values(package):
                backend.run('uci', '-c', str(directory), '-t', str(delta), 'delete', name)
        for key, value in edits:
            backend.run('uci', '-c', str(directory), '-t', str(delta), 'set', key + '=' + value)
        for package in packages:
            backend.run('uci', '-c', str(directory), '-t', str(delta), 'commit', package)
        candidates = {CONFIG / name: (directory / name).read_text() for name in packages}
    for package in packages:
        if (CONFIG / package).read_text() != original[CONFIG / package] or backend.run('uci', 'changes', package):
            raise ValueError('Configuration changed during apply; retry.')
    candidates[STATE / 'settings.json'] = json.dumps(settings)
    candidates[STATE / 'client.conf'] = render(settings)
    for path, value in original.items():
        if value is not None:
            atomic_write(STATE / (path.name + '.previous'), value)
    try:
        for path, value in candidates.items():
            atomic_write(path, value)
        backend.run('fw4', 'check')
        backend.run('/etc/init.d/firewall', 'reload')
        reload_client()
        backend.run('/etc/init.d/openvpn', 'enable')
    except Exception:
        for path, value in original.items():
            if value is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, value)
        backend.run('/etc/init.d/firewall', 'reload')
        reload_client()
        raise
    return status(backend)
