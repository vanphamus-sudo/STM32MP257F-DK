# Ethernet LAN and WAN

Release r29 adds [USER1/LD9 Ethernet recovery](recovery-button.md): hold USER1
until orange LD9 becomes solid (eight seconds), then release to restore untagged
Ethernet LAN access and reboot. Hardware acceptance testing remains required.

Release `1.0.0-r28` loads Ethernet settings automatically after sign-in, enabling
the port-mode selector without requiring a sidebar click or Reload settings.
Periodic dashboard refreshes preserve unsaved mode/VLAN edits. Verified desktop
and mobile browser behavior, backend validation, and the live authenticated API.
Installed 2026-11-06; existing LAN mode and network configuration were preserved.
Rollback backup: `/root/router-before-ethernet-autoload-20261106-022157/`.

OpenWrt settings → Network → Ethernet mode offers LAN, WAN (DHCP), and
LAN + WAN (VLAN trunk). Save stages configuration; reboot the board manually
when ready. The settings service does not restart networking or reboot the board.
Network service reloads performed elsewhere can also activate the saved settings.
Reload settings reads the saved configuration, not the currently running mode.

LAN retains untagged Ethernet clients at 192.168.10.1/24 with the existing DHCP
server. WAN removes Ethernet from that LAN and uses an upstream DHCP lease.
Enable and verify Wi-Fi hotspot or USB recovery access before changing to WAN.
The hotspot uses a separate subnet; its clients can open the settings page at
http://192.168.10.1:8081 while the empty LAN bridge retains that address.

Both mode uses tagged LAN VLAN 10 and WAN VLAN 20 by default. IDs are editable
from 1–4094 and must differ. Configure the managed switch port to the board as
a tagged member of both VLANs, client ports as untagged LAN members with LAN
PVID, and the upstream router/modem port as an untagged WAN member with WAN
PVID. Exclude those access ports from the opposite VLAN. There is no untagged
LAN on the board trunk. The kernel needs 802.1Q support, built in or supplied by a matching kmod-8021q package. This board has built-in support.

Ethernet WAN joins the existing WAN firewall zone and NAT rules. LTE is retained
with metric 20; Ethernet DHCP uses metric 10. This provides route preference,
not Internet health monitoring or seamless session failover. DHCP DNS remains
disabled in favor of the configured DNS servers. WAN must use a subnet different
from 192.168.10.0/24, 192.168.20.0/24 and any USB management subnet. Static WAN,
PPPoE and IPv6 WAN are not configured by this control.

Network/firewall files are backed up through the existing UCI transaction helper.
Pending UCI edits and stale settings are rejected; a save error restores both
files. Other modem, DHCP, VPN and forwarding configuration is preserved. Existing
DDNS and VPN configurations explicitly bound to LTE's logical `wan` interface
retain that binding; changing Ethernet mode does not migrate those settings.

Local validation uses `python -m unittest discover -s web`. Hardware validation
still requires a board and managed switch: reboot into each mode, verify leases,
LAN/WAN isolation and outbound NAT, and verify recovery access before deployment.
