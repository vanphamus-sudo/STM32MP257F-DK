# OpenWrt eMMC deployment — 2026-09-29

**Current layout (2026-10-29):** the kit now has [eMMC A/B root slots and r17](ab-flash-status.md).
The earlier partition table and deployment observations below are historical.

## Router application update — 2026-10-28

Installed `stm32-lte-router` **1.0.0-r13** over USB SSH at `192.168.7.1`.
The release adds Ethernet LAN, WAN (DHCP), and LAN/WAN VLAN trunk controls.
The board kernel already provides 802.1Q support. Existing network, firewall,
DHCP, Wi-Fi, VPN and application settings were verified unchanged by SHA-256.
Ethernet remains LAN on `eth0`; LTE WAN reports up. The running web and AT
services were restarted and verified; the previously stopped serial service
remains stopped. No reboot or Ethernet role change was performed.

The new HTML and JavaScript are served at `http://192.168.10.1:8081`;
unauthenticated Ethernet API access returns 401. Firewall validation passed.
VLAN traffic still requires a managed-switch hardware test.

Backup: `/root/router-before-ethernet-r13-20261028/config-and-app.tar.gz`.
Local package: `local/stm32-lte-router_1.0.0-r13_all.ipk`.

The STM32MP257F-DK now boots OpenWrt 24.10.8 (`r29233-443ec4032a`),
Linux 6.6.144, from onboard eMMC. This deployment uses Bootlin's ST prebuilt
firmware with matching packages and the project's router application; it is
not a locally compiled full firmware image.

## Access and networking

On 2026-10-02, persistent IPv4 ICMP echo-request input rules were added for
WAN and hotspot. Firewall syntax validation and reload passed; the WAN input
policy remains REJECT for other unsolicited traffic. USB ping passed (2/2),
and public IPv4 ping from the development PC passed (3/3); the WAN echo rule
recorded incoming traffic. The firewall before this change is backed up at
`/etc/router-web/firewall.before-ping-20261002`. Provisioning templates include
the same rules, and all 28 local tests passed.

- Wi-Fi: `STM32-LTE`, existing password retained, channel 6, Australia.
- Router settings: **http://192.168.10.1:8081**, existing login retained.
  Connect to the hotspot to access this address.
- LTE: Quectel EM060K-GL, Telstra APN `telstra.extranet`, managed by
  ModemManager/netifd and automatically connected at startup.
- Ethernet: `192.168.10.1/24`; **DHCP enabled** (`dhcp.lan.ignore=0`) at the
  user's subsequent request. Pool: `192.168.10.50`–`192.168.10.200`, lease 12 hours.
  dnsmasq was restarted and its active Ethernet pool verified. The user previously
  identified this connection as an existing home/office network; competing DHCP
  offers are possible while both routers share that network.
- Hotspot: `192.168.20.1/24`, DHCP enabled, IPv4 forwarding/NAT to LTE.
- USB management: `192.168.7.1/24`, SSH, DHCP without a default gateway or DNS
  advertisement. Windows received `192.168.7.114` during validation.
- Hotspot clients can access the settings page, but cannot forward to the
  Ethernet or USB networks. WAN administration is blocked.

## Installed layout and recovery

The standard Bootlin factory image targets SD boot. Its bootloader was not
written over this board's working eMMC boot chain. Existing TF-A, FIP, U-Boot,
OP-TEE and GPT were retained.

| eMMC partition | Use after deployment |
| --- | --- |
| p6 | Existing bootfs, with new `/openwrt/Image.gz` and DK DTB |
| p7 | Existing vendorfs retained |
| p8 | Existing OpenSTLinux root retained for recovery |
| p9 | OpenWrt ext4 root, replacing the former userfs |

The former userfs was backed up and restored into p8's underlying `/usr/local`.
OpenSTLinux's mount helper was adjusted to stop mounting p9 over that directory.
Its original helper remains in `/opt/openwrt-stage/mount-partitions.original.sh`
on p8.

The bootfs `/mmc1_extlinux/extlinux.conf` offers `OpenWrt` (default) and
`OpenSTLinux recovery`. Use the serial console, COM6 at 115200 8N1, to select
the recovery entry during boot. OpenSTLinux uses its retained kernel and p8
root. **The recovery entry is retained but has not been boot-tested.**

Stock SD-card sysupgrade is disabled in `/lib/upgrade/platform.sh`, including
the forced upgrade path, because its partition assumptions do not match this
eMMC layout. Do not use LuCI or `sysupgrade` to install a standard SD image.
The [signed remote updater](remote-updates.md) now implements an A/B OS update
path. It requires separately provisioned slots, staging storage and verified boot
fallback; this recorded eMMC deployment has not been converted or boot-tested
with that path.

## Validation

- Verified the full 512 MiB p9 write by SHA-256 readback before changing boot
  selection: `fad6b30397e62a055698966d664e62d8a5b6c8a2785be24eb155ffc19e06005c`.
- Two successful OpenWrt boots; LTE reconnected and the settings service and
  hotspot started automatically after reboot.
- Board Internet checks passed: ping, DNS and HTTPS over LTE.
- Authenticated settings API, DHCP/DNS apply, Wi-Fi apply and logout passed;
  unauthenticated status returned 401 and status responses omitted Wi-Fi keys.
- Firewall4 rules passed nftables validation. Final Ethernet DHCP setting
  was committed and verified as disabled after the user's network clarification.
- 22 local Python tests passed; JavaScript and shell syntax checks passed.
- Physical Ethernet/Wi-Fi client Internet forwarding was not tested during
  this deployment; board connectivity and service checks do not establish it.

Serial records: `logs/openwrt-first-boot.log`,
`logs/openwrt-serial-status.log`, `logs/openwrt-reboot-validation.log`.

## Local backups

Private artifacts are in ignored directory `local/openwrt-flash/`. Configuration
archives contain credentials and should remain private.

| File | Contents |
| --- | --- |
| `router-before-openwrt.tar.gz` | Previous configuration, application and boot files |
| `usr-local-backup.tar.gz` | Complete former userfs files |
| `router-openwrt-emmc-rootfs.img.gz` | Prepared root image before first boot and final provisioning |
| `router-openwrt-config-after-flash.tar.gz` | Final `/etc`, router application and eMMC upgrade guard |
| `extlinux-openwrt.conf` | Installed boot menu |

The configuration archive predates the subsequent Ethernet DHCP enablement.
Configuration archive SHA-256:
`dd05504721581337bce5a1c58cf881fe44b3e042f680d5bf4ad686ff200b0177`.
These are file and partition backups, not a full raw eMMC clone.

Firmware source: [Bootlin ST OpenWrt release](https://bootlin.com/pub/openwrt-st/openstlinux-6.6-openwrt-24.10.8-mpu-v26.02.18/openwrt-stm32-stm32mp2-factory-images.tar.gz).
Downloaded factory archive SHA-256:
`01c5b916de767cf3e88d2699064c9823601ce96a2ae9039710ef9ab4d6b13a40`.
