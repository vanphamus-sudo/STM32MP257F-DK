"""Authenticated web configuration for the supervised MQTT client."""
import copy
import ipaddress
import json
from pathlib import Path
import re
import ssl
import subprocess

from mqtt_client import validate

STATE = Path('/etc/router-web')
DEFAULTS = dict(enabled=False, host='', port=8883, serial='', username='', password='',
                ca_file='', verify_hostname=True, tls_enabled=True, hardware_version='STM32MP257F-DK',
                lan_ports=[], tcp_proxy_targets=[], serial_proxies={}, handlers={})
ADVANCED = ('hardware_version', 'lan_ports', 'tcp_proxy_targets', 'serial_proxies', 'handlers',
            'gps_file', 'network_quality_file', 'primary_interface', 'backup_interface', 'quality_target')


def current():
    path = STATE / 'mqtt.json'
    return dict(copy.deepcopy(DEFAULTS), **(json.loads(path.read_text()) if path.exists() else {}))


def status(backend):
    config = current()
    result = {key: config[key] for key in ('enabled', 'host', 'port', 'serial', 'username', 'verify_hostname', 'tls_enabled')}
    result.update(available=True, password_saved=bool(config['password']),
                  ca_saved=bool(config.get('ca_file')), advanced={key: config[key] for key in ADVANCED if key in config})
    active = backend.service_active('router-mqtt')
    result['state'] = 'disabled' if not config['enabled'] else 'running' if active else 'stopped'
    if active and config['enabled']:
        try:
            import time
            runtime = json.loads(Path('/tmp/router-mqtt-status.json').read_text())
            if time.time() - runtime['updated_at'] < 15:
                result['state'] = runtime['state']
                result['broker_acknowledged'] = runtime['broker_acknowledged']
        except (OSError, ValueError, KeyError):
            pass
    return result


def validate_advanced(data):
    if not isinstance(data, dict) or set(data) - set(ADVANCED):
        raise ValueError('Unknown advanced MQTT setting')
    for name in ('hardware_version', 'gps_file', 'network_quality_file', 'primary_interface', 'backup_interface'):
        if name in data and (not isinstance(data[name], str) or len(data[name]) > 256 or any(ord(c) < 32 for c in data[name])):
            raise ValueError('Invalid ' + name)
    ports = data.get('lan_ports', [])
    if 'quality_target' in data and (not isinstance(data['quality_target'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', data['quality_target'])):
        raise ValueError('quality_target must be an IPv4 address or hostname')
    if not isinstance(ports, list) or len(ports) > 4 or any(not isinstance(p, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', p) for p in ports):
        raise ValueError('lan_ports must contain up to four interface names')
    targets = data.get('tcp_proxy_targets', [])
    if not isinstance(targets, list) or len(targets) > 16:
        raise ValueError('Use up to 16 TCP proxy targets')
    for target in targets:
        try:
            host, port = target.rsplit(':', 1)
            ipaddress.IPv4Address(host)
            if not 1 <= int(port) <= 65535:
                raise ValueError()
        except (AttributeError, ValueError):
            raise ValueError('TCP proxy targets must be IPv4:port') from None
    serials = data.get('serial_proxies', {})
    if not isinstance(serials, dict) or len(serials) > 8:
        raise ValueError('Invalid serial proxies')
    from serial_tcp import BAUDS
    for name, settings in serials.items():
        if (not re.fullmatch(r'serial[1-9][0-9]*', name) or not isinstance(settings, dict)
                or set(settings) != {'device', 'baud'} or not isinstance(settings['device'], str)
                or not re.fullmatch(r'/dev/[A-Za-z0-9_.-]+', settings['device'])
                or type(settings['baud']) is not int or settings['baud'] not in BAUDS):
            raise ValueError('Serial proxies require a /dev device and supported baud')
    handlers = data.get('handlers', {})
    allowed = ('CONFIG', 'EVENT/GETFILE', 'EVENT/SETFILE', 'INDUSTRY/GET', 'INDUSTRY/SET', 'EVENT/SHELL', 'UPGRADE', 'EVENT/UPGRADE')
    if not isinstance(handlers, dict) or any(key not in allowed or not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value) or '..' in value.split('/') for key, value in handlers.items()):
        raise ValueError('Use absolute executable paths for supported operation handlers')
    return data


def service(action):
    subprocess.run(['/etc/init.d/router-mqtt', action], check=True, timeout=20,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply(data, backend, atomic_write):
    required = {'enabled', 'host', 'port', 'serial', 'username', 'password', 'tls_enabled', 'verify_hostname', 'ca_certificate', 'clear_ca', 'advanced'}
    if set(data) != required:
        raise ValueError('Supply all MQTT settings')
    previous = current()
    config = {key: data[key] for key in ('enabled', 'host', 'port', 'serial', 'username', 'tls_enabled', 'verify_hostname')}
    if any(type(data[key]) is not bool for key in ('enabled', 'tls_enabled', 'verify_hostname', 'clear_ca')):
        raise ValueError('MQTT switches must be boolean')
    for key in ('host', 'serial', 'username', 'password', 'ca_certificate'):
        if not isinstance(data[key], str):
            raise ValueError('Invalid ' + key)
    if len(data['password']) > 256 or len(data['username']) > 256:
        raise ValueError('Credentials must be at most 256 characters')
    if config['host'] and (len(config['host']) > 253 or not re.fullmatch(r'[A-Za-z0-9.:-]+', config['host'])):
        raise ValueError('Enter a broker hostname or IP address without a URL prefix')
    if config['serial'] and not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', config['serial']):
        raise ValueError('Serial number must contain 1–64 letters, digits, dots, underscores or hyphens')
    config['password'] = data['password'] or previous['password']
    config.update(validate_advanced(data['advanced']))
    ca = data['ca_certificate']
    if ca:
        if len(ca) > 16384:
            raise ValueError('CA certificate must be at most 16 KB')
        try:
            ssl.create_default_context(cadata=ca)
        except (ssl.SSLError, ValueError):
            raise ValueError('Enter a valid PEM CA certificate') from None
    config['ca_file'] = str(STATE / 'mqtt-ca.crt') if ca else '' if data['clear_ca'] else previous['ca_file']
    validate(config)
    # Validate port even while disabled so saved settings are always well formed.
    if type(config['port']) is not int or not 1 <= config['port'] <= 65535:
        raise ValueError('MQTT port must be 1–65535')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    ca_path = STATE / 'mqtt-ca.crt'
    old_ca = ca_path.read_text() if ca_path.exists() else None
    path = STATE / 'mqtt.json'
    old = path.read_text() if path.exists() else None
    try:
        if ca:
            atomic_write(ca_path, ca)
        atomic_write(path, json.dumps(config))
        service('enable' if config['enabled'] else 'disable')
        service('restart' if config['enabled'] else 'stop')
    except Exception:
        if old is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, old)
        if old_ca is None:
            ca_path.unlink(missing_ok=True)
        else:
            atomic_write(ca_path, old_ca)
        service('enable' if previous['enabled'] else 'disable')
        service('restart' if previous['enabled'] else 'stop')
        raise
    if data['clear_ca'] and not ca:
        ca_path.unlink(missing_ok=True)
    return status(backend)
