"""Bounded raw TCP and hex serial proxies, restricted by local configuration."""
import os
import re
import socket
import time


class Proxies:
    def __init__(self, config):
        self.config, self.sessions = config, {}

    def receive(self, suffix, raw):
        if len(raw) > 65536:
            raise ValueError('Proxy payload too large')
        parts = suffix.split('/')
        serial = len(parts) == 2 and re.fullmatch(r'serial[1-9][0-9]*', parts[1])
        if not serial and len(parts) != 4:
            raise ValueError('Invalid proxy topic')
        if serial:
            from mqtt_protocol import unhex
            raw = unhex(raw.decode('ascii'))
            settings = self.config.get('serial_proxies', {}).get(parts[1])
            if not settings:
                raise ValueError('Serial proxy is not configured')
        else:
            host, destination, source = parts[1:]
            if not destination.isdigit() or not source.isdigit() or not all(1 <= int(p) <= 65535 for p in (destination, source)):
                raise ValueError('Invalid proxy ports')
            if host + ':' + destination not in self.config.get('tcp_proxy_targets', []):
                raise ValueError('Proxy target is not allowed')
        if suffix not in self.sessions:
            if len(self.sessions) >= 8:
                raise ValueError('Proxy session limit reached')
            if serial:
                from serial_tcp import open_serial
                fd, original = open_serial(settings['device'], settings['baud'])
                session = dict(fd=fd, original=original, serial=True)
            else:
                sock = socket.create_connection((host, int(destination)), timeout=3)
                sock.setblocking(False)
                session = dict(fd=sock, serial=False)
            session.update(buffer=bytearray(), active=time.monotonic())
            self.sessions[suffix] = session
        session = self.sessions[suffix]
        if len(session['buffer']) + len(raw) > 131072:
            self.close(suffix)
            raise ValueError('Proxy output buffer full')
        session['buffer'].extend(raw)
        session['active'] = time.monotonic()

    def close(self, suffix):
        session = self.sessions.pop(suffix)
        if session['serial']:
            import termios
            try:
                termios.tcsetattr(session['fd'], termios.TCSANOW, session['original'])
            finally:
                os.close(session['fd'])
        else:
            session['fd'].close()

    def poll(self):
        outgoing = []
        for suffix, session in list(self.sessions.items()):
            try:
                if time.monotonic() - session['active'] > 60:
                    self.close(suffix)
                    continue
                fd = session['fd']
                if session['buffer']:
                    try:
                        count = os.write(fd, session['buffer']) if session['serial'] else fd.send(session['buffer'])
                        del session['buffer'][:count]
                    except BlockingIOError:
                        pass
                try:
                    data = os.read(fd, 32768) if session['serial'] else fd.recv(32768)
                except BlockingIOError:
                    continue
                if data:
                    session['active'] = time.monotonic()
                    outgoing.append((suffix, data.hex().encode() if session['serial'] else data))
                elif not session['serial']:
                    self.close(suffix)
            except OSError:
                self.close(suffix)
        return outgoing

    def close_all(self):
        for suffix in list(self.sessions):
            self.close(suffix)
