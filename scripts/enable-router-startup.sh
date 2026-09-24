#!/bin/sh
# Run after client DHCP and LTE forwarding have been verified.
set -eu
test -s /var/lib/misc/dnsmasq.leases
systemctl is-active --quiet router-firewall.service dnsmasq.service
cp /tmp/router-lte.service /tmp/router-lte.timer /etc/systemd/system/
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/systemd/system/router-firewall.service')
s = p.read_text().replace(
    'Before=dnsmasq.service',
    'DefaultDependencies=no\nWants=network-pre.target\n'
    'After=local-fs.target systemd-modules-load.service systemd-sysctl.service\n'
    'Before=network-pre.target dnsmasq.service shutdown.target\nConflicts=shutdown.target')
p.write_text(s)
p = Path('/usr/local/lib/router/rollback.sh')
s = p.read_text().replace('systemctl stop dnsmasq\n',
    'systemctl stop dnsmasq\n'
    'systemctl disable --now router-lte.timer || true\n'
    'systemctl stop router-lte.service || true\n')
p.write_text(s)
PY
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/router-firewall.service /etc/systemd/system/router-lte.service /etc/systemd/system/router-lte.timer
systemctl enable router-firewall.service dnsmasq.service router-lte.timer
systemctl start router-lte.service
systemctl start router-lte.timer
systemctl is-enabled router-firewall.service dnsmasq.service router-lte.timer
systemctl is-active router-firewall.service dnsmasq.service router-lte.timer
systemctl show router-lte.service -p Result -p ExecMainStatus
