import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import usb_tethering as usb
import recovery_button


class UsbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for package in ('network', 'dhcp', 'firewall'):
            (root / package).write_text(package)
        self.network = {'management': dict(device='usb0', proto='static', ipaddr='192.168.7.1', netmask='255.255.255.0')}
        self.firewall = {'management': dict(name='management'), 'wan': dict(name='wan', masq='1')}
        self.dhcp = {'router_dns': {'interface': ['hotspot', 'management']},
                     'management': {'interface': 'management', 'dhcp_option': ['3', '6']}}
        self.platform = SimpleNamespace(CONFIG=root, values=lambda p: getattr(self, p),
                                        run=Mock(return_value=''), transaction=Mock())

    def request(self, **changes):
        return dict(enabled=True, revision=usb.revision(self.platform)) | changes

    def test_enable_disable_gateway_dns_and_forwarding_preserve_usb_address(self):
        for enabled in (True, False):
            usb.apply(self.request(enabled=enabled), self.platform, lambda p, s: p.write_text(s))
            call = self.platform.transaction.call_args
            self.assertEqual(call.args[0], 'firewall')
            self.assertIn(('set', 'firewall.management_wan.enabled', '1'), call.args[1])
            self.assertIn(('set', 'firewall.management_wan.family', 'ipv4'), call.args[1])
            call.args[2]()
            self.platform.run.assert_called_with('fw4', 'check')
            dhcp_call = self.platform.transaction.call_args_list[-2]
            self.assertEqual(dhcp_call.args[0], 'dhcp')
            self.assertIn(('add_list', 'dhcp.management.dhcp_option',
                           '3,192.168.7.1' if enabled else '3'), dhcp_call.args[1])
            self.assertIn(('add_list', 'dhcp.management.dhcp_option',
                           '6,192.168.7.1' if enabled else '6'), dhcp_call.args[1])
            self.assertEqual((self.platform.CONFIG / 'network').read_text(), 'network')
            self.assertEqual((self.platform.CONFIG / 'dhcp').read_text(), 'dhcp')

    def test_status_tracks_gateway_advertisement_independently_of_forwarding(self):
        self.firewall['management_wan'] = dict(src='management', dest='wan', family='ipv4', enabled='1')
        self.assertFalse(usb.status(self.platform)['enabled'])
        self.dhcp['management']['dhcp_option'] = ['3,192.168.7.1', '6,192.168.7.1']
        self.assertTrue(usb.status(self.platform)['enabled'])

    def test_bad_input_stale_revision_pending_changes_and_missing_nat_rejected(self):
        for changes in ({'enabled': 'true'}, {'enabled': 1}, {'revision': 'old'}, {'extra': True}):
            with self.assertRaises((ValueError, RuntimeError)):
                usb.apply(self.request(**changes), self.platform, Mock())
        self.platform.run.return_value = 'pending'
        with self.assertRaises(RuntimeError):
            usb.apply(self.request(), self.platform, Mock())
        self.platform.run.return_value = ''
        self.firewall['wan']['masq'] = '0'
        with self.assertRaises(RuntimeError):
            usb.apply(self.request(), self.platform, Mock())
        self.platform.transaction.assert_not_called()

    def test_recovery_restores_disabled_usb_and_removes_gateway_dns_overrides(self):
        self.dhcp['router_dns'] = {'interface': ['hotspot'], 'notinterface': ['lan', 'management', 'guest']}
        self.network['management'].update(disabled='1', ipaddr='10.99.0.1', gateway='10.99.0.2')
        self.network.update(lan_bridge=dict(name='br-lan', ports=['eth0']),
                            wan=dict(proto='modemmanager'))
        self.firewall['lan'] = dict(name='lan', network=['lan'])
        self.firewall['wan']['network'] = ['wan']
        self.firewall['management_wan'] = dict(src='management', dest='wan', enabled='1')
        self.dhcp['management'] = dict(ignore='1', dhcp_option=['3,10.99.0.2'])
        plan = recovery_button.plans(self.network, self.dhcp, self.firewall)
        self.assertIn(('delete', 'network.management', None), plan['network'])
        self.assertIn(('set', 'network.management.ipaddr', '192.168.7.1'), plan['network'])
        self.assertIn(('set', 'network.management.disabled', '0'), plan['network'])
        self.assertIn(('set', 'dhcp.management.ignore', '0'), plan['dhcp'])
        for option in ('3', '6'):
            self.assertIn(('add_list', 'dhcp.management.dhcp_option', option), plan['dhcp'])
        self.assertIn(('add_list', 'dhcp.router_dns.interface', 'lan'), plan['dhcp'])
        self.assertIn(('add_list', 'dhcp.router_dns.interface', 'management'), plan['dhcp'])
        self.assertIn(('add_list', 'dhcp.router_dns.notinterface', 'guest'), plan['dhcp'])
        self.assertNotIn(('add_list', 'dhcp.router_dns.notinterface', 'management'), plan['dhcp'])
        self.assertIn(('set', 'firewall.management_wan.enabled', '1'), plan['firewall'])
        self.assertIn(('set', 'firewall.management_admin.dest_port', '22 80 443 8081'), plan['firewall'])

    def test_firewall_failure_rolls_back_dhcp_and_firewall(self):
        def transaction(package, edits, activate, write):
            write(self.platform.CONFIG / package, 'modified')
            if package == 'firewall':
                raise RuntimeError('invalid firewall')
        self.platform.transaction.side_effect = transaction
        with self.assertRaises(RuntimeError):
            usb.apply(self.request(), self.platform, lambda p, text: p.write_text(text))
        for package in ('dhcp', 'firewall'):
            self.assertEqual((self.platform.CONFIG / package).read_text(), package)


if __name__ == '__main__':
    unittest.main()
