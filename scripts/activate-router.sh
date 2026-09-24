#!/bin/sh
# Run on the board only after Ethernet has been isolated from the upstream LAN.
set -eu
base=/usr/local/lib/router
backup=/var/lib/router/backup-before-activation
test ! -e "$backup"
test ! -e /etc/systemd/network/10-router-lan.network
iptables-legacy-save | grep -q ROUTER_ && exit 1
ip6tables-legacy-save | grep -q ROUTER_ && exit 1
iptables-legacy-restore --test --noflush < /tmp/router-iptables.rules
ip6tables-legacy-restore --test --noflush < /tmp/router-ip6tables.rules
dnsmasq --test --conf-file=/tmp/dnsmasq-router.conf
mkdir -p "$base" "$backup"
iptables-legacy-save > "$backup/ipv4.rules"
ip6tables-legacy-save > "$backup/ipv6.rules"
cat /proc/sys/net/ipv4/ip_forward > "$backup/ip_forward"
cp -a /etc/dnsmasq.conf "$backup/dnsmasq.conf"
ip address > "$backup/addresses.txt"
ip route > "$backup/routes.txt"
cp /tmp/router-iptables.rules /tmp/router-ip6tables.rules "$base/"
cat > "$base/rollback.sh" <<'EOF'
#!/bin/sh
set -eu
systemctl stop dnsmasq
systemctl disable --now router-lte.timer || true
systemctl stop router-lte.service || true
systemctl disable dnsmasq router-firewall.service || true
systemctl mask dnsmasq
rm -f /etc/systemd/system/dnsmasq.service.d/99-router.conf
rm -f /etc/systemd/network/10-router-lan.network
sysctl -w net.ipv4.ip_forward="$(cat /var/lib/router/backup-before-activation/ip_forward)"
iptables-legacy-restore < /var/lib/router/backup-before-activation/ipv4.rules
ip6tables-legacy-restore < /var/lib/router/backup-before-activation/ipv6.rules
systemctl daemon-reload
networkctl reload
networkctl reconfigure end0
EOF
chmod 700 "$base/rollback.sh"
systemd-run --unit=router-activation-rollback --on-active=5m "$base/rollback.sh"
cat > "$base/firewall.sh" <<'EOF'
#!/bin/sh
set -eu
# Stop forwarding until both firewall families are installed.
sysctl -w net.ipv4.ip_forward=0
if ! iptables-legacy -C INPUT -j ROUTER_INPUT 2>/dev/null; then
    iptables-legacy-restore --noflush < /usr/local/lib/router/router-iptables.rules
fi
if ! ip6tables-legacy -C INPUT -j ROUTER_INPUT 2>/dev/null; then
    ip6tables-legacy-restore --noflush < /usr/local/lib/router/router-ip6tables.rules
fi
sysctl -w net.ipv4.ip_forward=1
EOF
chmod 700 "$base/firewall.sh"
cat > /etc/systemd/system/router-firewall.service <<'EOF'
[Unit]
Description=LTE router firewall and IPv4 forwarding
DefaultDependencies=no
Wants=network-pre.target
After=local-fs.target systemd-modules-load.service systemd-sysctl.service
Before=network-pre.target dnsmasq.service shutdown.target
Conflicts=shutdown.target

[Service]
Type=oneshot
ExecStart=/usr/local/lib/router/firewall.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
cp /tmp/dnsmasq-router.conf "$base/dnsmasq.conf"
mkdir -p /etc/systemd/system/dnsmasq.service.d
cat > /etc/systemd/system/dnsmasq.service.d/99-router.conf <<'EOF'
[Unit]
ConditionPathExists=
Requires=router-firewall.service
After=router-firewall.service systemd-networkd.service

[Service]
ExecStartPre=
ExecStartPre=/usr/bin/dnsmasq --test --conf-file=/usr/local/lib/router/dnsmasq.conf
ExecStart=
ExecStart=/usr/bin/dnsmasq --conf-file=/usr/local/lib/router/dnsmasq.conf -x /run/dnsmasq.pid
EOF
systemctl daemon-reload
systemctl start router-firewall.service
cp /tmp/10-router-lan.network /etc/systemd/network/10-router-lan.network
networkctl reload
networkctl reconfigure end0
systemctl unmask dnsmasq
systemctl start dnsmasq
systemctl is-active router-firewall dnsmasq
ip -br address
ip route
printf 'Activation complete; rollback timer is still armed. Verify over USB before cancelling.\n'
