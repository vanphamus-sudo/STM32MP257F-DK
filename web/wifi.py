"""Hotspot settings; the web handler serializes mutations with its settings lock."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

BASE = Path('/usr/local/lib/router')


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=15).strip()


def validate(data, previous):
    if not isinstance(data, dict) or set(data) != {'enabled', 'ssid', 'channel', 'password'}:
        raise ValueError('Supply the hotspot name, channel, password and enabled state.')
    if type(data['enabled']) is not bool or type(data['channel']) is not int or data['channel'] not in (1, 6, 11):
        raise ValueError('Choose channel 1, 6 or 11 and an on/off state.')
    ssid, password = data['ssid'], data['password']
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid):
        raise ValueError('Hotspot name must be 1–32 UTF-8 bytes without control characters.')
    if not isinstance(password, str) or (password and (not 8 <= len(password) <= 63 or any(not 32 <= ord(c) <= 126 for c in password))):
        raise ValueError('Wi-Fi passwords require 8–63 printable ASCII characters.')
    if not password and (ssid != previous.get('ssid') or not previous.get('psk')):
        raise ValueError('Enter a Wi-Fi password when changing the hotspot name.')
    psk = hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096, 32).hex() if password else previous['psk']
    return dict(enabled=data['enabled'], ssid=ssid, channel=data['channel'], psk=psk)


def render(data):
    return ('interface=wlan0\ndriver=nl80211\nctrl_interface=/run/router-hostapd\n'
            'country_code=AU\nieee80211d=1\nhw_mode=g\nieee80211n=1\nwmm_enabled=1\n'
            f"ssid2={data['ssid'].encode().hex()}\nchannel={data['channel']}\n"
            'auth_algs=1\nwpa=2\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n'
            f"wpa_psk={data['psk']}\nap_isolate=1\n")


def current():
    return json.loads((BASE / 'wifi.json').read_text())


def status():
    if not (BASE / 'wifi.json').exists():
        return dict(available=False)
    data = current()
    result = {key: data[key] for key in ('enabled', 'ssid', 'channel')}
    result.update(available=True, state='disabled', clients=0, gateway='192.168.20.1')
    try:
        output = run('hostapd_cli', '-s', '/var/lib/router-web', '-p', '/run/router-hostapd', '-i', 'wlan0', 'status')
        values = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        result['state'] = values.get('state', 'unavailable').lower()
        result['clients'] = int(values.get('num_sta[0]', '0'))
    except (subprocess.SubprocessError, ValueError):
        if data['enabled']:
            result['state'] = 'unavailable'
    return result


def activate(data):
    run('systemctl', 'restart' if data['enabled'] else 'stop', 'router-hotspot.service')
    if data['enabled']:
        for _ in range(20):
            try:
                if 'state=ENABLED' in run('hostapd_cli', '-s', '/var/lib/router-web', '-p', '/run/router-hostapd', '-i', 'wlan0', 'status'):
                    return
            except subprocess.SubprocessError:
                pass
            time.sleep(.25)
        raise RuntimeError('Hotspot did not become ready.')


def apply(data, atomic_write):
    previous = current()
    updated = validate(data, previous)
    old_config = (BASE / 'hostapd.conf').read_text()
    try:
        atomic_write(BASE / 'hostapd.conf', render(updated))
        activate(updated)
        atomic_write(BASE / 'wifi.json', json.dumps(updated))
    except Exception:
        atomic_write(BASE / 'hostapd.conf', old_config)
        activate(previous)
        raise
    if data['password']:
        (BASE / 'initial-wifi-password').unlink(missing_ok=True)
    return status()
