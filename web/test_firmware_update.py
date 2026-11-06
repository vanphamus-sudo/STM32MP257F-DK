import contextlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import firmware_update as update


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        for name, value in [('STATE', self.state / 'state'), ('ROOT', self.state / 'root'), ('TMP', self.state)]:
            mocked = patch.object(update, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        update.ROOT.mkdir()
        self.lock = patch.object(update, 'locked', side_effect=lambda: contextlib.nullcontext(Mock(fileno=lambda: 42)))
        self.lock.start()
        self.addCleanup(self.lock.stop)

    def test_url_rejects_plain_http_untrusted_hosts_credentials_and_ports(self):
        for url in ('http://updates.test/a', 'https://evil.test/a', 'https://user:pass@updates.test/a',
                    'https://updates.test:444/a', 'file:///etc/passwd', 'https://updates.test/a#fragment',
                    'https://updates.test/a\nheader'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                update.check_url(url, ['updates.test'])
        self.assertEqual(update.check_url('https://updates.test/a?token=123', ['updates.test']), 'https://updates.test/a?token=123')

    def test_redirect_cannot_escape_allowlist_or_downgrade_https(self):
        handler = update.Redirects(['updates.test'])
        for url in ('http://updates.test/a', 'https://evil.test/a'):
            with self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, '', {}, url)

    def test_settings_require_public_key_and_host_and_reject_private_key(self):
        with self.assertRaises(ValueError):
            update.settings(dict(enabled=True, public_key='', allowed_hosts=[]))
        with patch.object(update.subprocess, 'run', return_value=Mock(returncode=1)):
            with self.assertRaises(ValueError):
                update.settings(dict(enabled=True, public_key='private key', allowed_hosts=['updates.test']))
        result = update.settings(dict(enabled=False, public_key='', allowed_hosts=[]))
        self.assertFalse(result['enabled'])

    def test_disabled_submit_does_not_start_worker(self):
        with patch.object(update.subprocess, 'Popen') as process:
            with self.assertRaises(ValueError):
                update.submit({'firmware': 'https://updates.test/a'})
            process.assert_not_called()

    def test_signature_failure_never_stops_services_or_installs(self):
        job = dict(id='test', url='https://updates.test/a', config=dict(public_key='key', allowed_hosts=['updates.test']))
        with patch.object(update, 'download'), patch.object(update.bundle, 'verify', side_effect=ValueError('bad signature')), \
                patch.object(update, 'services') as services, patch.object(update, 'command') as command:
            result = update.perform(job)
        self.assertEqual(result['result'], 'fail')
        self.assertEqual(result['error'], 'bad signature')
        services.assert_not_called()
        command.assert_not_called()

    def test_partial_install_failure_attempts_rollback(self):
        job = dict(id='test', url='https://updates.test/a', config=dict(public_key='key', allowed_hosts=['updates.test']))
        control = 'Version: 1.0.0-r16\n'
        called = []
        def command(*args, **kwargs):
            called.append(args)
            if args[:2] == ('opkg', 'install'):
                raise subprocess.CalledProcessError(1, args)
            return ''
        with patch.object(update, 'download'), patch.object(update.bundle, 'verify', return_value=b'payload'), \
                patch.object(update.bundle, 'reconstruct', return_value=(control, {})), \
                patch.object(update, 'backup', return_value='Version: 1.0.0-r15\n'), \
                patch.object(update.subprocess, 'run', return_value=Mock(returncode=0)), \
                patch.object(update, 'active_services', return_value=['router-web']), \
                patch.object(update, 'services'), patch.object(update, 'healthy', return_value=True), \
                patch.object(update, 'command', side_effect=command):
            result = update.perform(job)
        self.assertEqual(result['result'], 'fail')
        self.assertTrue(result['rolled_back'])
        self.assertTrue(any(args[:3] == ('opkg', '--force-downgrade', 'install') for args in called))

    def test_old_release_is_rejected_before_service_stop(self):
        job = dict(id='test', url='https://updates.test/a', config=dict(public_key='key', allowed_hosts=['updates.test']))
        with patch.object(update, 'download'), patch.object(update.bundle, 'verify', return_value=b'payload'), \
                patch.object(update.bundle, 'reconstruct', return_value=('Version: 1.0.0-r14\n', {})), \
                patch.object(update, 'backup', return_value='Version: 1.0.0-r15\n'), \
                patch.object(update.subprocess, 'run', return_value=Mock(returncode=1)), \
                patch.object(update, 'services') as services:
            result = update.perform(job)
        self.assertEqual(result['result'], 'fail')
        services.assert_not_called()
        self.assertIn('newer', result['error'])


if __name__ == '__main__':
    unittest.main()
