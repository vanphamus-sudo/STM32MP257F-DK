"""OpenWrt adapter: UCI configuration, netifd status and procd services.

Only DHCP and the dedicated router_ap wifi-iface are editable through this API.
The initial network/firewall setup belongs to openwrt/provision.py.
"""
import json
import re
from pathlib import Path
import subprocess
import tempfile
import time
import threading

import wifi
import version_info

CONFIG = Path('/etc/config')
STATE = Path('/etc/router-web')
LEASES = Path('/tmp/dhcp.leases')
AT_LOCK = threading.Lock()


def send_at(data):
    command = data.get('command')
    if set(data) != {'command'} or not isinstance(command, str) or not 2 <= len(command) <= 256 or not command.upper().startswith('AT') or any(ord(c) < 32 or ord(c) > 126 for c in command):
        raise ValueError('Enter one AT command, 2–256 printable ASCII characters, without line breaks.')
    reserved = version_info.reserved_response(command)
    if reserved is not None:
        return dict(command=command, response=reserved.decode('ascii'), ok=command.upper() == 'AT$VERSION', truncated=False)
    if not AT_LOCK.acquire(blocking=False):
        raise RuntimeError('Another AT command is in progress. Wait for its response.')
    try:
        device = values('network')['wan']['device']
        result = subprocess.run(['mmcli', '-m', device, '--command=' + command, '--timeout=10'],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        output = result.stdout.strip()
        if 'Operation only allowed in debug mode' in output:
            raise RuntimeError('AT access is not enabled in ModemManager. Run the AT setup script on the router.')
        return dict(command=command, response=output[:8192] or '(empty response)',
                    ok=result.returncode == 0, truncated=len(output) > 8192)
    except subprocess.TimeoutExpired:
        raise RuntimeError('The modem did not respond within 15 seconds. The command may have been executed.') from None
    finally:
        AT_LOCK.release()


def run(*args):
    # Never interpret SSIDs, keys or UCI values as shell code.
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=30).strip()


def ubus(obj, method, **args):
    return json.loads(run('ubus', 'call', obj, method, json.dumps(args)))


def values(package):
    return ubus('uci', 'get', config=package)['values']


def service_active(name):
    data = ubus('service', 'list', name=name)
    return any(instance.get('running') for instance in data.get(name, {}).get('instances', {}).values())


def settings():
    data = values('dhcp')
    lan = data['lan']
    start = int(lan['start'])
    return dict(start=f'192.168.10.{start}', end=f"192.168.10.{start + int(lan['limit']) - 1}",
                lease_hours=int(lan['leasetime'].removesuffix('h')), dns=data['router_dns']['server'])


def ddns_status():
    if not Path('/etc/init.d/ddns').exists() or not (CONFIG / 'ddns').exists():
        return dict(available=False)
    configs = values('ddns')
    config = configs.get('router_ddns', {})
    instances = ubus('service', 'list', name='ddns').get('ddns', {}).get('instances', {})
    enabled = config.get('enabled', '0') == '1'
    running = bool(instances.get('router_ddns', {}).get('running'))
    # OpenWrt 24.10's DDNS scripts use PID files rather than procd instances.
    if not running:
        directory = Path(configs.get('global', {}).get('ddns_rundir', '/var/run/ddns'))
        try:
            pid = int((directory / 'router_ddns.pid').read_text().strip())
            if pid > 1:
                command = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
                running = any(arg.endswith(b'/dynamic_dns_updater.sh') for arg in command) and b'router_ddns' in command
        except (OSError, ValueError):
            pass
    return dict(available=True, enabled=enabled, provider=config.get('service_name', 'dyndns.org'),
                hostname=config.get('lookup_host', ''), username=config.get('username', ''),
                password_saved=bool(config.get('password')),
                state=('running' if running else 'stopped')
                if enabled else 'disabled')


def restart_ddns():
    # Background updater children inherit stdout. A captured pipe stays open for
    # their entire lifetime, making check_output time out after a successful start.
    subprocess.run(['/etc/init.d/ddns', 'restart'], check=True, timeout=30,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_ddns(data, atomic_write):
    if set(data) != {'enabled', 'provider', 'hostname', 'username', 'password'} or type(data['enabled']) is not bool:
        raise ValueError('Supply the DDNS provider, hostname and credentials.')
    if data['provider'] not in ('dyndns.org', 'no-ip.com'):
        raise ValueError('Choose DynDNS or No-IP.')
    hostname = data['hostname']
    if not isinstance(hostname, str) or len(hostname) > 253 or (hostname and
            ('.' not in hostname or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                                       for label in hostname.split('.')))):
        raise ValueError('Enter a valid DNS hostname.')
    for key in ('username', 'password'):
        value = data[key]
        if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Credentials must contain at most 256 characters without control characters.')
    if not ddns_status()['available']:
        raise ValueError('Install the OpenWrt DDNS packages first.')
    current = values('ddns').get('router_ddns', {})
    password = data['password'] or current.get('password', '')
    if data['enabled'] and not (hostname and data['username'] and password):
        raise ValueError('Hostname, username and password are required to enable DDNS.')
    if data['enabled'] and data['provider'] != current.get('service_name', data['provider']) and not data['password']:
        raise ValueError('Enter the password again when changing providers.')
    options = dict(enabled='1' if data['enabled'] else '0', service_name=data['provider'],
                   lookup_host=hostname, domain=hostname, username=data['username'], password=password,
                   interface='wan', ip_source='web', ip_url='https://api.ipify.org',
                   use_https='1', cacert='/etc/ssl/certs/ca-certificates.crt', use_ipv6='0',
                   check_interval='10', check_unit='minutes', force_interval='72', force_unit='hours',
                   retry_interval='60', retry_unit='seconds', use_syslog='2', use_logfile='0')
    # Recreate only our section, clearing incompatible options left by CLI/LuCI edits.
    edits = [('delete', 'ddns.router_ddns', None)] if current else []
    edits += [('set', 'ddns.router_ddns', 'service')]
    edits += [('set', 'ddns.router_ddns.' + key, value) for key, value in options.items()]
    transaction('ddns', edits, restart_ddns, atomic_write)
    return ddns_status()


def transaction(package, edits, activate, atomic_write):
    """Stage in private UCI dirs; restore the committed file if activation fails.

    Refuse pending LuCI/CLI edits instead of committing someone else's changes.
    The caller holds server.LOCK. Do not edit concurrently from LuCI/SSH.
    """
    if run('uci', 'changes', package):
        raise RuntimeError('Apply or revert pending UCI changes first.')
    path = CONFIG / package
    original = path.read_text()
    with tempfile.TemporaryDirectory(prefix='router-uci-') as temporary:
        directory = Path(temporary)
        saved = directory / 'delta'
        saved.mkdir()
        atomic_write(directory / package, original)
        for command, key, value in edits:
            argument = key if value is None else key + '=' + str(value)
            run('uci', '-c', str(directory), '-t', str(saved), command, argument)
        run('uci', '-c', str(directory), '-t', str(saved), 'commit', package)
        candidate = (directory / package).read_text()
        if path.read_text() != original or run('uci', 'changes', package):
            raise RuntimeError('Configuration changed during apply; retry.')
        atomic_write(STATE / (package + '.previous'), original)
        try:
            atomic_write(path, candidate)
            activate()
        except Exception:
            atomic_write(path, original)
            activate()
            raise


def restart_dns():
    run('/etc/init.d/dnsmasq', 'restart')
    for _ in range(20):
        if service_active('dnsmasq'):
            return
        time.sleep(.25)
    raise RuntimeError('dnsmasq did not start.')


def apply_settings(data, atomic_write):
    start, end = (int(data[key].rsplit('.', 1)[1]) for key in ('start', 'end'))
    edits = [('set', 'dhcp.lan.start', start), ('set', 'dhcp.lan.limit', end - start + 1),
             ('set', 'dhcp.lan.leasetime', str(data['lease_hours']) + 'h'),
             ('set', 'dhcp.router_dns.noresolv', '1'), ('delete', 'dhcp.router_dns.server', None)]
    edits += [('add_list', 'dhcp.router_dns.server', address) for address in data['dns']]
    transaction('dhcp', edits, restart_dns, atomic_write)
    return data


def wifi_current():
    data = values('wireless')
    ap = data['router_ap']
    radio = data[ap['device']]
    return dict(enabled=ap.get('disabled', '0') != '1' and radio.get('disabled', '0') != '1',
                ssid=ap['ssid'], channel=int(radio['channel']), psk=ap.get('key', ''))


def wifi_runtime(expected=None):
    for radio in ubus('network.wireless', 'status').values():
        if radio.get('pending'):
            continue
        for interface in radio.get('interfaces', []):
            if interface.get('section') == 'router_ap' and radio.get('up'):
                if expected and (interface.get('config', {}).get('ssid') != expected['ssid'] or
                                 str(radio.get('config', {}).get('channel')) != str(expected['channel'])):
                    continue
                return interface.get('ifname')
    return None


def wifi_status():
    if 'router_ap' not in values('wireless'):
        return dict(available=False)
    data = wifi_current()
    result = {key: data[key] for key in ('enabled', 'ssid', 'channel')}
    result.update(available=True, state='disabled', clients=0, gateway='192.168.20.1')
    if data['enabled']:
        interface = wifi_runtime()
        result['state'] = 'enabled' if interface else 'unavailable'
        if interface:
            try:
                result['clients'] = len(ubus('hostapd.' + interface, 'get_clients').get('clients', {}))
            except subprocess.SubprocessError:
                pass
    return result


def reload_wifi():
    run('/sbin/wifi', 'reload')
    expected = wifi_current()
    for _ in range(40):
        runtime = ubus('network.wireless', 'status')
        if any(radio.get('pending') for radio in runtime.values()):
            time.sleep(.25)
            continue
        if bool(wifi_runtime(expected if expected['enabled'] else None)) == expected['enabled']:
            return
        time.sleep(.25)
    raise RuntimeError('Hotspot did not reach the requested state.')


def apply_wifi(data, atomic_write):
    updated = wifi.validate(data, wifi_current())
    radio = values('wireless')['router_ap']['device']
    edits = [('set', 'wireless.router_ap.' + key, value) for key, value in
             [('disabled', '0' if updated['enabled'] else '1'), ('ssid', updated['ssid']), ('key', updated['psk'])]]
    edits += [('set', 'wireless.' + radio + '.channel', updated['channel']),
              ('set', 'wireless.' + radio + '.disabled', '0')]
    transaction('wireless', edits, reload_wifi, atomic_write)
    if data['password']:
        (STATE / 'initial-wifi-password').unlink(missing_ok=True)
    return wifi_status()


def status():
    services = {}
    for label, name in [('dnsmasq', 'dnsmasq'), ('ModemManager', 'modemmanager')]:
        services[label] = 'active' if service_active(name) else 'inactive'
    # firewall4 is a ruleset, not a persistent procd process.
    try:
        run('nft', 'list', 'table', 'inet', 'fw4')
        services['router-firewall'] = 'active'
    except subprocess.SubprocessError:
        services['router-firewall'] = 'inactive'
    interfaces = ubus('network.interface', 'dump')['interface']
    addresses, wan = {}, []
    for item in interfaces:
        ips = [address['address'] for address in item.get('ipv4-address', [])]
        addresses[item.get('l3_device', item['interface'])] = ips
        if item['interface'] in ('wan', 'wan_4'):
            wan.extend(ips)
    leases = []
    if LEASES.exists():
        for line in LEASES.read_text().splitlines():
            fields = line.split()
            if len(fields) >= 4 and fields[0].isdigit() and (fields[0] == '0' or int(fields[0]) > time.time()):
                leases.append(dict(address=fields[2], name=fields[3], mac=fields[1]))
    modem = dict(state='unavailable', operator='', signal=None)
    try:
        device = values('network')['wan']['device']
        data = json.loads(run('mmcli', '-m', device, '-J'))['modem']
        modem = dict(state=data['generic']['state'], operator=data.get('3gpp', {}).get('operator-name', ''),
                     signal=data['generic'].get('signal-quality', {}).get('value'))
    except (subprocess.SubprocessError, KeyError, ValueError):
        pass
    return dict(hostname=ubus('system', 'board')['hostname'], addresses=addresses,
                wan_addresses=list(dict.fromkeys(wan)), services=services, modem=modem,
                uptime=int(float(Path('/proc/uptime').read_text().split()[0])), leases=leases,
                settings=settings(), wifi=wifi_status())
