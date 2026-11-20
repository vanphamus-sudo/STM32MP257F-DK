import tempfile
import shlex
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import router_logs as logs

VALID = dict(local=dict(buffer_kib=128, file_enabled=False, storage='memory', file_kib=1024),
             remote=dict(enabled=False, host='', port=514, protocol='udp'))


class LogsTests(unittest.TestCase):
    def setUp(self):
        self.backend=Mock()
        self.system={'.type':'system','log_size':'128'}
        self.backend.values.side_effect=lambda package: {'cfg01':self.system} if package=='system' else {'wan':{'password':'private-value'}}
        self.backend.run.side_effect=lambda *args: '\n'.join('system.cfg01'+('' if k=='.type' else '.'+k)+'='+shlex.quote(v) for k,v in self.system.items()) if args[:3]==('uci','-q','show') else ''

    def test_defaults_and_remote_disabled_without_host(self):
        value=logs.settings(self.backend)
        self.assertEqual(value['local']['buffer_kib'],128)
        self.assertFalse(value['local']['file_enabled'])
        self.assertFalse(value['remote']['enabled'])

    def test_validation_blocks_bad_destinations_sizes_and_paths(self):
        for changes in (dict(host='a;reboot',enabled=True),dict(host=''),dict(port=0),dict(port=True),dict(protocol='tls')):
            remote=dict(VALID['remote'],enabled=True,**{k:v for k,v in changes.items() if k!='enabled'})
            if 'enabled' in changes:remote['enabled']=changes['enabled']
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                logs.validate(dict(VALID,remote=remote))
        for changes in (dict(buffer_kib=0),dict(buffer_kib=True),dict(file_kib=100000),dict(storage='/etc/shadow')):
            with self.assertRaises(ValueError):logs.validate(dict(VALID,local=dict(VALID['local'],**changes)))
        logs.validate(dict(VALID,remote=dict(enabled=True,host='2001:db8::1',port=514,protocol='tcp')))

    def test_save_uses_system_transaction_and_native_log_restart(self):
        data=dict(VALID,local=dict(VALID['local'],file_enabled=True,storage='persistent'),
                  remote=dict(enabled=True,host='collector.example.com',port=1514,protocol='tcp'))
        logs.save(data,self.backend,Mock())
        package,edits,activate,_=self.backend.transaction.call_args.args
        self.assertEqual(package,'system')
        self.assertIn(('set','system.cfg01.log_file','/root/router-logs/messages.log'),edits)
        self.assertIn(('set','system.cfg01.log_proto','tcp'),edits)
        self.assertTrue(all(key.startswith('system.cfg01.') for _,key,_ in edits))
        activate();self.assertIn(('/etc/init.d/log','restart'),[call.args for call in self.backend.run.call_args_list])

    def test_categories_search_and_secret_masking(self):
        raw=b'now kern.info kernel: usb link\nnow daemon.info app: password=private-value\nnow authpriv.info dropbear: login\nnow daemon.info app: <script>alert(1)</script>\n'
        with patch.object(logs.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=raw)) as command:
            value=logs.read(self.backend,category='application')
            self.assertEqual(len(value['lines']),2)
            self.assertNotIn('private-value',str(value))
            self.assertEqual(len(logs.read(self.backend,category='audit')['lines']),1)
            self.assertEqual(len(logs.read(self.backend,search='USB')['lines']),1)
            self.assertTrue(command.call_args.args[0][0]=='logread')
            logs.read(self.backend,category='kernel')
            self.assertEqual(command.call_args.args[0],['dmesg'])

    def test_bounds_and_untrusted_query(self):
        raw=('line\n'*1200).encode()
        with patch.object(logs.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=raw)):
            value=logs.read(self.backend,limit=100)
            self.assertEqual(len(value['lines']),100);self.assertTrue(value['truncated'])
        for arguments in (dict(category='../../etc/shadow'),dict(source='other'),dict(limit=1001),dict(search='x\n')):
            with self.assertRaises(ValueError):logs.read(self.backend,**arguments)

    def test_file_read_is_restricted_and_bounded(self):
        self.system['log_file']='/etc/shadow'
        with self.assertRaises(ValueError):logs.read(self.backend,source='file')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'messages';path.write_text('old\n'*100000+'last record\n')
            self.system['log_file']=str(path)
            with patch.dict(logs.FILES,memory=str(path)):
                value=logs.read(self.backend,source='file',limit=2)
            self.assertEqual(value['lines'][-1],'last record');self.assertTrue(value['truncated'])
        self.system.pop('log_file')
        self.assertIn('disabled',logs.read(self.backend,source='file')['note'])
