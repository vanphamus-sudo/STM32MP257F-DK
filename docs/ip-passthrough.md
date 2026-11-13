# Routed IPv4 passthrough (r35)

## r44 carrier DNS — 13 November 2026

Passthrough now uses LTE bearer DNS, including netifd's inactive peer DNS when
normal router operation disables peer DNS. It no longer falls back to
`dhcp.router_dns.server` or public resolvers. Missing carrier IPv4 DNS blocks
activation with an explicit error. DNS changes are part of the lease journal,
so reconciliation refreshes the handoff when carrier DNS changes.

Installed r44 with settings preserved, package hashes and firewall validated,
services restarted and USB management HTTP 200. All 26 recovery/passthrough
tests passed on the board. The installed lease reader selects carrier DNS
`101.168.244.100` and `101.168.244.102`; passthrough was Off at verification,
so a fresh downstream DHCP lease still requires client validation.
No reboot or standby-slot update was performed.
Rollback backup: `/root/router-before-r44-20261113-000133/`.

## r43 activation fix — 13 November 2026

Installed r43 to fix activation failing with `Command failed: ip`. This board's
kernel has `CONFIG_IP_ADVANCED_ROUTER` disabled, so `ip -j -4 rule show` fails
with `Address family not supported by protocol`. The prerequisite check now
accepts that failure only when `/proc/config.gz` proves IPv4 policy routing is
disabled; unknown configurations and other failures still block activation.
Kernels supporting policy routing still reject custom rules.

All 25 recovery/passthrough tests passed on the board, and the live activation
preflight passes. Settings and installed file hashes were verified, firewall
validation passed, services restarted, and USB management returned HTTP 200.
Passthrough remains Off with no designated client MAC; downstream packet testing
is still required. No reboot or standby-slot update was performed.
Rollback backup: `/root/router-before-r43-20261112-233304/`.

The router can hand its LTE IPv4 address to **one downstream router's Ethernet
WAN port**. The downstream router uses that address directly; the STM32 performs
IPv4 forwarding without source or destination NAT. This is a routed handoff, not
an Ethernet bridge to the mobile network. The EM060K-GL remains in its existing
MBIM USB mode under ModemManager.

This implementation is installed as r35 on the connected board's running root
slot as of **12 November 2026**. Host tests and isolated on-board DHCP/firewall
checks pass, but it has **not been packet-tested with a downstream client**. In particular,
netifd behavior after address removal, the Linux firewall and the downstream
DHCP client's acceptance of a /32 lease require live validation.

## Installation record — 12 November 2026

Upgraded the running board from r33 to r35, with its exact-kernel WireGuard,
CAKE/IFB and netfilter dependencies from the original cached, signature-verified
Bootlin target repository. Userspace dependencies came from signed OpenWrt
24.10.8 feeds. Installed ip-full, tc-full, iptables-nft, conntrack, WireGuard tools
and SQM scripts. Existing settings were verified unchanged by hashes; all packaged
files were verified against the local r35 package.

Backup on the board (directory name uses the board clock):
`/root/router-before-r35-20261112-000059/`. It contains `rollback.ipk`,
`configuration-and-app.tar.gz`, settings hashes, previous package/service lists
and the installation result.

The previously active router services were restarted, and `router-features` is
running and enabled at boot. USB management HTML and JavaScript return HTTP 200;
the unauthenticated features API returns HTTP 401. The firewall passes `fw4 check`,
and Internet DNS/HTTPS was verified with HTTP 200. Eighteen passthrough tests pass
on the board with no skips, including the native dnsmasq parser. The passthrough
guard and generated firewall for private enable/disable UCI copies pass kernel
`nft -c`; those checks do not apply rules or change live configuration.

**Passthrough remains disabled.** No reboot was performed. The standby A/B slot
and factory images were not updated. Routed client traffic, lease renewal and
physical recovery still need acceptance testing before enabling unattended use.

## Behavior

- The physical Ethernet port becomes a dedicated passthrough port. It no longer
  provides the normal 192.168.10.x LAN leases.
- The designated Ethernet WAN MAC receives the LTE-assigned IPv4 address through
  a dedicated DHCP server. Its netmask is /32. DHCP options 121 and 249 supply an
  on-link route to gateway **192.168.40.1** and a default route through it.
- The client must support DHCP classless routes. A downstream router should use
  its own firewall and, if desired, NAT for its own LAN clients.
- USB management remains **http://192.168.7.1:8081**. The existing Wi-Fi management
  network remains configured, but Wi-Fi clients cannot share LTE Internet while
  passthrough is active.
- LTE is handed off exclusively. Router-originated LTE IP traffic is blocked,
  including cloud MQTT, DDNS updates, FTP uploads and router VPN traffic. Local
  ModemManager control, SMS, signal monitoring and traffic counters remain usable.
- This hands off the address actually assigned by the carrier. A CGNAT/private
  carrier address stays CGNAT/private; passthrough does not create public inbound
  reachability or remove carrier filtering.
- IPv6 passthrough, Ethernet WAN/trunk modes, multiple downstream hosts and
  concurrent router VPN/WAN sharing are not supported.

## Enable

1. Install the r35 package and its dependencies, including **ip-full**, nftables,
   dnsmasq and **conntrack**. Build matching kernel dependencies through the
   project's OpenWrt package definition. The pinned factory rootfs builder does
   not download missing packages; capability checks will report unavailable
   passthrough until they are installed.
2. Connect USB management and verify you can sign in at 192.168.7.1:8081.
3. Use Ethernet **LAN** mode and an IPv4-only, connected LTE bearer. Disable
   watchdog, failover, WireGuard, the router OpenVPN client, guest VLAN and IPv6.
   Disable all port forwards/DMZ/custom NAT, custom IPv4 policy rules and firewall
   flow offloading. SQM may already be configured, but cannot be edited while
   passthrough is active because that change reloads networking.
4. Connect the downstream router's WAN port to Ethernet and configure that port
   as a DHCP client. Read its Ethernet WAN MAC address.
5. Open **Internet → IP passthrough**, enter that MAC and switch
   passthrough on. Apply. Activation validates USB/LTE state and conntrack support
   before editing configuration, then syntax-checks DHCP and installs the handoff.
6. Renew the downstream DHCP lease. Verify it receives the LTE address, the /32
   mask and the gateway/default routes. Test Internet access from that router.
7. Confirm connectivity through the USB management page within three minutes.
   Otherwise the previous configuration and normal routing are restored.

The MAC must be a nonzero unicast address. It selects the intended client; MAC
filtering does not authenticate a device against an attacker spoofing that MAC.
Only the existing dedicated router network/firewall profile is supported.

## Disable, reconnect and recovery

Apply passthrough **Off** from USB management and confirm the change. The LTE
address returns to the STM32, WAN masquerading returns, and Ethernet rejoins
the original LAN bridge. Renew the downstream lease to receive a private LAN
address again. Changing the designated MAC also requires a fresh client lease.

The feature supervisor checks the bearer every ten seconds. A changed LTE address
replaces the DHCP offer, host route and pinned neighbour. The previous address is
not re-added to the host during a carrier transition. Leases last two minutes;
the downstream client may need an explicit renew after a reconnect. Existing
sessions cannot survive an address change.

An ownership journal under `/tmp/router-passthrough` is written before live
network mutations. A failed activation restores the address and removes owned
routes, neighbours, DHCP state and firewall rules; the enclosing feature
transaction restores UCI/settings. Connection tracking for the address is cleared
on owner changes so old router/client flows are not reused by the new owner.
If conntrack fails during cleanup, recovery continues and logs a warning.

Stopping the feature supervisor stops its DHCP server and blocks passthrough
traffic, retaining the journal. Restarting the supervisor reconstructs the handoff.
A reboot clears runtime state and reconstructs it from netifd and saved settings.
Unconfirmed changes also roll back across reboot.

The long USER1 recovery gesture removes the passthrough interface/firewall zone,
restores Ethernet LAN and WAN NAT, and restores USB management before reboot.
Recovery also saves the passthrough switch as **Off** and clears any pending
feature confirmation so its rollback cannot undo recovery after reboot.
See [button recovery](recovery-button.md).

## Implementation and validation

`web/ip_passthrough.py` owns the runtime handoff. The settings API handles
validation, UCI edits and rollback; `router_supervisor.py` handles restart and
bearer changes. No vendor AT configuration is needed. The implementation removes
the LTE address from the Linux uplink while retaining the modem bearer, restores
its on-link default route, and routes the address as a /32 to a permanent
Ethernet neighbour. WAN masquerading is disabled while active. A separate
`inet router_passthrough` nftables table enforces client MAC/IP selection and
prevents access to other router networks. It survives firewall4 reloads.

Host tests cover input validation, incompatible configurations, UCI plans,
address/route ownership, DHCP option rendering, lease changes, failed activation,
configuration rollback, process stop/restart, stale-flow cleanup and recovery
during an incomplete bearer transition. Browser tests exercise passthrough
submission and network confirmation on desktop/mobile. A dnsmasq syntax test
runs only when the native Linux binary is available.

Before unattended use, validate on the board: real DHCP DORA and renewal,
downstream Internet traffic with unchanged WAN source address, unsolicited inbound
traffic where the carrier permits it, rejection of another MAC/source IP,
isolation from USB/LAN/Wi-Fi, lease changes, service restart, both confirmation
outcomes, reboot and USER1 recovery. This workspace's Windows tests do not prove
those packet-level behaviors.

References: [dnsmasq shared-network and DHCP options](https://dnsmasq.org/docs/dnsmasq-man.html),
[Linux address management](https://www.man7.org/linux/man-pages/man8/ip-address.8.html).
