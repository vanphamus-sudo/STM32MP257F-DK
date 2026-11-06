# LAN DHCP MAC-to-IP bindings

Software 1.0.0-r12 adds **Network → MAC-to-IP bindings** to the settings page
at **http://192.168.10.1:8081**. Sign in, choose **Add binding**, and either
select a connected LAN device or enter its MAC and desired LAN IPv4 address.
Optionally set a hostname. Choose **Stage binding**, then **Apply bindings**.
Edit and Remove also stage changes until Apply. Reload discards staged edits
after confirmation. Reconnect the client or renew its DHCP lease to use the
reserved address; existing leases are not forcibly removed or reassigned.

Allowed addresses are `192.168.10.2` through `192.168.10.254`, inside or outside
the dynamic pool. Router, network, broadcast, hotspot and USB addresses are
rejected. MAC addresses accept colon or hyphen notation and are normalized to
lowercase colon notation; zero, multicast and broadcast MACs are rejected.
An optional hostname accepts 1-63 letters, digits and hyphens, beginning and
ending with a letter or digit. Hostnames are normalized to lowercase.

Up to 100 bindings can be managed. Duplicate MACs, IPs, identifiers and
nonempty hostnames are rejected. IPs currently leased to a different MAC are
rejected until that lease expires or is released; select another unused IP
when appropriate. Reservations created through LuCI are displayed separately,
preserved and checked for conflicting MACs, wildcard MAC patterns, IPs and
hostnames. The page does not scan for manually configured static-IP devices;
choose addresses that are not already in use. A reservation is DHCP address
assignment, not an access-control rule or enforcement against MAC spoofing.

Ethernet LAN DHCP must be enabled for clients to receive these addresses. The
page displays a notice when it is disabled. Saving reservations does not turn
DHCP on or change the dynamic pool, DNS, hotspot, USB, firewall or DMZ settings.

The authenticated API is `GET /api/dhcp-reservations`, with a CSRF-protected
POST to the same endpoint. POST accepts a maximum 64 KiB body:

```json
{
  "revision": "revision returned by GET",
  "bindings": [
    {
      "id": "0123456789abcdef",
      "hostname": "server",
      "mac": "00:11:22:33:44:55",
      "ip": "192.168.10.100"
    }
  ]
}
```

The UI creates identifiers automatically. GET returns managed bindings,
unmanaged reservations, active LAN leases, DHCP enabled state and a revision.
Stale revisions return HTTP 409. Pending UCI edits are rejected; avoid concurrent
edits in LuCI/SSH. Validation errors leave staged browser edits available.

Bindings are `host` sections named `router_lease_<16 hex digits>` in
`/etc/config/dhcp`, scoped to the `router_dns` dnsmasq instance. Static-host
syntax is checked with `dnsmasq --test` before the private UCI transaction.
The transaction backs up the old config to `/etc/router-web/dhcp.previous`,
restarts dnsmasq and checks it is running. Activation failure attempts to
restore and reactivate the old configuration. Use USB SSH for recovery.
Reservations persist on the current boot medium; the earlier SD copy remains
a separate installation.

Release 1.0.0-r12 was installed on eMMC on 2026-10-26. Post-install checks
confirmed healthy services, LAN DHCP enabled, the new controls/script served,
unauthenticated API access denied, and byte-for-byte unchanged DHCP/firewall
configuration. No bindings were created automatically. The prior release is
backed up on the board at `/root/router-before-dhcp-bindings-20261026.tar.gz`.
Package: `local/stm32-lte-router_1.0.0-r12_all.ipk`.

All 75 Python tests and desktop/mobile DHCP and forwarding/DMZ browser checks
passed. Tests cover normalization, conflicts, existing reservations, active
leases, stale revisions, request authentication and CSRF. An isolated mount
namespace check used the real UCI and OpenWrt dnsmasq host renderer to verify
the generated MAC/IP/hostname directive and dnsmasq syntax without changing
live DHCP. A physical client renewal with a user-selected binding remains
untested. Log: `logs/dhcp-bindings-tests-20261026.log`.

See [OpenWrt DHCP and DNS configuration](https://openwrt.org/docs/guide-user/base-system/dhcp)
for the underlying `host`, `mac`, `ip`, `name` and `instance` options.
