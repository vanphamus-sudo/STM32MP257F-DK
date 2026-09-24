import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wifi
from server import atomic_write

class WifiTests(unittest.TestCase):
    def test_validation_and_secret_handling(self):
        args = dict(enabled=True, ssid='Test hotspot', channel=6, password='password123')
        old = wifi.validate(args, {})
        self.assertNotIn('password123', wifi.render(old))
        self.assertEqual(len(old['psk']), 64)
        self.assertEqual(wifi.validate(args | dict(password=''), old), old)
        for update in (dict(password='short'), dict(ssid='x\ninterface=usb0'), dict(channel=14),
                       dict(enabled='yes'), dict(ssid='new', password='')):
            with self.subTest(update=update), self.assertRaises(ValueError):
                wifi.validate(args | update, old)

    def test_failed_start_restores_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            old=wifi.validate(dict(enabled=True,ssid='Test',channel=6,password='password123'), {})
            (base/'wifi.json').write_text(json.dumps(old))
            (base/'hostapd.conf').write_text(wifi.render(old))
            with patch.object(wifi,'BASE',base), patch.object(wifi,'activate',side_effect=[RuntimeError('failed'),None]) as activate:
                with self.assertRaises(RuntimeError):
                    wifi.apply(dict(enabled=True,ssid='Test',channel=11,password=''),atomic_write)
                self.assertEqual((base/'hostapd.conf').read_text(),wifi.render(old))
                self.assertEqual(wifi.current(),old)
                self.assertEqual(activate.call_args.args[0],old)

if __name__=='__main__':
    unittest.main()
