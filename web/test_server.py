import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import server

VALID = dict(start='192.168.10.50', end='192.168.10.200', lease_hours=12, dns=['1.1.1.1', '8.8.8.8'])


class SettingsTests(unittest.TestCase):
    def test_four_character_password_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            salt = '1234567890abcdef' * 2
            digest = hashlib.pbkdf2_hmac('sha256', b'admin', bytes.fromhex(salt), 250000).hex()
            credentials = state / 'credentials.json'
            credentials.write_text(json.dumps(dict(username='admin', salt=salt, hash=digest)))
            with patch.object(server, 'STATE', state):
                with self.assertRaises(ValueError):
                    server.change_account(dict(username='admin', current_password='admin', new_password='abc', confirm_password='abc'))
                server.change_account(dict(username='admin', current_password='admin', new_password='abcd', confirm_password='abcd'))
                self.assertTrue(server.password_matches('abcd', json.loads(credentials.read_text())))

    def test_rejects_invalid_network_settings(self):
        for changes in [dict(start='192.168.7.50'), dict(start='192.168.10.1'),
                        dict(end='192.168.10.255'), dict(start='192.168.10.201'),
                        dict(lease_hours=True), dict(lease_hours=0),
                        dict(dns=['192.168.10.1']), dict(dns=['127.0.0.1']),
                        dict(dns=['1.1.1.1\ninterface=usb0']), dict(dns=[]),
                        dict(dns=[16843009]), dict(start=3232238130)]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                server.validate_settings(VALID | changes)

    def test_rollback_on_failed_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            config = state / 'dnsmasq.conf'
            original = server.render_config(VALID)
            config.write_text(original)
            with patch.object(server, 'STATE', state), patch.object(server, 'CONFIG', config), \
                    patch.object(server, 'run', side_effect=['OK', RuntimeError('restart failed'), 'OK']) as run:
                with self.assertRaises(RuntimeError):
                    server.apply_settings(VALID | dict(lease_hours=24))
                self.assertEqual(config.read_text(), original)
                self.assertEqual(run.call_count, 3)

    def test_successful_save_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            config = state / 'dnsmasq.conf'
            original = server.render_config(VALID)
            config.write_text(original)
            with patch.object(server, 'STATE', state), patch.object(server, 'CONFIG', config), patch.object(server, 'run'):
                server.apply_settings(VALID | dict(lease_hours=24))
                self.assertEqual(server.settings()['lease_hours'], 24)
                self.assertEqual((state / 'dnsmasq.previous').read_text(), original)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        # Each HTTP case gets independent credentials and the legacy host shape.
        self.port_patch = patch.object(server, 'PORT', 80)
        self.port_patch.start()
        self.addCleanup(self.port_patch.stop)
        server.SESSIONS.clear()
        server.ATTEMPTS.clear()
        salt = '1234567890abcdef' * 2
        digest = hashlib.pbkdf2_hmac('sha256', b'test-password', bytes.fromhex(salt), 250000).hex()
        (self.state / 'credentials.json').write_text(json.dumps(dict(salt=salt, hash=digest)))

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.temp.name)
        salt = '1234567890abcdef' * 2
        digest = hashlib.pbkdf2_hmac('sha256', b'test-password', bytes.fromhex(salt), 250000).hex()
        (cls.state / 'credentials.json').write_text(json.dumps(dict(salt=salt, hash=digest)))
        cls.state_patch = patch.object(server, 'STATE', cls.state)
        cls.state_patch.start()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        cls.state_patch.stop()
        cls.temp.cleanup()

    def request(self, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        request_headers = {'Host': server.HOST}
        if data is not None:
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        conn.request('GET' if data is None else 'POST', path,
                     None if data is None else json.dumps(data), request_headers)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def setUp(self):
        server.SESSIONS.clear()
        server.ATTEMPTS.clear()
        salt = '1234567890abcdef' * 2
        digest = hashlib.pbkdf2_hmac('sha256', b'test-password', bytes.fromhex(salt), 250000).hex()
        (self.state / 'credentials.json').write_text(json.dumps(dict(salt=salt, hash=digest)))

    def test_modbus_authentication_csrf_secrets_and_export(self):
        import copy
        from datetime import datetime, timezone
        import modbus_settings
        from modbus_collection import Store
        data = copy.deepcopy(modbus_settings.DEFAULTS)
        data['ftp']['password'] = 'private-ftp-password'
        device = dict(name='Meter', id=1, data_mode='big', registers=[
            dict(description='Voltage', address=0, format='FLOAT32', unit='V', function=4)])
        with patch.object(server, 'OPENWRT', True), patch.object(server, 'platform', create=True) as backend, \
                patch.object(modbus_settings, 'STATE', self.state):
            backend.service_active.return_value = False
            (self.state / 'modbus.json').write_text(json.dumps(data))
            with Store(self.state / 'modbus-data') as store:
                store.append(data, device, [240.5], [''], datetime.now(timezone.utc))
                ident = store.files()[0]['id']
            self.assertEqual(self.request('/api/modbus')[0], 401)
            self.assertEqual(self.request('/api/modbus/files/' + ident)[0], 401)
            self.assertEqual(self.request('/api/modbus', data)[0], 401)
            _, headers, body = self.request('/api/login', dict(username='admin', password='test-password'))
            auth = {'Cookie': headers['Set-Cookie'].split(';')[0], 'X-CSRF-Token': json.loads(body)['csrf']}
            code, _, body = self.request('/api/modbus', headers=auth)
            self.assertEqual(code, 200)
            self.assertNotIn(b'private-ftp-password', body)
            self.assertTrue(json.loads(body)['password_saved'])
            self.assertEqual(self.request('/api/modbus', data, {'Cookie': auth['Cookie']})[0], 403)
            with patch.object(modbus_settings, 'service'):
                self.assertEqual(self.request('/api/modbus', data, auth)[0], 200)
            code, headers, body = self.request('/api/modbus/files/' + ident, headers=auth)
            self.assertEqual(code, 200)
            self.assertTrue(headers['Content-Disposition'].startswith('attachment;'))
            self.assertIn(b'240.5', body)
            self.assertEqual(self.request('/api/modbus/files/../../credentials.json', headers=auth)[0], 404)

    def test_account_change_and_session_revocation(self):
        def login(username, password):
            return self.request('/api/login', dict(username=username, password=password))
        _, headers, body = login('admin', 'test-password')
        auth = {'Cookie': headers['Set-Cookie'].split(';')[0], 'X-CSRF-Token': json.loads(body)['csrf']}
        _, other_headers, _ = login('admin', 'test-password')
        other_cookie = other_headers['Set-Cookie'].split(';')[0]
        data = dict(username='owner', current_password='test-password',
                    new_password='new-test-password', confirm_password='new-test-password')
        self.assertEqual(self.request('/api/account', data)[0], 401)
        self.assertEqual(self.request('/api/account', data, {'Cookie': auth['Cookie']})[0], 403)
        original = (self.state / 'credentials.json').read_text()
        self.assertEqual(self.request('/api/account', data | dict(current_password='wrong'), auth)[0], 400)
        self.assertEqual(self.request('/api/account', data | dict(confirm_password='mismatch'), auth)[0], 400)
        self.assertEqual(self.request('/api/account', data | dict(username='invalid user'), auth)[0], 400)
        self.assertEqual((self.state / 'credentials.json').read_text(), original)
        (self.state / 'initial-password').write_text('test-password')
        self.assertEqual(self.request('/api/account', data, auth)[0], 200)
        self.assertFalse((self.state / 'initial-password').exists())
        self.assertNotIn('new-test-password', (self.state / 'credentials.json').read_text())
        self.assertEqual(self.request('/api/session', headers={'Cookie': auth['Cookie']})[0], 401)
        self.assertEqual(self.request('/api/session', headers={'Cookie': other_cookie})[0], 401)
        self.assertEqual(login('admin', 'test-password')[0], 401)
        _, headers, body = login('owner', 'new-test-password')
        self.assertEqual(json.loads(body)['username'], 'owner')
        auth = {'Cookie': headers['Set-Cookie'].split(';')[0], 'X-CSRF-Token': json.loads(body)['csrf']}
        digest = json.loads((self.state / 'credentials.json').read_text())['hash']
        self.assertEqual(self.request('/api/account', dict(username='renamed', current_password='new-test-password',
                                                         new_password='', confirm_password=''), auth)[0], 200)
        self.assertEqual(json.loads((self.state / 'credentials.json').read_text())['hash'], digest)
        self.assertEqual(login('renamed', 'new-test-password')[0], 200)

    def test_authentication_and_request_boundaries(self):
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/api/status')[0], 401)
        self.assertEqual(self.request('/', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('/api/login', dict(username='admin', password='test-password'),
                                      {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/login', dict(username='admin', password='wrong'))[0], 401)
        code, headers, body = self.request('/api/login', dict(username='admin', password='test-password'))
        self.assertEqual(code, 200)
        cookie = headers['Set-Cookie'].split(';')[0]
        csrf = json.loads(body)['csrf']
        self.assertEqual(self.request('/api/settings', VALID, {'Cookie': cookie})[0], 403)
        auth = {'Cookie': cookie, 'X-CSRF-Token': csrf}
        self.assertEqual(self.request('/api/settings', VALID | dict(dns=['127.0.0.1']), auth)[0], 400)
        with patch.object(server, 'apply_settings', return_value=VALID) as apply:
            self.assertEqual(self.request('/api/settings', VALID, auth)[0], 200)
            apply.assert_called_once_with(VALID)
        self.assertEqual(self.request('/api/logout', {}, auth)[0], 200)
        self.assertEqual(self.request('/api/session', headers={'Cookie': cookie})[0], 401)

    def test_forwarding_requires_authentication_and_csrf(self):
        self.assertEqual(self.request('/api/port-forwards')[0], 401)
        self.assertEqual(self.request('/api/port-forwards', {'revision':'x','rules':[]})[0], 401)
        code, headers, body = self.request('/api/login', dict(username='admin', password='test-password'))
        self.assertEqual(code, 200)
        cookie = headers['Set-Cookie'].split(';')[0]
        csrf = json.loads(body)['csrf']
        self.assertEqual(self.request('/api/port-forwards', {'revision':'x','rules':[]}, {'Cookie':cookie})[0], 403)
        with patch.object(server, 'OPENWRT', True), patch.object(server, 'platform', create=True), \
                patch.object(server.port_forwarding, 'apply', return_value={'rules':[]}) as apply:
            self.assertEqual(self.request('/api/port-forwards', {'revision':'x','rules':[]}, {'Cookie':cookie,'X-CSRF-Token':csrf})[0], 200)
            apply.assert_called_once()

    def test_openwrt_host_and_origin_port_boundaries(self):
        with patch.object(server, 'PORT', 8081):
            host = {'Host': server.HOST + ':8081'}
            self.assertEqual(self.request('/', headers=host)[0], 200)
            self.assertEqual(self.request('/')[0], 403)
            login = dict(username='admin', password='test-password')
            self.assertEqual(self.request('/api/login', login, host | {'Origin': 'http://' + server.HOST})[0], 403)
            self.assertEqual(self.request('/api/login', login, host | {'Origin': 'http://' + server.HOST + ':8081'})[0], 200)

    def test_remote_update_endpoints_require_authentication_and_csrf(self):
        for path in ('/api/firmware/settings', '/api/firmware/update'):
            self.assertEqual(self.request(path, {})[0], 401)
        code, headers, body = self.request('/api/login', dict(username='admin', password='test-password'))
        cookie = headers['Set-Cookie'].split(';')[0]
        for path in ('/api/firmware/settings', '/api/firmware/update'):
            self.assertEqual(self.request(path, {}, {'Cookie': cookie})[0], 403)
        with patch.object(server, 'OPENWRT', True), patch.object(server.firmware_update, 'submit', return_value={'message': 'queued'}) as submit:
            self.assertEqual(self.request('/api/firmware/update', {}, {'Cookie': cookie, 'X-CSRF-Token': json.loads(body)['csrf']})[0], 200)
            submit.assert_called_once()

    def test_serial_assignment_requires_authentication_and_csrf(self):
        route = '/api/serial-assignment'
        data = dict(mode='tcp', device='usb:067b:2303', tcp_baud=9600, tcp_port=5000)
        self.assertEqual(self.request(route, data)[0], 401)
        code, headers, body = self.request('/api/login', dict(username='admin', password='test-password'))
        self.assertEqual(code, 200)
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request(route, data, {'Cookie':cookie})[0], 403)
        with patch.object(server, 'OPENWRT', True), patch.object(server, 'platform', create=True), \
                patch.object(server.serial_assignment, 'apply', return_value={'mode':'tcp'}) as apply:
            self.assertEqual(self.request(route, data, {'Cookie':cookie, 'X-CSRF-Token':json.loads(body)['csrf']})[0], 200)
            apply.assert_called_once()

    def test_mqtt_requires_authentication_and_csrf(self):
        self.assertEqual(self.request('/api/mqtt', dict(enabled=True))[0], 401)
        code, headers, body = self.request('/api/login', dict(username='admin', password='test-password'))
        self.assertEqual(code, 200)
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('/api/mqtt', {}, {'Cookie': cookie})[0], 403)
        with patch.object(server, 'OPENWRT', True), patch.object(server, 'platform', create=True), \
                patch.object(server.mqtt_settings, 'apply', return_value={'enabled': False}) as apply:
            self.assertEqual(self.request('/api/mqtt', {}, {'Cookie': cookie, 'X-CSRF-Token': json.loads(body)['csrf']})[0], 200)
            apply.assert_called_once()

    def test_dhcp_bindings_require_authentication_and_csrf(self):
        self.assertEqual(self.request('/api/dhcp-reservations')[0],401)
        self.assertEqual(self.request('/api/dhcp-reservations',dict(revision='x',bindings=[]))[0],401)
        code,headers,body=self.request('/api/login',dict(username='admin',password='test-password'))
        self.assertEqual(code,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        data=dict(revision='x',bindings=[])
        self.assertEqual(self.request('/api/dhcp-reservations',data,{'Cookie':cookie})[0],403)
        with patch.object(server,'OPENWRT',True),patch.object(server,'platform',create=True), \
                patch.object(server.dhcp_reservations,'apply',return_value={'bindings':[]}) as apply:
            self.assertEqual(self.request('/api/dhcp-reservations',data,{'Cookie':cookie,'X-CSRF-Token':json.loads(body)['csrf']})[0],200)
            apply.assert_called_once()


if __name__ == '__main__':
    unittest.main()
