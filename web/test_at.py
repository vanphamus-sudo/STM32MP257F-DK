import subprocess
import unittest
from unittest.mock import patch
import openwrt_backend as b


class AtTests(unittest.TestCase):
    def test_rejects_multiline_and_invalid_commands(self):
        for command in ('', 'reboot', 'AT\rAT+CFUN=0', 'AT\n', 'AT\x00', 'ATé', 'AT' + 'x' * 255, None):
            with self.subTest(command=command), self.assertRaises(ValueError):
                b.send_at({'command': command})

    def test_shell_characters_are_passed_as_one_argument(self):
        command = 'AT+TEST="$(touch /tmp/x);"'
        with patch.object(b, 'values', return_value={'wan': {'device': '/sys/modem'}}), \
                patch.object(b.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'response: OK')) as run:
            self.assertTrue(b.send_at({'command': command})['ok'])
        self.assertEqual(run.call_args.args[0], ['mmcli', '-m', '/sys/modem', '--command=' + command, '--timeout=10'])
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_timeout_releases_lock_and_busy_is_rejected(self):
        b.AT_LOCK.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, 'in progress'):
                b.send_at({'command': 'AT'})
        finally:
            b.AT_LOCK.release()
        with patch.object(b, 'values', return_value={'wan': {'device': '/sys/modem'}}), \
                patch.object(b.subprocess, 'run', side_effect=subprocess.TimeoutExpired('mmcli', 15)):
            with self.assertRaisesRegex(RuntimeError, 'may have been executed'):
                b.send_at({'command': 'AT'})
        self.assertFalse(b.AT_LOCK.locked())

    def test_errors_and_output_limit(self):
        with patch.object(b, 'values', return_value={'wan': {'device': '/sys/modem'}}), \
                patch.object(b.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'ERROR' * 2000)):
            result = b.send_at({'command': 'AT'})
        self.assertFalse(result['ok'])
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['response']), 8192)
