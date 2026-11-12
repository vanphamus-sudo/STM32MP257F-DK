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
import version_info
import port_forwarding
import ethernet
import usb_tethering
import dhcp_reservations
import mqtt_settings
import mqtt_events
import firmware_update
import traffic_stats
import modbus_settings
import serial_assignment
import router_features

OPENWRT = Path('/etc/openwrt_release').exists()
if OPENWRT:
    import openwrt_backend as platform
    import openvpn_client
    import modem_details

ROOT = Path(__file__).resolve().parent
CONFIG = Path('/usr/local/lib/router/dnsmasq.conf')
STATE = Path('/etc/router-web' if OPENWRT else '/var/lib/router-web')
LOCK = threading.RLock()
SESSIONS = {}
ATTEMPTS = {}
HOST = '192.168.10.1'
PORT = 8081 if OPENWRT else 80
USB_HOST = '192.168.7.1'


def allowed_authorities():
    hosts = (HOST, USB_HOST) if OPENWRT else (HOST,)
    return tuple(authority for host in hosts for authority in
                 ((host, host + ':80') if PORT == 80 else (host + ':' + str(PORT),)))


def serve_usb_management():
    # USB may appear after LAN at boot. Bind only its management address.
    while True:
        try:
            http = ThreadingHTTPServer((USB_HOST, PORT), Handler)
        except OSError:
            time.sleep(5)
            continue
        with http:
            http.serve_forever()



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
    if OPENWRT:
        return platform.settings()
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
        if OPENWRT:
            return platform.apply_settings(data, atomic_write)
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
    if OPENWRT:
        return platform.status()
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
        return self.headers.get('Host') in allowed_authorities()

    def do_GET(self):
        if not self.allowed_host():
            return self.reply(403, dict(error=f'Open this page at http://{HOST}:{PORT}.'))
        assets = {'/user-guide.js': ('user-guide.js', 'text/javascript; charset=utf-8'), '/router-features.js': ('router-features.js', 'text/javascript; charset=utf-8'), '/usb-tethering.js': ('usb-tethering.js', 'text/javascript; charset=utf-8'), '/ethernet.js': ('ethernet.js', 'text/javascript; charset=utf-8'), '/': ('index.html', 'text/html; charset=utf-8'),
                  '/port-forwarding.js': ('port-forwarding.js', 'text/javascript; charset=utf-8'),
                  '/dhcp-reservations.js': ('dhcp-reservations.js', 'text/javascript; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/mqtt.js': ('mqtt.js', 'text/javascript; charset=utf-8'),
                  '/modbus.js': ('modbus.js', 'text/javascript; charset=utf-8'),
                  '/firmware.js': ('firmware.js', 'text/javascript; charset=utf-8'),
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
        if self.path in ('/api/features', '/api/features/backup', '/api/features/support') and OPENWRT:
            try:
                with LOCK, router_features.locked():
                    collect = {'/api/features': router_features.status,
                               '/api/features/backup': router_features.backup,
                               '/api/features/support': router_features.support}[self.path]
                    return self.reply(200, collect(platform))
            except Exception:
                return self.reply(503, dict(error='Router features are temporarily unavailable.'))
        if self.path == '/api/modbus' and OPENWRT:
            try:
                with LOCK:
                    return self.reply(200, modbus_settings.status(platform))
            except Exception:
                return self.reply(503, dict(error='Cannot read Modbus storage.'))
        if self.path.startswith('/api/modbus/files/') and OPENWRT:
            try:
                from modbus_collection import Store
                root = modbus_settings.storage_root(modbus_settings.current())
                if not (root / 'index.sqlite3').is_file():
                    raise ValueError('No saved files.')
                with Store(root) as store:
                    path = store.get(self.path.removeprefix('/api/modbus/files/'))
                    handle = path.open('rb')
                with handle:
                    # Snapshot the length of an active CSV; do not buffer the file.
                    length = os.fstat(handle.fileno()).st_size
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv; charset=utf-8')
                    self.send_header('Content-Length', str(length))
                    self.send_header('Content-Disposition', 'attachment; filename="' + path.name + '"')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    while length:
                        chunk = handle.read(min(length, 65536))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        length -= len(chunk)
                return
            except (OSError, ValueError):
                return self.reply(404, dict(error='Saved data is unavailable.'))
        if self.path == '/api/port-forwards' and OPENWRT:
            try:
                with LOCK:
                    return self.reply(200, port_forwarding.status(platform))
            except Exception:
                return self.reply(503, dict(error='Cannot read firewall rules. Check the firewall over USB.'))
        if self.path == '/api/usb-tethering' and OPENWRT:
            try:
                with LOCK:
                    return self.reply(200, usb_tethering.status(platform))
            except Exception:
                return self.reply(503, dict(error='Cannot read USB tethering settings.'))
        if self.path == '/api/ethernet' and OPENWRT:
            try:
                with LOCK:
                    return self.reply(200, ethernet.status(platform))
            except Exception:
                return self.reply(503, dict(error='Cannot read Ethernet settings.'))
        if self.path == '/api/dhcp-reservations' and OPENWRT:
            try:
                with LOCK:
                    return self.reply(200, dhcp_reservations.status(platform))
            except Exception:
                return self.reply(503, dict(error='Cannot read DHCP bindings. Check dnsmasq over USB.'))
        if self.path == '/api/modem/details' and OPENWRT:
            try:
                return self.reply(200, modem_details.collect(platform))
            except Exception:
                return self.reply(503, dict(error='Modem details are temporarily unavailable.'))
        if self.path == '/api/status':
            try:
                with LOCK:
                    data = status()
                    data['ddns'] = platform.ddns_status() if OPENWRT else dict(available=False)
                    data['openvpn'] = openvpn_client.status(platform) if OPENWRT else dict(available=False)
                    data['mqtt'] = mqtt_settings.status(platform) if OPENWRT else dict(available=False)
                    data['modbus'] = modbus_settings.status(platform) if OPENWRT else dict(available=False)
                    data['serial_assignment'] = serial_assignment.status(platform) if OPENWRT else dict(available=False)
                    data['firmware'] = firmware_update.status() if OPENWRT else dict(available=False)
                    data['traffic'] = traffic_stats.current() if OPENWRT else dict(available=False)
                    data['at_available'] = OPENWRT
                    data['port_forwarding_available'] = OPENWRT
                    data['dhcp_reservations_available'] = OPENWRT
                    data['ethernet_available'] = OPENWRT
                    data['usb_tethering_available'] = OPENWRT
                    data['router_features_available'] = OPENWRT
                    data['software'] = version_info.info()
                return self.reply(200, data)
            except Exception:
                self.log_error('Status collection failed')
                return self.reply(503, dict(error='Board status is temporarily unavailable.'))
        return self.reply(404, dict(error='Not found.'))

    def do_POST(self):
        origins = (None,) + tuple('http://' + authority for authority in allowed_authorities())
        if not self.allowed_host() or self.headers.get('Origin') not in origins:
            return self.reply(403, dict(error='Request origin is not allowed.'))
        if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
            return self.reply(415, dict(error='Expected JSON.'))
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = 1048576 if self.path == '/api/features/restore' else 262144 if self.path == '/api/modbus' else 65536 if self.path in ('/api/port-forwards', '/api/dhcp-reservations', '/api/mqtt', '/api/firmware/settings', '/api/features') else 20000 if self.path == '/api/openvpn/certificate' else 4096
            if not 0 < length <= limit:
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
        if self.path in ('/api/features', '/api/features/action', '/api/features/diagnostics',
                         '/api/features/restore', '/api/features/sms'):
            if not OPENWRT:
                return self.reply(404, dict(error='These router features require OpenWrt.'))
            try:
                with LOCK, router_features.locked():
                    handlers = {'/api/features': router_features.save,
                                '/api/features/action': router_features.action,
                                '/api/features/diagnostics': router_features.diagnose,
                                '/api/features/restore': router_features.restore,
                                '/api/features/sms': router_features.sms}
                    return self.reply(200, handlers[self.path](data, platform))
            except (ValueError, TypeError, KeyError) as error:
                return self.reply(400, dict(error=str(error)))
            except Exception:
                self.log_error('Router feature operation failed')
                return self.reply(503, dict(error='Operation failed. Check router services and package support; any pending network change will roll back automatically.'))
        if OPENWRT and self.path in ('/api/wifi', '/api/ddns', '/api/ethernet', '/api/usb-tethering', '/api/port-forwards', '/api/dhcp-reservations', '/api/openvpn', '/api/openvpn/toggle', '/api/openvpn/certificate', '/api/firmware/update', '/api/mqtt', '/api/modbus', '/api/serial-assignment') and router_features.public_pending():
            return self.reply(409, dict(error='Confirm or roll back the pending router network change first.'))
        if OPENWRT and self.path in ('/api/ethernet', '/api/port-forwards', '/api/openvpn', '/api/openvpn/toggle') and router_features.config()['passthrough']['enabled']:
            return self.reply(409, dict(error='Disable IP passthrough before changing Ethernet, NAT rules or router VPN settings.'))
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
            if OPENWRT and router_features.public_pending():
                return self.reply(409, dict(error='Confirm or roll back the pending router network change first.'))
            try:
                updated = apply_settings(data)
                return self.reply(200, dict(settings=updated, message='Settings applied. Renew client DHCP leases to use the new range or lease time.'))
            except (ValueError, TypeError):
                return self.reply(400, dict(error='Check the DHCP range, lease time and upstream IPv4 DNS addresses.'))
            except Exception:
                self.log_error('Settings apply failed; recovery attempted')
                return self.reply(500, dict(error='Could not apply settings. Check board services over USB before retrying.'))
        if self.path == '/api/modem/at':
            if set(data) == {'command'} and isinstance(data['command'], str) and all(32 <= ord(c) <= 126 for c in data['command']) and len(data['command']) <= 256:
                reserved = version_info.reserved_response(data['command'])
                if reserved is not None:
                    return self.reply(200, dict(command=data['command'], response=reserved.decode('ascii'), ok=data['command'].upper() == 'AT$VERSION', truncated=False))
            if not OPENWRT:
                return self.reply(400, dict(error='The AT console requires OpenWrt.'))
            try:
                return self.reply(200, platform.send_at(data))
            except ValueError as error:
                return self.reply(400, dict(error=str(error)))
            except RuntimeError as error:
                return self.reply(503, dict(error=str(error)))
            except Exception:
                return self.reply(503, dict(error='Cannot reach the LTE module. Check modem status and try again.'))
        if self.path in ('/api/firmware/settings', '/api/firmware/update'):
            if not OPENWRT:
                return self.reply(400, dict(error='Remote updates require OpenWrt.'))
            try:
                with LOCK:
                    result = firmware_update.settings(data) if self.path.endswith('/settings') else firmware_update.submit(data)
                return self.reply(200, dict(firmware=result, message='Update settings saved.' if self.path.endswith('/settings') else result['message']))
            except ValueError as error:
                return self.reply(400, dict(error=str(error)))
            except Exception:
                return self.reply(500, dict(error='Could not process update request. Check router services.'))
        if self.path == '/api/serial-assignment':
            if not OPENWRT:
                return self.reply(400, dict(error='Serial assignment requires OpenWrt.'))
            try:
                with LOCK:
                    updated = serial_assignment.apply(data, platform, atomic_write)
                return self.reply(200, dict(serial_assignment=updated, message='Serial port assignment saved.'))
            except (ValueError, TypeError) as error:
                return self.reply(400, dict(error=str(error)))
            except Exception:
                return self.reply(500, dict(error='Could not switch serial port. Previous settings restored; check service logs.'))
        if self.path == '/api/modbus':
            if not OPENWRT:
                return self.reply(400, dict(error='Modbus collection requires OpenWrt.'))
            try:
                with LOCK:
                    updated = modbus_settings.apply(data, platform, atomic_write)
                return self.reply(200, dict(modbus=updated, message='Modbus settings saved. ' + ('Collector starting.' if updated['enabled'] else 'Collection disabled.')))
            except (ValueError, TypeError) as error:
                return self.reply(400, dict(error=str(error)))
            except Exception:
                return self.reply(500, dict(error='Could not apply Modbus settings. Check router-modbus logs.'))
        if self.path == '/api/mqtt':
            if not OPENWRT:
                return self.reply(400, dict(error='MQTT settings require OpenWrt.'))
            try:
                with LOCK:
                    updated = mqtt_settings.apply(data, platform, atomic_write)
                return self.reply(200, dict(mqtt=updated, message='MQTT settings saved. ' + ('Client starting.' if updated['enabled'] else 'Client disabled.')))
            except (ValueError, TypeError) as error:
                return self.reply(400, dict(error=str(error)))
            except Exception:
                return self.reply(500, dict(error='Could not update MQTT. Check the router-mqtt service.'))
        if self.path in ('/api/openvpn', '/api/openvpn/certificate', '/api/openvpn/toggle'):
            if not OPENWRT:
                return self.reply(400, dict(error='OpenVPN requires OpenWrt.'))
            try:
                with LOCK:
                    action = (openvpn_client.import_certificate if self.path.endswith('/certificate') else
                              openvpn_client.toggle if self.path.endswith('/toggle') else openvpn_client.apply)
                    updated = action(data, platform, atomic_write)
                message = ('Certificate imported.' if self.path.endswith('/certificate') else
                           ('OpenVPN enabled. Connecting…' if updated['enabled'] else 'OpenVPN disabled.') if self.path.endswith('/toggle') else
                           'OpenVPN settings saved. Connection starts in the background.')
                return self.reply(200, dict(openvpn=updated, message=message))
            except ValueError as error:
                return self.reply(400, dict(error=str(error)))
            except Exception:
                self.log_error('OpenVPN update failed; recovery attempted')
                return self.reply(500, dict(error='Could not update OpenVPN. Check its service over USB.'))
        if self.path == '/api/usb-tethering':
            if not OPENWRT:
                return self.reply(400, dict(error='USB tethering requires OpenWrt.'))
            try:
                with LOCK:
                    updated = usb_tethering.apply(data, platform, atomic_write)
                return self.reply(200, dict(usb=updated, message='USB internet gateway advertisement saved for the next reboot. After reboot, reconnect USB to renew the gateway and DNS settings. Management remains at 192.168.7.1.'))
            except (ValueError, TypeError) as error:
                return self.reply(400, dict(error=str(error)))
            except RuntimeError as error:
                return self.reply(409, dict(error=str(error)))
            except Exception:
                self.log_error('USB tethering save failed; recovery attempted')
                return self.reply(500, dict(error='Could not save USB tethering settings.'))
        if self.path == '/api/ethernet':
            if not OPENWRT:
                return self.reply(400, dict(error='Ethernet modes require OpenWrt.'))
            try:
                with LOCK:
                    updated = ethernet.apply(data, platform, atomic_write)
                return self.reply(200, dict(ethernet=updated, message='Ethernet settings saved for the next reboot. Prepare your switch and reconnect after rebooting.'))
            except (ValueError, TypeError) as error:
                return self.reply(400, dict(error=str(error)))
            except RuntimeError as error:
                return self.reply(409, dict(error=str(error)))
            except Exception:
                self.log_error('Ethernet save failed; recovery attempted')
                return self.reply(500, dict(error='Could not save Ethernet settings. Check configuration over USB.'))
        if self.path == '/api/dhcp-reservations':
            if not OPENWRT:
                return self.reply(400, dict(error='DHCP bindings require OpenWrt.'))
            try:
                with LOCK:
                    updated = dhcp_reservations.apply(data, platform, atomic_write)
                return self.reply(200, dict(reservations=updated, message='DHCP bindings saved. Reconnect or renew client leases to use the reserved addresses.'))
            except (ValueError, TypeError) as error:
                return self.reply(400, dict(error=str(error)))
            except RuntimeError as error:
                return self.reply(409, dict(error=str(error)))
            except Exception:
                self.log_error('DHCP bindings apply failed; recovery attempted')
                return self.reply(500, dict(error='Could not apply bindings. Previous DHCP settings were restored where possible; check dnsmasq over USB.'))
        if self.path == '/api/port-forwards':
            if not OPENWRT:
                return self.reply(400, dict(error='Port forwarding requires OpenWrt.'))
            try:
                with LOCK:
                    updated = port_forwarding.apply(data, platform, atomic_write)
                return self.reply(200, dict(port_forwarding=updated, message='Port forwarding and DMZ saved. Firewall reloaded.'))
            except (ValueError, TypeError) as error:
                return self.reply(400, dict(error=str(error)))
            except RuntimeError as error:
                return self.reply(409, dict(error=str(error)))
            except Exception:
                self.log_error('Port forwarding apply failed; recovery attempted')
                return self.reply(500, dict(error='Firewall apply failed; previous settings restored where possible. Check firewall status over USB.'))
        if self.path == '/api/ddns':
            if not OPENWRT:
                return self.reply(400, dict(error='DDNS requires OpenWrt.'))
            try:
                with LOCK:
                    updated = platform.apply_ddns(data, atomic_write)
                return self.reply(200, dict(ddns=updated, message='DDNS settings saved. Updates run in the background.'))
            except ValueError as error:
                return self.reply(400, dict(error=str(error)))
            except Exception:
                self.log_error('DDNS apply failed; recovery attempted')
                return self.reply(500, dict(error='Could not apply DDNS settings. Check DDNS services over USB.'))
        if self.path == '/api/wifi':
            try:
                with LOCK:
                    updated = platform.apply_wifi(data, atomic_write) if OPENWRT else wifi.apply(data, atomic_write)
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
                mqtt_events.web_login(data.get('username', ''), self.client_address[0], False, STATE)
                return self.reply(401, dict(error='Incorrect username or password.'))
            for token, item in list(SESSIONS.items()):
                if item['expires'] <= now:
                    del SESSIONS[token]
            if len(SESSIONS) >= 32:
                del SESSIONS[next(iter(SESSIONS))]
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            SESSIONS[token] = dict(csrf=csrf, expires=now + 8 * 3600)
        mqtt_events.web_login(credentials.get('username', 'admin'), self.client_address[0], True, STATE)
        return self.reply(200, dict(csrf=csrf, username=credentials.get('username', 'admin')), cookie=f'router_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800')


def serve_management():
    if OPENWRT:
        threading.Thread(target=serve_usb_management, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == '__main__':
    serve_management()
