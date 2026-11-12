# Settings navigation (r36)

The sidebar groups related settings and links directly to individual advanced
settings. Clicking a link opens the target's collapsed section and moves keyboard
focus to it. Direct URL fragments work after sign-in and when the feature becomes
available. Navigation preserves unsaved form values.

| Group | Settings |
| --- | --- |
| Status | Network overview, connection details, LAN clients, traffic statistics, signal history, event history |
| Internet | Ethernet mode, WAN failover, IP passthrough, DDNS, IPv6, data allowance, SQM, connection watchdog |
| Local network | LAN/DHCP/DNS, MAC-to-IP bindings, Wi-Fi hotspot, USB tethering, isolated VLAN |
| Firewall | Port forwarding, DMZ |
| VPN | OpenVPN client, WireGuard VPN |
| Cellular | Modem status, operator/bands, signal recording, SMS settings/inbox, GNSS, SIM/hardware options, AT console |
| Services | Serial assignment, Modbus collection, MQTT client |
| System | Alerts, diagnostics/backup, login details, software updates, service status, software version |

Unavailable panel links are hidden. A group is hidden only when all its links
are hidden; in particular, the VPN heading remains available for WireGuard even
if the OpenVPN panel is unavailable. On mobile, selecting a link closes the menu.
Each group can be collapsed independently.

R37 adds **System → Start here / user guide**, with searchable explanations,
examples and help beside settings. See [the guided settings page](guided-settings.md).

## Installation — 12 November 2026

Installed `1.0.0-r36` over r35 on the board's running root slot. Existing settings
were verified unchanged; all packaged files were checked against the local IPK.
Previously active services were restarted and verified running. No reboot or
network reconfiguration was performed. The standby root and factory images were
not updated.

Rollback backup on the board:
`/root/router-before-r36-20261112-002952/`, including `rollback.ipk`, application
and configuration archive, settings hashes and the installation report.

Validation: 195 Python tests completed with six platform-specific skips. Browser
checks passed at 1440 and 390 pixels for grouping, navigation targets, independent
VPN visibility, collapsed-section opening, focus, URL fragments, unsaved edits and
layout. Existing advanced-feature, Ethernet and USB browser checks also passed.
The served USB management page returned HTTP 200 and its VPN group was verified
to contain both OpenVPN and WireGuard links. The board firewall check passed.
