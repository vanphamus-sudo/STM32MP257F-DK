import os
import select
import socket
import threading
import time
import unittest
import serial_tcp as s
import version_info

CONFIG = dict(enabled=True, device='/dev/ttyUSB4', baud=115200, listen='0.0.0.0', port=5000, idle_seconds=60)


class ConfigTests(unittest.TestCase):
    def test_invalid_config(self):
        for changes in ({'enabled': 'yes'}, {'device': '/etc/passwd'}, {'baud': True},
                        {'baud': 1234}, {'port': 80}, {'idle_seconds': 0}, {'listen': 'hostname'}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, OSError)):
                s.validate(CONFIG | changes)


@unittest.skipUnless(os.name == 'posix', 'Pseudo-terminal integration requires Linux')
class BridgeTests(unittest.TestCase):
    def test_reserved_commands_are_ordinary_serial_data(self):
        payload = b'AT$VERSION\r\nAT$UNKNOWN\r\n'
        self.client.sendall(payload)
        self.assertEqual(self.read_serial(len(payload)), payload)
        self.assertFalse(select.select([self.client], [], [], .1)[0])

    def setUp(self):
        import tty
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        os.set_blocking(self.slave, False)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(8)
        self.address = self.listener.getsockname()
        self.stop = threading.Event()
        self.errors = []
        def run():
            try:
                s.bridge(self.listener, self.slave, .7, self.stop.is_set)
            except Exception as error:
                self.errors.append(error)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        self.client = socket.create_connection(self.address, timeout=2)

    def tearDown(self):
        self.stop.set()
        self.client.close()
        self.thread.join(2)
        self.listener.close()
        os.close(self.master)
        os.close(self.slave)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.errors, [])

    def read_serial(self, size):
        result = bytearray()
        while len(result) < size:
            self.assertTrue(select.select([self.master], [], [], 2)[0], 'Serial receive timed out')
            result.extend(os.read(self.master, size - len(result)))
        return bytes(result)

    def test_binary_both_directions_and_single_client(self):
        payload = bytes(range(256)) * 16
        self.client.sendall(payload)
        self.assertEqual(self.read_serial(len(payload)), payload)
        with socket.create_connection(self.address, timeout=2) as second:
            try:
                self.assertEqual(second.recv(1), b'')
            except ConnectionResetError:
                pass
        os.write(self.master, payload)
        result = bytearray()
        while len(result) < len(payload):
            result.extend(self.client.recv(len(payload) - len(result)))
        self.assertEqual(result, payload)

    def test_idle_disconnect_and_reconnect(self):
        self.client.sendall(b'A')
        self.assertEqual(self.read_serial(1), b'A')
        self.assertEqual(self.client.recv(1), b'')
        self.client.close()
        self.client = socket.create_connection(self.address, timeout=2)
        self.client.sendall(b'B')
        self.assertEqual(self.read_serial(1), b'B')

    def test_activity_renews_timeout(self):
        for _ in range(4):
            self.client.sendall(b'C')
            self.assertEqual(self.read_serial(1), b'C')
            time.sleep(.3)
        os.write(self.master, b'D')
        self.assertEqual(self.client.recv(1), b'D')

    def test_disconnect_does_not_drop_queued_serial_bytes(self):
        payload = bytes(range(256)) * 32
        self.client.sendall(payload)
        self.client.shutdown(socket.SHUT_WR)
        self.assertEqual(self.read_serial(len(payload)), payload)


if __name__ == '__main__':
    unittest.main()
