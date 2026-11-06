import socket
import threading
import time
import unittest
from unittest.mock import patch
import at_tcp
import openwrt_backend
import version_info


class AtTcpTests(unittest.TestCase):
    def test_reserved_commands_never_reach_modem(self):
        with patch.object(at_tcp.modem, 'send_at') as send:
            self.assertEqual(at_tcp.response('AT$VERSION'), version_info.at_response())
            self.assertIn(b'UNKNOWN SOFTWARE COMMAND', at_tcp.response('at$other'))
            send.assert_not_called()
        with patch.object(openwrt_backend.subprocess, 'run') as run:
            self.assertFalse(openwrt_backend.send_at({'command': 'AT$UNKNOWN'})['ok'])
            run.assert_not_called()

    def test_modem_response_has_terminal_ok(self):
        with patch.object(at_tcp.modem, 'send_at', return_value={'ok': True, 'response': "response: '+CSQ: 26,99'"}):
            self.assertEqual(at_tcp.response('AT+CSQ'), b'\r\n+CSQ: 26,99\r\nOK\r\n')

    def test_split_lines_single_client_and_idle_timeout(self):
        with at_tcp.Server(('127.0.0.1', 0), idle_seconds=.7) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with socket.create_connection(server.server_address, timeout=2) as client:
                    client.settimeout(2)
                    client.sendall(b'AT$VER')
                    time.sleep(.05)
                    client.sendall(b'SION\r\nAT$UNKNOWN\n')
                    expected = version_info.at_response() + b'\r\nERROR: UNKNOWN SOFTWARE COMMAND\r\n'
                    data = bytearray()
                    while len(data) < len(expected):
                        chunk = client.recv(4096)
                        self.assertTrue(chunk)
                        data.extend(chunk)
                    self.assertEqual(data, expected)
                    with socket.create_connection(server.server_address, timeout=2) as second:
                        try:
                            self.assertEqual(second.recv(1), b'')
                        except ConnectionResetError:
                            pass
                    self.assertEqual(client.recv(1), b'')
            finally:
                server.shutdown()
                thread.join(2)


if __name__ == '__main__':
    unittest.main()
