import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import modbus_settings as mb
import serial_assignment as sa
from test_modbus import config


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module in (sa, mb):
            p = patch.object(module, 'STATE', self.root)
            p.start()
            self.addCleanup(p.stop)
        self.mb = config()
        self.tcp = copy.deepcopy(sa.DEFAULT)
        (self.root/'modbus.json').write_text(json.dumps(self.mb))
        (self.root/'serial-tcp.json').write_text(json.dumps(self.tcp))
        self.backend = Mock()
        self.backend.service_active.side_effect = lambda n: n == 'router-modbus'
        self.data = dict(mode='tcp', device='usb:067b:2303', tcp_baud=9600, tcp_port=5000)

    def write(self, path, value):
        path.write_text(value)

    @patch.object(sa.subprocess, 'run', return_value=Mock(returncode=0))
    @patch.object(sa, 'service')
    def test_switch_both_directions_and_disable(self, service, run):
        for mode in ('tcp', 'modbus', 'disabled'):
            self.data['mode'] = mode
            result = sa.apply(self.data, self.backend, self.write)
            self.assertEqual(result['mode'], mode)
            self.assertEqual(sa.bridge()['enabled'], mode == 'tcp')
            self.assertEqual(mb.current()['enabled'], mode == 'modbus')
            self.assertEqual(service.call_args_list[0].args, ('router-serial','stop'))
            self.assertEqual(service.call_args_list[1].args, ('router-modbus','stop'))
            service.reset_mock()

    @patch.object(sa.subprocess, 'run', return_value=Mock(returncode=0))
    @patch.object(sa, 'service')
    def test_start_failure_restores_configs_and_service(self, service, run):
        def fail(name, action):
            if name == 'router-serial' and action == 'start':
                raise OSError('start failed')
        service.side_effect = fail
        with self.assertRaises(OSError):
            sa.apply(self.data, self.backend, self.write)
        self.assertEqual(mb.current(), self.mb)
        self.assertEqual(sa.bridge(), self.tcp)
        self.assertIn(unittest.mock.call('router-modbus','start'), service.call_args_list)

    @patch.object(sa, 'service')
    def test_invalid_modbus_config_does_not_stop_services(self, service):
        bad = mb.current()
        bad['devices'] = []
        (self.root/'modbus.json').write_text(json.dumps(bad))
        self.data['mode'] = 'modbus'
        with self.assertRaises(ValueError):
            sa.apply(self.data, self.backend, self.write)
        service.assert_not_called()

    @patch.object(mb, 'service')
    def test_modbus_apply_cannot_take_bridge_port(self, service):
        self.tcp['enabled'] = True
        (self.root/'serial-tcp.json').write_text(json.dumps(self.tcp))
        with self.assertRaisesRegex(ValueError, 'Serial port assignment'):
            mb.apply(self.mb, self.backend, self.write)
        service.assert_not_called()
