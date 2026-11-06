#!/usr/bin/env python3
"""Always-on traffic accounting, independent of the MQTT connection."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

RUNTIME = Path('/tmp/router-traffic.json')
PROFILE = Path('/etc/router-web/system-slots.json')
ROLES = ('wan', 'sim1', 'sim2', 'lan', 'wlan')


def query(*args):
    try:
        return json.loads(subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=5))
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.new')
    with temporary.open('w') as handle:
        os.chmod(temporary, 0o600)
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def state_path():
    if PROFILE.exists():
        data = json.loads(PROFILE.read_text())
        staging = Path(data['staging_directory'])
        if not staging.is_mount():
            raise RuntimeError('Shared traffic storage is not mounted')
        return staging / 'router-traffic/state.json'
    return Path('/etc/router-web/traffic-state.json')


def current():
    try:
        data = json.loads(RUNTIME.read_text())
        data['stale_seconds'] = max(0, round(time.time() - data['updated_at']))
        return data
    except (OSError, ValueError):
        return dict(available=False, roles={})


def interface_sample(device):
    if not isinstance(device, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', device):
        return None
    base = Path('/sys/class/net') / device
    try:
        return dict(device=device, ifindex=int((base / 'ifindex').read_text()),
                    tx=int((base / 'statistics/tx_bytes').read_text()),
                    rx=int((base / 'statistics/rx_bytes').read_text()))
    except (OSError, ValueError):
        return None


class Accounting:
    def __init__(self, data=None):
        self.data = data or dict(available=True, started_at=int(time.time()), roles={})

    def sample(self, mapping, boot, uptime, wall):
        roles = self.data['roles']
        for role in ROLES:
            item = roles.setdefault(role, dict(total_tx_bytes=0, total_rx_bytes=0))
            sample = mapping.get(role)
            item.update(available=sample is not None, tx_bytes_per_second=0, rx_bytes_per_second=0)
            if sample is None:
                continue
            previous = item.get('last')
            identity = (boot, sample['device'], sample['ifindex'])
            same = previous and identity == (previous['boot'], previous['device'], previous['ifindex'])
            for direction in ('tx', 'rx'):
                raw = sample[direction]
                if not previous or boot != previous['boot']:
                    delta = raw  # Include measured counters accumulated earlier in this boot.
                elif same:
                    delta = raw - previous[direction] if raw >= previous[direction] else raw
                else:
                    delta = 0  # A newly assigned device may contain traffic from its former role.
                item['total_' + direction + '_bytes'] += delta
                elapsed = uptime - previous['uptime'] if same else 0
                if elapsed > 0:
                    item[direction + '_bytes_per_second'] = round(delta / elapsed, 2)
                item['boot_' + direction + '_bytes'] = raw
            item.update(device=sample['device'], last=dict(sample, boot=boot, uptime=uptime))
        self.data.update(available=True, updated_at=int(wall), boot_id=boot)
        return self.data

    def public(self):
        return dict(self.data, roles={name: {key: value for key, value in item.items() if key != 'last'}
                                     for name, item in self.data['roles'].items()})


def run():
    import fcntl
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = json.loads(path.read_text()) if path.exists() else None
        accounting = Accounting(data)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        last_save, last_modem, modem_device, sim = 0, 0, None, 'sim1'
        try:
            while True:
                now = time.monotonic()
                if now - last_modem >= 30 or last_modem == 0:
                    listing = query('mmcli', '-L', '-J').get('modem-list', [])
                    generic = query('mmcli', '-m', listing[0], '-J').get('modem', {}).get('generic', {}) if listing else {}
                    ports = [port.split()[0] for port in generic.get('ports', []) if port.endswith('(net)')]
                    modem_device = ports[0] if ports else None
                    sim = 'sim2' if str(generic.get('primary-sim-slot')) == '2' else 'sim1'
                    last_modem = now
                mapping = {}
                for role, name in [('wan', 'wan'), ('lan', 'lan'), ('wlan', 'hotspot')]:
                    interface = query('ubus', 'call', 'network.interface.' + name, 'status')
                    device = interface.get('l3_device') or interface.get('device')
                    mapping[role] = interface_sample(device)
                mapping[sim] = interface_sample(modem_device)
                accounting.sample(mapping, boot, float(Path('/proc/uptime').read_text().split()[0]), time.time())
                atomic(RUNTIME, accounting.public())
                if now - last_save >= 300 or last_save == 0:
                    atomic(path, accounting.data)
                    last_save = now
                if stop.wait(5):
                    break
        finally:
            final_mapping = {role: interface_sample(item.get('device'))
                             for role, item in accounting.data['roles'].items() if item.get('available')}
            accounting.sample(final_mapping, boot, float(Path('/proc/uptime').read_text().split()[0]), time.time())
            atomic(RUNTIME, accounting.public())
            atomic(path, accounting.data)


if __name__ == '__main__':
    run()
