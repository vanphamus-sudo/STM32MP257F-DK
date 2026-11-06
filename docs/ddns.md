# Dynamic DNS

## Dev kit deployment — 2026-10-02

The running OpenWrt dev kit was upgraded over USB SSH to application
`stm32-lte-router 1.0.0-r2`. Installed DDNS packages are `2.8.2-r64`, with
`curl 8.22.0-r1` and `ca-bundle 20260816-r1` from the configured, signed
OpenWrt 24.10.8 feeds. No firmware partitions were flashed and no reboot was
performed. DDNS and router-web are enabled for startup; DDNS remains disabled
until provider details are entered on the page.

Live checks passed for authentication, CSRF rejection, invalid-hostname
rejection, disabled DDNS apply, secret omission, page assets, native No-IP
updater, HTTPS public IPv4 discovery, package status and deployed source hashes.
DHCP and Wi-Fi settings were preserved; LTE, dnsmasq, ModemManager and firewall
remained active. Configuration and backups have mode 0600. All 26 local tests
and the JavaScript syntax check passed. Provider acceptance and DNS propagation
remain untested because no DDNS account was configured.

The pre-upgrade configuration/application backup is on the board at
`/root/router-before-ddns-20261002/config-and-app.tar.gz` (private). Installation
reported obsolete CA-file warnings and an unresolved feed dependency for
`kmod-nf-conntrack-netlink` while resolving the existing router package. The
requested application and DDNS packages nevertheless installed successfully;
the CA bundle, HTTPS requests and active firewall were verified afterward.
No kernel packages were replaced as part of this update.

## Configuration

### DDNS save fix — 2026-10-02

Application `1.0.0-r3` fixes enabled-account saves timing out: the OpenWrt
24.10 DDNS background worker inherited the captured restart output pipe,
keeping the web request waiting until its 30-second timeout and rollback.
Restart now redirects standard streams to `/dev/null`; status also checks the
legacy worker PID file and process identity, alongside procd instances.
The failure and fix were reproduced on the board using a background child.
All 28 local tests passed. A private pre-fix backup is stored at
`/root/router-before-ddns-fix-20261002/config-and-app.tar.gz`.
The failed requests had rolled back the account details; enter them again in
the page after refreshing. A provider record already showing the public IP
does not establish that the router configuration was saved successfully.

On OpenWrt, the authenticated settings page includes DDNS controls when
`ddns-scripts` is installed. Choose DynDNS or No-IP, enter an existing provider
hostname and provider credentials, turn DDNS on and apply. Leave the password
blank to retain it; changing providers requires entering it again.

The application package depends on `ddns-scripts`, `ddns-scripts-services`,
`ddns-scripts-noip`, `curl` and `ca-bundle`. Existing installations need these
packages from their matching firmware feed. The factory builder overlays files
onto a prebuilt root filesystem; that base must include these dependencies.

The dedicated UCI section is `ddns.router_ddns`. Updates and public IPv4 discovery
use HTTPS; discovery uses `https://api.ipify.org`. Checks run every ten minutes,
forced updates every 72 hours, and failures retry after 60 seconds. OpenWrt's
native service manages startup and retries. Other DDNS sections are preserved,
but applying settings restarts the DDNS service. Passwords remain in root-only
configuration and rollback backup files and never appear in API responses.
Configuration is retained during sysupgrade.

The badge reports the updater process state, not provider acceptance or DNS
propagation. Check `logread` and resolve the hostname externally to confirm an
update. DDNS does not bypass carrier NAT or create forwarding rules. The legacy
OpenSTLinux page does not expose this feature.

Configuration follows the [OpenWrt DDNS defaults](https://github.com/openwrt/packages/blob/master/net/ddns-scripts/files/etc/config/ddns)
and [native service lifecycle](https://github.com/openwrt/packages/blob/master/net/ddns-scripts/files/etc/init.d/ddns).
