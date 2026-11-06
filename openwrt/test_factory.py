"""Host checks for factory initialization and modem discovery edge cases."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'openwrt'), str(ROOT / 'web')]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'openwrt' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


factory = load('factory-initialize')
modem = load('factory-modem')


class FactoryTests(unittest.TestCase):
    def test_first_boot_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'
            serial = Path(directory) / 'serial'
            serial.write_text('new-board-serial\0')

            def path(value):
                return {'/etc/router-web': state, '/proc/device-tree/serial-number': serial}[value]

            def uci(*args):
                if args == ('show', 'wireless'):
                    return 'wireless.radio0=wifi-device\nwireless.default_radio0=wifi-iface'
                return ''

            with patch.object(factory, 'Path', side_effect=path), \
                 patch.object(factory, 'uci', side_effect=uci) as commands, \
                 patch.object(factory.subprocess, 'run'):
                factory.main()
                self.assertTrue((state / 'configured').exists())
                password = (state / 'initial-wifi-password').read_text().strip()
                self.assertGreaterEqual(len(password), 18)
                calls = [c.args for c in commands.call_args_list]
                self.assertIn(('set', 'wireless.router_ap.key=' + password), calls)
                self.assertIn(('set', 'usbgadget.g1.serialnumber=new-board-serial'), calls)
                self.assertEqual(json.loads((state / 'credentials.json').read_text())['username'], 'admin')
                commands.reset_mock()
                factory.main()
                commands.assert_not_called()
                self.assertEqual((state / 'initial-wifi-password').read_text().strip(), password)

    def test_missing_radio_leaves_retry_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'
            serial = Path(directory) / 'serial'
            serial.write_text('board')
            with patch.object(factory, 'Path', side_effect=lambda p: state if p == '/etc/router-web' else serial), \
                 patch.object(factory, 'uci', return_value=''), patch.object(factory.subprocess, 'run'):
                with self.assertRaisesRegex(RuntimeError, 'No Wi-Fi'):
                    factory.main()
                self.assertFalse((state / 'factory-initialized').exists())
                self.assertFalse((state / 'configured').exists())

    def test_modem_path_change_reloads_once(self):
        device = '/sys/devices/platform/usb1/1-2'
        for current, expected in [('old-path', True), (device, False)]:
            with self.subTest(current=current):
                def run(*args):
                    if args == ('mmcli', '-L', '-J'):
                        return json.dumps({'modem-list': ['/org/freedesktop/ModemManager1/Modem/0']})
                    if args[0] == 'mmcli':
                        return json.dumps({'modem': {'generic': {'device': device}}})
                    return current
                with patch.object(modem, 'run', side_effect=run) as commands:
                    modem.poll()
                    self.assertEqual(any(c.args == ('/etc/init.d/network', 'reload')
                                         for c in commands.call_args_list), expected)

    def test_no_modem_or_ambiguous_modems_preserve_config(self):
        for devices in ([], ['one', 'two']):
            with patch.object(modem, 'run', return_value=json.dumps({'modem-list': devices})) as commands:
                modem.poll()
                self.assertEqual(commands.call_count, 1)


if __name__ == '__main__':
    unittest.main()
