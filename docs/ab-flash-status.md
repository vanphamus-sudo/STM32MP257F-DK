# Dev kit A/B eMMC deployment — 29 October 2026

**Later application update:** both slots now have [r18 telemetry and traffic accounting](mqtt-telemetry.md).
The A/B layout and committed OS generation below are unchanged.

The connected STM32MP257F-DK is prepared for A/B OS updates and has router
application **1.0.0-r17** installed in both root slots. **Slot A is active and
confirmed**; slot B is the tested standby. Linux remains **6.6.144**, OpenWrt
**24.10.8**. No SD card was present during preparation.

Settings page: **http://192.168.10.1:8081**. MQTT and remote update controls are
present. Remote downloads remain disabled until a production signing public key
and allowed update host are configured on the webpage. No production signing
private key was copied to the kit.

## Installed structure

Linux MMC names changed between resets (`mmcblk0`, `mmcblk1`, `mmcblk2`). GPT
partition UUIDs identify storage; these Linux names must not be hard-coded.
U-Boot's eMMC boot filesystem is **MMC 1:6** on this kit.

| eMMC partition | Role | Partition capacity |
| --- | --- | --- |
| p1–p5 | Existing boot metadata, FIP and redundant U-Boot environment | Retained |
| p6 | Shared bootfs, original boot files and `/router-slots/A`, `/router-slots/B` | 64 MiB |
| p7 | Existing vendorfs | Retained |
| p8 | Existing OpenSTLinux recovery filesystem | 3 GiB, retained |
| p9 | Router root A | 768 MiB |
| p10 | Router root B | 768 MiB |
| p11 | Shared ext4 update staging and immutable image cache | 2,646,081,536 bytes, about 2.46 GiB |

Both root filesystems currently occupy 512 MiB within their 768 MiB slots. The
profile permits root images up to 768 MiB. Staging had **1,836,974,080 free bytes**
after the final checks and the 512 MiB baseline cache. It mounts automatically at
`/mnt/update-storage`, separately from either root.

| Identity | PARTUUID |
| --- | --- |
| Bootfs | `5efa9b5d-f64d-4578-a34d-17fcbad8d7a3` |
| U-Boot environment | `3a69dfb9-866b-48cb-82d0-9117024eb19d` |
| Root A | `1376b394-4b0e-4cb4-a1e4-3b87b697588e` |
| Root B | `dccbb865-b073-4a95-ab9b-83b938113fce` |
| Update staging | `b6b97f22-655f-43c2-92fe-81b43d35254c` |

The former oversized p9 was split without moving its start or changing its UUID.
Its existing 512 MiB filesystem fit entirely within the new A partition. GPT
entries p1–p8 were preserved. No boot firmware or recovery filesystem was flashed.
Both GPT copies were checksummed, written and read back before rebooting.

## Boot configuration

`/etc/router-web/system-slots.json` records the UUIDs, image limit, staging path,
health interfaces (`lan`, `wan`) and tested boot/watchdog flags. The early
`09_router_storage` hook creates a UUID-based environment-device link; the
`router-storage` startup service mounts staging before router services start.

The CRC-verified redundant environment records are the final two 8 KiB records
in the existing environment partition: offsets **0x7e000** and **0x7c000**.
`/etc/fw_env.config` addresses that partition through
`/dev/disk/by-partuuid/3a69dfb9-866b-48cb-82d0-9117024eb19d`. Native fw_setenv writes
were verified by U-Boot reading the saved probe after reset.

The boot hook selects `/router-slots/${router_slot}/extlinux.conf`, persists trial
attempts, and returns to `router_previous` when attempts expire. A normal system
update grants three attempts. Boot confirmation checks the webpage and LAN/WAN
interfaces before clearing the trial flag and committing the generation/cache.
Final state: `router_slot=A`, `router_trial=0`, generation **1**.
The next OS release for this kit must therefore use generation **2 or higher**.

The original boot environment is backed up on bootfs at
`/router-slots/original-u-boot-environment.txt`. The original
`/mmc1_extlinux/extlinux.conf` and OpenSTLinux recovery boot files remain. From
the serial U-Boot prompt, `run bootcmd_stm32mp` invokes the original boot scan/menu.
The retained OpenSTLinux recovery OS itself was not boot-tested in this session.

## Hardware validation completed

- Booted A and B, then finalized r17 on both. Verified the active root by block
  identity and the installed version in the inactive root.
- Stopped watchdog feeding with the source filesystem read-only. Serial captured
  the secure watchdog panic and **IWDG system reset**. U-Boot then reported its
  watchdog servicing and booted normally.
- Verified an actual three-attempt trial decremented from 3 to 2 on B's first boot.
  Separately tested the exhausted-attempt path with one final attempt at an absent
  test entry. U-Boot reset and automatically selected known-good B, clearing the
  trial flag. Neither real slot was damaged by that test.
- Ran a genuinely signed, local **reuse-only delta rehearsal** through the native
  system installer. It reconstructed the known baseline, wrote/read back inactive
  A, staged the matching kernel/DTB, rebooted, passed health checks and committed
  generation 1. The 1,011-byte test artifact reused existing images; this is not a
  size claim for a changed OS release. Its test key was not installed as a trusted
  production key. The application was finalized at r17 after the baseline test.
- Confirmed authenticated `/api/status` reports r17 and the ready A/B profile;
  anonymous status returns 401. Main page, MQTT and update assets return 200.
- Confirmed AT TCP `AT$VERSION` reports r17, firewall validation passes, LTE WAN
  and the Wi-Fi hotspot are up, and all **40** pre-existing configuration files
  checked retain their original SHA-256 hashes.
- Offline suite: 118 tests run, five Windows-inapplicable Linux serial tests
  skipped. Desktop and mobile MQTT/update form tests passed.

The signed rehearsal exercised local verification/install/reboot/confirmation,
not HTTPS hosting or MQTT delivery. Those require the user's server/broker and
production signing configuration. No physical power-cut or cold-power-cycle test
was performed.

## Backups and artifacts

Private backups and machine-readable verification records are under ignored local
directory `local/ab-preparation-20261029/`. They include both original GPT regions,
the original environment partition, bootfs, settings/application archive and a
consistent compressed root filesystem snapshot. These contain credentials and
must remain private.

Original uncompressed root snapshot SHA-256:
`53085f92d44414c5246fbefcf5de64f99e6dc9d27d1f0752704752d9209a0934`.
The compressed copy transferred to the PC was decompressed and hash-verified.

Installed package: `local/stm32-lte-router_1.0.0-r17_all.ipk`.
Serial evidence is in `logs/ab-partition-watchdog-boot.log`,
`logs/ab-slot-a-first-boot.log`, `logs/ab-slot-b-first-boot.log`,
`logs/ab-failed-trial-fallback.log` and `logs/ab-signed-delta-install-boot.log`.

Preparation scripts: `scripts/prepare-kit-ab.py` and
`scripts/initialize-ab-slot.py`. Both default to read-only validation. The first
is pinned to this kit's former exact layout and deliberately refuses to run again
on the new layout; the second refuses to overwrite an inactive filesystem.

For future releases, use the [remote update guide](remote-updates.md). The initial
image cache is a private kit snapshot; use a full, sanitized signed OS release
before distributing later deltas publicly.
