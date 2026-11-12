# USB tethering and management

Release **1.0.0-r30** adds **Network → USB tethering** to the authenticated router settings page. Use tethering when the PC has no Ethernet connection and needs the router's LTE/private-network connection.

| Setting | USB address and DHCP | Gateway and DNS | Forwarding |
|---|---|---|---|
| Off: gateway advertisements disabled (default) | Router 192.168.7.1/24; clients .100–.150 | Neither advertised | IPv4 USB-to-uplink forwarding remains available |
| On: gateway advertisements enabled | Same addresses | Both advertised as 192.168.7.1 | IPv4 USB management zone to WAN, with existing WAN NAT |

The USB gadget stays enabled in both modes. Turning gateway advertisements off does not remove USB management access. The control is **Use router as internet gateway over USB**. It changes DHCP gateway/DNS advertisements only; USB-to-WAN forwarding and USB DNS access remain enabled in both modes. A manually configured client can still use the router as a gateway when advertisements are off.

## Enable

1. Connect a data-capable cable to the board's USB device port. Windows should enumerate the existing NCM adapter.
2. Open router settings through your existing access method. The USB settings address after applying this release's USB configuration is **http://192.168.7.1:8081**; SSH remains **192.168.7.1**.
3. Select **Network → USB tethering → On — management and network access**.
4. Select **Save for next reboot**. The saved configuration is shown; the running network is not restarted by this button.
5. Reboot the router when ready. Disconnect and reconnect the PC's USB network connection to obtain a fresh DHCP lease. Leave IPv4 addressing and DNS automatic on the PC.
6. Check `ipconfig /all`: the USB adapter should have `192.168.7.100–150`, mask `255.255.255.0`, and gateway/DNS `192.168.7.1`.
7. Test the actual target service. For internet-capable SIMs, also test browser internet access. For a private-only SIM, public internet access may be unavailable by design.

For example:

```powershell
# Example private target and TCP port; replace both with your actual service.
Test-NetConnection 10.50.20.30 -Port 502 -InformationLevel Detailed
```

No Windows static route is needed for this normal single-uplink tethering case. If Windows was previously configured to ignore USB default routes using the dual-network guide, restore its original `IgnoreDefaultRoutes` setting before expecting a DHCP default route to work. Do not change company adapter settings.

Forwarding follows the router's routing table and active WAN zone; this control does not pin traffic exclusively to LTE. Ethernet WAN can take priority if configured. The private APN, SIM permissions, router route, remote firewall and service must permit the destination. The feature does not change the APN or SIM configuration.

## Disable

Select **Off — management only**, save, reboot, and reconnect USB to renew the lease. Windows then receives no USB default gateway or DNS advertisement. The management IP, SSH and settings page remain available. Existing leases retain old options until renewed.

If company Ethernet and tethering are connected together, Windows can have two default gateways. This option is intended for the no-Ethernet case. For deliberate simultaneous access, use the separate [Windows routing guide](windows-ethernet-usb-lte-private-network.md), adapting the real USB gateway to **192.168.7.1** and controlling default routes on Windows.

## USER1 access recovery

After Linux has started, hold **USER1** until orange **LD9** stays on at eight seconds, then release. Recovery restores both:

- Existing untagged Ethernet LAN at **192.168.10.1/24**.
- USB management at **192.168.7.1/24**, DHCP **.100–.150**, with no default gateway or DNS advertised. USB gateway and DNS advertisements are turned **off**; forwarding remains available.

USB management firewall rules permit DHCP, ping, SSH and web administration, including port **8081**. Renew the PC's USB lease and open **http://192.168.7.1:8081**. A short USER1 press still reboots without changing settings.

Three post-reboot LD9 flashes now require both the Ethernet and USB management addresses to be present. They do not prove the PC received a lease or that a browser can log in. Recovery restores network configuration for the existing USB gadget; it does not reinstall missing gadget drivers, repair a cable, or repair boot firmware. Do not hold USER1 during power-on; see [button recovery details](recovery-button.md).

## Implementation and validation

The authenticated, CSRF-protected `/api/usb-tethering` endpoint stages DHCP and firewall changes using the existing UCI transaction helper. Revision checks cover network, DHCP and firewall files; pending edits are rejected. A failed firewall transaction restores both saved files. No network service is reloaded by Save. Recovery uses the existing durable recovery journal and resets the USB network, DHCP and management firewall sections.

Both application packaging paths include the USB backend and browser script. Factory provisioning defaults to gateway advertisements off, with tethering forwarding available. Existing installations retain their configuration when the application package is installed; use the control and reboot to apply tethering.

### Deployment and checks — 10 November 2026

Installed **1.0.0-r30** on the connected dev kit's running root slot. Backup:
`/root/router-before-usb-tethering-20261110-062335/application-and-config.tar.gz`
(the directory name uses the board's clock). Network, DHCP, firewall and USB gadget
configuration bytes were verified unchanged by installation. Tethering remains off;
the board was not rebooted. The standby root slot and existing factory images
were not updated.

Validation completed:

- 154 web/backend Python tests passed, with five platform-specific skips; four OpenWrt tests passed.
- Desktop and mobile browser tests passed for USB controls and the existing Ethernet controls.
- On the actual router, private copies of its UCI configuration passed enable/disable, gateway/DNS, and recovery checks. The generated firewall rules passed kernel `nft -c` validation; live settings were verified unchanged.
- After installation, router-web, router-button and router-at were running; the new HTML and JavaScript returned HTTP 200; the USB API rejected unauthenticated access with HTTP 401.

Physical USER1 gestures, post-reboot USB DHCP/gateway/DNS renewal, and end-to-end
PC traffic through the SIM still require hardware acceptance testing. The
isolated configuration checks do not establish those physical results.

### Gateway advertisement control update � 11 November 2026

Installed **1.0.0-r31** on the connected router's running root slot. The USB control
is now **Use router as internet gateway over USB**. Saving either choice retains
USB-to-WAN forwarding and USB DNS access; only DHCP gateway/DNS advertisements
follow the selected value. Factory provisioning and USER1 recovery use the same
forwarding policy, with gateway advertisements off by default.

Backup: `/root/router-before-r31-20261110-235836/` (board clock), including a
rollback IPK and configuration/application archive. Installation verified every
packaged file against its SHA-256 hash and preserved existing settings. Previously
active application services were restarted and verified running; the new control
was verified in the served web page. No reboot or live network reconfiguration
was performed. Existing USB forwarding settings remain unchanged until the USB
control is saved and its saved configuration applied at reboot. The standby root
slot and factory images were not updated.

Validation: 155 Python tests completed with five platform-specific skips; desktop
and mobile USB browser checks passed. Physical USB lease renewal and end-to-end
tethering remain hardware acceptance checks.

### USB web listener fix � 11 November 2026

Diagnosed USB connectivity from Windows with USB as the only default route.
DNS, internet HTTPS, a 1 MB HTTPS download, Windows connectivity probe and a
1500-byte IPv4 path test succeeded. A 20-packet internet ping had no loss.
The router settings service, however, listened only on 192.168.10.1:8081.

Installed **1.0.0-r33** with an additional listener bound specifically to
192.168.7.1:8081, retrying while that address is unavailable at boot. Host/origin
validation permits the two explicit management addresses and retains authentication
and CSRF enforcement. Verified from Windows: USB page HTTP 200, unauthenticated
USB API HTTP 401, and internet HTTPS HTTP 200. Existing settings were preserved;
no reboot or network reconfiguration was performed. Backup before final install:
`/root/router-before-r33-20261111-001257/`. Application service state and packaged
file hashes were verified by the installer. The full suite passed before the
startup correction (156 tests, five skips); the server suite including listener
startup coverage passed after correction (16 tests). This fixes the confirmed
USB management failure; no general internet failure was reproduced during checks.
