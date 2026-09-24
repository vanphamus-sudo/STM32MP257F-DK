#!/usr/bin/env python3
"""Install the authorized Wi-Fi hotspot without enabling any boot units."""
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
sys.path.insert(0, '/tmp/router-web')
import wifi
from server import atomic_write

def run(*args):
    subprocess.run(args, check=True)

base = wifi.BASE
backup = Path('/var/lib/router-web/before-wifi')
backup.mkdir(exist_ok=True)
for name in ('dnsmasq.conf', 'router-iptables.rules'):
    if not (backup / name).exists():
        shutil.copy2(base / name, backup / name)
if not (base / 'wifi.json').exists():
    password = secrets.token_urlsafe(12)
    data = wifi.validate(dict(enabled=True, ssid='STM32-LTE', channel=6, password=password), {})
    atomic_write(base / 'wifi.json', json.dumps(data))
    atomic_write(base / 'hostapd.conf', wifi.render(data))
    atomic_write(base / 'initial-wifi-password', password + '\n')
shutil.copy2('/tmp/wifi-dhcp.conf', base / 'wifi-dhcp.conf')
conf = base / 'dnsmasq.conf'
include = 'conf-file=/usr/local/lib/router/wifi-dhcp.conf\n'
if include not in conf.read_text():
    atomic_write(conf, conf.read_text().rstrip() + '\n' + include)
run('/usr/bin/dnsmasq', '--test', '--conf-file=' + str(conf))
rules = [
    ('filter', 'ROUTER_INPUT', '-i wlan0 -p udp --sport 68 --dport 67 -j ACCEPT'),
    ('filter', 'ROUTER_INPUT', '-i wlan0 -s 192.168.20.0/24 -p udp --dport 53 -j ACCEPT'),
    ('filter', 'ROUTER_INPUT', '-i wlan0 -s 192.168.20.0/24 -p tcp -m multiport --dports 53,80 -j ACCEPT'),
    ('filter', 'ROUTER_FORWARD', '-i wlan0 -o wwu1u1i8 -s 192.168.20.0/24 -m conntrack --ctstate NEW,ESTABLISHED,RELATED -j ACCEPT'),
    ('filter', 'ROUTER_FORWARD', '-i wwu1u1i8 -o wlan0 -d 192.168.20.0/24 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT'),
    ('nat', 'ROUTER_NAT', '-s 192.168.20.0/24 -o wwu1u1i8 -j MASQUERADE'),
]
stored = (base / 'router-iptables.rules').read_text()
for table, chain, text in rules:
    prefix = ['iptables-legacy', '-t', table]
    if subprocess.run(prefix + ['-C', chain] + text.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        position = '4' if chain == 'ROUTER_INPUT' else '2' if chain == 'ROUTER_FORWARD' else '1'
        run(*prefix, '-I', chain, position, *text.split())
    line = '-A ' + chain + ' ' + text + '\n'
    if line not in stored:
        marker = '-A ' + chain + ' -j DROP\n' if table == 'filter' else '-I POSTROUTING 1 -j ROUTER_NAT\n'
        stored = stored.replace(marker, line + marker)
atomic_write(base / 'router-iptables.rules', stored)
shutil.copy2('/tmp/router-hotspot.service', '/etc/systemd/system/router-hotspot.service')
run('systemctl', 'daemon-reload')
run('systemctl', 'restart', 'dnsmasq')
wifi.activate(wifi.current())
for name in ('server.py', 'wifi.py', 'index.html', 'app.js', 'style.css'):
    shutil.copy2('/tmp/router-web/' + name, '/usr/local/lib/router-web/' + name)
run('systemctl', 'restart', 'router-web')
print(json.dumps(wifi.status()))
