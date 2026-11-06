# OpenWrt migration

The repository supports OpenWrt with the existing settings page. The board was
flashed on 2026-09-29 using a custom eMMC installation that retains the working
ST bootloader and OpenSTLinux recovery filesystem. See the
[board flash record](openwrt-flash-status.md) for its layout, validation and recovery.
The generic build/install instructions below also support a fresh microSD image.

## Architecture

| Function | OpenWrt implementation |
| --- | --- |
| Ethernet LAN | netifd/UCI, br-lan, 192.168.10.1/24 |
| LTE WAN | netifd modemmanager protocol, Quectel EM060K-GL, telstra.extranet, IPv4 |
| DHCP/DNS | OpenWrt dnsmasq, /etc/config/dhcp |
| Firewall/NAT | firewall4/nftables, /etc/config/firewall |
| Hotspot | netifd/wpad, router_ap, 192.168.20.1/24, AU, WPA2, client isolation |
| Settings page | Python under procd, http://192.168.10.1:8081 |
| Credentials | /etc/router-web, preserved by package conffiles/sysupgrade |
| Optional USB management | Existing gadget interface, 192.168.7.1/24, DHCP .100-.150 without gateway/DNS options |

LAN and hotspot DHCP pools initially run from .50 through .200 with 12-hour
leases. Only IPv4 forwarding to WAN is allowed. Hotspot-to-LAN/USB forwarding is
blocked; Wi-Fi clients can reach DNS, DHCP and the custom settings page, but not
SSH or LuCI. LAN permits SSH and LuCI as well. WAN has no inbound administration
rules. No IPv6 routing is configured. The custom page continues to use HTTP and
the existing authenticated API, CSRF protection and account settings.

The old systemd units, raw dnsmasq files, iptables rules and connect-lte helper
are for OpenSTLinux only. Do not install or run them on OpenWrt. netifd owns the
LTE connection, addresses and routes; do not run a second connection helper.

## Build the package/image

Use a Linux build host and the **Bootlin ST feed**, with the OpenWrt version
matching its selected release. Its currently documented openwrt-24.10 branch
uses OpenWrt v24.10.8. Follow the feed's setup instructions to install its STM32
target and ST package overrides before adding this package:

- [Bootlin feed and release instructions](https://github.com/bootlin/openwrt-feed-st)
- [Board image definitions](https://github.com/bootlin/openwrt-feed-st/blob/openwrt-24.10/target/linux/stm32/image/Makefile)
- [OpenWrt ModemManager protocol implementation](https://github.com/openwrt/packages/blob/openwrt-24.10/net/modemmanager/files/lib/netifd/proto/modemmanager.sh)

From this repository on Linux:

```sh
sh openwrt/prepare-package.sh /path/to/openwrt
cd /path/to/openwrt
make menuconfig
```

Select:

- Target System: STMicroelectronics STM32; Subtarget: STM32MP2.
- Profile: **STM32MP257F-DK-DEMO** (the DK profile also works for the source port;
  DEMO includes the documented USB-C/remote-processor support).
- Network: **stm32-lte-router** (built into the image, not just a module).
- ModemManager: **MBIM and QMI support enabled** in its configuration.
- LuCI, optionally including luci-proto-modemmanager for advanced administration.
- Keep the board profile's brcmfmac/Murata firmware and wpad packages selected.

The package selects Python, dnsmasq, firewall4, rpcd/UCI/ubus, ModemManager and
USB MBIM/QMI/serial drivers. Drivers must come from the exact target image build;
the old OpenSTLinux .ko files cannot be reused. Keep adequate root filesystem
space for Python, ModemManager and LuCI; check the resulting image size.

```sh
make defconfig
make -j"$(nproc)"
```

Record the OpenWrt and ST feed commit IDs with the build. Re-run prepare-package.sh
after changing this repository. To compile just this package in a configured
tree: `make package/stm32-lte-router/compile V=s`.

Boot the resulting **257F-DK factory image** from a spare microSD using Bootlin's
flashing instructions. Keep the working OpenSTLinux card as a fallback. A full
firmware/boot-chain change is required; installing this package on OpenSTLinux
does not convert the operating system. Do not use an EV1 or MP157 image.

## Provision on OpenWrt

Use the ST-LINK serial console for the first configuration and reboot. Discover
the names again; OpenSTLinux names end0/wwu1u1i8 are not assumed:

```sh
ip link
wifi config
uci show wireless
/etc/init.d/dbus start
/etc/init.d/modemmanager start
mmcli -L
mmcli -m 0 -J
```

Take the **modem.generic.device** sysfs path from mmcli. ModemManager's UCI
`device` is that path, not /dev/cdc-wdm0, the modem index, or the WAN network
interface. Choose the existing 2.4 GHz radio and the actual Ethernet device.
The provisioning tool keeps radio hardware/calibration options and disables
other wifi-ifaces on that selected radio. Use a fresh image: the tool replaces
the network, DHCP and firewall configurations with this router's topology.

Example only, substituting the discovered devices:

```sh
python3 /usr/lib/router-web/provision.py \
  --lan-device eth0 --radio radio0 \
  --modem-device /sys/devices/REPLACE_WITH_ACTUAL_MODEM_PATH \
  --output /tmp/router-preview
```

The default mode writes root-only candidates without changing active config.
Inspect network/dhcp/firewall in that directory. Wireless contains the generated
key: do not publish it. To install, run the same arguments with **--install** and
a new output directory, for example `/tmp/router-install`. Existing UCI edits
must first be applied or reverted. Installation backs up to
`/etc/router-web/before-openwrt`, validates UCI and `fw4 check`, and restores the
old files on failure. It refuses to overwrite an existing backup. Installation
does not restart active networking; finish from the console:

```sh
passwd
/etc/init.d/dbus enable
/etc/init.d/modemmanager enable
/etc/init.d/network enable
/etc/init.d/dnsmasq enable
/etc/init.d/firewall enable
/etc/init.d/router-web enable
reboot
```

The web service is gated on `/etc/router-web/configured`; simply installing the
package does not provision or start a router. The first web login remains
**admin/admin**, following the existing project convention. Change it through
Account after signing in. To preserve the old login, securely copy its
`/var/lib/router-web/credentials.json` to `/etc/router-web/credentials.json`
before provisioning, with the directory mode 0700 and file mode 0600.
Provisioning does not overwrite an existing credential file. Wi-Fi gets a new
generated password at `/etc/router-web/initial-wifi-password`; change it in the
page if desired. LuCI/SSH use the separate OpenWrt root password.

Add `--usb-device usb0` only if that gadget device actually exists in the new
image. This assigns its management address but does not create a USB gadget or
configure its kernel/UDC support. USB DHCP supplies .100-.150 without a default
gateway or DNS server; a static host address such as 192.168.7.2/24 also works.
Without it, recover through serial. Keep the
USB Type-C port's host/device role consistent with the physical modem setup.

## Validation and recovery

After reboot, connect an isolated Ethernet client and verify:

1. A 192.168.10.50-200 lease, DNS resolution and Internet traffic over LTE.
2. `ifstatus wan`, `mmcli -L`, and `logread` show a connected modem.
3. `fw4 check` and `nft list table inet fw4` succeed; WAN input is rejected.
4. http://192.168.10.1:8081 supports login, status, DHCP/DNS and Wi-Fi changes.
5. Wi-Fi clients receive 192.168.20.50-200 and can use LTE and the settings page,
   but cannot access Ethernet/USB clients or SSH/LuCI on the router.
6. Disconnect/reconnect the modem and power-cycle the board; confirm recovery,
   DHCP, firewall, settings persistence and credentials. Re-run throughput tests.

Do not simultaneously edit DHCP/Wi-Fi through LuCI/SSH and the custom page. The
page rejects pending UCI changes and restores its last committed config when a
service activation fails. It manages a fixed topology and whole-hour lease
times; arbitrary LuCI topology changes are outside its supported UI schema.
Backups from page changes are `/etc/router-web/dhcp.previous` and
`/etc/router-web/wireless.previous` (the latter contains a key).

To restore the configuration from before provisioning, use serial:

```sh
/etc/init.d/router-web stop
/etc/init.d/router-web disable
cp /etc/router-web/before-openwrt/network /etc/config/network
cp /etc/router-web/before-openwrt/dhcp /etc/config/dhcp
cp /etc/router-web/before-openwrt/firewall /etc/config/firewall
cp /etc/router-web/before-openwrt/wireless /etc/config/wireless
reboot
```

This restores OpenWrt's previous configuration. To restore the former operating
system, power down and boot the saved OpenSTLinux card instead.

Local checks: `python3 -m unittest discover -s web -p 'test_*.py'`,
`node --check web/app.js`, and shell syntax checks of the package scripts.
On 2026-09-29, all 22 Python tests passed, JavaScript/shell syntax checks passed,
and prepare-package.sh successfully staged the sources into a temporary build-tree
fixture. This fixture is not an SDK and does not compile firmware.
Mocked UCI/procd tests establish adapter behavior, not target driver support or
actual routing. The later eMMC deployment used Bootlin's prebuilt kernel plus
matching target packages and the architecture-independent application IPK.
Its hardware checks are recorded separately in the board flash record.

For the Python/static-asset application alone, a Linux cross compiler is not
required: `python3 openwrt/build-ipk.py stm32-lte-router_1.0.0-r1_all.ipk`
creates an installable IPK. Install it only on OpenWrt with the matching firmware
package feeds configured, then provision and enable the service as above.
