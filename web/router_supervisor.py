#!/usr/bin/env python3
"""procd supervisor for opt-in connection recovery and router monitoring."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

import router_features as features
import traffic_stats
import ip_passthrough

TABLE = '10900'
PRIORITY = '10900'


def query(*args):
    try:
        return json.loads(features.execute(*args))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return {}


def interface(name):
    return query('ubus', 'call', 'network.interface.' + name, 'status')


def health(device, targets):
    if not isinstance(device, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', device):
        return False
    for target in targets:
        try:
            result = subprocess.run(['ping', '-I', device, '-c', '1', '-W', '2', target],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
            if result.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    return False


class Supervisor:
    def __init__(self, backend):
        self.backend = backend
        self.last_health = self.last_signal = self.last_save = 0
        self.failures = self.attempts = self.recoveries = 0
        self.last_recovery = 0
        self.current_uplink = None
        self.last_vpn = None
        self.last_weak = False
        self.last_allowance = None
        self.runtime = {}
        self.accounting_path = (traffic_stats.state_path().with_name('allowance-state.json')
                                if traffic_stats.PROFILE.exists() else features.STATE / 'feature-accounting.json')
        self.state = features.read(self.accounting_path, {})
        self.started = False
        self.gnss_enabled = False

    def route(self, name):
        """Dedicated policy table; throw routes retain all specific main routes."""
        status = interface(name)
        device = status.get('l3_device')
        if not status.get('up') or not device:
            raise RuntimeError('Selected uplink is unavailable.')
        marker = Path('/tmp/router-failover-owned')
        rules = query('ip', '-j', '-4', 'rule', 'show')
        if not marker.exists():
            existing = query('ip', '-j', '-4', 'route', 'show', 'table', TABLE)
            if existing or any(str(rule.get('priority')) in (PRIORITY, '10890', '10891') for rule in rules):
                raise RuntimeError('Failover table or rule priority 10900 is already in use.')
            features.atomic(marker, 'owned')
        # Bound health probes must bypass the active failover default. Otherwise
        # a failed Ethernet route would prevent testing whether LTE is healthy.
        for priority, uplink in [('10890', 'ethernet_wan'), ('10891', 'wan')]:
            old = next((r for r in rules if str(r.get('priority')) == priority), None)
            dev = interface(uplink).get('l3_device')
            if old and old.get('oif') != dev:
                features.execute('ip', '-4', 'rule', 'del', 'priority', priority)
                old = None
            if dev and not old:
                features.execute('ip', '-4', 'rule', 'add', 'priority', priority, 'oif', dev, 'lookup', 'main')
        # Flush only our dedicated table, never main or any other policy table.
        features.execute('ip', '-4', 'route', 'flush', 'table', TABLE)
        routes = query('ip', '-j', '-4', 'route', 'show', 'table', 'main')
        seen = set()
        for route in routes:
            destination = route.get('dst', 'default')
            if destination != 'default' and destination not in seen:
                features.execute('ip', '-4', 'route', 'add', 'throw', destination, 'table', TABLE)
                seen.add(destination)
        default = next((r for r in status.get('route', []) if r.get('target') == '0.0.0.0' and r.get('mask') == 0), {})
        gateway = default.get('nexthop')
        args = ['ip', '-4', 'route', 'replace', 'default']
        if gateway and gateway != '0.0.0.0':
            args += ['via', gateway, 'onlink']
        features.execute(*(args + ['dev', device, 'table', TABLE]))
        if not any(str(rule.get('priority')) == PRIORITY for rule in rules):
            features.execute('ip', '-4', 'rule', 'add', 'priority', PRIORITY, 'lookup', TABLE)
        if self.current_uplink != name:
            features.event('uplink', 'Active uplink: ' + name)
        self.current_uplink = name

    def clear_route(self):
        marker = Path('/tmp/router-failover-owned')
        if marker.exists():
            rules = query('ip', '-j', '-4', 'rule', 'show')
            if any(str(rule.get('priority')) == PRIORITY for rule in rules):
                features.execute('ip', '-4', 'rule', 'del', 'priority', PRIORITY, 'lookup', TABLE)
            for priority in ('10890', '10891'):
                if any(str(rule.get('priority')) == priority for rule in rules):
                    features.execute('ip', '-4', 'rule', 'del', 'priority', priority)
            features.execute('ip', '-4', 'route', 'flush', 'table', TABLE)
            marker.unlink()
        self.current_uplink = None

    def quota_rule(self, blocked, devices):
        # A separate nftables table survives firewall4 reloads. Do not alter fw4.
        exists = subprocess.run(['nft', 'list', 'table', 'inet', 'router_allowance'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not blocked:
            if exists:
                features.execute('nft', 'delete', 'table', 'inet', 'router_allowance')
            return
        devices = [d for d in devices if re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', d)]
        if not devices:
            raise RuntimeError('Cannot identify the cellular interface for allowance cutoff.')
        script = ('delete table inet router_allowance\n' if exists else '')
        script += 'table inet router_allowance { chain forward { type filter hook forward priority -5; policy accept; '
        for device in set(devices):
            script += 'oifname "' + device + '" counter drop; '
        script += '} }\n'
        subprocess.run(['nft', '-f', '-'], input=script, text=True, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)

    def account(self, settings):
        measured = traffic_stats.current()
        if not measured.get('available') or measured.get('stale_seconds', 999) > 30:
            self.runtime['allowance_error'] = 'Traffic counters unavailable; last allowance state retained.'
            if not settings['enabled'] or not settings['cutoff']:
                self.quota_rule(False, [])
            return
        self.runtime.pop('allowance_error', None)
        roles = [measured.get('roles', {}).get(name, {}) for name in ('sim1', 'sim2')]
        totals = {d: sum(r.get('total_' + d + '_bytes', 0) for r in roles) for d in ('tx', 'rx')}
        state = features.allowance_update(settings, totals, self.state.get('allowance', {}), datetime.now(timezone.utc))
        self.state['allowance'] = state
        cutoff = settings['enabled'] and settings['cutoff'] and state['exceeded']
        self.quota_rule(cutoff, [r['device'] for r in roles if r.get('available') and r.get('device')])
        self.runtime['allowance'] = dict(state, cutoff=cutoff)
        if settings['enabled'] and state['percent'] >= settings['warning_percent'] and not state.get('warned'):
            features.event('data-usage', 'Cellular data allowance is at ' + str(state['percent']) + ' percent.')
            state['warned'] = True
        # Save usage every five minutes; force a save at warning/cutoff transitions.
        transition = (state['cycle'], state.get('warned'), cutoff)
        if transition != self.last_allowance or time.monotonic() - self.last_save >= 300:
            features.atomic(self.accounting_path, self.state)
            self.last_save = time.monotonic()
            self.last_allowance = transition

    def recover(self, settings):
        now = time.monotonic()
        backoff = min(86400, settings['cooldown'] * 2 ** min(self.attempts, 8))
        if self.attempts and now - self.last_recovery < backoff:
            return
        self.last_recovery = now
        self.attempts += 1
        if self.attempts % settings['reset_after'] == 0:
            features.execute('mmcli', '-m', features.modem(self.backend), '--reset')
            features.event('recovery', 'Modem reset after repeated connectivity failures.')
        else:
            features.execute('ifdown', 'wan')
            features.execute('ifup', 'wan')
            features.event('recovery', 'LTE reconnect requested after connectivity failures.')
        self.failures = 0

    def connections(self, settings):
        w, f = settings['watchdog'], settings['failover']
        if not f['enabled']:
            self.clear_route()
        if not w['enabled'] and not f['enabled']:
            return
        if time.monotonic() - self.last_health < w['interval']:
            return
        self.last_health = time.monotonic()
        lte, wired = interface('wan'), interface('ethernet_wan')
        lte_ok = bool(lte.get('up')) and health(lte.get('l3_device'), w['targets'])
        wired_ok = bool(wired.get('up')) and health(wired.get('l3_device'), w['targets'])
        old = self.runtime.get('lte_healthy')
        if old is not None and old != lte_ok:
            features.event('connectivity', 'LTE Internet recovered.' if lte_ok else 'LTE Internet health checks failed.')
        self.runtime.update(lte_healthy=lte_ok, ethernet_healthy=wired_ok, checked_at=int(time.time()))
        if f['enabled']:
            self.recoveries = self.recoveries + 1 if wired_ok else 0
            if wired_ok and (self.current_uplink in (None, 'ethernet_wan') or self.recoveries >= f['recoveries']):
                self.route('ethernet_wan')
            elif lte_ok:
                self.route('wan')
            else:
                self.clear_route()
        self.failures = 0 if lte_ok else self.failures + 1
        if lte_ok:
            self.attempts = 0
        if w['enabled'] and self.failures >= w['failures']:
            self.recover(w)
        self.runtime.update(active_uplink=self.current_uplink, consecutive_failures=self.failures,
                            recovery_attempts=self.attempts)

    def sample_signal(self, settings):
        s = settings['signal']
        if not s['enabled'] or time.monotonic() - self.last_signal < s['interval']:
            return
        self.last_signal = time.monotonic()
        import modem_details
        info = modem_details.collect(self.backend)
        sample = dict(time=int(time.time()), **{k: info.get(k) for k in ('rsrp', 'rsrq', 'sinr', 'cell_id', 'band', 'status')})
        path = Path('/tmp/router-signal.json')
        samples = features.read(path, [])
        if samples and samples[-1].get('cell_id') and sample['cell_id'] and samples[-1]['cell_id'] != sample['cell_id']:
            features.event('cell', 'Serving LTE cell changed.')
        features.atomic(path, (samples + [sample])[-s['samples']:])
        try:
            weak = float(str(sample['rsrp']).split()[0]) < settings['alerts']['weak_rsrp']
            if weak and not self.last_weak:
                features.event('signal', 'LTE signal strength is below the configured threshold.')
            self.last_weak = weak
        except ValueError:
            pass

    def vpn(self, settings):
        import openvpn_client
        openvpn = openvpn_client.status(self.backend)
        wg = query('ubus', 'call', 'network.interface.rf_wg', 'status')
        handshake_recent = False
        if wg.get('up'):
            try:
                handshakes = features.execute('wg', 'show', 'rf_wg', 'latest-handshakes')
                handshake_recent = any(0 < time.time() - int(line.split()[1]) < 180
                                       for line in handshakes.splitlines() if len(line.split()) == 2)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                pass
        state = (openvpn.get('state'), bool(wg.get('up')), handshake_recent)
        if self.last_vpn is not None and self.last_vpn != state:
            features.event('vpn', 'VPN status changed: OpenVPN ' + str(state[0]) + ', WireGuard ' +
                           ('recent handshake' if state[2] else 'waiting for handshake' if state[1] else 'down'))
        self.last_vpn = state
        self.runtime['vpn'] = dict(openvpn=state[0], wireguard_up=state[1], wireguard_recent_handshake=state[2])
        if settings['gnss']['enabled']:
            if not self.gnss_enabled:
                features.execute('mmcli', '-m', features.modem(self.backend), '--location-enable-gps-raw')
                self.gnss_enabled = True
            self.runtime['gnss'] = query('mmcli', '-m', features.modem(self.backend), '--location-get-gps-raw', '-J')
        else:
            self.gnss_enabled = False
            self.runtime.pop('gnss', None)

    def tick(self):
        pending = features.read(features.STATE / 'feature-pending.json', None)
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if pending and (pending['deadline'] <= time.time() or pending['boot'] != boot):
            features.rollback(self.backend)
        settings = features.config()
        # Passthrough needs to run during its own confirmation window, while
        # ordinary watchdog/failover work remains paused for network edits.
        if not pending or pending['section'] == 'passthrough':
            try:
                self.runtime['passthrough'] = ip_passthrough.reconcile(settings['passthrough'], self.backend)
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
                self.runtime['passthrough'] = dict(state='error', reason=str(error)[:240])
        if not self.started:
            features.event('startup', 'Router feature supervisor started.')
            self.started = True
        # Do not interfere with an unconfirmed transaction or cellular recovery.
        if not features.public_pending():
            errors = {}
            for name, operation in [('allowance', lambda: self.account(settings['allowance'])),
                                    ('connections', lambda: self.connections(settings)),
                                    ('signal', lambda: self.sample_signal(settings)),
                                    ('vpn', lambda: self.vpn(settings))]:
                try:
                    operation()
                except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
                    # A failed modem read or quota update must not stop recovery.
                    errors[name] = type(error).__name__
            self.runtime['feature_errors'] = errors
        self.runtime.pop('error', None)
        self.runtime['updated_at'] = int(time.time())
        features.atomic(features.RUNTIME, self.runtime)


def main():
    import openwrt_backend
    supervisor = Supervisor(openwrt_backend)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        while not stop.is_set():
            try:
                with features.locked():
                    supervisor.tick()
                    supervisor.runtime.pop('error', None)
            except Exception as error:
                supervisor.runtime['error'] = 'Supervisor operation failed: ' + type(error).__name__
                features.atomic(features.RUNTIME, supervisor.runtime)
            stop.wait(10)
    finally:
        with features.locked():
            ip_passthrough.suspend()
            features.atomic(supervisor.accounting_path, supervisor.state)
            supervisor.clear_route()


if __name__ == '__main__':
    main()
