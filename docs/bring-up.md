# Bring up the first router prototype

## Current router activation (2026-09-24)

The board now uses systemd-networkd for Ethernet `end0` at `192.168.10.1/24`
and USB management `usb0` at `192.168.7.1/24`. dnsmasq serves Ethernet addresses
`192.168.10.50–200`, advertising `192.168.10.1` as gateway and DNS. Connect end0
only to an isolated test PC or LAN. USB retains its original networkd DHCP server.

The installed kernel has no nftables IPv4/inet support. Active filtering and NAT
use `config/router-iptables.rules` and `config/router-ip6tables.rules`, installed
through `router-firewall.service`. IPv4 forwarding is enabled only after both
firewall families load. IPv6 forwarding is blocked. NetworkManager remains masked;
LTE uses ModemManager and the bearer-aware helper. The older nftables and
NetworkManager instructions below are historical and do not describe this deployment.

`scripts/activate-router.sh` records backups under
`/var/lib/router/backup-before-activation` and initially arms a five-minute rollback.
That timer was cancelled after services and USB management were verified. Manual
rollback on the board is `sh /usr/local/lib/router/rollback.sh`. This restores
Ethernet DHCP-client configuration, previous firewall rules and forwarding, and
stops/masks dnsmasq. Reconnect Ethernet to the upstream network after rollback.

The test client received `192.168.10.119`; DHCP exchange, DNS requests, NAT and
bidirectional LTE forwarding were observed. Browser confirmation remains pending.
Boot services have not been enabled: automatic approval review rejected execution
of `scripts/enable-router-startup.sh` pending explicit approval for persistent
firewall/DHCP startup and recurring LTE reconnection. The LAN address file itself
is persistent, so the current setup is not yet a complete reboot-ready router.
`config/router-lte.service` and `.timer` are staged. No reboot was performed.

LTE is now connected and tested on Telstra using `telstra.extranet`. The current
ST NetworkManager build lacks its WWAN plugin, so the working path is direct
ModemManager plus the bearer-aware `scripts/connect-lte.py` helper. Run on the board:

```sh
sh /usr/local/src/router-drivers/connect-lte.sh
resolvectl query -i wwu1u1i8 example.com
curl -4 --interface wwu1u1i8 https://example.com
```

The helper derives IPv4 address, gateway and DNS from the actual data bearer;
it does not assume fixed carrier addresses. It handles static IPv4 MBIM settings,
leaves Ethernet/USB with networkd, and gives LTE metric 700 so Ethernet remains
preferred while connected. It is not yet an automatic boot/reconnect service.
NetworkManager, dnsmasq and nftables remain masked/inactive. The NetworkManager
instructions later in this guide require a build containing its WWAN plugin.

Driver update: QMI/MBIM/WDM modules have now been built for kernel 6.6.129 and
installed successfully. ModemManager recognizes EM060K-GL using cdc_mbim, with
control port `/dev/cdc-wdm0` and data interface `wwu1u1i8`. The earlier driver
blocker below is resolved. LTE activation/data testing is the next step, subject
to the user's instruction to keep NetworkManager/DHCP/firewall inactive until
configured and tested. See `drivers/modem/README.md` for build and rollback notes.

Latest progress: router packages are installed and dpkg audit is clean. NetworkManager,
dnsmasq and nftables are masked/inactive as requested. NetworkManager is configured
to leave end0, usb0 and wlan0 unmanaged; systemd-networkd remains in control.
NetworkManager and dnsmasq also have staging ConditionPathExists drop-ins at
`/etc/systemd/system/<service>.service.d/90-router-staging.conf`; remove these only
when the tested configuration is ready for activation. Ethernet currently provides
Internet access at 192.168.40.102, not the isolated router LAN.

The EM060K-GL is physically detected (2c7c:030b) but LTE is not ready: the installed
kernel lacks USB QMI/MBIM/WDM support and the ST feed does not supply these modules.
Resolve that prerequisite before attempting the connection commands below.

Current verified state: eMMC installation and Linux boot succeeded. COM6 is the
Linux console; USB management is 192.168.7.1 and Ethernet LAN is `end0`.
The board currently uses systemd-networkd and has apt, but no default Internet
route or installed nmcli/mmcli/nft/dnsmasq commands. The historical initial setup
below is retained for reference. Replace `eth0` with `end0` in example commands.
Do not migrate network management until package availability is established;
preserve the working systemd-networkd USB management connection.

## 1. Establish Linux access

The PC currently sees the ST-Link on COM6 and COM7. ST-Link presence alone does
not establish that the application processor has booted Linux.

Current hardware state: no screen and no microSD inserted. A display is optional;
serial access is sufficient. The board can boot from microSD or eMMC, but an eMMC
installation has not been established. ST recommends microSD for initial use.
Use the board-specific [STM32MP25 Discovery Starter Package guide](https://wiki.st.com/stm32mpu/wiki/STM32MP25_Discovery_kits_-_Starter_Package)
to prepare OpenSTLinux media, and the [DK hardware guide](https://wiki.st.com/stm32mpu/wiki/STM32MP257x-DKx_-_hardware_description)
for boot-source selection. Identify the card and its contents before programming;
flashing replaces data on the selected medium. Do not use an EV1 board flash layout.

### Without a microSD card: onboard eMMC

For this project the user has no microSD, so use the onboard 8 GB eMMC.
STM32CubeProgrammer is already installed on this PC under
`C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin`.

The ST-Link connection on CN21 is for power/debug/serial. USB flashing uses the
processor USB connection on CN15, requiring a USB data cable to the PC while
maintaining suitable board power. Before changing switches, power off the board
and record their original positions. UM3385 tables 4-5 specify logical boot pins:

| Mode | BOOT0 | BOOT1 | BOOT2 | BOOT3 |
| --- | --- | --- | --- | --- |
| Forced USB programming | 0 | 0 | 0 | 0 |
| Cortex-A35 eMMC boot | 0 | 1 | 0 | 0 |

BOOT0/1 are on SW1; BOOT2/3 are on SW2. Follow the board markings and the manual's
switch illustration rather than inferring physical switch direction from this table.
First establish USB DFU detection without writing flash. Then obtain and inspect
the matching OpenSTLinux Starter Package's STM32MP257F-DK eMMC flash layout and
all referenced images. Programming will replace existing eMMC data, so confirm
the target and whether anything needs preserving before starting the write.
After successful programming, power down, select eMMC boot, and capture the
serial console on the next boot. No display is needed.

From PowerShell in this project:

```powershell
.\scripts\windows\Read-BoardConsole.ps1 -Port COM6 -Seconds 30 -SendEnter
```

Close other terminal programs using that port first. If there is no prompt, verify
the power LEDs, suitable power supply, boot switches and bootable OpenSTLinux media
against UM3385. A passive capture without `-SendEnter` can record a normal boot.
Use an interactive serial terminal at 115200, 8 data bits, no parity, 1 stop bit,
no flow control to log in. COM7 is the second virtual port; its presence does not
mean it is the Linux console. Do not flash or change boot switches until the
existing boot setup is identified.

On the board collect:

```sh
cat /etc/os-release
ip -brief address
ip route
systemctl is-active NetworkManager systemd-networkd
```

Once SSH is reachable, copy the project scripts/config directory with scp or your
usual transfer tool and run `sh scripts/board-status.sh` on the board. No Windows
cross compiler is needed for these configuration and shell files. A full Yocto
image build needs a supported Linux build host for your selected ST release.

## 2. Confirm the target stack

Required: `ip`, `nmcli`, `mmcli`, `nft`, `dnsmasq`; services: NetworkManager,
ModemManager and D-Bus. Install through the image's supported package feed, if one
exists, or add the packages to a matching OpenSTLinux build. Do not assume apt is
available. `yocto/router-packages.inc` is a starting selection, not a build result.

This prototype uses NetworkManager for LAN addressing and LTE host IP setup.
Check existing network ownership before adopting it: systemd-networkd and
NetworkManager must not both configure the same interface. Do not globally
disable the current manager while connected through it.

ModemManager establishes the bearer; NetworkManager applies bearer addresses,
routes and DNS. `mmcli --simple-connect` plus `ip link set up` is insufficient
for a general modem. NetworkManager also handles connection activation retries;
a custom reconnect daemon is unnecessary at this stage.

## 3. Prepare isolated LAN and LTE profiles

Use a working serial console for network changes. Connect the Ethernet LAN to a
test client or isolated switch: running a DHCP server on an existing office/home
LAN would conflict with its router. Confirm 192.168.10.0/24 does not overlap.
Keep the client's other network connections off during the routing test.

Selected hardware is a Quectel EM060K-GL with a Telstra SIM and user-supplied APN
`telstra.extranet`. Connect the modem through a compatible USB carrier with SIM,
antennas and suitable power to the board's USB host. Verify enumeration with
`lsusb`, then `mmcli -L`; USB composition and driver support must be checked on
the installed BSP before choosing QMI or MBIM. Do not change modem firmware or
USB composition as an initial troubleshooting step.

Adapt the following commands to the actual Ethernet interface. These create
profiles with autoconnect disabled, so activation remains an explicit next step.

```sh
nmcli device status
mmcli -L
nmcli connection add type ethernet ifname eth0 con-name router-lan \
  connection.autoconnect no ipv4.method manual \
  ipv4.addresses 192.168.10.1/24 ipv4.never-default yes ipv6.method disabled
nmcli connection add type gsm ifname '*' con-name router-lte \
  connection.autoconnect no gsm.apn telstra.extranet ipv4.method auto ipv6.method disabled
```

For a SIM PIN or credentials, use `nmcli --ask connection up router-lte` rather
than committing secrets to this project. LTE use requires your active data plan.
After activation inspect `nmcli device status` and `ip -brief address` to identify
the real WAN data interface. Do not assume it is wwan0 or that its address is public.

## 4. Validate and activate the router

Save the current network profiles, dnsmasq configuration, firewall and forwarding
value before changes. Record their original state for recovery. Retain a serial
console: the example firewall intentionally does not allow SSH from an unspecified
USB management interface. Add a narrowly scoped management rule if needed.

Edit both config files for the discovered interfaces. Review the existing
`nft list ruleset`: other base chains/firewall managers can still drop packets
accepted by these project tables. Do not run competing firewall managers.

```sh
nft -c -f config/router.nft
dnsmasq --test --conf-file=config/dnsmasq-router.conf
```

These checks require the target tools and kernel support. For the first session,
apply the firewall once (it has no global flush), activate LAN, then forwarding:

```sh
nft -f config/router.nft
nmcli connection up router-lan
sysctl -w net.ipv4.ip_forward=1
```

Ensure no existing DHCP/DNS service already owns the LAN or the same listening
ports. Start dnsmasq in a separate console for this temporary test:

```sh
dnsmasq --keep-in-foreground --conf-file=config/dnsmasq-router.conf
```

Activate `router-lte` with `nmcli --ask connection up router-lte`. Confirm its
address, default route and DNS with `nmcli device show` and `ip route`. If the WAN
name differs from the template, update the firewall before enabling forwarding.
To replace existing project tables, use one nft transaction containing deletion
of those two tables followed by their replacement definitions; syntax-check first.

## 5. Acceptance checks and recovery

1. Board: LTE connection is active, WAN has an address and a usable default route.
2. Client: receives 192.168.10.50-200, gateway/DNS 192.168.10.1 through DHCP.
3. Client: reaches 192.168.10.1, an Internet IP, and a hostname.
4. Firewall: unsolicited WAN TCP/UDP services and WAN-to-LAN forwarding are blocked.
5. Reconnect the modem and confirm its data interface, routes and client access recover.

Until these pass, leave autoconnect off and do not install persistent forwarding
or firewall configuration. For later persistence, integrate with the image's
service layout so the firewall loads before forwarding and DHCP, and verify a reboot.

For temporary-test recovery, stop the foreground dnsmasq with Ctrl+C, restore the
recorded forwarding value, disconnect project profiles and reactivate the previous
LAN profile. Then remove only project tables:

```sh
nmcli connection down router-lte
nmcli connection down router-lan
nft delete table inet lte_router
nft delete table ip lte_router_nat
```

Remove the project profiles with `nmcli connection delete router-lte router-lan`
if no longer needed. Restore any original files/services changed during integration.

## References

- [ST UM3385: board connectors, power and boot configuration](https://www.st.com/resource/en/user_manual/um3385-discovery-kit-with-stm32mp257f-mpu-stmicroelectronics.pdf)
- [ModemManager: host IP configuration responsibilities](https://modemmanager.org/docs/modemmanager/ip-connectivity-setup-in-lte-modems/)
- [NetworkManager nmcli manual](https://networkmanager.dev/docs/api/latest/nmcli.html)
- [Quectel EM060K series and vendor documentation](https://www.quectel.com/product/lte-a-em060k-series/)

The physical board has one onboard Ethernet connector; a second Ethernet interface
requires additional hardware. The saved chat's eth1 example is not an onboard port.
