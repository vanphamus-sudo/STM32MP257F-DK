#!/usr/bin/env python3
"""One-client binary TCP/serial bridge for Linux/OpenWrt."""
import argparse
import json
import os
import re
from pathlib import Path
import select
import signal
import socket
import stat
import time

LIMIT = 65536
BAUDS = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400)


def validate(data):
    if not isinstance(data, dict) or set(data) != {'enabled', 'device', 'baud', 'listen', 'port', 'idle_seconds'}:
        raise ValueError('Supply enabled, device, baud, listen, port and idle_seconds.')
    if type(data['enabled']) is not bool:
        raise ValueError('enabled must be boolean.')
    device = data['device']
    if not isinstance(device, str) or not (device.startswith('/dev/') or re.fullmatch(r'usb:[0-9a-f]{4}:[0-9a-f]{4}', device)) or '..' in device or '\n' in device:
        raise ValueError('Choose a /dev/ serial device or usb:vendor:product selector.')
    if type(data['baud']) is not int or data['baud'] not in BAUDS:
        raise ValueError('Unsupported baud rate.')
    socket.inet_pton(socket.AF_INET, data['listen'])
    if type(data['port']) is not int or not 1024 <= data['port'] <= 65535:
        raise ValueError('TCP port must be 1024–65535.')
    if type(data['idle_seconds']) is not int or not 1 <= data['idle_seconds'] <= 86400:
        raise ValueError('Idle timeout must be 1–86400 seconds.')
    return data


def open_serial(device, baud):
    import fcntl
    import termios
    import tty
    if device.startswith('usb:'):
        _, vendor, product = device.split(':')
        matches = []
        for tty_path in Path('/sys/class/tty').glob('ttyUSB*'):
            for parent in (tty_path / 'device').resolve().parents:
                try:
                    if (parent / 'idVendor').read_text().strip() == vendor and (parent / 'idProduct').read_text().strip() == product:
                        matches.append(Path('/dev') / tty_path.name)
                        break
                except OSError:
                    continue
        if len(matches) != 1:
            raise ValueError('USB serial selector must identify exactly one connected converter.')
        resolved = matches[0].resolve(strict=True)
    else:
        resolved = Path(device).resolve(strict=True)
    if not stat.S_ISCHR(resolved.stat().st_mode):
        raise ValueError('Serial device must be a character device.')
    # Do not steal the Linux console or a port owned by ModemManager/getty.
    if any(line.split()[0] == resolved.name for line in Path('/proc/consoles').read_text().splitlines()):
        raise ValueError('The serial device is a kernel console.')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            for entry in (process / 'fd').iterdir():
                if entry.resolve() == resolved:
                    raise ValueError('Serial device is already in use by another process.')
        except (OSError, PermissionError):
            continue
    fd = os.open(str(resolved), os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    original = None
    try:
        original = termios.tcgetattr(fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        attrs[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CSIZE | getattr(termios, 'CRTSCTS', 0))
        attrs[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
        attrs[4] = attrs[5] = getattr(termios, 'B' + str(baud))
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        return fd, original
    except BaseException:
        if original is not None:
            termios.tcsetattr(fd, termios.TCSANOW, original)
        os.close(fd)
        raise


def bridge(listener, serial_fd, idle_seconds, stop=lambda: False):
    """Bounded buffers provide backpressure; rejected clients receive no serial data."""
    listener.setblocking(False)
    client = None
    closing = False
    to_serial, to_tcp = bytearray(), bytearray()
    last_activity = time.monotonic()
    def disconnect():
        nonlocal client, closing
        if client is not None:
            client.close()
            client = None
        closing = False
        to_serial.clear()
        to_tcp.clear()
    try:
        while not stop():
            if closing and not to_serial and not to_tcp:
                disconnect()
            if client is not None and time.monotonic() - last_activity >= idle_seconds:
                disconnect()
            readers = [listener]
            if client is None or len(to_tcp) < LIMIT:
                readers.append(serial_fd)
            if client is not None and not closing and len(to_serial) < LIMIT:
                readers.append(client)
            writers = ([serial_fd] if to_serial else []) + ([client] if client is not None and to_tcp else [])
            deadline = min(.25, max(0, idle_seconds - (time.monotonic() - last_activity))) if client else .25
            ready, writable, _ = select.select(readers, writers, [], deadline)
            if listener in ready:
                incoming, _ = listener.accept()
                if client is not None:
                    incoming.close()
                else:
                    # Drain stale input before assigning the serial stream to a new client.
                    import termios
                    termios.tcflush(serial_fd, termios.TCIOFLUSH)
                    incoming.setblocking(False)
                    incoming.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    client = incoming
                    last_activity = time.monotonic()
            try:
                if serial_fd in ready:
                    data = os.read(serial_fd, min(4096, LIMIT - len(to_tcp)))
                    if not data:
                        raise OSError('Serial device disconnected.')
                    if client is not None:
                        to_tcp.extend(data)
                        last_activity = time.monotonic()
                if client is not None and client in ready:
                    data = client.recv(min(4096, LIMIT - len(to_serial)))
                    if not data:
                        closing = True
                    else:
                        to_serial.extend(data)
                        last_activity = time.monotonic()
                if serial_fd in writable and to_serial:
                    count = os.write(serial_fd, to_serial)
                    del to_serial[:count]
                if client is not None and client in writable and to_tcp:
                    count = client.send(to_tcp)
                    del to_tcp[:count]
            except BlockingIOError:
                continue
            except (ConnectionError, BrokenPipeError):
                disconnect()
    finally:
        disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/router-web/serial-tcp.json')
    parser.add_argument('--check-enabled', action='store_true')
    args = parser.parse_args()
    path = Path(args.config)
    if not path.exists():
        return
    config = validate(json.loads(path.read_text()))
    if args.check_enabled:
        raise SystemExit(0 if config['enabled'] else 1)
    if not config['enabled']:
        return
    import termios
    import fcntl
    stopped = False
    def shutdown(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    fd, original = open_serial(config['device'], config['baud'])
    try:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((config['listen'], config['port']))
            listener.listen(8)
            print('TCP serial bridge listening; one client, idle timeout ' + str(config['idle_seconds']) + 's', flush=True)
            bridge(listener, fd, config['idle_seconds'], lambda: stopped)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)
        fcntl.ioctl(fd, termios.TIOCNXCL)
        os.close(fd)


if __name__ == '__main__':
    main()
