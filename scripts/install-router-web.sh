#!/bin/sh
# Install/start only the web UI. Does not enable router boot or LTE retry services.
set -eu
mkdir -p /usr/local/lib/router-web /var/lib/router-web
chmod 700 /var/lib/router-web
cp /tmp/router-web/server.py /tmp/router-web/wifi.py /tmp/router-web/index.html /tmp/router-web/style.css /tmp/router-web/app.js /usr/local/lib/router-web/
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import secrets
state = Path('/var/lib/router-web')
credentials = state / 'credentials.json'
if not credentials.exists():
    password = 'admin'
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 250000).hex()
    credentials.write_text(json.dumps(dict(username='admin', salt=salt, hash=digest)))
    os.chmod(credentials, 0o600)
    initial = state / 'initial-password'
    initial.write_text(password + '\n')
    os.chmod(initial, 0o600)
PY
cp /tmp/router-web.service /etc/systemd/system/router-web.service
systemd-analyze verify /etc/systemd/system/router-web.service
systemctl daemon-reload
systemctl restart router-web.service
# Open HTTP only on the isolated Ethernet LAN. Keep WAN and USB unchanged.
if ! iptables-legacy -C ROUTER_INPUT -i end0 -s 192.168.10.0/24 -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    iptables-legacy -I ROUTER_INPUT 4 -i end0 -s 192.168.10.0/24 -p tcp --dport 80 -j ACCEPT
fi
python3 - <<'PY'
from pathlib import Path
path = Path('/usr/local/lib/router/router-iptables.rules')
text = path.read_text()
rule = '-A ROUTER_INPUT -i end0 -s 192.168.10.0/24 -p tcp --dport 80 -j ACCEPT\n'
if rule not in text:
    path.write_text(text.replace('-A ROUTER_INPUT -j DROP\n', rule + '-A ROUTER_INPUT -j DROP\n'))
PY
systemctl is-active router-web.service
