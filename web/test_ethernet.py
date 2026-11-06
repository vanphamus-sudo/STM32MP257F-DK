import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import ethernet


class EthernetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for package in ('network', 'firewall'):
            (root / package).write_text(package)
        self.network = {'lan_bridge': {'ports': ['end0']}, 'wan': {'proto': 'modemmanager'}}
        self.firewall = {'wan': {'name': 'wan', 'network': ['wan', 'vpn']}}
        self.platform = SimpleNamespace(CONFIG=root, values=lambda p: self.network if p == 'network' else self.firewall,
                                        run=Mock(return_value=''), transaction=Mock())
        self.write = lambda path, text: path.write_text(text)

    def request(self, **kwargs):
        return dict(mode='both', lan_vlan=10, wan_vlan=20,
                    revision=ethernet.revision(self.platform)) | kwargs

    def test_modes_preserve_lte_and_firewall_networks(self):
        for mode in ('lan', 'wan', 'both'):
            with self.subTest(mode=mode):
                self.platform.transaction.reset_mock()
                ethernet.apply(self.request(mode=mode), self.platform, self.write)
                calls = self.platform.transaction.call_args_list
                network, fw = calls[0].args[1], calls[1].args[1]
                self.assertFalse(any(key.startswith('network.wan') for _, key, _ in network))
                self.assertIn(('add_list', 'firewall.wan.network', 'vpn'), fw)
                if mode != 'lan':
                    self.assertIn(('add_list', 'firewall.wan.network', 'ethernet_wan'), fw)
                    self.assertIn(('set', 'network.ethernet_wan.device', 'end0' if mode == 'wan' else 'end0.20'), network)
                if mode != 'wan':
                    self.assertIn(('add_list', 'network.lan_bridge.ports', 'end0' if mode == 'lan' else 'end0.10'), network)

    def test_validation_and_stale_revision_do_not_write(self):
        for changes in ({'mode': 'bad'}, {'lan_vlan': True}, {'wan_vlan': 4095},
                        {'lan_vlan': 20}, {'revision': 'stale'}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, RuntimeError)):
                ethernet.apply(self.request(**changes), self.platform, self.write)
        self.platform.transaction.assert_not_called()

    def test_external_bridge_ports_and_pending_edits_are_rejected(self):
        self.network['lan_bridge']['ports'].append('usb0')
        with self.assertRaises(RuntimeError):
            ethernet.apply(self.request(), self.platform, self.write)
        self.network['lan_bridge']['ports'] = ['end0']
        self.platform.run.return_value = 'pending edit'
        with self.assertRaises(RuntimeError):
            ethernet.apply(self.request(), self.platform, self.write)
        self.platform.transaction.assert_not_called()

    def test_second_file_failure_restores_both_files(self):
        def transaction(package, edits, activate, write):
            write(self.platform.CONFIG / package, 'changed')
            if package == 'firewall':
                raise RuntimeError('fw4 validation failed')
        self.platform.transaction.side_effect = transaction
        with self.assertRaises(RuntimeError):
            ethernet.apply(self.request(), self.platform, self.write)
        for package in ('network', 'firewall'):
            self.assertEqual((self.platform.CONFIG / package).read_text(), package)


if __name__ == '__main__':
    unittest.main()
