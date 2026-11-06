# STM32MP257F-DK router factory image

This bundle installs the router onto **blank onboard eMMC** using STM32CubeProgrammer.
It includes the USB programming firmware, eMMC TF-A/FIP boot chain, boot filesystem,
OpenWrt root filesystem, flash layout, and SHA-256 checksums. Extract the complete
ZIP before using it. A raw rootfs image alone cannot initialize a blank kit.

Status: assembled and checked offline; **not yet boot-tested on a blank kit**.
The kernel/packages and ST boot firmware were used by the previously working
router, but this factory layout and first-boot initialization are new.
This is an assembly of existing binary releases and this project's application,
not a new compilation of the kernel or OpenWrt distribution.

## Flash onboard eMMC

1. Use an STM32MP257F-DK. Connect ST-LINK CN21 for serial and processor USB CN15
   for CubeProgrammer, with stable board power. With power off, select forced USB
   programming: BOOT0=0, BOOT1=0, BOOT2=0, BOOT3=0, then power on. BOOT0/1 are on
   SW1 and BOOT2/3 on SW2; use the board markings/manual for physical orientation.
2. Open STM32CubeProgrammer, select USB, refresh, and identify the intended board.
3. Select `FlashLayout_router_emmc_stm32mp257f-dk.tsv` from the extracted folder.
   Start programming. **This replaces the eMMC partition table, boot firmware and
   filesystems. Existing eMMC data is lost.** Wait for successful completion.
4. Power off; select Cortex-A35 eMMC boot: BOOT0=0, BOOT1=1, BOOT2=0, BOOT3=0.
   Remove any bootable microSD, then power on. Monitor ST-LINK serial at 115200 8N1.

CLI equivalent, from the extracted folder, after checking the USB target:

```powershell
& 'C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe' -l usb
# Replace USB1 if your intended board has a different enumerated port.
& 'C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe' -c port=USB1 -w FlashLayout_router_emmc_stm32mp257f-dk.tsv
```

## First use

- Ethernet LAN: `192.168.10.1/24`, DHCP `.50` through `.200`. Connect an isolated
  computer or LAN; this image starts its own DHCP server.
- Settings: **http://192.168.10.1:8081**, initial login **admin / admin**.
  Change the password in Account after signing in.
- Wi-Fi: **STM32-LTE**, Australia, channel 6, WPA2, subnet `192.168.20.0/24`.
  Each kit generates its own Wi-Fi password on first boot. Read it on serial:
  `cat /etc/router-web/initial-wifi-password`, or change it through the Ethernet
  settings page. Client isolation and LTE NAT are enabled.
- LTE: attach one Quectel EM060K-GL with a working Telstra SIM. APN defaults to
  `telstra.extranet`, IPv4, roaming disabled. ModemManager starts automatically;
  a background service discovers the modem's actual USB path, including after
  unplug/replug. Other carriers require changing `network.wan.apn` using UCI/LuCI.
- USB management: `192.168.7.1/24`, DHCP `.100` through `.150`, no advertised
  default route. Serial number and locally administered MACs derive from each kit.
- Set a root password using `passwd` on serial. SSH/LuCI use the separate root
  account. The web account is independent. No previous board keys or login hashes
  are included; SSH host keys are generated on the new kit.

If Wi-Fi hardware is not detected during initialization, its uci-defaults script
remains for retry on the next boot. Inspect `logread`, then reboot. The web service
starts only after first-boot initialization succeeds.

## Storage and checks

The standard ST eMMC partition offsets are retained: p6 bootfs, p7 empty vendorfs,
p8 OpenWrt rootfs, p9 empty userfs. The root filesystem is 512 MiB; unused partition
capacity is not automatically expanded. There is no OpenSTLinux recovery OS.
Stock SD-card sysupgrade is disabled; reflash this complete bundle for recovery.
[Remote OS updates](remote-updates.md) require separate A/B provisioning and boot tests.
Do not write these images using LuCI's stock firmware upgrade page.

`SHA256SUMS` covers every bundle payload. `validation.json` records ext4 filesystem
checks, source versions, sanitization, and the hardware test limitation.
Before deploying, validate a cold boot, Ethernet/Wi-Fi client DHCP and LTE traffic,
settings login, modem reconnect, and persistence across another power cycle.

Source firmware: [Bootlin ST OpenWrt feed](https://github.com/bootlin/openwrt-feed-st)
and the locally retained ST OpenSTLinux v26.06.10 starter package. Rebuild from the
project root with Python 3: `python openwrt/build-factory.py`. This requires the
saved artifacts in `local/openwrt-flash`, extracted ST release, and portable
e2fsprogs in `local/image-tools`.
