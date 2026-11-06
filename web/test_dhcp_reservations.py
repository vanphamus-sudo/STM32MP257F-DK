from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import dhcp_reservations as dr


def binding(**changes):
    return dict(id='0123456789abcdef',hostname='server',mac='00:11:22:33:44:55',ip='192.168.10.100')|changes


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend=Mock()
        self.backend.LEASES=Path(self.temp.name)/'leases'
        self.config={'router_dns':{'.type':'dnsmasq'},'lan':{'.type':'dhcp','ignore':'0'}}
        self.backend.values.return_value=self.config

    def apply(self,items):
        return dr.apply(dict(revision=dr.revision(self.config),bindings=items),self.backend,Mock())

    def test_normalizes_and_writes_only_owned_host_sections(self):
        self.apply([binding(mac='02-AB-CD-EF-12-34',hostname='Server')])
        edits=self.backend.transaction.call_args.args[1]
        key='dhcp.router_lease_0123456789abcdef'
        self.assertIn(('set',key+'.mac','02:ab:cd:ef:12:34'),edits)
        self.assertIn(('set',key+'.ip','192.168.10.100'),edits)
        self.assertIn(('set',key+'.instance','router_dns'),edits)
        self.assertTrue(all(e[1].startswith('dhcp.router_lease_') for e in edits))
        self.backend.run.assert_called_once_with('dnsmasq','--test','--conf-file=/dev/null','--dhcp-host=02:ab:cd:ef:12:34,192.168.10.100,server')
        self.assertIs(self.backend.transaction.call_args.args[2],self.backend.restart_dns)

    def test_accepts_lan_ips_outside_dynamic_pool_and_optional_hostname(self):
        for ip in ('192.168.10.2','192.168.10.254'):
            self.apply([binding(ip=ip,hostname='')])
        self.config['lan']['ignore']='1'
        self.assertFalse(dr.status(self.backend)['lan_enabled'])

    def test_rejects_invalid_mac_ip_hostname_and_fields(self):
        cases=[dict(mac='ff:ff:ff:ff:ff:ff'),dict(mac='01:11:22:33:44:55'),dict(mac='00:00:00:00:00:00'),
               dict(mac='00:11:22:33:44:55;reboot'),dict(mac=123),dict(ip='192.168.10.1'),
               dict(ip='192.168.10.0'),dict(ip='192.168.10.255'),dict(ip='192.168.7.100'),
               dict(ip='192.168.20.100'),dict(ip='::1'),dict(ip=123),dict(hostname='bad\nname'),
               dict(hostname='-host'),dict(hostname='host;reboot'),dict(id='../../x'),dict(extra=True)]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.apply([binding(**changes)])
        self.backend.transaction.assert_not_called()

    def test_rejects_duplicate_ids_macs_ips_and_hostnames(self):
        other=binding(id='fedcba9876543210',mac='02:11:22:33:44:66',ip='192.168.10.101',hostname='other')
        for field in ('id','mac','ip','hostname'):
            duplicate=other|{field:binding()[field]}
            if field=='hostname':duplicate[field]='SERVER'
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'unique'):self.apply([binding(),duplicate])
        self.backend.transaction.assert_not_called()

    def test_preserves_external_reservations_and_rejects_conflicts(self):
        self.config['existing']={'.type':'host','name':'camera','mac':['02:aa:bb:cc:dd:ee','04:aa:bb:cc:dd:ee'],'ip':'192.168.10.200'}
        for changes in (dict(ip='192.168.10.200'),dict(mac='04:aa:bb:cc:dd:ee'),dict(hostname='CAMERA')):
            with self.assertRaisesRegex(ValueError,'LuCI'):self.apply([binding(**changes)])
        self.config['existing']['mac']='00:11:22:*:*:*'
        with self.assertRaisesRegex(ValueError,'LuCI'):self.apply([binding()])
        self.config['existing']['mac']='02:aa:bb:cc:dd:ee'
        self.apply([binding()])
        self.assertFalse(any('existing' in e[1] for e in self.backend.transaction.call_args.args[1]))
        self.assertEqual(dr.status(self.backend)['unmanaged'][0]['ip'],'192.168.10.200')

    def test_blocks_ip_in_use_by_another_mac_and_ignores_expired_leases(self):
        self.backend.LEASES.write_text('0 02:aa:bb:cc:dd:ee 192.168.10.100 camera *\n')
        with self.assertRaisesRegex(ValueError,'currently leased'):self.apply([binding()])
        self.backend.LEASES.write_text('1 02:aa:bb:cc:dd:ee 192.168.10.100 camera *\n0 00:11:22:33:44:55 192.168.10.100 server *\n0 02:11:22:33:44:66 192.168.20.100 hotspot *\ninvalid\n')
        self.apply([binding()])
        self.assertEqual(len(dr.status(self.backend)['leases']),1)

    def test_stale_revision_limit_delete_and_collision(self):
        with self.assertRaisesRegex(RuntimeError,'Reload'):
            dr.apply(dict(revision='stale',bindings=[]),self.backend,Mock())
        with self.assertRaises(ValueError):self.apply([binding()]*101)
        key=dr.PREFIX+binding()['id']
        self.config[key]={'.type':'host','name':'server','mac':binding()['mac'],'ip':binding()['ip']}
        self.assertEqual(dr.status(self.backend)['bindings'],[binding()])
        self.apply([])
        self.assertIn(('delete','dhcp.'+key,None),self.backend.transaction.call_args.args[1])
        self.config[key]['.type']='dnsmasq'
        with self.assertRaisesRegex(ValueError,'unrecognized'):self.apply([])

    def test_invalid_dnsmasq_syntax_cannot_commit(self):
        self.backend.run.side_effect=RuntimeError('dnsmasq test failed')
        with self.assertRaises(RuntimeError):self.apply([binding()])
        self.backend.transaction.assert_not_called()


if __name__=='__main__':unittest.main()
