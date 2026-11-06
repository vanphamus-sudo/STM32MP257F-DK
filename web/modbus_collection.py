#!/usr/bin/env python3
"""Read-only Modbus RTU collection with a durable CSV/FTP outbox."""
import argparse
import csv
from datetime import datetime, timezone
import ftplib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import select
import signal
import sqlite3
import ssl
import struct
import threading
import time
import uuid

import modbus_settings as settings

LOG = logging.getLogger('router-modbus')


def crc16(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return struct.pack('<H', crc)


def decode(payload, fmt, mode):
    # Registers always carry MSB first. Little-endian devices swap the WORDS
    # of 32-bit values (CDAB); 16-bit values remain a single Modbus register.
    if len(payload) == 4 and mode == 'little':
        payload = payload[2:4] + payload[0:2]
    if fmt.startswith('BIN'):
        return format(int.from_bytes(payload, 'big'), '0' + str(len(payload) * 8) + 'b')
    if fmt.startswith('HEX'):
        return '0x' + payload.hex().upper()
    value = struct.unpack('>' + {'FLOAT32': 'f', 'UINT16': 'H', 'INT16': 'h', 'UINT32': 'I', 'INT32': 'i'}[fmt], payload)[0]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Non-finite meter value')
    return value


class RTU:
    def __init__(self, config, stop):
        import termios
        from serial_tcp import open_serial
        self.config, self.stop = config, stop
        self.fd, self.original = open_serial(config['device'], config['baud'])
        self.tx_bytes = self.rx_bytes = self.errors = 0
        try:
            attrs = termios.tcgetattr(self.fd)
            attrs[2] &= ~(termios.PARENB | termios.PARODD | termios.CSTOPB)
            if config['parity'] != 'none':
                attrs[2] |= termios.PARENB
                if config['parity'] == 'odd':
                    attrs[2] |= termios.PARODD
            if config['stop_bits'] == 2:
                attrs[2] |= termios.CSTOPB
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        except BaseException:
            self.close()
            raise

    def close(self):
        import fcntl
        import termios
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.original)
            fcntl.ioctl(self.fd, termios.TIOCNXCL)
        finally:
            os.close(self.fd)

    def read(self, device, register):
        import termios
        count = 2 if register['format'].endswith('32') else 1
        request = struct.pack('>BBHH', device['id'], register['function'], register['address'], count)
        request += crc16(request)
        # Include the RTU inter-frame silence before flushing a late response.
        if self.stop.wait(max(0.00175, 3.5 * 11 / self.config['baud'])):
            raise InterruptedError('Collection stopped')
        termios.tcflush(self.fd, termios.TCIFLUSH)
        deadline = time.monotonic() + self.config['timeout_seconds']
        sent = 0
        while sent < len(request):
            if self.stop.is_set():
                raise InterruptedError('Collection stopped')
            if time.monotonic() >= deadline:
                raise TimeoutError('Serial write timeout')
            if select.select([], [self.fd], [], 0.05)[1]:
                try:
                    size = os.write(self.fd, request[sent:])
                except BlockingIOError:
                    continue
                sent += size
                self.tx_bytes += size
        response = bytearray()
        while time.monotonic() < deadline and not self.stop.is_set():
            if not select.select([self.fd], [], [], 0.05)[0]:
                continue
            try:
                chunk = os.read(self.fd, 256)
            except BlockingIOError:
                continue
            if not chunk:
                raise OSError('Serial device disconnected')
            response.extend(chunk)
            self.rx_bytes += len(chunk)
            if len(response) >= 3:
                length = 5 if response[1] & 0x80 else 5 + response[2]
                if len(response) >= length:
                    break
        LOG.debug('TX %s RX %s', request.hex(), response.hex())
        if len(response) < 5:
            raise TimeoutError('Modbus response timeout')
        if crc16(response[:-2]) != response[-2:]:
            raise ValueError('Modbus CRC mismatch')
        if response[0] != device['id'] or response[1] not in (register['function'], register['function'] | 0x80):
            raise ValueError('Unexpected Modbus device or function')
        if response[1] & 0x80:
            raise ValueError('Modbus exception ' + str(response[2]))
        if response[2] != count * 2 or len(response) != 5 + count * 2:
            raise ValueError('Unexpected Modbus byte count')
        return decode(bytes(response[3:-2]), register['format'], device['data_mode'])


def csv_bytes(row):
    out = io.StringIO(newline='')
    csv.writer(out).writerow(row)
    return out.getvalue().encode('utf-8')


def csv_label(value):
    # Meter labels are free text. Keep spreadsheets from interpreting formulas.
    return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'index.sqlite3', check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, name TEXT UNIQUE, device INTEGER, created REAL, status TEXT)')
            self.db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def files(self):
        with self.lock:
            rows = self.db.execute('SELECT * FROM files ORDER BY created DESC LIMIT 1000').fetchall()
            return [dict(row, bytes=(self.root / row['name']).stat().st_size) for row in rows if (self.root / row['name']).is_file()]

    def get(self, ident):
        if not re.fullmatch(r'[0-9a-f]{32}', ident):
            raise ValueError('Invalid file ID.')
        with self.lock:
            row = self.db.execute('SELECT * FROM files WHERE id=?', (ident,)).fetchone()
            if not row:
                raise ValueError('File not found.')
            path = self.root / row['name']
            if path.is_symlink() or path.parent.resolve() != self.root.resolve():
                raise ValueError('Invalid data file.')
            return path

    def recover(self):
        # Restart/config changes seal the old schema before accepting new rows.
        with self.lock, self.db:
            self.db.execute("UPDATE files SET status='pending' WHERE status='collecting'")

    def due(self, now, upload_time):
        with self.lock, self.db:
            row = self.db.execute("SELECT value FROM meta WHERE key='last_rotation'").fetchone()
            today = now.strftime('%Y-%m-%d')
            if now.strftime('%H:%M') >= upload_time and (not row or row[0] != today):
                self.db.execute("UPDATE files SET status='pending' WHERE status='collecting'")
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('last_rotation', ?)", (today,))
                return True
        return False

    def append(self, config, device, values, errors, stamp):
        row = [stamp.isoformat()]
        for value, error in zip(values, errors):
            row.extend([value, error])
        payload = csv_bytes(row)
        with self.lock:
            usage = sum(path.stat().st_size for path in self.root.glob('*.csv'))
            if usage + len(payload) + 65536 > config['max_storage_mb'] * 1024 * 1024:
                raise OSError('Storage limit reached; export data or increase the storage limit')
            active = self.db.execute("SELECT * FROM files WHERE device=? AND status='collecting'", (device['id'],)).fetchone()
            if active is None:
                ident = uuid.uuid4().hex
                name = re.sub(r'[^A-Za-z0-9_-]', '_', device['name'])
                name = f"{config['serial']}_{name}_{device['id']}_{stamp.strftime('%Y%m%dT%H%M%S')}_{ident}.csv"
                header = ['timestamp_utc']
                for register in device['registers']:
                    label = f"{register['description']} [{register['unit']}] ({register['function']}:{register['address']})"
                    header.extend([csv_label(label), csv_label(label + ' error')])
                with (self.root / name).open('xb') as handle:
                    handle.write(csv_bytes(header))
                    handle.flush()
                    os.fsync(handle.fileno())
                with self.db:
                    self.db.execute('INSERT INTO files VALUES (?, ?, ?, ?, ?)', (ident, name, device['id'], stamp.timestamp(), 'collecting'))
            else:
                name = active['name']
            with (self.root / name).open('ab') as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

    def pending(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM files WHERE status='pending' ORDER BY created")]

    def uploaded(self, ident):
        with self.lock, self.db:
            self.db.execute("UPDATE files SET status='uploaded' WHERE id=?", (ident,))

    def prune(self, days, now):
        with self.lock, self.db:
            expired = [row for row in self.db.execute("SELECT * FROM files WHERE status!='collecting'")
                       if not (self.root / row['name']).exists()
                       or (self.root / row['name']).stat().st_mtime < now - days * 86400]
            for row in expired:
                (self.root / row['name']).unlink(missing_ok=True)
                self.db.execute('DELETE FROM files WHERE id=?', (row['id'],))
            return len(expired)


def upload_file(config, path, factory=None, stop=None):
    ftp = config['ftp']
    client = (factory or (lambda: ftplib.FTP_TLS(context=ssl.create_default_context()) if ftp['tls'] else ftplib.FTP()))()
    def checkpoint(*_):
        if stop is not None and stop.is_set():
            raise InterruptedError('Upload stopped')
    try:
        checkpoint()
        client.connect(ftp['host'], ftp['port'], timeout=15)
        checkpoint()
        client.login(ftp['username'], ftp['password'])
        checkpoint()
        if ftp['tls']:
            client.prot_p()
        client.set_pasv(True)
        client.cwd(ftp['directory'])
        client.voidcmd('TYPE I')
        try:
            if client.size(path.name) == path.stat().st_size:
                # UUID names make retries safe after a crash following rename.
                return
        except ftplib.error_perm:
            pass
        checkpoint()
        # A failed transfer never leaves a completed-looking CSV at the server.
        with path.open('rb') as handle:
            client.storbinary('STOR ' + path.name + '.part', handle, callback=checkpoint)
        checkpoint()
        client.rename(path.name + '.part', path.name)
    finally:
        client.close()


def upload_pending(config, store, stop, report, upload=upload_file):
    for row in store.pending():
        if stop.is_set():
            return
        try:
            # Hold the data file open while uploading so retention cannot remove it.
            # Pruning runs in this same worker, not in the collector thread.
            upload(config, store.get(row['id']))
            store.uploaded(row['id'])
            report(upload_error='', last_upload=datetime.now(timezone.utc).isoformat())
            LOG.info('Uploaded %s', row['name'])
        except Exception as error:
            # FTP replies can contain server-provided secrets. Do not publish them.
            report(upload_error='FTP upload failed (' + type(error).__name__ + '); retry in one minute.')
            LOG.warning('FTP upload failed (%s); retry in one minute', type(error).__name__)
            return


def run(config, stop):
    root = settings.storage_root(config)
    with Store(root) as store:
        store.recover()
        runtime = dict(state='starting', tx_bytes=0, rx_bytes=0, read_errors=0,
                       collection_error='', upload_error='')
        runtime_lock = threading.Lock()
        def report(**items):
            with runtime_lock:
                runtime.update(items)
                runtime['updated_at'] = time.time()
                temp = settings.RUNTIME.with_suffix('.new')
                temp.write_text(json.dumps(runtime))
                temp.replace(settings.RUNTIME)

        def check_storage():
            if settings.storage_root(config).resolve() != root.resolve():
                raise OSError('Storage changed')

        def uploader():
            next_retry = 0
            while not stop.is_set():
                try:
                    check_storage()
                    store.due(datetime.now().astimezone(), config['upload_time'])
                    if time.monotonic() >= next_retry:
                        upload_pending(config, store, stop, report,
                                       upload=lambda cfg, path: upload_file(cfg, path, stop=stop))
                        if not stop.is_set():
                            store.prune(config['retention_days'], time.time())
                        next_retry = time.monotonic() + 60
                except Exception as error:
                    report(upload_error='Storage/upload unavailable (' + type(error).__name__ + ').')
                    next_retry = time.monotonic() + 60
                stop.wait(1)

        worker = threading.Thread(target=uploader, name='modbus-ftp', daemon=True)
        worker.start()
        serial = None
        next_scan = 0
        try:
            while not stop.is_set():
                if time.monotonic() < next_scan:
                    report()
                    stop.wait(min(5, max(0, next_scan - time.monotonic())))
                    continue
                try:
                    check_storage()
                    if serial is None:
                        serial = RTU(config['serial_port'], stop)
                    for device in config['devices']:
                        if stop.is_set():
                            break
                        values, errors = [], []
                        stamp = datetime.now(timezone.utc)
                        for register in device['registers']:
                            if stop.is_set():
                                raise InterruptedError('Collection stopped')
                            try:
                                values.append(serial.read(device, register))
                                errors.append('')
                            except (TimeoutError, ValueError) as error:
                                serial.errors += 1
                                values.append('')
                                errors.append(str(error))
                            report(tx_bytes=serial.tx_bytes, rx_bytes=serial.rx_bytes, read_errors=serial.errors)
                        store.append(config, device, values, errors, stamp)
                    report(state='collecting', collection_error='', last_collection=datetime.now(timezone.utc).isoformat())
                    next_scan = time.monotonic() + config['interval_minutes'] * 60
                except InterruptedError:
                    break
                except Exception as error:
                    report(state='error', collection_error='Collection unavailable (' + type(error).__name__ + '). Check serial port and storage.')
                    LOG.warning('Collection unavailable (%s)', type(error).__name__)
                    if serial is not None:
                        try:
                            serial.close()
                        except OSError:
                            pass
                        serial = None
                    next_scan = time.monotonic() + 60
        finally:
            stop.set()
            worker.join(timeout=35)
            if serial is not None:
                serial.close()
            report(state='stopped')
            # Do not close a DB while a stalled remote transfer still uses it.
            if worker.is_alive():
                worker.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-enabled', action='store_true')
    args = parser.parse_args()
    config = settings.validate(settings.current())
    if args.check_enabled:
        raise SystemExit(0 if config['enabled'] else 1)
    if not config['enabled']:
        return
    os.umask(0o077)
    logging.basicConfig(level=logging.DEBUG if config['debug'] else logging.INFO)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    # procd stop/start can overlap briefly. Never allow two collectors/outbox
    # workers to operate while the previous process is shutting down.
    import fcntl
    with Path('/tmp/router-modbus.lock').open('a') as singleton:
        fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(config, stop)


if __name__ == '__main__':
    main()
