import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import router_features as f
import router_supervisor as supervisor


class RouterFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.config = self.root / 'config'
        self.config.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(f, 'STATE', self.state).start()
        patch.object(f, 'RUNTIME', self.root / 'runtime.json').start()
        self.backend = Mock(CONFIG=self.config)
        self.backend.values.return_value = dict(wan=dict(device='/sys/devices/modem'))

    def test_defaults_are_opt_in_and_private_key_never_returned(self):
        settings = f.config()
        for section in ('watchdog', 'failover', 'allowance', 'wireguard', 'guest', 'sqm', 'ipv6', 'sms', 'gnss'):
            self.assertFalse(settings[section]['enabled'])
        settings['wireguard']['private_key'] = 'secret'
        f.atomic(self.state / 'features.json', settings)
        with patch.object(f, 'capability', return_value={}):
            result = f.status(self.backend)
        self.assertNotIn('private_key', result['settings']['wireguard'])
        self.assertTrue(result['settings']['wireguard']['private_key_saved'])
        self.assertEqual(f.config()['wireguard']['private_key'], 'secret')

    def test_watchdog_rejects_injection_private_addresses_duplicates_and_booleans(self):
        for targets in (['1.1.1.1;reboot', '8.8.8.8'], ['127.0.0.1', '8.8.8.8'], ['1.1.1.1']*2, [123, '8.8.8.8']):
            data = dict(f.DEFAULTS['watchdog'], targets=targets)
            with self.assertRaises(ValueError):
                f.validate('watchdog', data, {})
        with self.assertRaises(ValueError):
            f.validate('watchdog', dict(f.DEFAULTS['watchdog'], failures=True), {})

    def test_wireguard_requires_real_keys_and_preserves_existing_private_key(self):
        import base64
        private = base64.b64encode(bytes(range(32))).decode()
        data = dict(f.DEFAULTS['wireguard'], enabled=True, peer_key=private, endpoint='vpn.example.com')
        validated = f.validate('wireguard', data, dict(private_key=private))
        self.assertEqual(validated['private_key'], private)
        with self.assertRaises(ValueError):
            f.validate('wireguard', data | dict(peer_key='invalid'), dict(private_key=private))
        with self.assertRaises(ValueError):
            f.validate('wireguard', data | dict(endpoint='$(reboot)'), dict(private_key=private))

    def test_guest_subnet_and_vlan_isolation(self):
        for subnet in ('192.168.10.1/24', '192.168.7.2/24', '192.168.30.0/24', '192.168.30.1/16'):
            with self.assertRaises(ValueError):
                f.validate('guest', dict(f.DEFAULTS['guest'], subnet=subnet), {})
        self.backend.values.return_value = dict(router_ethernet=dict(mode='both', device='eth0', lan_vlan='10', wan_vlan='20'))
        plan = f.plan('guest', dict(f.DEFAULTS['guest'], enabled=True), self.backend)
        firewall = plan['firewall']
        self.assertIn(('set', 'firewall.rf_guest.input', 'REJECT'), firewall)
        self.assertIn(('set', 'firewall.rf_guest.forward', 'REJECT'), firewall)
        self.assertIn(('set', 'firewall.rf_guest_wan.dest', 'wan'), firewall)
        self.assertFalse(any(value in ('lan', 'management') for _, _, value in firewall))

    def test_billing_cycle_december_and_reset(self):
        self.assertEqual(f.billing_cycle(datetime(2026, 1, 2), 15), '2025-12-15')
        self.assertEqual(f.billing_cycle(datetime(2026, 1, 15), 15), '2026-01-15')
        settings = dict(f.DEFAULTS['allowance'], limit_mb=1)
        when = datetime(2026, 1, 20, tzinfo=timezone.utc)
        first = f.allowance_update(settings, dict(tx=100, rx=200), {}, when)
        second = f.allowance_update(settings, dict(tx=500100, rx=600200), first, when)
        self.assertEqual(second['used'], 1100000)
        self.assertTrue(second['exceeded'])
        reset = f.allowance_update(settings, dict(tx=500200, rx=600300), second, datetime(2026, 2, 1))
        self.assertEqual(reset['used'], 0)
        self.assertFalse(reset['exceeded'])

    def test_counter_reset_never_subtracts_usage(self):
        old = dict(cycle='2026-01-01', last=dict(tx=1000, rx=2000), used=5000)
        result = f.allowance_update(f.DEFAULTS['allowance'], dict(tx=1, rx=2), old, datetime(2026, 1, 2))
        self.assertEqual(result['used'], 5000)

    def test_rollback_restores_and_removes_created_files(self):
        (self.config / 'network').write_text('candidate')
        (self.config / 'sqm').write_text('new')
        pending = dict(token='abc', deadline=0, section='guest', files={'uci/network':'original', 'uci/sqm':None})
        f.atomic(self.state / 'feature-pending.json', pending)
        with patch.object(f, 'reload_services'), patch.object(f, 'event'):
            f.rollback(self.backend)
        self.assertEqual((self.config / 'network').read_text(), 'original')
        self.assertFalse((self.config / 'sqm').exists())
        self.assertIsNone(f.public_pending())

    def test_confirm_requires_token_before_deadline(self):
        import time
        f.atomic(self.state / 'feature-pending.json', dict(token='correct', deadline=time.time()+60, section='guest'))
        with self.assertRaises(ValueError):
            f.confirm('wrong')
        self.assertIsNotNone(f.public_pending())
        with patch.object(f, 'event'):
            f.confirm('correct')
        self.assertIsNone(f.public_pending())

    def test_alarm_ids_do_not_collide_and_use_existing_wire_schema(self):
        settings = f.config()
        settings['alerts']['mqtt'] = True
        f.atomic(self.state / 'features.json', settings)
        queue = self.state / 'mqtt-state/outbox'
        f.atomic(self.state / 'mqtt-state/pending.json', {'ALARM:1':dict(topic='ALARM', data=dict(id=1))})
        f.event('recovery', 'LTE reconnect requested.')
        f.event('signal', 'Weak signal.')
        alarms = [json.loads(p.read_text()) for p in queue.glob('*.json')]
        self.assertEqual({a['data']['id'] for a in alarms}, {2, 3})
        self.assertTrue(all(a['topic'] == 'ALARM' and a['data']['event']['type'] == 'system' for a in alarms))

    def test_support_report_omits_coordinates_and_secrets(self):
        f.atomic(f.RUNTIME, dict(gnss={'latitude':123}, active_uplink='wan'))
        with patch.object(f, 'capability', return_value={}):
            report = f.support(self.backend)
        self.assertNotIn('gnss', report['runtime'])
        self.assertNotIn('settings', report)

    def test_restore_rejects_traversal_wrong_board_and_executable_uci(self):
        base = dict(format='stm32-router-settings', version=1, notice='', device='this-board')
        required = {'uci/'+p:'config interface test\n' for p in ('network','firewall','dhcp','wireless')}
        with patch.object(f, 'device_identity', return_value='this-board'):
            for data in [base | dict(files=required | {'state/../../shadow':'evil'}),
                         base | dict(files=required, device='other-board'),
                         base | dict(files=required | {'uci/firewall':"config include x\n option path /tmp/evil\n"})]:
                with self.assertRaises(ValueError):
                    f.restore(data, self.backend)

    def test_backup_excludes_credentials_and_update_trust(self):
        (self.state / 'credentials.json').write_text('secret')
        (self.state / 'firmware.json').write_text('trust')
        (self.config / 'network').write_text('network')
        with patch.object(f, 'device_identity', return_value='board'):
            backup = f.backup(self.backend)
        self.assertNotIn('state/credentials.json', backup['files'])
        self.assertNotIn('state/firmware.json', backup['files'])

    def test_recovery_backoff_and_escalation(self):
        service = supervisor.Supervisor(self.backend)
        settings = dict(f.DEFAULTS['watchdog'], reset_after=2, cooldown=120)
        with patch.object(f, 'execute') as execute, patch.object(f, 'event'), patch.object(supervisor.time, 'monotonic', return_value=1000):
            service.recover(settings)
            self.assertEqual(execute.call_count, 2)
            service.recover(settings)
            self.assertEqual(execute.call_count, 2)
        with patch.object(f, 'execute') as execute, patch.object(f, 'event'), patch.object(supervisor.time, 'monotonic', return_value=1400):
            service.recover(settings)
            self.assertIn('--reset', execute.call_args.args)

    def test_diagnostics_are_bounded_and_do_not_use_shell(self):
        for target in ('-c100', 'example.com;reboot', '$(reboot)', 'a\nreboot'):
            with self.assertRaises(ValueError):
                f.diagnose(dict(tool='ping', target=target), self.backend)
        with patch.object(f.subprocess, 'run', return_value=Mock(stdout='ok', returncode=0)) as run:
            self.assertTrue(f.diagnose(dict(tool='ping', target='1.1.1.1'), self.backend)['ok'])
            self.assertNotIn('shell', run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs['timeout'], 20)

    def test_stale_save_does_not_modify_files(self):
        with self.assertRaises(ValueError):
            f.save(dict(section='watchdog', settings=f.DEFAULTS['watchdog'], revision='stale'), self.backend)
        self.assertFalse((self.state / 'features.json').exists())

    def test_ipv6_plan_enables_lan_forwarding_without_opening_wan_admin(self):
        plan = f.plan('ipv6', {'enabled':True}, self.backend)
        self.assertIn(('set', 'firewall.lan_wan.family', 'any'), plan['firewall'])
        self.assertIn(('set', 'network.rf_wan6.reqprefix', 'auto'), plan['network'])
        self.assertFalse(any('8081' == value or '22' == value for _, _, value in plan['firewall']))

    def test_pending_change_rejects_other_feature_saves(self):
        f.atomic(self.state / 'feature-pending.json', dict(token='pending', deadline=9999999999, section='guest'))
        with self.assertRaisesRegex(ValueError, 'previous network change'):
            f.save(dict(section='alerts', settings=f.DEFAULTS['alerts'], revision=f.revision()), self.backend)

    def test_shared_allowance_storage_uses_existing_traffic_partition(self):
        profile = self.root / 'system-slots.json'
        profile.write_text('{}')
        with patch.object(supervisor.traffic_stats, 'PROFILE', profile), \
                patch.object(supervisor.traffic_stats, 'state_path', return_value=self.root / 'shared/traffic.json'):
            service = supervisor.Supervisor(self.backend)
        self.assertEqual(service.accounting_path, self.root / 'shared/allowance-state.json')


if __name__ == '__main__':
    unittest.main()
