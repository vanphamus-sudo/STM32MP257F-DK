import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import ip_passthrough as p
import router_features as f

MAC = '02:11:22:33:44:55'
SETTINGS = dict(enabled=True, client_mac=MAC)


class PassthroughTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        self.root = Path(self.temp.name)
        patch.object(p, 'ROOT', self.root / 'passthrough').start()
        patch.object(f, 'STATE', self.root / 'settings').start()
        self.packages = dict(network=dict(lan_bridge=dict(ports=['end0']),
            router_ethernet=dict(device='end0', mode='lan', lan_vlan='12', wan_vlan='22'),
            management=dict(device='usb0', ipaddr='192.168.7.1'),
            wan=dict(proto='modemmanager', iptype='ipv4')),
            firewall=dict(wan=dict(masq='1')), openvpn={},
            dhcp=dict(router_dns=dict(server=['1.1.1.1', '8.8.8.8'])))
        self.backend = Mock()
        self.backend.values.side_effect = lambda name: copy.deepcopy(self.packages[name])
        self.wan = dict(up=True, l3_device='wwan0', **{'ipv4-address':[dict(address='100.64.5.10', mask=30)],
            'route':[dict(target='0.0.0.0', mask=0, nexthop='100.64.5.9', metric=20)]})
        def ubus(obj, method):
            if obj == 'network.interface.management':
                return dict(up=True, **{'ipv4-address':[dict(address='192.168.7.1', mask=24)]})
            if obj == 'network.interface.rf_passthrough':
                return dict(up=True, l3_device='end0', **{'ipv4-address':[dict(address=p.GATEWAY, mask=24)]})
            return copy.deepcopy(self.wan)
        self.backend.ubus.side_effect = ubus
        patch.object(p, 'available', return_value=True).start()
        patch.object(f, 'execute', return_value='').start()
        patch.object(p, 'query', return_value=[dict(priority=0, table='local'),
                                             dict(priority=32766, table='main'), dict(priority=32767, table='default')]).start()

    def test_mac_validation_blocks_multicast_zero_and_injection(self):
        for mac in ('ff:ff:ff:ff:ff:ff', '01:00:00:00:00:01', '00:00:00:00:00:00',
                    '02:11:22:33:44:55;reboot', '02-11-22-33-44-55', None):
            with self.assertRaises(ValueError):
                p.validate(dict(enabled=True, client_mac=mac))
        self.assertEqual(p.validate(dict(enabled=True, client_mac='02:AA:BB:CC:DD:EE'))['client_mac'], '02:aa:bb:cc:dd:ee')
        self.assertEqual(p.validate(dict(enabled=False, client_mac=''))['client_mac'], '')

    def test_preflight_requires_usb_and_exclusive_ipv4(self):
        p.preflight(SETTINGS, self.backend, f.config())
        self.packages['network']['management']['ipaddr'] = '192.168.8.1'
        with self.assertRaisesRegex(ValueError, 'USB management'):
            p.preflight(SETTINGS, self.backend, f.config())
        self.packages['network']['management']['ipaddr'] = '192.168.7.1'
        settings = f.config()
        settings['watchdog']['enabled'] = True
        with self.assertRaisesRegex(ValueError, 'Disable watchdog'):
            p.preflight(SETTINGS, self.backend, settings)
        self.packages['network']['wan']['iptype'] = 'ipv4v6'
        with self.assertRaisesRegex(ValueError, 'IPv4-only'):
            p.preflight(SETTINGS, self.backend, f.config())

    def test_preflight_rejects_wan_trunk_openvpn_nat_and_overlap(self):
        original = copy.deepcopy(self.packages)
        mutations = [('network', 'router_ethernet', 'mode', 'both'),
                     ('openvpn', 'router_vpn', 'enabled', '1'),
                     ('network', 'lan', 'ipaddr', '192.168.40.2')]
        for package, section, option, value in mutations:
            self.packages = copy.deepcopy(original)
            self.packages[package].setdefault(section, {})[option] = value
            with self.assertRaises(ValueError):
                p.preflight(SETTINGS, self.backend, f.config())
        self.packages = copy.deepcopy(original)
        self.packages['firewall']['forward'] = {'.type':'redirect', 'enabled':'1'}
        with self.assertRaisesRegex(ValueError, 'Disable port forwards'):
            p.preflight(SETTINGS, self.backend, f.config())

    def test_preflight_rejects_policy_routing_and_flow_offload(self):
        with patch.object(p, 'query', return_value=[dict(priority=10900, table=10900)]):
            with self.assertRaisesRegex(ValueError, 'policy routing'):
                p.preflight(SETTINGS, self.backend, f.config())
        self.packages['firewall']['defaults'] = dict(flow_offloading='1')
        with self.assertRaisesRegex(ValueError, 'flow offloading'):
            p.preflight(SETTINGS, self.backend, f.config())

    def test_enable_disable_plans_preserve_usb_and_vlan_preferences(self):
        edits = p.plan(SETTINGS, self.backend)
        self.assertIn(('delete', 'network.lan_bridge.ports', None), edits['network'])
        self.assertIn(('set', 'network.rf_passthrough.device', 'end0'), edits['network'])
        self.assertIn(('set', 'firewall.wan.masq', '0'), edits['firewall'])
        self.assertIn(('set', 'network.router_ethernet.lan_vlan', '12'), edits['network'])
        self.assertFalse(any('management' in key for commands in edits.values() for _, key, _ in commands))
        self.packages['network']['rf_passthrough'] = dict(device='end0')
        self.packages['network']['lan_bridge']['ports'] = []
        disabled = p.plan(dict(enabled=False, client_mac=MAC), self.backend)
        self.assertIn(('add_list', 'network.lan_bridge.ports', 'end0'), disabled['network'])
        self.assertIn(('set', 'firewall.wan.masq', '1'), disabled['firewall'])

    def test_lease_accepts_carrier_nat_and_rejects_multiple_or_management_addresses(self):
        self.assertEqual(p.lease(self.backend)['address'], '100.64.5.10')
        self.assertEqual(p.lease(self.backend)['dns'], ['1.1.1.1','8.8.8.8'])
        self.wan['ipv4-address'].append(dict(address='100.64.5.11', mask=30))
        with self.assertRaises(ValueError):
            p.lease(self.backend)
        self.wan['ipv4-address'] = [dict(address='192.168.7.1', mask=24)]
        with self.assertRaisesRegex(ValueError, 'management'):
            p.lease(self.backend)
        self.wan['up'] = False
        self.assertIsNone(p.lease(self.backend))

    def test_dhcp_offer_contains_exact_wan_address_single_mac_and_classless_routes(self):
        conf = p.dhcp_config(p.lease(self.backend), 'end0', MAC)
        self.assertIn('dhcp-host=' + MAC + ',100.64.5.10,2m', conf)
        self.assertIn('dhcp-ignore=tag:!known', conf)
        self.assertIn('shared-network=end0,100.64.5.10', conf)
        self.assertIn('dhcp-option-force=121,192.168.40.1/32,0.0.0.0,0.0.0.0/0,192.168.40.1', conf)
        self.assertIn('dhcp-option-force=249,', conf)
        self.assertIn('port=0\n', conf)

    def test_guard_has_no_address_translation_and_blocks_other_clients(self):
        script = p.firewall(p.lease(self.backend), 'end0', MAC)
        self.assertNotIn('snat', script)
        self.assertNotIn('dnat', script)
        self.assertIn('ether saddr != ' + MAC + ' drop', script)
        self.assertIn('iifname "end0" ip saddr != 100.64.5.10 drop', script)
        self.assertIn('oifname "wwan0" iifname != "end0" drop', script)
        self.assertIn('iifname "end0" oifname != "wwan0" drop', script)
        self.assertIn('meta nfproto ipv6 drop', script)

    def runtime_mocks(self, fail_start=False):
        self.packages['network']['rf_passthrough'] = dict(device='end0')
        self.packages['network']['lan_bridge']['ports'] = []
        self.live = dict(address=True, route=False, neighbor=False, dhcp=False, nft=False)
        self.commands = []
        def query(*args):
            if 'addr' in args:
                return [dict(addr_info=[dict(family='inet', local=self.wan['ipv4-address'][0]['address'])] if self.live['address'] else [])]
            if 'neigh' in args:
                return [dict(lladdr=MAC)] if self.live['neighbor'] else []
            if 'route' in args:
                return [dict(dev='end0', dst=self.old_address)] if self.live['route'] else []
            raise AssertionError(args)
        self.old_address = self.wan['ipv4-address'][0]['address']
        def execute(*args, **kwargs):
            self.commands.append(args)
            if args[:4] == ('ip', '-4', 'addr', 'del'):
                self.assertTrue((p.ROOT / 'journal.json').exists())
                self.assertTrue(self.live['nft'])
                self.live['address'] = False
            if args[:4] == ('ip', '-4', 'addr', 'replace'):
                self.live['address'] = True
            if args[:4] == ('ip', '-4', 'route', 'replace') and args[4] != 'default':
                self.live['route'] = True
            if args[:4] == ('ip', '-4', 'route', 'del'):
                self.live['route'] = False
            if args[:3] == ('ip', '-4', 'neigh'):
                self.live['neighbor'] = args[3] == 'replace'
            if args[:3] == ('nft', 'delete', 'table'):
                self.live['nft'] = False
            if args[0] == 'dnsmasq' and '--test' not in args:
                if fail_start:
                    raise RuntimeError('DHCP failed')
                self.live['dhcp'] = True
            return ''
        patch.object(p, 'query', side_effect=query).start()
        patch.object(f, 'execute', side_effect=execute).start()
        patch.object(p, 'nft_exists', side_effect=lambda:self.live['nft']).start()
        patch.object(p, 'nft_apply', side_effect=lambda script:self.live.update(nft=True)).start()
        patch.object(p, 'dhcp_pid', side_effect=lambda:100 if self.live['dhcp'] else None).start()
        patch.object(p, 'stop_dhcp', side_effect=lambda:self.live.update(dhcp=False)).start()
        patch.object(p, 'clear_connections').start()
        patch.object(f, 'event').start()

    def test_handoff_is_journalled_before_address_removal_and_is_idempotent(self):
        self.runtime_mocks()
        result = p.reconcile(SETTINGS, self.backend)
        self.assertEqual(result['state'], 'active')
        self.assertFalse(self.live['address'])
        self.assertTrue(self.live['route'] and self.live['neighbor'] and self.live['dhcp'])
        starts = sum(c[0] == 'dnsmasq' and '--test' not in c for c in self.commands)
        p.reconcile(SETTINGS, self.backend)
        self.assertEqual(sum(c[0] == 'dnsmasq' and '--test' not in c for c in self.commands), starts)
        p.cleanup(self.backend)
        self.assertTrue(self.live['address'])
        self.assertFalse(self.live['route'] or self.live['neighbor'] or self.live['dhcp'] or self.live['nft'])
        self.assertFalse((p.ROOT / 'journal.json').exists())

    def test_activation_failure_restores_host_address_and_removes_owned_objects(self):
        self.runtime_mocks(fail_start=True)
        with self.assertRaisesRegex(RuntimeError, 'DHCP failed'):
            p.reconcile(SETTINGS, self.backend)
        self.assertTrue(self.live['address'])
        self.assertFalse(self.live['route'] or self.live['neighbor'] or self.live['nft'])
        self.assertFalse((p.ROOT / 'journal.json').exists())

    def test_lease_change_never_readds_stale_carrier_address(self):
        self.runtime_mocks()
        p.reconcile(SETTINGS, self.backend)
        self.wan['ipv4-address'][0]['address'] = '100.64.5.14'
        self.wan['route'][0]['nexthop'] = '100.64.5.13'
        self.live['address'] = True  # netifd installed the new bearer address.
        p.reconcile(SETTINGS, self.backend)
        journal = json.loads((p.ROOT / 'journal.json').read_text())
        self.assertEqual(journal['lease']['address'], '100.64.5.14')
        self.assertFalse(any(c[:4] == ('ip','-4','addr','replace') for c in self.commands))

    def test_stop_suspends_traffic_and_retains_recovery_journal(self):
        self.runtime_mocks()
        p.reconcile(SETTINGS, self.backend)
        with patch.object(p, 'nft_apply') as nft:
            p.suspend()
        self.assertIn('iifname "end0" drop', nft.call_args.args[0])
        self.assertFalse(self.live['dhcp'])
        self.assertTrue((p.ROOT / 'journal.json').exists())
        self.assertEqual(p.reconcile(SETTINGS, self.backend)['state'], 'active')
        self.assertTrue(self.live['dhcp'])
        self.assertFalse(self.live['address'])

    def test_carrier_down_removes_old_lease_without_reassigning_it(self):
        self.runtime_mocks()
        p.reconcile(SETTINGS, self.backend)
        self.wan['up'] = False
        self.assertEqual(p.reconcile(SETTINGS, self.backend)['state'], 'waiting')
        self.assertFalse(self.live['dhcp'] or self.live['route'])
        self.assertFalse(any(c[:4] == ('ip','-4','addr','replace') for c in self.commands))

    def test_cleanup_during_incomplete_bearer_does_not_block_recovery(self):
        self.runtime_mocks()
        p.reconcile(SETTINGS, self.backend)
        self.wan['ipv4-address'] = []
        p.cleanup(self.backend)
        self.assertFalse(self.live['dhcp'] or self.live['route'] or self.live['nft'])
        self.assertFalse((p.ROOT / 'journal.json').exists())

    def test_conntrack_cleanup_is_address_scoped_and_fails_on_real_errors(self):
        with patch.object(p.subprocess, 'run', return_value=Mock(returncode=1, stderr='0 flow entries have been deleted.')) as run:
            p.clear_connections('100.64.5.10')
        self.assertEqual(run.call_count, 4)
        self.assertTrue(all(call.args[0][-1] == '100.64.5.10' for call in run.call_args_list))
        with patch.object(p.subprocess, 'run', return_value=Mock(returncode=1, stderr='Operation not permitted')):
            with self.assertRaises(RuntimeError):
                p.clear_connections('100.64.5.10')

    def test_activation_failure_rolls_back_uci_and_saved_feature_settings(self):
        self.backend.CONFIG = self.root / 'config'
        self.backend.CONFIG.mkdir()
        for name in f.PACKAGES:
            (self.backend.CONFIG / name).write_text(name + ' original')
        def begin(section, backend):
            pending = dict(section=section, token='pending', deadline=9999999999,
                           files=f.snapshot(backend), boot='test')
            f.atomic(f.STATE / 'feature-pending.json', pending)
            return pending
        def transaction(package, edits, activate, write):
            (self.backend.CONFIG / package).write_text(package + ' candidate')
        self.backend.transaction.side_effect = transaction
        with patch.object(f, 'capability', return_value={'passthrough':True}), \
                patch.object(f, 'begin_change', side_effect=begin), patch.object(f, 'reload_services'), \
                patch.object(f, 'event'), patch.object(p, 'preflight'), patch.object(p, 'cleanup') as cleanup, \
                patch.object(p, 'activate', side_effect=ValueError('activation failed')):
            with self.assertRaisesRegex(ValueError, 'activation failed'):
                f.save(dict(section='passthrough', settings=SETTINGS, revision=f.revision()), self.backend)
        self.assertGreaterEqual(cleanup.call_count, 2)
        self.assertTrue(all((self.backend.CONFIG / name).read_text() == name + ' original' for name in f.PACKAGES))
        self.assertFalse(f.config()['passthrough']['enabled'])
        self.assertIsNone(f.public_pending())

    def test_unowned_route_prevents_handoff_without_mutation(self):
        self.runtime_mocks()
        self.live['route'] = True
        with self.assertRaisesRegex(RuntimeError, 'route to the LTE address'):
            p.reconcile(SETTINGS, self.backend)
        self.assertTrue(self.live['address'])
        self.assertFalse((p.ROOT / 'journal.json').exists())

    @unittest.skipUnless(shutil.which('dnsmasq'), 'dnsmasq syntax check requires Linux package')
    def test_real_dnsmasq_parser(self):
        import socket
        p.ROOT.mkdir()
        path = p.ROOT / 'dnsmasq.conf'
        # shared-network resolves the interface index even in --test mode.
        interface = next((name for _, name in socket.if_nameindex() if name != 'lo'), 'lo')
        path.write_text(p.dhcp_config(p.lease(self.backend), interface, MAC))
        result = subprocess.run(['dnsmasq', '--test', '--conf-file=' + str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
