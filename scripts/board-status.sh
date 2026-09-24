#!/bin/sh
# Read-only diagnostics. Some details may require root on the target.
set -u
run() {
    printf '\n>>> %s\n' "$*"
    if command -v "$1" >/dev/null 2>&1; then
        "$@" 2>&1 || printf '(command failed or unavailable on this image)\n'
    else
        printf '(not installed)\n'
    fi
}
run uname -a
run cat /etc/os-release
if [ -r /proc/device-tree/model ]; then
    printf '\nBoard: '
    tr -d '\000' < /proc/device-tree/model
    printf '\n'
fi
run ip -brief address
run ip route
run lsusb
run systemctl is-active NetworkManager systemd-networkd ModemManager dnsmasq nftables
run nmcli device status
run mmcli -L
run sysctl net.ipv4.ip_forward
run nft list ruleset
printf '\nRequired commands:\n'
for tool in ip nmcli mmcli nft dnsmasq; do
    command -v "$tool" || printf 'MISSING: %s\n' "$tool"
done
