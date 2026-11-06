import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import mqtt_data
import mqtt_settings as settings
from mqtt_protocol import FIELDS, Protocol, TELEMETRY, unhex
from mqtt_proxy import Proxies


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Mock()
        self.adapter.telemetry.return_value = {}
        self.adapter.operation.return_value = {'gpio': {}, 'serial': {}}
        self.adapter.events.return_value = []
        self.adapter.proxies.poll.return_value = []
        self.sent = []
        self.protocol = Protocol('BOARD001', self.adapter, lambda topic, raw: self.sent.append((topic, raw)))

    def receive(self, suffix, data, **kwargs):
        self.protocol.receive('/RX/BOARD001/' + suffix, json.dumps(data).encode(), **kwargs)

    def login(self):
        self.receive('LOGIN', {'login': '1580381938'})

    def test_login_empty_payload_and_retry(self):
        self.protocol.tick(0)
        self.assertEqual(self.sent, [('/TX/BOARD001/LOGIN', b'')])
        self.protocol.tick(29)
        self.assertEqual(len(self.sent), 1)
        self.protocol.tick(30)
        self.assertEqual(len(self.sent), 2)

    def test_all_telemetry_after_login_and_schedule(self):
        self.adapter.telemetry.return_value = {'nettype': '4G'}
        self.login()
        self.protocol.tick(0)
        topics = [topic for topic, _ in self.sent]
        for name in TELEMETRY:
            self.assertIn('/TX/BOARD001/DEVINFO/' + name, topics)
        count = len(self.sent)
        self.protocol.tick(59)
        self.assertEqual(len(self.sent), count)
        self.protocol.tick(60)
        self.assertEqual(self.sent[-1][0], '/TX/BOARD001/DEVINFO/GPS')
        self.protocol.tick(180)
        self.assertEqual(sum(topic.endswith('/HEARTBEAT') for topic, _ in self.sent), 2)

    def test_absent_sim_does_not_publish_empty_signal(self):
        self.adapter.telemetry.return_value = {}
        self.protocol.telemetry('SIM2')
        self.assertEqual(self.sent, [])

    def test_requests_match_schema_and_types(self):
        self.login()
        for name, fields in FIELDS.items():
            self.adapter.telemetry.return_value = {key: 12 for key in fields.split()}
            self.receive('DEVINFO/' + name, {'get': ''})
            payload = json.loads(self.sent[-1][1])
            self.assertEqual(set(payload), set(fields.split()))
            self.assertTrue(all(isinstance(value, str) for value in payload.values()))

    def test_rssi_is_preserved_in_published_sim_payload(self):
        self.login()
        self.adapter.telemetry.return_value = dict(rssi='-60', rsrp='-88')
        self.receive('DEVINFO/SIM1', {'get': ''})
        self.assertEqual(json.loads(self.sent[-1][1])['rssi'], '-60')

    def test_retained_other_device_and_prelogin_commands_ignored(self):
        self.receive('EVENT/SHELL', {'shell': 'reboot'})
        self.receive('LOGIN', {'login': '1'}, retained=True)
        self.assertFalse(self.protocol.logged_in)
        self.login()
        self.receive('EVENT/SHELL', {'shell': 'reboot'}, retained=True)
        self.protocol.receive('/RX/OTHER/EVENT/SHELL', b'{"shell":"reboot"}')
        self.adapter.operation.assert_not_called()

    def test_config_hex_and_files(self):
        self.login()
        self.receive('CONFIG', {'cli': '616263'})
        self.adapter.operation.assert_called_with('CONFIG', {'cli': 'abc'})
        self.receive('EVENT/SETFILE', {'filename': '/etc/rxconfig/cli.conf', 'data': '00ff'})
        self.adapter.operation.assert_called_with('EVENT/SETFILE', {'filename': '/etc/rxconfig/cli.conf', 'data': b'\x00\xff'})
        self.receive('CONFIG', {'cli': 'not hex'})
        self.assertEqual(json.loads(self.sent[-1][1])['result'], 'fail')

    def test_alarm_only_matching_id_is_acknowledged(self):
        self.login()
        self.receive('ALARM', {'id': 17})
        self.adapter.ack.assert_called_once_with('ALARM', 17)

    def test_industry_filter_and_unsupported_commands(self):
        self.login()
        self.receive('INDUSTRY/GET', {'get': ['gpio']})
        self.assertEqual(json.loads(self.sent[-1][1]), {'gpio': {}})
        self.adapter.operation.side_effect = ValueError('Unsupported')
        self.receive('UPGRADE', {'firmware': 'https://example.com/fw.bin'})
        self.assertEqual(json.loads(self.sent[-1][1])['result'], 'fail')

    def test_proxy_raw_and_poll(self):
        self.login()
        self.protocol.receive('/RX/BOARD001/PROXY/127.0.0.1/80/1234', b'\xff\x00')
        self.adapter.proxies.receive.assert_called_once_with('PROXY/127.0.0.1/80/1234', b'\xff\x00')
        self.adapter.proxies.poll.return_value = [('PROXY/serial1', b'00ff')]
        self.protocol.tick(0)
        self.assertIn(('/TX/BOARD001/PROXY/serial1', b'00ff'), self.sent)

    def test_malformed_messages_do_not_escape(self):
        self.login()
        for raw in (b'[]', b'bad', b'\xff', b'{}' * 70000):
            self.protocol.receive('/RX/BOARD001/CONFIG', raw)
        for value in ('f', 'ff gg', 'zz', None):
            with self.assertRaises(ValueError):
                unhex(value)


class ProxyTests(unittest.TestCase):
    def test_tcp_proxy_binary_roundtrip_and_allowlist(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(2)
        port = listener.getsockname()[1]
        proxies = Proxies({'tcp_proxy_targets': ['127.0.0.1:' + str(port)]})
        self.addCleanup(proxies.close_all)
        with self.assertRaises(ValueError):
            proxies.receive('PROXY/127.0.0.1/1/2', b'x')
        suffix = f'PROXY/127.0.0.1/{port}/42'
        proxies.receive(suffix, b'\x00\xffhello')
        peer, _ = listener.accept()
        self.addCleanup(peer.close)
        peer.settimeout(2)
        proxies.poll()
        self.assertEqual(peer.recv(20), b'\x00\xffhello')
        peer.sendall(b'\x01\xfereply')
        result = []
        for _ in range(100):
            result = proxies.poll()
            if result:
                break
            time.sleep(.01)
        self.assertEqual(result, [(suffix, b'\x01\xfereply')])


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.patch = patch.object(settings, 'STATE', self.state)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.backend = Mock()
        self.backend.service_active.return_value = True
        self.data = dict(enabled=True, host='broker.example.com', port=8883, serial='BOARD001',
                         username='user', password='secret', tls_enabled=True, verify_hostname=True,
                         ca_certificate='', clear_ca=False, advanced={})

    @staticmethod
    def write(path, data):
        path.write_text(data)

    def test_save_redacts_secret_and_blank_keeps_it(self):
        with patch.object(settings, 'service') as service:
            result = settings.apply(self.data, self.backend, self.write)
            self.assertNotIn('password', result)
            self.assertTrue(result['password_saved'])
            service.assert_any_call('enable')
            service.assert_any_call('restart')
            settings.apply(dict(self.data, password=''), self.backend, self.write)
            self.assertEqual(settings.current()['password'], 'secret')

    def test_bad_inputs_do_not_save_or_restart(self):
        for change in ({'port': True}, {'port': 0}, {'serial': 'bad/#'}, {'host': 'https://host'},
                       {'advanced': {'tcp_proxy_targets': ['evil:80']}}, {'advanced': {'unknown': 1}},
                       {'advanced': {'handlers': {'EVENT/SHELL': 'reboot'}}}, {'ca_certificate': 'bad cert'},
                       {'tls_enabled': 'yes'}, {'password': 123}):
            with self.subTest(change=change), patch.object(settings, 'service') as service:
                with self.assertRaises((ValueError, TypeError)):
                    settings.apply(dict(self.data, **change), self.backend, self.write)
                service.assert_not_called()

    def test_restart_failure_restores_previous_configuration(self):
        old = dict(settings.DEFAULTS, host='previous')
        (self.state / 'mqtt.json').write_text(json.dumps(old))
        with patch.object(settings, 'service', side_effect=[None, OSError('failure'), None, None]):
            with self.assertRaises(OSError):
                settings.apply(self.data, self.backend, self.write)
        self.assertEqual(settings.current(), old)

    def test_disabled_can_save_empty_broker(self):
        with patch.object(settings, 'service'):
            result = settings.apply(dict(self.data, enabled=False, host='', serial='', username='', password=''), self.backend, self.write)
        self.assertEqual(result['state'], 'disabled')


class DataTests(unittest.TestCase):
    def test_measured_periods_survive_mqtt_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            snapshot = dict(available=True, stale_seconds=0, roles={'wan': dict(available=True, device='wwan0', total_tx_bytes=1024, total_rx_bytes=2048)})
            with patch.object(mqtt_data.traffic_stats, 'current', return_value=snapshot):
                adapter = mqtt_data.RouterData({'serial': 'BOARD001'}, state)
                self.assertEqual(adapter.flow('wwan0', 'WAN'), ('1.0', '2.0'))
                other = mqtt_data.RouterData({'serial': 'BOARD001'}, state)
                self.assertEqual(other.flow('wwan0', 'WAN'), ('0.0', '0.0'))
                snapshot['roles']['wan']['total_rx_bytes'] += 1024
                self.assertEqual(other.flow('wwan0', 'WAN'), ('0.0', '1.0'))

    def test_wlan_uses_hotspot_and_traffic_is_independent_per_topic(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = mqtt_data.RouterData({'serial': 'BOARD001'}, Path(directory))
            adapter.interface = Mock(return_value={})
            with patch.object(mqtt_data, 'query', return_value={}):
                adapter.snapshot()
            self.assertEqual([call.args[0] for call in adapter.interface.call_args_list], ['wan', 'lan', 'hotspot'])
            with patch.object(mqtt_data, 'read', return_value='1024'):
                self.assertEqual(adapter.flow('wwan0', 'SIM1'), ('1.0', '1.0'))
                self.assertEqual(adapter.flow('wwan0', 'WAN'), ('1.0', '1.0'))
            with patch.object(mqtt_data, 'read', return_value='2048'):
                self.assertEqual(adapter.flow('wwan0', 'SIM1'), ('1.0', '1.0'))
                self.assertEqual(adapter.flow('wwan0', 'WAN'), ('1.0', '1.0'))

    def test_alarm_survives_restart_until_matching_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            queue = state / 'outbox'
            queue.mkdir()
            (queue / '1.json').write_text(json.dumps(dict(topic='ALARM', data={'id': 7, 'time': '1', 'event': {'type': 'system', 'object': 'power-on', 'action': '', 'data': ''}})))
            adapter = mqtt_data.RouterData({'serial': 'BOARD001'}, state)
            first = adapter.events()
            self.assertEqual(first[0][1]['id'], 7)
            other = mqtt_data.RouterData({'serial': 'BOARD001'}, state)
            self.assertEqual(other.events(), first)
            other.ack('ALARM', 8)
            self.assertTrue(other.pending)
            other.ack('ALARM', 7)
            self.assertFalse(mqtt_data.RouterData({'serial': 'BOARD001'}, state).pending)

    def test_uninstalled_operations_fail_instead_of_claiming_success(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = mqtt_data.RouterData({'serial': 'BOARD001'}, Path(directory))
            for name in ('CONFIG', 'EVENT/SHELL', 'EVENT/GETFILE', 'INDUSTRY/SET', 'UPGRADE'):
                with self.assertRaises(ValueError):
                    adapter.operation(name, {})


if __name__ == '__main__':
    unittest.main()
