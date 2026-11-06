# Current OpenWrt installation copied to CN6 SD

On 2026-10-26 the user authorized replacing the 58.2 GiB SDXC card in CN6
(CID `0034323030303030000000066a01928a`) with a bootable copy of the current
eMMC OpenWrt system. The source is OpenWrt 24.10.8, Linux 6.6.144.

The copy uses the locally retained Bootlin STM32MP257F-DK factory image's
SD bootloader, FIP and partition layout. It copies the currently installed
kernel and DTB from eMMC bootfs and takes a frozen, consistent snapshot of
the current 512 MiB root filesystem. This preserves installed applications,
network settings, VPN material, credentials and SSH identity. Secrets are
not included in this document.

The SD has a unique GPT disk GUID, unique partition GUIDs and a separate
root filesystem UUID. Partition 5 grows to fill the card. The SD boot menu
uses its own root PARTUUID, avoiding selection of the eMMC root filesystem.
Both `/extlinux/extlinux.conf` and `/mmc0_extlinux/extlinux.conf` on the SD
boot partition select the SD root. The original eMMC boot selection is retained.

Preparation script: `local/clone-current-to-sd.py`. A continuation script,
`local/resume-sd-clone.py`, handled asynchronous creation of partition device
nodes on the first run; the main script now waits for those nodes.

Validation includes root copy SHA-256 readback, ext4 filesystem checks,
kernel/DTB comparison, and comparison of core settings and web credentials.
Actual SD boot must still be verified on the board after changing physical
boot switches.

Preparation completed successfully. Final read-only filesystem check passed;
the expanded root reports 57.5 GiB total and 57.3 GiB available.
SD root PARTUUID: `505848ac-a30f-4134-a2d3-f94a9bcad6ec`.
Snapshot SHA-256: `c7814847bb7bc308ee96330dcd7e279d3ece6bd3212a4bf20acd7df8cad0ef56`.
The resize required a metadata correction followed by a clean check.
`logs/sd-clone-20261026.log` records the initial resize check; final successful
checks and boot configuration were verified separately.

SD boot was confirmed live on 2026-10-26 after changing the physical switches.
The running kernel command line selects the SD root PARTUUID above, the
root filesystem reports 57.5 GiB, and the card CID matches the approved SD.
The router web application and its serial/AT Python services are running.

For Cortex-A35 SD boot, power off and set BOOT[3:0] to `0001`:
BOOT0=1 and BOOT1=BOOT2=BOOT3=0. SW1 controls BOOT0/1; SW2 controls BOOT2/3.
Follow the board's 0/1 markings. eMMC boot is BOOT[3:0]=`0010`.
See ST UM3385 sections 7.8 and 8.3.

After SD boot, verify `/proc/cmdline` matches `/etc/sd-clone.json`, `/` is
backed by the SD partition, filesystem capacity is approximately 58 GiB,
and the router application, network and configured services start.
The retained stock-sysupgrade guard remains in the copied system.
