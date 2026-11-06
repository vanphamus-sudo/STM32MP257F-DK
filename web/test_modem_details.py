import unittest
from unittest.mock import patch
import modem_details as modem

class ModemDetailsTests(unittest.TestCase):
    def test_lte_serving_cell(self):
        data = modem.serving_cell('+QENG: "servingcell","NOCONN","LTE","FDD",505,01,8322A01,36,1275,3,4,4,309F,-86,-10,-57,16,-,-')
        self.assertEqual(data['band'], 'LTE BAND 3')
        self.assertEqual(data['rsrp'], '-86.0 dBm')
        self.assertEqual(data['sinr'], '16.0 dB')
        self.assertEqual(data['cell_id'], str(int('8322A01', 16)))
        self.assertIn('12447', data['lac'])

    def test_invalid_or_other_radio_does_not_invent_metrics(self):
        for response in ('ERROR', '+QENG: "servingcell","SEARCH"', '+QENG: "servingcell","NOCONN","WCDMA",1,2,3'):
            self.assertEqual(modem.serving_cell(response), {})

    def test_unavailable_modem_has_all_fields(self):
        class Backend:
            def values(self, name): return {'wan': {'device': 'test'}}
            def send_at(self, data): raise RuntimeError('busy')
        with patch.object(modem, 'query', return_value={}):
            result = modem.collect(Backend())
        self.assertEqual(set(result), set(modem.FIELDS))
        self.assertIsNone(result['band'])
        self.assertIsNone(result['iccid'])
