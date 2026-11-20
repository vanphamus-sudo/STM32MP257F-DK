import tempfile
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import modem_auto as auto


class ModemAutoTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'USB sysfs interface names require Linux')
    def test_detects_only_supported_ready_devices_and_resolves_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, pid in [('rg', '0316'), ('em', '030b'), ('rm', '0801'), ('other', '9999')]:
                device = root / name
                device.mkdir()
                (device / 'idVendor').write_text('2c7c\n')
                (device / 'idProduct').write_text(pid + '\n')
                (device / (name + ':1.3') / 'net' / 'wwan0').mkdir(parents=True)
            self.assertEqual({item['model'] for item in auto.discover(root)},
                             {'RG255C-GL', 'EM060K-GL', 'RM520N-GL'})
            (root / 'em/em:1.3/net/wwan0').rmdir()
            self.assertEqual({item['model'] for item in auto.discover(root)},
                             {'RG255C-GL', 'RM520N-GL'})

    def test_multiple_devices_preserve_selected_path(self):
        choices = [dict(model='RG255C-GL', device='/sys/rg'),
                   dict(model='EM060K-GL', device='/sys/em')]
        self.assertEqual(auto.choose(choices, '/sys/em'), choices[1])
        self.assertIsNone(auto.choose(choices, '/sys/missing'))

    def reconcile(self, state, model, settings, pending=''):
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            if args[:3] == ('uci', '-q', 'get'):
                return settings.get(args[3].split('.')[-1], '')
            if args == ('uci', 'changes', 'network'):
                return pending
            return ''
        with patch.object(auto, 'run', side_effect=run), \
             patch.object(auto, 'discover', return_value=[dict(model=model, device='/sys/new')]), \
             patch.object(auto, 'write_json'):
            auto.reconcile(state)
        return calls

    def test_swap_to_lte_saves_5g_profile_and_removes_unsupported_mode(self):
        state = dict(model='RG255C-GL', profiles={})
        calls = self.reconcile(state, 'EM060K-GL',
                               dict(device='/sys/old', proto='modemmanager', allowedmode='5g'))
        self.assertIn(('uci', 'set', 'network.wan.allowedmode=4g'), calls)
        self.assertIn(('uci', 'set', 'network.wan.device=/sys/new'), calls)
        self.assertEqual(state['profiles']['RG255C-GL']['allowedmode'], '5g')
        calls = self.reconcile(state, 'RG255C-GL',
                               dict(device='/sys/old', proto='modemmanager', allowedmode='4g'))
        self.assertIn(('uci', 'set', 'network.wan.allowedmode=5g'), calls)

    def test_pending_ui_changes_are_not_committed(self):
        state = dict(model='RG255C-GL', profiles={})
        calls = self.reconcile(state, 'EM060K-GL', dict(device='/sys/old'), 'network.wan.apn=x')
        self.assertNotIn(('uci', 'commit', 'network'), calls)
        self.assertNotIn(('ifdown', 'wan'), calls)
        self.assertEqual(state, dict(model='RG255C-GL', profiles={}))

    def test_same_modem_preserves_explicit_5g_and_is_idempotent(self):
        state = dict(model='RG255C-GL', profiles={})
        calls = self.reconcile(state, 'RG255C-GL',
                               dict(device='/sys/new', proto='modemmanager', allowedmode='5g'))
        self.assertNotIn(('ifdown', 'wan'), calls)
        self.assertEqual(state['profiles']['RG255C-GL']['allowedmode'], '5g')

    def test_first_rg_after_em_enables_both_radio_modes(self):
        state = dict(model='EM060K-GL', profiles={})
        calls = self.reconcile(state, 'RG255C-GL',
                               dict(device='/sys/new', proto='modemmanager', allowedmode='4g'))
        self.assertIn(('uci', 'set', 'network.wan.allowedmode=4g|5g'), calls)
        self.assertIn(('uci', 'set', 'network.wan.preferredmode=5g'), calls)

    def test_no_modem_leaves_configuration_and_saved_profiles_untouched(self):
        state = dict(model='RG255C-GL', profiles={})
        with patch.object(auto, 'run', return_value='/sys/old') as run, \
             patch.object(auto, 'discover', return_value=[]), \
             patch.object(auto, 'write_json'):
            auto.reconcile(state)
        self.assertEqual(state, dict(model='RG255C-GL', profiles={}))
        self.assertEqual(run.call_count, 1)

    def test_rm520_after_lte_defaults_to_4g_5g_and_retains_other_profiles(self):
        state = dict(model='EM060K-GL', profiles={
            'RG255C-GL': dict(allowedmode='5g', preferredmode='')})
        calls = self.reconcile(state, 'RM520N-GL',
                               dict(device='/sys/new', proto='modemmanager', allowedmode='4g'))
        self.assertIn(('uci', 'set', 'network.wan.allowedmode=4g|5g'), calls)
        self.assertIn(('uci', 'set', 'network.wan.preferredmode=5g'), calls)
        self.assertEqual(state['profiles']['RG255C-GL']['allowedmode'], '5g')
        self.assertEqual(state['model'], 'RM520N-GL')

    def test_rm520_saved_mode_restored_independently(self):
        state = dict(model='RG255C-GL', profiles={
            'RM520N-GL': dict(allowedmode='4g|5g', preferredmode='5g')})
        calls = self.reconcile(state, 'RM520N-GL',
                               dict(device='/sys/new', proto='modemmanager', allowedmode='5g'))
        self.assertIn(('uci', 'set', 'network.wan.allowedmode=4g|5g'), calls)
        self.assertEqual(state['profiles']['RG255C-GL']['allowedmode'], '5g')


if __name__ == '__main__':
    unittest.main()
