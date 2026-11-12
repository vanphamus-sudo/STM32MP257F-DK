# Additional router services (r34)

The authenticated settings page links advanced settings from their relevant
[sidebar groups](navigation.md): Internet, Local network, VPN, Cellular and System. These
changes are included in the r35 package installed on the running board on
12 November 2026. Existing settings were preserved. The feature supervisor is
running; passthrough remains off. See the [installation and validation record](ip-passthrough.md).

## Implemented software features

| Feature | Behavior and limits |
| --- | --- |
| Connection watchdog | Checks two to four public IPv4 addresses through LTE. Consecutive failures trigger `ifdown/ifup wan`, with modem resets after repeated recovery attempts. Exponential cooldown limits restart loops. A reply from any target counts as healthy; ICMP-blocking networks need suitable targets. |
| WAN failover | Ethernet primary, LTE backup; probes each interface separately and requires multiple successful checks before returning to Ethernet. IPv4 only. Existing sessions may reconnect. Requires Ethernet WAN or trunk mode. |
| Data allowance | Uses SIM1 + SIM2 lifetime counters, without adding duplicate WAN counters. Upload and download both count. Decimal MB, billing days 1–28, midnight UTC reset, threshold alert and optional client-forwarding cutoff. Router-originated traffic remains possible. This is an estimate, not carrier billing. |
| Backup/restore | Same-board JSON export of network, firewall, DHCP, Wi-Fi, DDNS, SQM, OpenVPN and selected application settings/certificates. Secrets are included. Credentials, firmware trust, executable handlers, accounting and A/B partition descriptions are excluded. Imports are bounded, allowlisted and parsed before installation; executable UCI includes are rejected. |
| Alerts/history | Bounded 200-event local history; acknowledged MQTT `ALARM` messages reuse the existing outbox. Startup, LTE connectivity, recovery, serving-cell changes, weak signal, data warnings, VPN changes and configuration events are recorded. Optional SMS for connectivity, recovery and allowance alerts. |
| LTE signal history | Bounded in-memory history for RSRP, RSRQ, SINR, serving cell and band. Three signal traces plus a recent-samples table. Reboot clears signal samples. |
| WireGuard | One peer, private/public keys, address, endpoint, allowed networks, keepalive and optional remote access to LAN. A separate firewall zone rejects router input. No WAN listener is opened automatically. |
| Isolated VLAN | One additional tagged Ethernet network, DHCP/DNS and WAN forwarding, with router input and inter-zone forwarding rejected. Requires existing Ethernet trunk mode and a managed switch; no additional Wi-Fi SSID is created. |
| SQM | CAKE with `piece_of_cake.qos`, configured interface and upload/download rates. LTE capacity changes require tuning. |
| Diagnostics | Bounded ping, DNS lookup and traceroute. JSON support report contains runtime, capabilities, signal and events; configuration, keys, certificates, SMS and GNSS coordinates are excluded. |
| SMS | Bounded inbox read and manual send using ModemManager; optional alert recipient. Outgoing messages use a restricted 160-character ASCII subset. No remote SMS command execution. Carrier support and charges apply. |
| IPv6 | Dual-stack LTE request, DHCPv6 prefix delegation, LAN RA/DHCPv6, WAN-zone membership and essential ICMPv6/DHCPv6 rules. Carrier/APN prefix delegation and working OpenWrt IPv6 packages are required. IPv6 failover is not implemented. |
| Cellular controls | Roaming policy, MCC/MNC selection and supported LTE band selection. Unsupported bands are rejected. Unconfirmed changes restore previous preferences. |
| IP passthrough (r35) | Exclusive routed IPv4 handoff to one Ethernet MAC using a /32 DHCP lease and classless routes, without STM32 NAT. USB management remains available. Requires dedicated Ethernet LAN mode, connected IPv4 LTE, conntrack and conflicting services disabled. Installed with isolated DHCP/firewall validation; routed client traffic is not yet tested. See [passthrough setup and limits](ip-passthrough.md). |
| Dual SIM | Manual slot selection appears only when ModemManager reports multiple populated slots. This does not create a second SIM socket or implement automatic per-SIM failover. |
| GNSS | Raw GPS enable/disable and authenticated runtime fixes when ModemManager reports support. Requires antenna, firmware support and sky view; fixes are not exported in support reports. |

## Hardware features still requiring implementation

**eSIM provisioning is not implemented.** The panel reports it as unavailable;
a modem-specific implementation and hardware validation are required. IP
passthrough is implemented and installed as a routed IPv4 handoff in r35, without
changing the modem USB mode, and still requires end-to-end client validation.

## Build and activation

Build the application package on this Windows workspace:

```powershell
& 'C:\Users\Van Pham\AppData\Local\Python\pythoncore-3.14-64\python.exe' openwrt/build-ipk.py local/stm32-lte-router_1.0.0-r34_all.ipk
```

The OpenWrt package declares `wireguard-tools`, `kmod-wireguard`, `sqm-scripts`,
`kmod-sched-cake`, `ip-full`, `odhcp6c` and `odhcpd-ipv6only` in addition to the
existing dependencies. Build/install kernel modules matching the board's exact
OpenWrt kernel; do not force incompatible modules. The custom factory builder
copies the services into its pinned base rootfs; it does not download these
extra packages. Missing packages are reported by capability checks. A complete
OpenWrt image built through `prepare-package.sh` includes declared dependencies.

After installing the package and dependencies on OpenWrt:

```sh
/etc/init.d/router-traffic enable
/etc/init.d/router-traffic start
/etc/init.d/router-features enable
/etc/init.d/router-features start
/etc/init.d/router-web restart
```

Factory source integration enables the supervisor at boot. The standalone
script-free application package requires the explicit activation above, including
when upgrading an older board that did not have this service. Updating an already
active supervisor uses the existing signed updater's stop/restart lifecycle.

Watchdog, failover, quota enforcement, WireGuard, VLAN, SQM, IPv6, SMS and GNSS
are initially off. Signal collection and local event recording are initially on;
remote notifications are off. Enable features individually after configuring
their settings.

## Recovery and persistence

Network-affecting feature edits require a running supervisor. Before changing
files, the API saves a private snapshot and a three-minute confirmation deadline.
Confirm connectivity from the settings page; otherwise the supervisor restores
the files and reloads services. Reboot with an unconfirmed change also triggers
rollback. Other web configuration writes are blocked while confirmation is pending.
Do not edit UCI concurrently through LuCI or SSH during this window.

Settings and event history live under `/etc/router-web`. Allowance checkpoints
use the traffic service's shared storage when A/B storage is configured, otherwise
`/etc/router-web/feature-accounting.json`. Runtime and signal history live under
`/tmp`. Usage checkpoints are written every
five minutes and on warning/cutoff transitions; persistent traffic totals allow
catch-up after ordinary service restarts. Allowance settings remain slot local,
so configure the same limit and billing day in both A/B slots. The first
sample of a newly tracked billing cycle establishes its baseline; installing the
feature mid-cycle cannot reconstruct previous carrier usage. System clock changes
can affect cycle boundaries; synchronize time before enabling allowance controls.

Failover reserves IPv4 route table/rule priority `10900` and bound-probe rule
priorities `10890` and `10891`. It refuses existing reservations it does not own.
It preserves specific main-table routes and removes its rules on service stop.
Cutoff uses a separate `inet router_allowance` nftables table so firewall4 reloads
do not silently remove it. Disabling allowance enforcement removes the table;
stopping the supervisor leaves an active cutoff in place until restart or reboot.

Backups include private material and are not encrypted. Store them securely.
After restoring, confirm connectivity and restart MQTT, Modbus and serial services
as applicable so they reread their restored settings. Reapply OpenVPN from its
panel if its service was running during restoration. A support report omits
credentials but contains network topology and usage metadata.

## Validation

```powershell
& 'C:\Users\Van Pham\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m unittest discover -s web
& 'C:\Users\Van Pham\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m unittest discover -s openwrt
node web/test_router_features_browser.cjs
```

Host tests cover validation, secret masking, alarm IDs, cycle rollover, counter
resets, restoration, confirmation tokens, recovery backoff, diagnostic boundaries,
HTTP authentication/CSRF, desktop/mobile form behavior, text injection and graphs.
They cannot establish kernel/module compatibility, modem behavior, carrier prefix
delegation, real failover, isolation or throughput. Verify those on the board with
USB recovery connected before unattended use.

Implementation references: [ModemManager mmcli](https://www.freedesktop.org/software/ModemManager/man/latest/mmcli.1.html),
[OpenWrt ModemManager](https://git.openwrt.org/feed/packages/tree/net/modemmanager/README.md),
[OpenWrt SQM](https://openwrt.org/docs/guide-user/network/traffic-shaping/sqm).
