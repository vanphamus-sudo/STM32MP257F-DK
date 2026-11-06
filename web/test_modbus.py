import copy
import csv
from datetime import datetime, timezone, timedelta
import ftplib
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

import modbus_collection as mb
import modbus_settings as settings


def config():
    data = copy.deepcopy(settings.DEFAULTS)
    data.update(enabled=True, serial='BOARD001', upload_time='14:55')
    data['ftp'].update(host='127.0.0.1', username='meter', password='secret')
    data['devices'] = [dict(name='Eastron METER', id=1, data_mode='little', registers=[
        dict(description='Voltage', address='0x0000', format='FLOAT32', unit='V', function=4),
        dict(description='Current', address=6, format='UINT16', unit='A', function=3)])]
    return settings.validate(data)


class ValidationTests(unittest.TestCase):
    def test_addresses_formats_and_duplicate_ids(self):
        data = config()
        self.assertEqual(data['devices'][0]['registers'][0]['address'], 0)
        for mutate in [lambda d: d.update(retention_days=32),
                       lambda d: d.update(interval_minutes=0),
                       lambda d: d.update(upload_time='24:00'),
                       lambda d: d['ftp'].update(host='ftp://example.com'),
                       lambda d: d['ftp'].update(password='secret\r\nDELE file'),
                       lambda d: d['serial_port'].update(device='/dev/../console'),
                       lambda d: d['devices'].append(copy.deepcopy(d['devices'][0])),
                       lambda d: d['devices'][0].update(id=0),
                       lambda d: d['devices'][0]['registers'][0].update(address=65535),
                       lambda d: d['devices'][0]['registers'][0].update(function=6)]:
            bad = copy.deepcopy(data)
            mutate(bad)
            with self.assertRaises(ValueError):
                settings.validate(bad)

    def test_usb_missing_does_not_fall_back_to_flash(self):
        data = config()
        data['save_mode'] = 'usb'
        with patch.object(os.path, 'ismount', return_value=False), self.assertRaises(ValueError):
            settings.storage_root(data)

    def test_failed_service_start_rolls_back_and_password_is_hidden(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, 'STATE', Path(directory)):
            old = config()
            path = Path(directory) / 'modbus.json'
            path.write_text(json.dumps(old))
            new = copy.deepcopy(old)
            new['interval_minutes'] = 3
            new['ftp']['password'] = ''
            calls = []
            def service(action):
                calls.append(action)
                if calls == ['stop', 'enable', 'start']:
                    raise OSError('failed')
            with patch.object(settings, 'service', side_effect=service), self.assertRaises(OSError):
                settings.apply(new, Mock(), lambda p, text: p.write_text(text))
            self.assertEqual(json.loads(path.read_text()), old)
            self.assertEqual(calls, ['stop', 'enable', 'start', 'enable', 'start'])
            backend = Mock()
            backend.service_active.return_value = False
            with patch.object(settings, 'service'):
                result = settings.apply(new, backend, lambda p, text: p.write_text(text))
            self.assertEqual(result['ftp']['password'], '')
            self.assertTrue(result['password_saved'])
            self.assertEqual(json.loads(path.read_text())['ftp']['password'], 'secret')


class ProtocolTests(unittest.TestCase):
    def test_known_crc_and_all_decoders(self):
        self.assertEqual(mb.crc16(bytes.fromhex('01030000000a')).hex(), 'c5cd')
        for fmt, payload, value in [('FLOAT32', struct.pack('>f', 240.5), 240.5),
                                    ('UINT16', b'\xff\xff', 65535), ('INT16', b'\xff\xfe', -2),
                                    ('UINT32', b'\xff' * 4, 4294967295), ('INT32', b'\xff' * 4, -1),
                                    ('HEX16', b'\xab\xcd', '0xABCD'), ('HEX32', b'\xab\xcd\x12\x34', '0xABCD1234'),
                                    ('BIN16', b'\x00\x01', '0' * 15 + '1'), ('BIN32', b'\x00\x00\x00\x01', '0' * 31 + '1')]:
            self.assertEqual(mb.decode(payload, fmt, 'big'), value)
            swapped = payload[2:] + payload[:2] if len(payload) == 4 else payload
            self.assertEqual(mb.decode(swapped, fmt, 'little'), value)
        with self.assertRaises(ValueError):
            mb.decode(struct.pack('>f', float('nan')), 'FLOAT32', 'big')

    def read_response(self, response, register=None):
        serial = object.__new__(mb.RTU)
        serial.config = config()['serial_port']
        serial.stop = threading.Event()
        serial.fd = 42
        serial.tx_bytes = serial.rx_bytes = serial.errors = 0
        chunks = [response[:2], response[2:4], response[4:]]
        fake_termios = types.SimpleNamespace(tcflush=Mock(), TCIFLUSH=0)
        select = lambda readers, writers, _, timeout: (readers, writers, [])
        writes = []
        def write(fd, data):
            writes.append(data[:2])
            return len(data[:2])
        with patch.dict(sys.modules, termios=fake_termios), patch.object(mb.select, 'select', side_effect=select), \
                patch.object(mb.os, 'read', side_effect=chunks), patch.object(mb.os, 'write', side_effect=write):
            value = serial.read(config()['devices'][0], register or config()['devices'][0]['registers'][0])
        return value, b''.join(writes), serial

    def test_fragmented_reply_and_partial_writes(self):
        payload = b'\x01\x04\x04' + bytes.fromhex('80004370')  # 240.5, CDAB
        value, request, serial = self.read_response(payload + mb.crc16(payload))
        self.assertEqual(value, 240.5)
        self.assertEqual(request, bytes.fromhex('010400000002') + mb.crc16(bytes.fromhex('010400000002')))
        self.assertEqual(serial.tx_bytes, 8)
        self.assertEqual(serial.rx_bytes, 9)

    def test_bad_crc_wrong_slave_and_meter_exception(self):
        for payload, message in [(bytes.fromhex('01040400004370ffff'), 'CRC'),
                                 (bytes.fromhex('02040400004370'), 'device'),
                                 (bytes.fromhex('018402'), 'exception 2'),
                                 (bytes.fromhex('0104020000'), 'byte count')]:
            response = payload if message == 'CRC' else payload + mb.crc16(payload)
            with self.assertRaisesRegex(ValueError, message):
                self.read_response(response)


class StoreTests(unittest.TestCase):
    def test_multidevice_rotation_restart_export_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            data = config()
            device = data['devices'][0]
            stamp = datetime.now(timezone.utc)
            with mb.Store(directory) as store:
                store.append(data, device, [240.5, ''], ['', 'Modbus response timeout'], stamp)
                other = copy.deepcopy(device)
                other.update(id=57, name='Meter two')
                store.append(data, other, [230, 1], ['', ''], stamp)
                self.assertEqual(len(store.files()), 2)
                self.assertFalse(store.due(datetime(2026, 11, 5, 14, 54), '14:55'))
                self.assertTrue(store.due(datetime(2026, 11, 5, 14, 55), '14:55'))
                self.assertFalse(store.due(datetime(2026, 11, 5, 15, 0), '14:55'))
                self.assertEqual(len(store.pending()), 2)
                store.append(data, device, [241, 2], ['', ''], stamp + timedelta(seconds=60))
                self.assertEqual(len(store.files()), 3)
                report = Mock()
                mb.upload_pending(data, store, threading.Event(), report, upload=Mock(side_effect=OSError('secret')))
                self.assertEqual(len(store.pending()), 2)
                self.assertNotIn('secret', str(report.call_args))
                ident = store.pending()[0]['id']
                rows = list(csv.reader(io.StringIO(store.get(ident).read_text())))
                self.assertEqual(rows[1][1:], ['240.5', '', '', 'Modbus response timeout'])
            with mb.Store(directory) as store:
                store.recover()
                self.assertEqual(len(store.pending()), 3)
                upload = Mock()
                mb.upload_pending(data, store, threading.Event(), Mock(), upload=upload)
                self.assertEqual(upload.call_count, 3)
                self.assertTrue(all(f['status'] == 'uploaded' for f in store.files()))
                with self.assertRaises(ValueError):
                    store.get('../credentials.json')

    def test_retention_and_quota(self):
        with tempfile.TemporaryDirectory() as directory, mb.Store(directory) as store:
            data = config()
            stamp = datetime.now(timezone.utc)
            store.append(data, data['devices'][0], [1, 2], ['', ''], stamp)
            store.recover()
            path = store.get(store.files()[0]['id'])
            os.utime(path, (stamp.timestamp() - 2 * 86400,) * 2)
            self.assertEqual(store.prune(1, stamp.timestamp()), 1)
            self.assertEqual(store.files(), [])
            data['max_storage_mb'] = 1
            (Path(directory) / 'full.csv').write_bytes(b'0' * 1024 * 1024)
            with self.assertRaisesRegex(OSError, 'Storage limit'):
                store.append(data, data['devices'][0], [1, 2], ['', ''], stamp)


class FTPTests(unittest.TestCase):
    def test_ftps_validation_and_partial_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.csv'
            path.write_bytes(b'data\r\n')
            data = config()
            data['ftp']['tls'] = True
            ftp = Mock()
            ftp.size.side_effect = ftplib.error_perm('550 not found')
            mb.upload_file(data, path, lambda: ftp)
            ftp.prot_p.assert_called_once()
            ftp.storbinary.assert_called_once()
            ftp.rename.assert_called_once_with('sample.csv.part', 'sample.csv')
            ftp.close.assert_called_once()
            ftp.reset_mock()
            ftp.storbinary.side_effect = OSError('connection lost')
            with self.assertRaises(OSError):
                mb.upload_file(data, path, lambda: ftp)
            ftp.rename.assert_not_called()
            ftp.close.assert_called_once()
            ftp.reset_mock()
            ftp.size.side_effect = None
            ftp.size.return_value = path.stat().st_size
            mb.upload_file(data, path, lambda: ftp)
            ftp.storbinary.assert_not_called()  # Recovery after remote rename/local crash.

    def test_real_passive_ftp_transfer(self):
        received, commands, failures = {}, [], []
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(5)
        def serve():
            try:
                connection, _ = listener.accept()
                with connection, connection.makefile('rwb', buffering=0) as control:
                    control.write(b'220 Test FTP\r\n')
                    passive = None
                    for line in control:
                        command = line.decode().strip()
                        commands.append(command)
                        verb, _, arg = command.partition(' ')
                        if verb in ('USER', 'PASS', 'TYPE', 'CWD'):
                            control.write(b'230 OK\r\n' if verb in ('USER', 'PASS') else b'200 OK\r\n')
                        elif verb == 'SIZE':
                            control.write(b'550 Not found\r\n')
                        elif verb == 'PASV':
                            passive = socket.socket()
                            passive.bind(('127.0.0.1', 0))
                            passive.listen()
                            passive.settimeout(5)
                            port = passive.getsockname()[1]
                            control.write(f'227 Entering Passive Mode (127,0,0,1,{port//256},{port%256})\r\n'.encode())
                        elif verb == 'STOR':
                            control.write(b'150 Transfer\r\n')
                            data_socket, _ = passive.accept()
                            with data_socket:
                                contents = bytearray()
                                while chunk := data_socket.recv(4096):
                                    contents.extend(chunk)
                            passive.close()
                            received[arg] = bytes(contents)
                            control.write(b'226 Complete\r\n')
                        elif verb == 'RNFR':
                            old = arg
                            control.write(b'350 Rename\r\n')
                        elif verb == 'RNTO':
                            received[arg] = received.pop(old)
                            control.write(b'250 Renamed\r\n')
            except Exception as error:
                failures.append(error)
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'meter.csv'
                content = b'timestamp,voltage\r\n2026-11-05,240.5\r\n'
                path.write_bytes(content)
                data = config()
                data['ftp']['port'] = listener.getsockname()[1]
                mb.upload_file(data, path)
                worker.join(5)
                self.assertEqual(received, {'meter.csv': content})
                self.assertIn('STOR meter.csv.part', commands)
                self.assertEqual(failures, [])
        finally:
            listener.close()
            worker.join(5)


if __name__ == '__main__':
    unittest.main()
