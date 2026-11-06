"""Exclusive, persistent assignment of the external serial converter."""
import copy
import json
from pathlib import Path
import subprocess

import modbus_settings
import serial_tcp

STATE = Path('/etc/router-web')
DEFAULT = dict(enabled=False, device='usb:067b:2303', baud=9600,
               listen='0.0.0.0', port=5000, idle_seconds=60)


def bridge():
    path = STATE / 'serial-tcp.json'
    return json.loads(path.read_text()) if path.exists() else copy.deepcopy(DEFAULT)


def status(backend):
    tcp, mb = bridge(), modbus_settings.current()
    return dict(available=True, mode='conflict' if tcp['enabled'] and mb['enabled'] else
                'tcp' if tcp['enabled'] else 'modbus' if mb['enabled'] else 'disabled',
                device=mb['serial_port']['device'] if mb['enabled'] else tcp['device'],
                tcp_baud=tcp['baud'], tcp_port=tcp['port'],
                tcp_running=backend.service_active('router-serial'),
                modbus_running=backend.service_active('router-modbus'))


def service(name, action):
    subprocess.run(['/etc/init.d/' + name, action], check=True, timeout=45,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply(data, backend, atomic_write):
    if not isinstance(data, dict) or set(data) != {'mode', 'device', 'tcp_baud', 'tcp_port'}:
        raise ValueError('Supply serial mode, device, TCP baud and TCP port.')
    if data['mode'] not in ('disabled', 'tcp', 'modbus'):
        raise ValueError('Choose Disabled, TCP serial bridge or Modbus collection.')
    old_tcp, old_mb = bridge(), modbus_settings.current()
    tcp, mb = copy.deepcopy(old_tcp), copy.deepcopy(old_mb)
    tcp.update(enabled=data['mode'] == 'tcp', device=data['device'],
               baud=data['tcp_baud'], port=data['tcp_port'])
    mb['enabled'] = data['mode'] == 'modbus'
    mb['serial_port']['device'] = data['device']
    serial_tcp.validate(tcp)
    mb = modbus_settings.validate(mb)
    if mb['enabled']:
        modbus_settings.storage_root(mb)
    paths = [STATE / 'serial-tcp.json', modbus_settings.STATE / 'modbus.json']
    originals = [p.read_text() if p.exists() else None for p in paths]
    names = ['router-serial', 'router-modbus']
    boot = [subprocess.run(['/etc/init.d/' + n, 'enabled'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15).returncode == 0 for n in names]
    running = [backend.service_active(n) for n in names]
    try:
        for name in names:
            service(name, 'stop')
        for path, config in zip(paths, [tcp, mb]):
            atomic_write(path, json.dumps(config))
        for name, config in zip(names, [tcp, mb]):
            service(name, 'enable' if config['enabled'] else 'disable')
            if config['enabled']:
                service(name, 'start')
    except Exception:
        for name in names:
            try:
                service(name, 'stop')
            except Exception:
                pass
        for path, original in zip(paths, originals):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, original)
        for name, enabled, active in zip(names, boot, running):
            service(name, 'enable' if enabled else 'disable')
            if active:
                service(name, 'start')
        raise
    return status(backend)
