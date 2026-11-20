import json
import socket
import subprocess
import threading
import time
import unittest
from unittest.mock import Mock, patch

import at_audit
import at_tcp


class AtAuditTests(unittest.TestCase):
    def test_conservative_command_masking(self):
        for command, expected in [
            ('AT+CPIN=5557', 'AT+CPIN=[redacted]'),
            ('AT+CGAUTH=1,1,"user","secret"', 'AT+CGAUTH=[redacted]'),
            ('AT+CPWD="SC","old","new"', 'AT+CPWD=[redacted]'),
            ('ATD0412345678;', 'ATD [redacted]'),
            ('AT+QCFG="password","secret"', 'AT+QCFG=[redacted]'),
            ('AT+CPIN?', 'AT+CPIN?'), ('ATI', 'ATI'), ('AT$VERSION','AT$VERSION'),
            ('AT&F','AT&F'), ('AT&W','AT&W'),
            ('AT+CGAUTH=?','AT+CGAUTH=?')]:
            with self.subTest(command=command):
                self.assertEqual(at_audit.command_label(command), expected)

    def test_events_are_single_line_json_in_authpriv(self):
        sink=Mock(LOG_PID=1,LOG_AUTHPRIV=80,LOG_NOTICE=5)
        with patch.object(at_audit,'syslog',sink):
            at_audit.record('connection_closed',client_ip='192.168.10.104',reason='test\nnewline')
        sink.openlog.assert_called_once_with('router-at-audit',1,80)
        level,text=sink.syslog.call_args.args
        self.assertEqual(level,5);self.assertNotIn('\n',text)
        record=json.loads(text)
        self.assertIn('timestamp',record);self.assertEqual(record['client_ip'],'192.168.10.104')

    def test_privacy_guard_fails_closed(self):
        with patch.object(at_audit.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            self.assertTrue(at_audit.prepare_modem())
            self.assertEqual(run.call_args.args[0],['mmcli','--set-logging=INFO'])
        for value in (OSError('not available'),subprocess.TimeoutExpired('mmcli',5)):
            with patch.object(at_audit.subprocess,'run',side_effect=value):
                self.assertFalse(at_audit.prepare_modem())

    def test_tcp_events_secret_masking_results_rejection_and_timeout(self):
        events=[]
        def audit(event,**fields):events.append(dict(event=event,**fields))
        with patch.object(at_audit,'record',side_effect=audit), \
             patch.object(at_audit,'prepare_modem',return_value=True), \
             patch.object(at_tcp.modem,'send_at',return_value={'ok':True,'response':'private-response'}), \
             at_tcp.Server(('127.0.0.1',0),idle_seconds=.3) as server:
            thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                with socket.create_connection(server.server_address,timeout=2) as client:
                    client.settimeout(2)
                    client.sendall(b'AT+CPIN=5557\r')
                    self.assertIn(b'private-response',client.recv(2048))
                    with socket.create_connection(server.server_address,timeout=2) as second:
                        try:second.recv(1)
                        except ConnectionResetError:pass
                    client.sendall(b'AT+INVALID\x00\r'+b'AT'+b'x'*260+b'\r')
                    data=b''
                    while True:
                        part=client.recv(2048)
                        if not part:break
                        data+=part
                    self.assertIn(b'INVALID AT COMMAND',data);self.assertIn(b'COMMAND TOO LONG',data)
            finally:
                server.shutdown();thread.join(2)
        text=json.dumps(events)
        self.assertNotIn('5557',text);self.assertNotIn('private-response',text)
        self.assertTrue(any(e['event']=='command_received' and e['command']=='AT+CPIN=[redacted]' for e in events))
        self.assertTrue(any(e['event']=='command_completed' and e['result']=='ok' and e['delivered'] for e in events))
        self.assertTrue(any(e['event']=='connection_rejected' for e in events))
        self.assertTrue(any(e['event']=='connection_closed' and e['reason']=='idle_timeout' for e in events))
        self.assertTrue(all('client_ip' in e and 'connection' in e for e in events))

    def test_guard_failure_never_forwards_command(self):
        events=[]
        with patch.object(at_audit,'record',side_effect=lambda event,**fields:events.append(dict(event=event,**fields))), \
             patch.object(at_audit,'prepare_modem',return_value=False), \
             patch.object(at_tcp.modem,'send_at') as send, \
             at_tcp.Server(('127.0.0.1',0)) as server:
            thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                with socket.create_connection(server.server_address,timeout=2) as client:
                    client.sendall(b'AT+CPIN=5557\r');self.assertIn(b'PRIVACY GUARD',client.recv(2048))
            finally:server.shutdown();thread.join(2)
        send.assert_not_called()
        self.assertTrue(any(e.get('result')=='privacy_guard_failed' for e in events))
