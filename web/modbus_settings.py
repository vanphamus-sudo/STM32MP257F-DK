"""Configuration and authenticated file access for the Modbus collector."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sqlite3

STATE = Path('/etc/router-web')
RUNTIME = Path('/tmp/router-modbus-status.json')
DEFAULTS = dict(enabled=False, serial='STM32MP257F', interval_minutes=1,
                upload_time='00:00', retention_days=1, save_mode='memory',
                usb_mount='/mnt/modbus', max_storage_mb=64, debug=False,
                serial_port=dict(device='/dev/ttyUSB0', baud=9600, parity='none',
                                 data_bits=8, stop_bits=1, timeout_seconds=2),
                ftp=dict(host='', port=21, username='', password='', directory='/', tls=False),
                devices=[])
FORMATS = ('FLOAT32', 'UINT16', 'INT16', 'UINT32', 'INT32', 'BIN16', 'BIN32', 'HEX16', 'HEX32')


def current():
    path = STATE / 'modbus.json'
    return json.loads(path.read_text()) if path.exists() else copy.deepcopy(DEFAULTS)


def integer(value, low, high, label):
    # Addresses and device IDs may be entered in decimal or hexadecimal.
    if isinstance(value, str):
        try:
            value = int(value, 16 if value.lower().startswith('0x') else 10)
        except ValueError:
            pass
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be {low}-{high}.')
    return value


def text(value, limit, label, empty=True):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value) or (not empty and not value.strip()):
        raise ValueError('Invalid ' + label + '.')
    return value


def validate(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULTS):
        raise ValueError('Supply all Modbus settings.')
    data = copy.deepcopy(data)
    for key in ('enabled', 'debug'):
        if type(data[key]) is not bool:
            raise ValueError(key + ' must be boolean.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', text(data['serial'], 64, 'router serial', False)):
        raise ValueError('Router serial must use letters, numbers, underscores or hyphens.')
    for key, low, high in [('interval_minutes', 1, 1440), ('retention_days', 1, 31), ('max_storage_mb', 1, 1024)]:
        data[key] = integer(data[key], low, high, key)
    if not isinstance(data['upload_time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', data['upload_time']):
        raise ValueError('Upload time must be HH:MM in router local time.')
    if data['save_mode'] not in ('memory', 'usb'):
        raise ValueError('Choose memory or USB storage.')
    if not re.fullmatch(r'/mnt/[A-Za-z0-9_-]+', text(data['usb_mount'], 128, 'USB mount')):
        raise ValueError('USB mount must be a direct directory under /mnt.')
    port = data['serial_port']
    if not isinstance(port, dict) or set(port) != set(DEFAULTS['serial_port']):
        raise ValueError('Supply all serial port settings.')
    if not isinstance(port['device'], str) or not re.fullmatch(r'(?:/dev/[A-Za-z0-9_.-]+|usb:[0-9a-f]{4}:[0-9a-f]{4})', port['device']):
        raise ValueError('Choose a /dev/ serial port or usb:vendor:product selector.')
    from serial_tcp import BAUDS
    if type(port['baud']) is not int or port['baud'] not in BAUDS:
        raise ValueError('Unsupported baud rate.')
    if port['parity'] not in ('none', 'even', 'odd') or type(port['data_bits']) is not int or port['data_bits'] != 8:
        raise ValueError('RTU requires 8 data bits and none/even/odd parity.')
    port['stop_bits'] = integer(port['stop_bits'], 1, 2, 'Stop bits')
    port['timeout_seconds'] = integer(port['timeout_seconds'], 1, 10, 'Response timeout')
    ftp = data['ftp']
    if not isinstance(ftp, dict) or set(ftp) != set(DEFAULTS['ftp']):
        raise ValueError('Supply all FTP settings.')
    host = text(ftp['host'], 253, 'FTP host')
    if host and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]*', host):
        raise ValueError('FTP host must be a hostname or IP without a URL prefix.')
    ftp['port'] = integer(ftp['port'], 1, 65535, 'FTP port')
    for key in ('username', 'password'):
        text(ftp[key], 256, 'FTP ' + key)
    directory = text(ftp['directory'], 256, 'FTP directory', False)
    if not directory.startswith('/') or '..' in directory.split('/'):
        raise ValueError('FTP directory must be an absolute path without .. components.')
    if type(ftp['tls']) is not bool:
        raise ValueError('FTP TLS must be boolean.')
    devices = data['devices']
    if not isinstance(devices, list) or len(devices) > 32:
        raise ValueError('Configure up to 32 devices.')
    seen = set()
    total = 0
    for device in devices:
        if not isinstance(device, dict) or set(device) != {'name', 'id', 'data_mode', 'registers'}:
            raise ValueError('Each device needs name, id, data_mode and registers.')
        text(device['name'], 64, 'device name', False)
        device['id'] = integer(device['id'], 1, 255, 'Device ID')
        if device['id'] in seen:
            raise ValueError('Device IDs must be unique.')
        seen.add(device['id'])
        if device['data_mode'] not in ('big', 'little'):
            raise ValueError('Data mode must be big or little.')
        registers = device['registers']
        if not isinstance(registers, list) or not 1 <= len(registers) <= 128:
            raise ValueError('Each device needs 1-128 registers.')
        total += len(registers)
        for register in registers:
            if not isinstance(register, dict) or set(register) != {'description', 'address', 'format', 'unit', 'function'}:
                raise ValueError('Each register needs description, address, format, unit and function.')
            text(register['description'], 80, 'register description', False)
            text(register['unit'], 24, 'register unit')
            register['address'] = integer(register['address'], 0, 65535, 'Register address')
            if register['format'] not in FORMATS:
                raise ValueError('Unsupported register format.')
            if register['format'].endswith('32') and register['address'] == 65535:
                raise ValueError('32-bit registers need two consecutive addresses.')
            register['function'] = integer(register['function'], 3, 4, 'Read function')
    if total > 512:
        raise ValueError('Configure up to 512 registers in total.')
    if data['enabled'] and (not devices or not host):
        raise ValueError('Add at least one device and the FTP server before enabling collection.')
    return data


def storage_root(config):
    if config['save_mode'] == 'memory':
        return STATE / 'modbus-data'
    mount = Path(config['usb_mount'])
    # Never fall back to flash if a removable drive is absent.
    if not os.path.ismount(mount) or mount.is_symlink():
        raise ValueError('USB storage is not mounted at the configured mount point.')
    return mount / 'router-modbus'


def status(backend):
    config = current()
    result = copy.deepcopy(config)
    result['ftp']['password'] = ''
    result['password_saved'] = bool(config['ftp']['password'])
    result.update(available=True, state='disabled' if not config['enabled'] else 'stopped', files=[])
    if config['enabled'] and backend.service_active('router-modbus'):
        result['state'] = 'running'
        try:
            import time
            runtime = json.loads(RUNTIME.read_text())
            if time.time() - runtime['updated_at'] < 20:
                result['runtime'] = runtime
                result['state'] = runtime['state']
        except (OSError, ValueError, KeyError):
            pass
    try:
        from modbus_collection import Store
        root = storage_root(config)
        if (root / 'index.sqlite3').exists():
            with Store(root) as store:
                result['files'] = store.files()
    except (OSError, ValueError, sqlite3.Error):
        result['storage_error'] = 'Configured storage is unavailable.'
    return result


def service(action):
    subprocess.run(['/etc/init.d/router-modbus', action], check=True, timeout=45,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply(data, backend, atomic_write):
    previous = current()
    candidate = copy.deepcopy(data)
    if isinstance(candidate.get('ftp'), dict) and candidate['ftp'].get('password') == '':
        candidate['ftp']['password'] = previous['ftp']['password']
    candidate = validate(candidate)
    if candidate['enabled']:
        from serial_assignment import bridge
        if bridge()['enabled']:
            raise ValueError('Select Modbus collection in Serial port assignment before enabling collection.')
    if candidate['enabled']:
        storage_root(candidate)
    path = STATE / 'modbus.json'
    existed = path.exists()
    # Stop the old collector before changing its configuration or storage.
    service('stop')
    try:
        atomic_write(path, json.dumps(candidate))
        service('enable' if candidate['enabled'] else 'disable')
        if candidate['enabled']:
            service('start')
    except Exception:
        if existed:
            atomic_write(path, json.dumps(previous))
        else:
            path.unlink(missing_ok=True)
        service('enable' if previous['enabled'] else 'disable')
        if previous['enabled']:
            service('start')
        raise
    return status(backend)
