import json
import unittest
import subprocess
from unittest.mock import patch
import openwrt_backend as backend
import server


class DdnsTests(unittest.TestCase):
    def test_restart_does_not_capture_background_worker_output(self):
        with patch.object(backend.subprocess, 'run') as run:
            backend.restart_ddns()
        run.assert_called_once_with(['/etc/init.d/ddns', 'restart'], check=True, timeout=30,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)

    def test_legacy_pid_status_checks_worker_identity(self):
        config = {'router_ddns': {'enabled': '1'}}
        with patch.object(backend.Path, 'exists', return_value=True), \
                patch.object(backend, 'values', return_value=config), \
                patch.object(backend, 'ubus', return_value={}), \
                patch.object(backend.Path, 'read_text', return_value='123'), \
                patch.object(backend.Path, 'read_bytes', return_value=b'/bin/sh\0/usr/lib/ddns/dynamic_dns_updater.sh\0-S\0router_ddns\0'):
            self.assertEqual(backend.ddns_status()['state'], 'running')
        with patch.object(backend.Path, 'exists', return_value=True), \
                patch.object(backend, 'values', return_value=config), \
                patch.object(backend, 'ubus', return_value={}), \
                patch.object(backend.Path, 'read_text', return_value='123'), \
                patch.object(backend.Path, 'read_bytes', return_value=b'/usr/bin/unrelated\0router_ddns\0'):
            self.assertEqual(backend.ddns_status()['state'], 'stopped')

    def setUp(self):
        self.data = dict(enabled=True, provider='dyndns.org', hostname='router.example.com',
                         username='user', password='')
        self.current = dict(service_name='dyndns.org', password='saved-secret')

    def apply(self, data):
        with patch.object(backend, 'ddns_status', return_value={'available': True}), \
                patch.object(backend, 'values', return_value={'router_ddns': self.current}), \
                patch.object(backend, 'transaction') as transaction:
            backend.apply_ddns(data, server.atomic_write)
            return transaction.call_args.args[1]

    def test_preserves_secret_and_uses_https_public_ip(self):
        edits = self.apply(self.data)
        self.assertIn(('set', 'ddns.router_ddns.password', 'saved-secret'), edits)
        self.assertIn(('set', 'ddns.router_ddns.ip_source', 'web'), edits)
        self.assertIn(('set', 'ddns.router_ddns.use_https', '1'), edits)
        self.assertTrue(all(key.startswith('ddns.router_ddns') for _, key, _ in edits))

    def test_rejects_invalid_inputs(self):
        for changes in ({'hostname': 'bad;hostname'}, {'hostname': '-bad.example.com'},
                        {'enabled': 'true'}, {'provider': 'custom'}, {'username': 'user\n'},
                        {'provider': 'no-ip.com'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.apply(self.data | changes)

    def test_requires_credentials_but_allows_disabling(self):
        self.current = {}
        with self.assertRaises(ValueError):
            self.apply(self.data)
        self.apply(self.data | dict(enabled=False, hostname='', username=''))

    def test_status_never_returns_secret(self):
        with patch.object(backend.Path, 'exists', return_value=True), \
                patch.object(backend, 'values', return_value={'router_ddns': self.current}), \
                patch.object(backend, 'ubus', return_value={}):
            result = backend.ddns_status()
        self.assertTrue(result['password_saved'])
        self.assertNotIn('saved-secret', json.dumps(result))
        self.assertNotIn('password', result)
