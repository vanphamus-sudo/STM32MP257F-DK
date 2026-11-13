import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import recovery_button as button


class RecoveryTests(unittest.TestCase):
    def config(self, mode):
        return ({'lan_bridge': {'name': 'br-lan', 'ports': [] if mode == 'wan' else ['end0.10' if mode == 'both' else 'end0']},
                 'router_ethernet': {'device': 'end0', 'mode': mode},
                 'wan': {'proto': 'modemmanager'}, 'ethernet_wan': {'proto': 'dhcp'}},
                {'router_dns': {'interface': ['hotspot'], 'notinterface': ['lan', 'management']},
                 'lan': {'ignore': '1', 'dhcp_option': ['3,10.0.0.1']}},
                {'lan': {'name': 'lan', 'network': ['lan']},
                 'wan': {'name': 'wan', 'network': ['wan', 'ethernet_wan', 'vpn']}})

    def test_press_boundaries(self):
        self.assertIsNone(button.gesture(.1))
        self.assertEqual(button.gesture(.15), 'reboot')
        self.assertEqual(button.gesture(7.99), 'reboot')
        self.assertEqual(button.gesture(8), 'recover')
        self.assertEqual(button.gesture(60), 'recover')

    def test_recovery_all_modes_preserves_unrelated_settings(self):
        for mode in ('lan', 'wan', 'both'):
            configs = self.config(mode)
            before = copy.deepcopy(configs)
            edits = button.plans(*configs)
            self.assertEqual(configs, before)
            self.assertIn(('add_list', 'network.lan_bridge.ports', 'end0'), edits['network'])
            self.assertIn(('set', 'network.lan.ipaddr', '192.168.10.1'), edits['network'])
            self.assertIn(('set', 'dhcp.lan.ignore', '0'), edits['dhcp'])
            self.assertIn(('add_list', 'firewall.wan.network', 'vpn'), edits['firewall'])
            self.assertNotIn(('add_list', 'firewall.wan.network', 'ethernet_wan'), edits['firewall'])
            self.assertIn(('set', 'firewall.lan_web.dest_port', '8081'), edits['firewall'])
            self.assertFalse(any(key.startswith('network.wan') for _, key, _ in edits['network']))
            self.assertEqual(set(edits), {'network', 'dhcp', 'firewall'})

    def test_missing_port_fails_without_guessing(self):
        configs = self.config('wan')
        configs[0].pop('router_ethernet')
        with self.assertRaises(RuntimeError):
            button.plans(*configs)

    def test_recovery_removes_passthrough_and_restores_wan_nat(self):
        network, dhcp, firewall = self.config('lan')
        network['rf_passthrough'] = dict(device='end0')
        firewall['rf_passthrough'] = dict(name='rf_passthrough')
        edits = button.plans(network, dhcp, firewall)
        self.assertIn(('delete', 'network.rf_passthrough', None), edits['network'])
        self.assertIn(('delete', 'firewall.rf_passthrough', None), edits['firewall'])
        self.assertIn(('set', 'firewall.wan.masq', '1'), edits['firewall'])

    def test_only_kernel_user1_events_change_state(self):
        hardware = button.Hardware.__new__(button.Hardware)
        hardware.input = None
        hardware.pressed = False
        hardware.events = Mock()
        hardware.events.recvfrom.side_effect = [
            (b'SUBSYSTEM=button\0BUTTON=BTN_1\0ACTION=pressed\0', (123, 1)),
            (b'SUBSYSTEM=button\0BUTTON=BTN_2\0ACTION=pressed\0', (0, 1)),
            BlockingIOError(),
        ]
        self.assertFalse(hardware.down())
        hardware.events.recvfrom.side_effect = [
            (b'SUBSYSTEM=button\0BUTTON=BTN_1\0ACTION=pressed\0', (0, 1)), BlockingIOError()]
        self.assertTrue(hardware.down())
        hardware.events.recvfrom.side_effect = [
            (b'SUBSYSTEM=button\0BUTTON=BTN_1\0ACTION=released\0', (0, 1)), BlockingIOError()]
        self.assertFalse(hardware.down())

    def test_validation_failure_and_interrupted_write_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'state'
            state.mkdir()
            saved = {'passthrough': {'enabled': True, 'client_mac': '02:00:00:00:00:01'},
                     'watchdog': {'enabled': True}}
            (state / 'features.json').write_text(json.dumps(saved))
            (state / 'feature-pending.json').write_text('pending snapshot')
            originals = {p: p + ' original' for p in ('network', 'dhcp', 'firewall')}
            for p, text in originals.items():
                (root / p).write_text(text)
            configs = dict(zip(originals, self.config('wan')))
            def run(*args):
                if args == ('fw4', 'check'):
                    raise RuntimeError('invalid firewall')
                return ''
            platform = SimpleNamespace(CONFIG=root, STATE=state, values=configs.__getitem__, run=Mock(side_effect=run))
            write = lambda p, text: p.write_text(text)
            with patch.object(button.os, 'sync', create=True), self.assertRaises(RuntimeError):
                button.recover(platform, write)
            self.assertEqual({p: (root / p).read_text() for p in originals}, originals)
            self.assertFalse((state / 'button-recovery-pending.json').exists())
            self.assertEqual(json.loads((state / 'features.json').read_text()), saved)
            self.assertEqual((state / 'feature-pending.json').read_text(), 'pending snapshot')
            (state / 'button-recovery-pending.json').write_text(json.dumps(originals))
            (root / 'network').write_text('partial write')
            with patch.object(button.os, 'sync', create=True):
                button.restore_pending(platform, write)
            self.assertEqual((root / 'network').read_text(), originals['network'])
            platform.run.side_effect = lambda *args: ''
            with patch.object(button.os, 'sync', create=True):
                button.recover(platform, write)
            recovered = json.loads((state / 'features.json').read_text())
            self.assertFalse(recovered['passthrough']['enabled'])
            self.assertEqual(recovered['passthrough']['client_mac'], saved['passthrough']['client_mac'])
            self.assertEqual(recovered['watchdog'], saved['watchdog'])
            self.assertFalse((state / 'feature-pending.json').exists())
            # A power loss during publication restores application state too.
            journal = originals | {'state/features.json': json.dumps(saved),
                                   'state/feature-pending.json': 'pending snapshot'}
            (state / 'button-recovery-pending.json').write_text(json.dumps(journal))
            with patch.object(button.os, 'sync', create=True):
                button.restore_pending(platform, write)
            self.assertEqual(json.loads((state / 'features.json').read_text()), saved)
            self.assertEqual((state / 'feature-pending.json').read_text(), 'pending snapshot')


if __name__ == '__main__':
    unittest.main()
