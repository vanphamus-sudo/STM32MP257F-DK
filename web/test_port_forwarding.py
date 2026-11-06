import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import openwrt_backend as backend
import port_forwarding as pf
import server


def rule(**changes):
    return dict(id='0123456789abcdef', name='Web server', enabled=True, protocol='tcp',
                source_zone='wan', external_port='8080', destination_zone='lan',
                destination_ip='192.168.10.100', internal_port='80', source_ip='',
                external_ip='', reflection=False) | changes


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.config = {zone: {'.type': 'zone', 'name': zone} for zone in ('wan', 'lan', 'hotspot', 'management', 'router_vpn')}
        self.backend = Mock()
        self.backend.values.return_value = self.config

    def apply(self, rules):
        return pf.apply(dict(revision=pf.revision(self.config), rules=rules), self.backend, Mock())

    def test_mapping_ranges_restrictions_and_loopback(self):
        self.apply([rule(protocol='tcp udp', external_port='8000-8010', internal_port='9000-9010',
                         source_ip='203.0.113.7/24', external_ip='198.51.100.2', reflection=True)])
        edits = self.backend.transaction.call_args.args[1]
        key = 'firewall.router_pf_0123456789abcdef'
        for name, value in dict(proto='tcp udp', src_dport='8000-8010', dest_port='9000-9010',
                                src_ip='203.0.113.0/24', src_dip='198.51.100.2', reflection='1',
                                reflection_src='internal', family='ipv4', target='DNAT').items():
            self.assertIn(('set', key+'.'+name, value), edits)
        self.assertTrue(all(edit[1].startswith('firewall.router_pf_') for edit in edits))

    def test_dmz_all_protocols_preserves_ports_and_follows_specific_rules(self):
        self.config['existing']={'.type':'redirect', 'name':'Camera','src':'wan','src_dport':'9000',
                                 'proto':'tcp','dest':'lan','dest_ip':'192.168.10.90'}
        dmz=dict(enabled=True,destination_zone='hotspot',destination_ip='192.168.20.100')
        pf.apply(dict(revision=pf.revision(self.config),rules=[rule()],dmz=dmz),self.backend,Mock())
        edits=self.backend.transaction.call_args.args[1]
        key='firewall.router_dmz'
        self.assertIn(('set',key+'.proto','all'),edits)
        self.assertIn(('set',key+'.src','wan'),edits)
        self.assertIn(('set',key+'.dest','hotspot'),edits)
        self.assertIn(('set',key+'.dest_ip','192.168.20.100'),edits)
        self.assertIn(('set',key+'.reflection','0'),edits)
        self.assertFalse(any(e[1] in (key+'.src_dport',key+'.dest_port') for e in edits))
        self.assertGreater(edits.index(('set',key,'redirect')),
                           max(i for i,e in enumerate(edits) if pf.PREFIX in e[1]))
        self.assertFalse(any('existing' in e[1] for e in edits))

    def test_dmz_defaults_disabled_and_legacy_requests_preserve_existing_dmz(self):
        self.assertEqual(pf.status(self.backend)['dmz'],pf.DMZ_DEFAULT)
        self.config[pf.DMZ_SECTION]={'.type':'redirect','name':'Router DMZ host','enabled':'1',
                                    'proto':'all','src':'wan','dest':'lan','dest_ip':'192.168.10.200'}
        state=pf.status(self.backend)
        self.assertTrue(state['dmz']['enabled'])
        self.assertEqual(state['unmanaged'],[])
        self.apply([rule()])
        edits=self.backend.transaction.call_args.args[1]
        self.assertIn(('delete','firewall.router_dmz',None),edits)
        self.assertIn(('set','firewall.router_dmz.enabled','1'),edits)
        self.assertIn(('set','firewall.router_dmz.dest_ip','192.168.10.200'),edits)

    def test_disable_dmz_keeps_host_or_removes_empty_section(self):
        self.config[pf.DMZ_SECTION]={'.type':'redirect','enabled':'1','dest':'lan','dest_ip':'192.168.10.200'}
        for ip in ('192.168.10.200',''):
            pf.apply(dict(revision=pf.revision(self.config),rules=[],dmz=dict(enabled=False,destination_zone='lan',destination_ip=ip)),self.backend,Mock())
            edits=self.backend.transaction.call_args.args[1]
            self.assertIn(('delete','firewall.router_dmz',None),edits)
            if ip:
                self.assertIn(('set','firewall.router_dmz.enabled','0'),edits)
            else:
                self.assertFalse(any(e[0]=='set' and e[1].startswith('firewall.router_dmz') for e in edits))

    def test_invalid_dmz_targets_and_payloads_never_reach_transaction(self):
        valid=dict(enabled=True,destination_zone='lan',destination_ip='192.168.10.200')
        for value in (None,{}, valid|dict(enabled='true'), valid|dict(destination_ip=''),
                      valid|dict(destination_ip='192.168.10.1'), valid|dict(destination_ip='192.168.10.255'),
                      valid|dict(destination_ip='192.168.7.100'), valid|dict(destination_ip='::1'),
                      valid|dict(destination_zone='management'), valid|dict(destination_zone=[]),
                      valid|dict(destination_ip=123), valid|dict(extra='value')):
            with self.subTest(value=value),self.assertRaises(ValueError):
                pf.apply(dict(revision=pf.revision(self.config),rules=[],dmz=value),self.backend,Mock())
        self.backend.transaction.assert_not_called()

    def test_dmz_rejects_existing_catchall_and_section_collision(self):
        dmz=dict(enabled=True,destination_zone='lan',destination_ip='192.168.10.200')
        self.config['other_dmz']={'.type':'redirect','src':'wan','proto':'all','dest_ip':'192.168.10.201'}
        with self.assertRaisesRegex(ValueError,'all-port'):
            pf.apply(dict(revision=pf.revision(self.config),rules=[],dmz=dmz),self.backend,Mock())
        self.config.pop('other_dmz')
        self.config[pf.DMZ_SECTION]={'.type':'rule'}
        with self.assertRaisesRegex(ValueError,'unrecognized DMZ'):
            pf.apply(dict(revision=pf.revision(self.config),rules=[],dmz=dmz),self.backend,Mock())
        self.backend.transaction.assert_not_called()

    def test_bad_inputs_never_reach_transaction(self):
        cases = [dict(external_port='0'), dict(external_port='65536'), dict(external_port='90-80'),
                 dict(external_port='80;reboot'), dict(internal_port='80-81'), dict(enabled='true'),
                 dict(reflection=1), dict(name='bad\nname'), dict(id='../bad'), dict(protocol='all'),
                 dict(source_zone='management'), dict(destination_zone='management'),
                 dict(destination_ip='192.168.7.10'), dict(destination_ip='192.168.10.1'),
                 dict(destination_ip='192.168.10.255'), dict(destination_ip='127.0.0.1'),
                 dict(source_ip='::1'), dict(source_ip='1.2.3.4;foo'), dict(external_ip='224.0.0.1'),
                 dict(source_zone='router_vpn', reflection=True), dict(extra='unsupported')]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.apply([rule(**changes)])
        self.backend.transaction.assert_not_called()

    def test_overlap_checks_protocols_sources_addresses_and_ranges(self):
        first=rule(external_port='8000-8010', internal_port='8000-8010')
        second=rule(id='fedcba9876543210', external_port='8010', internal_port='80')
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.apply([first, second])
        for changes in (dict(protocol='udp'), dict(enabled=False), dict(source_zone='router_vpn')):
            self.apply([first, second | changes])
        self.apply([first | dict(source_ip='203.0.113.0/25'), second | dict(source_ip='203.0.113.128/25')])
        self.apply([first | dict(external_ip='198.51.100.1'), second | dict(external_ip='198.51.100.2')])

    def test_duplicate_ids_limit_and_stale_revision(self):
        with self.assertRaisesRegex(ValueError, 'unique'):
            self.apply([rule(), rule(enabled=False)])
        with self.assertRaises(ValueError):
            self.apply([rule()] * 101)
        with self.assertRaisesRegex(RuntimeError, 'Reload'):
            pf.apply(dict(revision='stale', rules=[]), self.backend, Mock())
        self.backend.transaction.assert_not_called()

    def test_unmanaged_rules_preserved_and_conflicts_rejected(self):
        self.config['existing']={'.type':'redirect','name':'Existing camera','src':'wan','dest':'lan',
                                 'src_dport':'8080','dest_port':'80','dest_ip':'192.168.10.101','proto':'tcp'}
        with self.assertRaisesRegex(ValueError, 'Existing camera'):
            self.apply([rule()])
        self.apply([rule(external_port='8081')])
        edits=self.backend.transaction.call_args.args[1]
        self.assertFalse(any('existing' in e[1] for e in edits))
        state=pf.status(self.backend)
        self.assertEqual(state['unmanaged'][0]['name'],'Existing camera')

    def test_enable_delete_and_status_roundtrip(self):
        managed=pf.PREFIX+rule()['id']
        self.config[managed]={'.type':'redirect','name':'Disabled rule','enabled':'0','src':'wan',
                              'dest':'lan','proto':['tcp','udp'],'src_dport':'8080','dest_port':'80',
                              'dest_ip':'192.168.10.100','reflection':'0'}
        state=pf.status(self.backend)
        self.assertFalse(state['rules'][0]['enabled'])
        self.assertEqual(state['rules'][0]['protocol'],'tcp udp')
        self.apply([])
        self.assertIn(('delete','firewall.'+managed,None),self.backend.transaction.call_args.args[1])

    def test_firewall_check_precedes_reload(self):
        self.apply([rule()])
        activate=self.backend.transaction.call_args.args[2]
        activate()
        self.assertEqual([call.args for call in self.backend.run.call_args_list],
                         [('fw4','check'),('/etc/init.d/firewall','reload'),('nft','list','table','inet','fw4')])
        self.backend.run.reset_mock()
        self.backend.run.side_effect=RuntimeError('Invalid candidate')
        with self.assertRaises(RuntimeError):
            activate()
        self.assertEqual(self.backend.run.call_count,1)

    def test_transaction_restores_previous_firewall_after_activation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original='config defaults\n option input REJECT\n'
            (root/'firewall').write_text(original)
            calls=[]
            def run(*args):
                if 'commit' in args:
                    candidate=Path(args[args.index('-c')+1])/'firewall'
                    candidate.write_text(original+'# candidate\n')
                return ''
            def activate():
                calls.append((root/'firewall').read_text())
                if len(calls)==1:
                    raise RuntimeError('Firewall validation failed')
            with patch.object(backend,'CONFIG',root),patch.object(backend,'STATE',root),patch.object(backend,'run',side_effect=run):
                with self.assertRaises(RuntimeError):
                    backend.transaction('firewall',[],activate,server.atomic_write)
            self.assertEqual((root/'firewall').read_text(),original)
            self.assertEqual(calls,[original+'# candidate\n',original])
            self.assertEqual((root/'firewall.previous').read_text(),original)


if __name__ == '__main__':
    unittest.main()
