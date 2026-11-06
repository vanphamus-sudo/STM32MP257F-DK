# Port forwarding

Open **http://192.168.10.1:8081**, sign in, and choose **Firewall → Port forwarding**.
The feature requires OpenWrt/firewall4. It is included in software 1.0.0-r10.

Choose **Add rule**, enter a name, incoming zone, protocol, external port,
destination client and internal port. **Stage rule** updates the local list;
**Apply all changes** validates and activates the complete list. Existing
connections can retain their conntrack mapping until they expire; test new
connections after changing a rule.

Supported controls:

- Create, edit, duplicate, delete, enable and disable up to 100 managed rules.
- TCP, UDP or both; single ports and equal-length ranges, including translation
  such as external `8000-8010` to internal `9000-9010`.
- Incoming WAN/LTE and the existing `router_vpn` OpenVPN zone when configured.
- LAN destinations `192.168.10.2-254` and hotspot destinations `192.168.20.2-254`.
  Router, network, broadcast and USB management addresses are rejected.
- Optional allowed source IPv4 address/subnet and incoming destination IPv4 match.
- Optional WAN NAT loopback using the destination zone. Source restrictions apply
  to incoming forwarding; loopback allows local clients to use the external address.
- HTTP, HTTPS, SSH, remote desktop and WireGuard presets; DHCP client suggestions.
- Versioned JSON export/import. Export includes staged edits; import replaces the
  staged managed list and requires Apply before activation. Unknown rule fields fail
  validation. Reload discards staged edits after confirmation.

For example, to reach a web server listening on `192.168.10.100:80`, create a
WAN TCP rule with external port `8080`, LAN destination `192.168.10.100`, and
internal port `80`. Keep the client's address stable using its static settings
or a DHCP reservation in LuCI. Its return traffic must route through this board.
External testing requires an actual listener and a client on another network.
Carrier NAT, upstream routers, VPN-server policy or a host firewall can prevent
inbound connections even when this router's forwarding rule is correct.

The interface starts with no newly exposed ports. Existing redirects created
through LuCI or SSH are listed separately and preserved. Enabled managed rules
with overlapping source zone, protocol, external ports, source subnet and
external address are rejected. Conflicts with existing redirects are rejected
or require review in LuCI when their format is unsupported. Disabled rules do
not reserve ports. These are IPv4 DNAT rules; this interface does not configure
IPv6, UPnP, schedules or router-input service rules. DMZ host support was added
in release 1.0.0-r11, as described below.

The authenticated API is `GET /api/port-forwards` and CSRF-protected
`POST /api/port-forwards` with `{ "revision": "...", "rules": [...], "dmz": {...} }`.
The GET result supplies the revision, rule fields, available zones, limit and
unmanaged redirect summaries. POST accepts a maximum 64 KiB JSON body. JSON
exports use `{ "version": 2, "rules": [...], "dmz": {...} }`, without a revision;
the UI uses the revision it loaded. Version 1 rule imports remain supported and
preserve the current DMZ setting. API clients omitting `dmz` also preserve it.
Stale revisions return HTTP 409 and retain staged edits.
Do not edit the firewall concurrently in LuCI or SSH; pending UCI changes are
rejected rather than committed by this service.

Rules are named `router_pf_<16 hex digits>` in `/etc/config/firewall`. The
existing private UCI transaction writes a backup to
`/etc/router-web/firewall.previous`, checks `fw4 check`, reloads firewall4, and
verifies the nftables table exists. Failure attempts to restore and reactivate
the previous configuration. Recover over USB SSH if activation reports failure.
Rules persist in the current boot medium. The earlier SD clone is a separate
installation and does not receive later eMMC software/configuration changes.

Validation: 61 Python tests including request authentication/CSRF, revision
handling, invalid destinations, overlap detection, third-party preservation,
and rollback. Headless desktop/mobile browser checks cover staging, presets,
CRUD, import, safe text rendering and layout. Enabled rules were compiled and
checked by the board's actual UCI/firewall4/nftables tools in a private mount
namespace, without changing active firewall rules. No end-to-end WAN client
forwarding test has been performed.

Installed on the board's eMMC on 2026-10-26. Post-install checks confirmed
version 1.0.0-r10, the running web service, delivery of the new controls and
JavaScript, HTTP 401 for unauthenticated rule access, and a valid, unchanged
active firewall with zero new forwarding rules. WAN and `router_vpn` sources
are available. The previous application/configuration backup is
`/root/router-before-port-forwarding-20261026.tar.gz` on the board.
Package: `local/stm32-lte-router_1.0.0-r10_all.ipk`.
Regression log: `logs/port-forwarding-tests-20261026.log`.
Browser screenshots: `logs/port-forwarding-desktop.png` and
`logs/port-forwarding-mobile.png`.

## DMZ host

In software 1.0.0-r11, choose **Firewall → DMZ host**. Select a LAN or hotspot
destination and enter a stable client IPv4 address. Enable it and select
**Apply all changes** to activate. DMZ is disabled by default. Disabling it
retains the selected address; clearing the address while disabled removes the
managed DMZ section on the next apply.

The DMZ rule forwards unmatched incoming WAN/LTE IPv4 traffic for all IP
protocols, with ports unchanged. Every existing specific redirect and managed
port forward precedes it. An existing third-party all-port WAN redirect must
be reviewed in LuCI before enabling DMZ. DMZ has no NAT loopback rule, and only
one managed host can be configured. It does not apply to the VPN or USB zones,
does not configure IPv6, and does not create an isolated network segment.

Enabling DMZ exposes the destination host and can redirect WAN connections
that would otherwise reach router services, including WAN ping and public
serial/AT listeners. USB management remains available. Host firewall rules,
correct return routing and a usable incoming WAN connection still matter.
This feature cannot bypass LTE carrier NAT or an upstream firewall.

The `dmz` object contains exactly `enabled` (boolean), `destination_zone`
(`lan` or `hotspot`) and `destination_ip` (client IPv4 text). Its UCI section is
`firewall.router_dmz`, with IPv4 DNAT, source `wan`, protocol `all`, no port
translation and reflection disabled. It is recreated last on each apply,
sharing port forwarding's revision checks, configuration backup, validation
and rollback. Version 2 JSON imports include and stage DMZ settings along
with rules; they do not activate automatically.

Release 1.0.0-r11 was installed on eMMC on 2026-10-26. Post-install checks
confirmed that DMZ is disabled with no host selected, the firewall file is
unchanged, firewall4 validation passes, all router services run, the DMZ page
and JavaScript are served, and unauthenticated API access returns HTTP 401.
The previous release is backed up on the board at
`/root/router-before-dmz-20261026.tar.gz`; the package is
`local/stm32-lte-router_1.0.0-r11_all.ipk`.

All 66 Python regression tests passed, including DMZ target validation,
disabling/removal, preservation by legacy API clients, catch-all conflict
checks and specific-forward priority. Desktop/mobile browser tests passed for
DMZ staging, saving, version 1 preservation and version 2 imports. Real UCI,
firewall4 and nftables checks in a private mount namespace verified that the
all-protocol DMZ rule preserves ports and follows specific WAN redirects;
the active firewall was untouched. External packet forwarding remains
untested. Test log: `logs/dmz-tests-20261026.log`.

Source: [OpenWrt firewall configuration](https://openwrt.org/docs/guide-user/firewall/firewall_configuration),
including the `redirect`, `src_dport`, `dest_port`, `src_ip`, `src_dip` and
`reflection` options.
