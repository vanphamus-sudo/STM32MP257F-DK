import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import openwrt_backend as backend
import server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'openwrt'))
import provision
import initialize

VALID = dict(start='192.168.10.50', end='192.168.10.200', lease_hours=12, dns=['1.1.1.1'])


class OpenWrtTests(unittest.TestCase):
    def test_dhcp_inclusive_range_and_dns_list(self):
        with patch.object(backend, 'transaction') as transaction:
            self.assertEqual(backend.apply_settings(VALID, server.atomic_write), VALID)
        edits = transaction.call_args.args[1]
        self.assertIn(('set', 'dhcp.lan.limit', 151), edits)
        self.assertIn(('add_list', 'dhcp.router_dns.server', '1.1.1.1'), edits)
        self.assertFalse(any('hotspot' in key for _, key, _ in edits))

    def test_dhcp_read_round_trip(self):
        config = dict(lan=dict(start='50', limit='151', leasetime='12h'), router_dns=dict(server=['1.1.1.1']))
        with patch.object(backend, 'values', return_value=config):
            self.assertEqual(backend.settings(), VALID)

    def test_transaction_restores_committed_config_after_service_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'dhcp'
            config.write_text('original')
            def command(*args):
                if 'commit' in args:
                    (Path(args[2]) / 'dhcp').write_text('candidate')
                return ''
            with patch.object(backend, 'CONFIG', root), patch.object(backend, 'STATE', root), \
                    patch.object(backend, 'run', side_effect=command):
                activations = []
                def activate():
                    activations.append(config.read_text())
                    if len(activations) == 1:
                        raise RuntimeError('service failed')
                with self.assertRaisesRegex(RuntimeError, 'service failed'):
                    backend.transaction('dhcp', [], activate, server.atomic_write)
            self.assertEqual(activations, ['candidate', 'original'])
            self.assertEqual(config.read_text(), 'original')
            self.assertEqual((root / 'dhcp.previous').read_text(), 'original')

    def test_pending_changes_are_not_committed(self):
        with patch.object(backend, 'run', return_value='dhcp.lan.start=80') as run:
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                backend.transaction('dhcp', [], lambda: None, server.atomic_write)
            run.assert_called_once_with('uci', 'changes', 'dhcp')

    def test_uci_values_are_single_arguments_not_shell_input(self):
        ssid = "Test ' \" ; $(touch /tmp/unsafe)"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'wireless').write_text('original')
            with patch.object(backend, 'CONFIG', root), patch.object(backend, 'STATE', root), \
                    patch.object(backend, 'run', return_value='') as run:
                backend.transaction('wireless', [('set', 'wireless.router_ap.ssid', ssid)], lambda: None, server.atomic_write)
            sets = [call.args for call in run.call_args_list if 'set' in call.args]
            self.assertEqual(sets[0][-1], 'wireless.router_ap.ssid=' + ssid)

    def test_failed_staging_does_not_touch_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dhcp').write_text('original')
            with patch.object(backend, 'CONFIG', root), patch.object(backend, 'STATE', root), \
                    patch.object(backend, 'run', side_effect=['', RuntimeError('uci failed')]):
                with self.assertRaises(RuntimeError):
                    backend.transaction('dhcp', [('set', 'dhcp.lan.start', 50)], lambda: None, server.atomic_write)
            self.assertEqual((root / 'dhcp').read_text(), 'original')

    def test_wifi_secret_not_returned(self):
        current = dict(enabled=True, ssid='Test', channel=6, psk='secret123')
        with patch.object(backend, 'values', return_value={'router_ap': {}}), \
                patch.object(backend, 'wifi_current', return_value=current), \
                patch.object(backend, 'wifi_runtime', return_value='phy0-ap0'), \
                patch.object(backend, 'ubus', return_value={'clients': {'aa:bb:cc:dd:ee:ff': {}}}):
            status = backend.wifi_status()
        self.assertEqual(status['clients'], 1)
        self.assertEqual(status['state'], 'enabled')
        self.assertNotIn('psk', status)
        self.assertNotIn('secret123', json.dumps(status))

    def test_wifi_readiness_rejects_stale_runtime(self):
        radio = dict(up=True, config=dict(channel='6'), interfaces=[
            dict(section='router_ap', ifname='phy0-ap0', config=dict(ssid='Old'))])
        with patch.object(backend, 'ubus', return_value={'radio0': radio}):
            self.assertIsNone(backend.wifi_runtime(dict(ssid='New', channel=6)))
            self.assertIsNone(backend.wifi_runtime(dict(ssid='Old', channel=11)))
            self.assertEqual(backend.wifi_runtime(dict(ssid='Old', channel=6)), 'phy0-ap0')
            radio['pending'] = True
            self.assertIsNone(backend.wifi_runtime(dict(ssid='Old', channel=6)))

    def test_wifi_apply_changes_only_dedicated_ap_and_radio(self):
        current = dict(enabled=True, ssid='Test', channel=6, psk='a' * 64)
        with patch.object(backend, 'wifi_current', return_value=current), \
                patch.object(backend, 'values', return_value={'router_ap': {'device': 'radio2'}}), \
                patch.object(backend, 'transaction') as transaction, \
                patch.object(backend, 'wifi_status', return_value={'available': True}):
            backend.apply_wifi(dict(enabled=False, ssid='Test', channel=11, password=''), server.atomic_write)
        edits = transaction.call_args.args[1]
        self.assertIn(('set', 'wireless.router_ap.disabled', '1'), edits)
        self.assertIn(('set', 'wireless.radio2.channel', 11), edits)
        self.assertIn(('set', 'wireless.router_ap.key', 'a' * 64), edits)

    def test_generated_config_preserves_router_boundaries(self):
        result = provision.configs('eth0', '/sys/devices/platform/usb/1-1', 'usb0')
        self.assertIn('"telstra.extranet"', result['network'])
        self.assertIn('"192.168.7.1"', result['network'])
        sections = result['firewall'].split('config ')
        forwards = [s for s in sections if s.startswith('forwarding ')]
        self.assertEqual(len(forwards), 3)
        usb_forward = next(s for s in forwards if s.startswith('forwarding "management_wan"'))
        self.assertIn('option enabled "1"', usb_forward)
        self.assertTrue(all('option dest "wan"' in s and 'option family "ipv4"' in s for s in forwards))
        incoming_wan = [s for s in sections if s.startswith('rule ') and 'option src "wan"' in s]
        self.assertEqual(len(incoming_wan), 1)
        self.assertIn('rule "wan_ping"', incoming_wan[0])
        self.assertIn('option proto "icmp"', incoming_wan[0])
        self.assertIn('list icmp_type "echo-request"', incoming_wan[0])
        self.assertEqual(result['dhcp'].count('option limit "151"'), 2)

    def test_device_validation_and_optional_management(self):
        provision.configs('eth0', '/sys/devices/platform/soc@0/42080000.bus:usb@482e0000/usb1/1-1.1', 'usb0')
        for lan, modem, usb in [('eth0;reboot', '/sys/devices/usb', None),
                                ('eth0', '/dev/cdc-wdm0', None), ('eth0', '/sys/devices/usb', 'eth0')]:
            with self.assertRaises(ValueError):
                provision.configs(lan, modem, usb)
        self.assertNotIn('192.168.7.1', provision.configs('eth0', '/sys/devices/usb')['network'])

    def test_initialization_keeps_existing_login(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            initialize.initialize(state)
            original = (state / 'credentials.json').read_text()
            self.assertTrue(server.password_matches('admin', json.loads(original)))
            initialize.initialize(state)
            self.assertEqual((state / 'credentials.json').read_text(), original)

    def test_server_dispatches_openwrt_settings_with_validation(self):
        with patch.object(server, 'OPENWRT', True), patch.object(server, 'platform', backend, create=True), \
                patch.object(backend, 'apply_settings', return_value=VALID) as apply:
            server.apply_settings(VALID)
            apply.assert_called_once()
            with self.assertRaises(ValueError):
                server.apply_settings(VALID | dict(start='192.168.7.1'))


if __name__ == '__main__':
    unittest.main()
