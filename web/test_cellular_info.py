import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

import cellular_info as info
import modem_details
import router_features as features


class CellularInfoTests(unittest.TestCase):
    def test_band3_channel_and_ranges_are_in_mhz(self):
        label=info.band_label(3,1275)
        self.assertIn('1805-1880 MHz',label)
        self.assertIn('1710-1785 MHz',label)
        self.assertIn('current downlink 1812.5 MHz',label)

    def test_channel_range_edges_tdd_and_downlink_only(self):
        self.assertIn('current downlink 758 MHz',info.band_label(28,9210))
        self.assertIn('current downlink 617 MHz',info.band_label(71,68586))
        self.assertIn('2300-2400 MHz',info.band_label(40,38650))
        self.assertIn('downlink-only',info.band_label(29,9660))
        self.assertNotIn('current downlink',info.band_label(3,100))
        self.assertNotIn('current downlink',info.band_label(3,1950))
        self.assertNotIn('current downlink',info.band_label(999,1275))

    def test_unknown_channel_does_not_discard_other_metrics(self):
        value=modem_details.serving_cell('+QENG: "servingcell","NOCONN","LTE","FDD",505,01,8322A01,36,-,3,4,4,309F,-86,-10,-57,16,-,-')
        self.assertIn('1805-1880 MHz',value['band'])
        self.assertEqual(value['rsrp'],'-86.0 dBm')
        self.assertNotIn('current downlink',value['band'])

    def test_directory_integrity_country_names_and_leading_zeros(self):
        data=info.directory();countries={c['mcc']:c for c in data['countries']}
        self.assertEqual(countries['505']['name'],'Australia')
        self.assertEqual(countries['734']['name'],'Venezuela (Bolivarian Republic of)')
        self.assertIn('Saint Helena',countries['658']['name'])
        self.assertEqual(countries['419']['name'],'Kuwait')
        entries={c['mcc']+n['mnc']:n['name'] for c in data['countries'] for n in c['networks']}
        self.assertEqual(entries['50501'],'Telstra Corporation Ltd.')
        self.assertIn('Optus',entries['50502'])
        self.assertIn('Vodafone',entries['50503'])
        self.assertIn('T-Mobile',entries['310260'].replace(' ',''))
        self.assertEqual(entries['45204'],'Viettel')
        self.assertEqual(len(entries),2255)
        for c in data['countries']:
            self.assertRegex(c['mcc'],r'^\d{3}$')
            self.assertLess(len(c['name']),120)
            for network in c['networks']:
                self.assertRegex(network['mnc'],r'^\d{2,3}$')
                self.assertTrue(network['name'])

    def test_live_names_and_saved_unknown_codes_do_not_modify_directory(self):
        before=copy.deepcopy(info.directory())
        result=info.choices(dict(code='50501',name='Telstra'),'999001')
        by_code={c['mcc']+n['mnc']:n['name'] for c in result['countries'] for n in c['networks']}
        self.assertEqual(by_code['50501'],'Telstra')
        self.assertIn('999001',by_code)
        self.assertEqual(info.directory(),before)

    def test_supported_band_options_only_label_lte(self):
        result=info.band_options(['eutran-71','utran-1','eutran-3','any'])
        self.assertEqual([r['value'] for r in result],['eutran-3','eutran-71'])
        self.assertTrue(all('MHz' in r['label'] for r in result))


class SmsInboxTests(unittest.TestCase):
    def test_delete_checks_selected_modem_and_deletes_only_selected_message(self):
        path='/org/freedesktop/ModemManager1/SMS/12'
        with patch.object(features,'execute',side_effect=[json.dumps({'modem.messaging.sms':[path]}),'deleted']) as execute:
            result=features.sms({'action':'delete','id':12},self.backend)
        self.assertIn('deleted',result['message'])
        self.assertEqual(execute.call_args.args,('mmcli','-m','test-modem','--messaging-delete-sms='+path))

    def test_delete_rejects_invalid_or_missing_message_without_deletion(self):
        for payload in ({'action':'delete','id':True},{'action':'delete','id':-1},{'action':'delete','id':'1; reboot'},{'action':'delete','id':1,'all':True}):
            with patch.object(features,'execute') as execute:
                with self.assertRaises(ValueError):features.sms(payload,self.backend)
                execute.assert_not_called()
        with patch.object(features,'execute',return_value=json.dumps({'modem.messaging.sms':[]})) as execute:
            with self.assertRaisesRegex(ValueError,'no longer'):features.sms({'action':'delete','id':12},self.backend)
            self.assertEqual(execute.call_count,1)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(features,'STATE',self.state).start()
        config=features.config();config['sms']['enabled']=True
        features.atomic(self.state/'features.json',config)
        self.backend=Mock();self.backend.values.return_value={'wan':{'device':'test-modem'}}

    def test_actual_flat_mmcli_list_returns_received_text_without_mutation(self):
        commands=[]
        def execute(*args,**kwargs):
            commands.append(args)
            if '--messaging-list-sms' in args:
                return json.dumps({'modem.messaging.sms':['/org/freedesktop/ModemManager1/SMS/1']})
            return json.dumps({'sms':{'content':{'number':'+10000000000','text':'Test only'},'properties':{'state':'received','timestamp':'2026-11-12T00:00:00Z'}}})
        with patch.object(features,'execute',side_effect=execute):result=features.sms({'action':'list'},self.backend)
        self.assertEqual(result['messages'][0]['text'],'Test only')
        self.assertEqual(result['messages'][0]['state'],'received')
        self.assertEqual(result['total'],1)
        self.assertEqual(result['failed'],0)
        self.assertFalse(result['truncated'])
        self.assertFalse(any('--send' in c or '--messaging-delete-sms' in c for c in commands))

    def test_nested_older_shape_and_empty_list(self):
        for listed in ({'modem.messaging.sms':[]},{'modem':{'messaging':{'sms':[]}}}):
            with patch.object(features,'execute',return_value=json.dumps(listed)):
                result=features.sms({'action':'list'},self.backend)
            self.assertEqual(result['messages'],[])
            self.assertEqual(result['total'],0)

    def test_unknown_shape_is_not_misreported_as_empty(self):
        with patch.object(features,'execute',return_value='{}'):
            with self.assertRaisesRegex(RuntimeError,'unrecognized SMS list'):
                features.sms({'action':'list'},self.backend)

    def test_one_disappearing_message_does_not_hide_other_messages(self):
        listed={'modem.messaging.sms':['/org/freedesktop/ModemManager1/SMS/1','/org/freedesktop/ModemManager1/SMS/2']}
        with patch.object(features,'execute',side_effect=[json.dumps(listed),RuntimeError('gone'),json.dumps({'sms':{'content':{'text':'Available'},'properties':{'state':'received'}}})]):
            result=features.sms({'action':'list'},self.backend)
        self.assertEqual(result['failed'],1)
        self.assertEqual(result['messages'][0]['text'],'Available')
        self.assertEqual(result['total'],2)

    def test_batch_is_bounded(self):
        listed={'modem.messaging.sms':['/org/freedesktop/ModemManager1/SMS/'+str(i) for i in range(45)]}
        def execute(*args,**kwargs):
            return json.dumps(listed if '--messaging-list-sms' in args else {'sms':{'content':{'text':'Test'},'properties':{'state':'received'}}})
        with patch.object(features,'execute',side_effect=execute):result=features.sms({'action':'list'},self.backend)
        self.assertEqual(len(result['messages']),30)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['total'],45)

    def test_sms_off_requires_explicit_enable(self):
        config=features.config();config['sms']['enabled']=False
        features.atomic(self.state/'features.json',config)
        with self.assertRaisesRegex(ValueError,'Enable SMS'):
            features.sms({'action':'list'},self.backend)


if __name__=='__main__':unittest.main()
