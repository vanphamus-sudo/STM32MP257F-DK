import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import openvpn_client as vpn
import server


class OpenvpnTests(unittest.TestCase):
    def test_toggle_uses_saved_settings_and_only_changes_enabled(self):
        saved=vpn.DEFAULTS | {'remote':'vpn.example.com','port':1197}
        with patch.object(vpn,'current',return_value=saved), patch.object(vpn,'apply') as apply:
            vpn.toggle({'enabled':True},'backend','writer')
            apply.assert_called_once_with(saved | {'enabled':True},'backend','writer')
        for data in ({'enabled':'true'},{'enabled':True,'remote':'other.example.com'},{}):
            with self.assertRaises(ValueError):
                vpn.toggle(data,'backend','writer')

    def test_connected_state_rejects_a_stale_event_from_an_old_process(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'connected'
            with patch.object(vpn, 'CONNECTED', marker):
                self.assertEqual(vpn.connected_address(123), '')
                marker.write_text('123 10.87.0.2\n')
                self.assertEqual(vpn.connected_address(123), '10.87.0.2')
                self.assertEqual(vpn.connected_address(456), '')
                marker.unlink()
                self.assertEqual(vpn.connected_address(123), '')

    def test_rejects_injection_and_invalid_routes(self):
        for changes in ({'remote': 'host\nup /tmp/run'}, {'remote': 'host;cmd'}, {'remote': '1.2.3.999'},
                        {'port': True}, {'port': 0}, {'enabled': 'true'}, {'protocol': 'udp\nscript'},
                        {'keepalive': '10 120\nup x'}, {'keepalive': '120 10'},
                        {'server_fingerprint': 'bad'}, {'vpn_subnet': '0.0.0.0/0'},
                        {'vpn_subnet': '192.168.10.0/24'}, {'vpn_subnet': '10.87.0.1/24'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                vpn.validate(vpn.DEFAULTS | changes)

    def test_verification_and_lte_default_route_are_preserved(self):
        result = vpn.render(vpn.validate(vpn.DEFAULTS))
        self.assertIn('remote 3.24.63.90 1197\n', result)
        self.assertIn('proto udp4\n', result)
        self.assertIn('cipher AES-256-GCM\n', result)
        self.assertFalse(vpn.DEFAULTS['enabled'])
        self.assertIn('remote-cert-tls server\n', result)
        self.assertIn('allow-compression no\n', result)
        self.assertIn('route-nopull\n', result)
        self.assertIn('route 10.87.0.0 255.255.255.0 vpn_gateway\n', result)
        self.assertNotIn('redirect-gateway', result)
        pinned = vpn.render(vpn.validate(vpn.DEFAULTS | {'server_fingerprint': 'ab' * 32}))
        self.assertIn('peer-fingerprint AB:AB:', pinned)
        self.assertNotIn('remote-cert-tls', pinned)

    def test_certificate_input_rejects_encrypted_keys_and_scripts(self):
        for kind, text in [('key', '-----BEGIN ENCRYPTED PRIVATE KEY-----\nAA==\n-----END ENCRYPTED PRIVATE KEY-----'),
                           ('tls', 'up /tmp/script'), ('../key', 'secret'), ('ca', 'not a certificate')]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                vpn.validate_file(kind, text)

    def test_pair_mismatch_prevents_enable(self):
        with patch.object(vpn.Path, 'exists', return_value=True), patch.object(vpn, 'openssl', side_effect=['public1', 'public2']):
            with self.assertRaisesRegex(ValueError, 'do not match'):
                vpn.check_material(vpn.DEFAULTS)

    def test_status_omits_keys_and_certificate_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state/'client.key').write_text('a secret private key')
            with patch.object(vpn, 'STATE', state), patch.object(vpn.Path, 'exists', return_value=True), \
                    patch.object(vpn, 'current', return_value=vpn.DEFAULTS), \
                    patch.object(vpn, 'openssl', return_value='subject=CN=test'):
                backend = Mock()
                backend.ubus.return_value = {}
                output = json.dumps(vpn.status(backend))
            self.assertNotIn('a secret private key', output)
            self.assertNotIn('BEGIN', output)

    def test_failed_firewall_validation_restores_all_committed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, state = root/'config', root/'state'
            config.mkdir(); state.mkdir()
            (config/'openvpn').write_text('old VPN')
            (config/'firewall').write_text('old firewall')
            (state/'settings.json').write_text(json.dumps(vpn.DEFAULTS))
            (state/'client.conf').write_text('old client')
            def run(*args):
                if args == ('fw4', 'check'):
                    raise subprocess.CalledProcessError(1, args)
                return ''
            backend = Mock()
            backend.run.side_effect = run
            backend.values.return_value = {}
            with patch.object(vpn, 'CONFIG', config), patch.object(vpn, 'STATE', state), \
                    patch.object(vpn.Path, 'exists', return_value=True), patch.object(vpn, 'reload_client'):
                with self.assertRaises(subprocess.CalledProcessError):
                    vpn.apply(vpn.DEFAULTS, backend, server.atomic_write)
            self.assertEqual((config/'openvpn').read_text(), 'old VPN')
            self.assertEqual((config/'firewall').read_text(), 'old firewall')
            self.assertEqual((state/'client.conf').read_text(), 'old client')
            self.assertEqual(json.loads((state/'settings.json').read_text()), vpn.DEFAULTS)


if __name__ == '__main__':
    unittest.main()
