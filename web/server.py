#!/usr/bin/env python3
"""Small, authenticated LAN settings service for the STM32 router."""
import hashlib
import hmac
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import threading
import time
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import wifi

ROOT = Path(__file__).resolve().parent
CONFIG = Path('/usr/local/lib/router/dnsmasq.conf')
STATE = Path('/var/lib/router-web')
LOCK = threading.RLock()
SESSIONS = {}
ATTEMPTS = {}
HOST = '192.168.10.1'


def password_matches(password, credentials):
    if not isinstance(password, str) or len(password) > 256:
        return False
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(credentials['salt']), 250000).hex()
    return hmac.compare_digest(digest, credentials['hash'])


def change_account(data):
    username = data.get('username')
    password = data.get('new_password', '')
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', username):
        raise ValueError('Username must be 1–32 letters, numbers, dots, underscores or hyphens.')
    if not isinstance(password, str) or (password and not 4 <= len(password) <= 256):
        raise ValueError('Use a password of 4–256 characters, or leave it blank to keep your password.')
    if password != data.get('confirm_password', ''):
        raise ValueError('New passwords do not match.')
    credentials = json.loads((STATE / 'credentials.json').read_text())
    if not password_matches(data.get('current_password'), credentials):
        raise ValueError('Current password is incorrect.')
    credentials['username'] = username
    if password:
        credentials['salt'] = secrets.token_hex(16)
        credentials['hash'] = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(credentials['salt']), 250000).hex()
    # Remove the obsolete plaintext installation password before committing changes.
    (STATE / 'initial-password').unlink(missing_ok=True)
    atomic_write(STATE / 'credentials.json', json.dumps(credentials))
    SESSIONS.clear()
    return username


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=15).strip()


def atomic_write(path, text):
    temporary = path.with_name(path.name + '.new')
    with temporary.open('w', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def validate_settings(data):
    if not isinstance(data, dict) or set(data) != {'start', 'end', 'lease_hours', 'dns'}:
        raise ValueError('Supply the DHCP range, lease time and DNS servers.')
    if not isinstance(data['start'], str) or not isinstance(data['end'], str):
        raise ValueError('DHCP addresses must be strings.')
    start, end = ipaddress.IPv4Address(data['start']), ipaddress.IPv4Address(data['end'])
    subnet = ipaddress.IPv4Network('192.168.10.0/24')
    if any(ip not in subnet or int(ip) & 255 not in range(2, 255) for ip in (start, end)):
        raise ValueError('DHCP addresses must be between 192.168.10.2 and 192.168.10.254.')
    if start > end:
        raise ValueError('The first DHCP address must come before the last address.')
    hours = data['lease_hours']
    if type(hours) is not int or not 1 <= hours <= 168:
        raise ValueError('Lease time must be a whole number from 1 to 168 hours.')
    if not isinstance(data['dns'], list) or not 1 <= len(data['dns']) <= 3:
        raise ValueError('Enter between one and three DNS servers.')
    dns = []
    for item in data['dns']:
        if not isinstance(item, str):
            raise ValueError('DNS addresses must be strings.')
        address = ipaddress.IPv4Address(item)
        if (address.is_loopback or address.is_multicast or address.is_unspecified
                or address.is_link_local or address.is_reserved or address in subnet
                or address in ipaddress.IPv4Network('192.168.7.0/24')
                or address in ipaddress.IPv4Network('192.168.20.0/24')):
            raise ValueError('Use reachable upstream IPv4 DNS servers outside the LAN and USB subnets.')
        dns.append(str(address))
    return dict(start=str(start), end=str(end), lease_hours=hours, dns=dns)


def settings():
    lines = CONFIG.read_text().splitlines()
    pool = next(line.split('=', 1)[1].split(',') for line in lines if line.startswith('dhcp-range='))
    return dict(start=pool[0], end=pool[1], lease_hours=int(pool[3].removesuffix('h')),
                dns=[line.split('=', 1)[1] for line in lines if line.startswith('server=')])


def render_config(data):
    return ('# Managed by the router settings page\ninterface=end0\n'
            'listen-address=192.168.10.1\nbind-dynamic\ndomain-needed\nbogus-priv\n'
            f"dhcp-range={data['start']},{data['end']},255.255.255.0,{data['lease_hours']}h\n"
            'dhcp-option=option:router,192.168.10.1\n'
            'dhcp-option=option:dns-server,192.168.10.1\nno-resolv\n'
            + ''.join(f'server={address}\n' for address in data['dns'])
            + ('conf-file=/usr/local/lib/router/wifi-dhcp.conf\n' if (wifi.BASE / 'wifi-dhcp.conf').exists() else ''))


def apply_settings(data):
    data = validate_settings(data)
    with LOCK:
        old = CONFIG.read_text()
        candidate = STATE / 'dnsmasq.candidate'
        atomic_write(candidate, render_config(data))
        run('/usr/bin/dnsmasq', '--test', '--conf-file=' + str(candidate))
        atomic_write(STATE / 'dnsmasq.previous', old)
        try:
            atomic_write(CONFIG, candidate.read_text())
            run('systemctl', 'restart', 'dnsmasq.service')
            run('systemctl', 'is-active', '--quiet', 'dnsmasq.service')
        except Exception:
            atomic_write(CONFIG, old)
            run('systemctl', 'restart', 'dnsmasq.service')
            raise
    return data


def status():
    services = {}
    for name in ('dnsmasq', 'router-firewall', 'ModemManager'):
        try:
            services[name] = run('systemctl', 'is-active', name)
        except subprocess.CalledProcessError as error:
            services[name] = error.output.strip() or 'inactive'
    interfaces = json.loads(run('ip', '-j', '-4', 'address', 'show'))
    addresses = {item['ifname']: [a['local'] for a in item['addr_info']] for item in interfaces}
    leases = []
    path = Path('/var/lib/misc/dnsmasq.leases')
    if path.exists():
        for line in path.read_text().splitlines():
            fields = line.split()
            if len(fields) >= 4 and (fields[0] == '0' or int(fields[0]) > time.time()):
                leases.append(dict(address=fields[2], name=fields[3], mac=fields[1]))
    modem = dict(state='unavailable', operator='', signal=None)
    try:
        data = json.loads(run('mmcli', '-m', '0', '-J'))['modem']
        modem = dict(state=data['generic']['state'], operator=data.get('3gpp', {}).get('operator-name', ''),
                     signal=data['generic'].get('signal-quality', {}).get('value'))
    except (subprocess.SubprocessError, KeyError, ValueError):
        pass
    return dict(hostname=run('hostname'), addresses=addresses, services=services, modem=modem,
                uptime=int(float(Path('/proc/uptime').read_text().split()[0])), leases=leases,
                settings=settings(), wifi=wifi.status())


class Handler(BaseHTTPRequestHandler):
    server_version = 'Router'

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def reply(self, code, data, content_type='application/json', cookie=None):
        body = json.dumps(data).encode() if content_type == 'application/json' else data
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            token = cookie['router_session'].value
        except (KeyError, ValueError, CookieError):
            return None
        with LOCK:
            session = SESSIONS.get(token)
            if session and session['expires'] > time.monotonic():
                return session
            SESSIONS.pop(token, None)
        return None

    def allowed_host(self):
        return self.headers.get('Host') in (HOST, HOST + ':80')

    def do_GET(self):
        if not self.allowed_host():
            return self.reply(403, dict(error='Open this page at http://192.168.10.1.'))
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path in assets:
            filename, mime = assets[self.path]
            return self.reply(200, (ROOT / filename).read_bytes(), mime)
        session = self.session()
        if not session:
            return self.reply(401, dict(error='Sign in to view board settings.'))
        if self.path == '/api/session':
            credentials = json.loads((STATE / 'credentials.json').read_text())
            return self.reply(200, dict(csrf=session['csrf'], username=credentials.get('username', 'admin')))
        if self.path == '/api/status':
            try:
                with LOCK:
                    data = status()
                return self.reply(200, data)
            except Exception:
                self.log_error('Status collection failed')
                return self.reply(503, dict(error='Board status is temporarily unavailable.'))
        return self.reply(404, dict(error='Not found.'))

    def do_POST(self):
        if (not self.allowed_host() or self.headers.get('Origin') not in
                (None, 'http://' + HOST, 'http://' + HOST + ':80')):
            return self.reply(403, dict(error='Request origin is not allowed.'))
        if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
            return self.reply(415, dict(error='Expected JSON.'))
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, TimeoutError):
            return self.reply(400, dict(error='Invalid request.'))
        if self.path == '/api/login':
            return self.login(data)
        session = self.session()
        if not session:
            return self.reply(401, dict(error='Sign in again to continue.'))
        if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
            return self.reply(403, dict(error='Refresh the page and try again.'))
        if self.path == '/api/logout':
            with LOCK:
                for token, item in list(SESSIONS.items()):
                    if item is session:
                        del SESSIONS[token]
            return self.reply(200, dict(ok=True), cookie='router_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict')
        if self.path == '/api/account':
            with LOCK:
                # Recheck after acquiring the lock: another request may have changed credentials.
                if self.session() is not session:
                    return self.reply(401, dict(error='Sign in again to continue.'))
                attempts = session.setdefault('account_attempts', [])
                now = time.monotonic()
                attempts[:] = [stamp for stamp in attempts if stamp > now - 60]
                if len(attempts) >= 5:
                    return self.reply(429, dict(error='Too many attempts. Wait one minute.'))
                attempts.append(now)
                try:
                    username = change_account(data)
                except ValueError as error:
                    return self.reply(400, dict(error=str(error)))
                except OSError:
                    return self.reply(500, dict(error='Could not save login details. Try again.'))
            return self.reply(200, dict(username=username, message='Login details updated. Sign in again.'),
                              cookie='router_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict')
        if self.path == '/api/settings':
            try:
                updated = apply_settings(data)
                return self.reply(200, dict(settings=updated, message='Settings applied. Renew client DHCP leases to use the new range or lease time.'))
            except (ValueError, TypeError):
                return self.reply(400, dict(error='Check the DHCP range, lease time and upstream IPv4 DNS addresses.'))
            except Exception:
                self.log_error('Settings apply failed; recovery attempted')
                return self.reply(500, dict(error='Could not apply settings. Check board services over USB before retrying.'))
        if self.path == '/api/wifi':
            try:
                with LOCK:
                    updated = wifi.apply(data, atomic_write)
                return self.reply(200, dict(wifi=updated, message='Hotspot settings applied. Reconnect Wi-Fi devices if the name or password changed.'))
            except ValueError as error:
                return self.reply(400, dict(error=str(error)))
            except Exception:
                self.log_error('Wi-Fi apply failed; recovery attempted')
                return self.reply(500, dict(error='Could not apply hotspot settings. Previous settings were restored where possible; check over Ethernet or USB.'))
        return self.reply(404, dict(error='Not found.'))

    def login(self, data):
        now = time.monotonic()
        with LOCK:
            for address, times in list(ATTEMPTS.items()):
                recent = [stamp for stamp in times if stamp > now - 60]
                if recent:
                    ATTEMPTS[address] = recent
                else:
                    del ATTEMPTS[address]
            attempts = ATTEMPTS.setdefault(self.client_address[0], [])
            if len(attempts) >= 5:
                return self.reply(429, dict(error='Too many attempts. Wait one minute.'))
            attempts.append(now)
            password = data.get('password', '')
            if not isinstance(password, str) or len(password) > 256:
                return self.reply(400, dict(error='Invalid password.'))
            credentials = json.loads((STATE / 'credentials.json').read_text())
            if data.get('username') != credentials.get('username', 'admin') or not password_matches(password, credentials):
                return self.reply(401, dict(error='Incorrect username or password.'))
            for token, item in list(SESSIONS.items()):
                if item['expires'] <= now:
                    del SESSIONS[token]
            if len(SESSIONS) >= 32:
                del SESSIONS[next(iter(SESSIONS))]
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            SESSIONS[token] = dict(csrf=csrf, expires=now + 8 * 3600)
        return self.reply(200, dict(csrf=csrf, username=credentials.get('username', 'admin')), cookie=f'router_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800')


if __name__ == '__main__':
    ThreadingHTTPServer((HOST, 80), Handler).serve_forever()
