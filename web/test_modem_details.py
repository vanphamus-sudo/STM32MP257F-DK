import unittest
import io
import json
from unittest.mock import patch
import modem_details as modem

class ModemDetailsTests(unittest.TestCase):
    def test_lte_serving_cell(self):
        data = modem.serving_cell('+QENG: "servingcell","NOCONN","LTE","FDD",505,01,8322A01,36,1275,3,4,4,309F,-86,-10,-57,16,-,-')
        self.assertIn('LTE BAND 3',data['band'])
        self.assertIn('1805-1880 MHz',data['band'])
        self.assertIn('1710-1785 MHz',data['band'])
        self.assertIn('1812.5 MHz',data['band'])
        self.assertEqual(data['rsrp'], '-86.0 dBm')
        self.assertEqual(data['sinr'], '16.0 dB')
        self.assertEqual(data['cell_id'], str(int('8322A01', 16)))
        self.assertIn('12447', data['lac'])
        self.assertEqual(data['cell'], dict(mcc=505, mnc=1, lac=12447, cellid=int('8322A01', 16)))

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

    def test_location_lookup_sends_only_cell_fields(self):
        cell = dict(mcc=505, mnc=1, lac=12447, cellid=137505281)
        reply = io.BytesIO(json.dumps(dict(result=200, data=dict(lat=-33.86, lon=151.2))).encode())
        with patch.object(modem, 'collect', return_value=dict(cell=cell, imsi='private')), \
                patch.object(modem, 'urlopen', return_value=reply) as request:
            result = modem.locate(None)
        self.assertEqual(result['latitude'], -33.86)
        self.assertEqual(request.call_args.args[0], 'https://api.mylnikov.org/geolocation/cell?mcc=505&mnc=1&lac=12447&cellid=137505281&v=1.1&data=open')
        self.assertEqual(request.call_args.kwargs, dict(timeout=7))

    def test_missing_cell_does_not_contact_provider(self):
        with patch.object(modem, 'collect', return_value={}), patch.object(modem, 'urlopen') as request:
            with self.assertRaises(ValueError):
                modem.locate(None)
            request.assert_not_called()

    def test_lookup_timeout_is_reported(self):
        with patch.object(modem, 'collect', return_value=dict(
                cell=dict(mcc=505, mnc=1, lac=12447, cellid=123))), \
                patch.object(modem, 'urlopen', side_effect=TimeoutError):
            with self.assertRaisesRegex(RuntimeError, 'Check the Internet connection'):
                modem.locate(None)

    def test_location_rejects_bad_or_missing_coordinates(self):
        for body in ({'result': 404}, {'result': 200, 'data': {'lat': 0, 'lon': 0}},
                     {'result': 200, 'data': {'lat': 91, 'lon': 1}},
                     {'result': 200, 'data': {'lat': float('nan'), 'lon': 1}}, []):
            reply = io.BytesIO(json.dumps(body).encode())
            with self.subTest(body=body), patch.object(modem, 'collect', return_value=dict(
                    cell=dict(mcc=505, mnc=1, lac=12447, cellid=123))), \
                    patch.object(modem, 'urlopen', return_value=reply):
                with self.assertRaises(RuntimeError):
                    modem.locate(None)
