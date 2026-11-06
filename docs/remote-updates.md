# Signed remote application and OS updates

Release `1.0.0-r17` provides **System → Remote updates** on the authenticated router
webpage. Application and OS/kernel releases use the same HTTPS download and
signature verification path, from either the webpage or MQTT.

**Dev kit status:** r17 is installed in both eMMC A/B slots. Both slots, hardware
watchdog reset, failed-trial fallback and a signed local delta installation have
been verified. See [the current deployment record](ab-flash-status.md). Other
boards and the factory bundle still require their own A/B provisioning and tests.

## Two update types

| Type | Contents | Installation |
| --- | --- | --- |
| Application | Router Python services, webpage and application startup scripts | Reconstruct an IPK, back up the installed application, install with opkg, restart previously running services and check health. On an install/health failure, attempt to reinstall the backup. OS, kernel and network configuration are preserved. |
| System | Matching ext4 rootfs, gzip ARM64 kernel and STM32MP257F-DK DTB | Reconstruct images, check hashes/ext4 and the board DTB, write/read back the inactive root partition, preserve configuration/identity, stage boot files, then reboot into a bounded boot trial. Bootloader/TF-A/FIP and partition tables are preserved. |

Application rollback is a recovery attempt after a reported failure, not a
power-fail-safe A/B installation. Its last backup remains at
`/etc/router-web/update-state/rollback.ipk`. If power fails during opkg writes,
recover using serial/SSH and that backup or the retained OS recovery path.

The system updater requires an explicitly provisioned A/B profile. It never
uses stock `sysupgrade` or writes the active root partition. OpenWrt's upgrade
behavior is [platform-specific](https://openwrt.org/docs/techref/sysupgrade);
this project's custom eMMC layout deliberately blocks the stock path.

## Configure the webpage

First install the current application IPK and matching OpenWrt dependencies, then
restart the router-web service. The package dependencies include Paho, OpenSSL,
blkid, e2fsprogs/tune2fs and U-Boot environment tools. Existing factory base
images do not automatically gain new dependency packages merely by copying
application files; include them when assembling an OS release.

1. Generate an RSA signing key on the release/build machine. Keep the private
   key off routers and download servers. Example:

   ```sh
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out signing-private.pem
   openssl pkey -in signing-private.pem -pubout -out signing-public.pem
   ```

2. In **System → Remote updates**, paste the **public** key and enter allowed
   download hostnames, one per line. Include any redirect/CDN destinations.
3. Enable remote updates and save. This enables requests from both the webpage
   and MQTT. HTTPS certificate verification is always enabled for downloads,
   independently of the MQTT transport setting.
4. Enter the URL of a signed `.rupdate` file and click **Install signed update**.
   Progress and the final result appear in the panel. Application installation
   briefly restarts the page. A system installation reboots the router.

Only HTTPS port 443 is allowed. URLs with userinfo/fragments, unlisted hosts,
HTTP downgrade redirects or redirects to unlisted hosts are rejected. The signed
download is limited to 256 MiB, with a five-minute download budget and 15-second
socket timeout. The release signer is the trust authority; valid signatures
authorize executable application/OS code.

Settings are stored under `/etc/router-web/update.json`. A wrong signature,
unsupported target, missing/mismatched delta base or downgrade aborts before an
application installation or root partition write. Supply a full bundle if a
delta base is unavailable. No automatic full-image download is attempted.

## Build the smallest applicable application bundle

```sh
python3 openwrt/build-ipk.py local/router-r15.ipk
python3 openwrt/build-update.py local/router-r15.ipk local/router-r15.rupdate --base local/router-r14.ipk --private-key signing-private.pem
```

Use actual versioned IPK paths from your build. Omit `--base` for a full bundle.
Application bundles omit unchanged files. For changed files, the builder chooses
between compressed replacement and a copy/literal delta, accounting for delta
metadata overhead. Text matching uses lines; binary matching uses blocks.
The device verifies every reused base and reconstructed target file by SHA-256.
Locally edited application files may therefore require a full bundle.

The signed target is an allowlisted, script-free `stm32-lte-router` package.
Maintainer scripts and writes outside its application/service paths are rejected.
The target package version must compare newer according to opkg. Network settings,
web credentials, MQTT credentials, VPN material and signing configuration are not
distributed in application bundles.

## Prepare A/B system updates once

This is a hardware/storage provisioning task; a webpage setting cannot safely
invent partition offsets. Prepare and back up the board from a recovery system.
The provisioning tool does **not** create, shrink or resize partitions.

Required layout and checks:

- Two distinct ext4-capable GPT root partitions, A and B. Each must accommodate
  your rootfs image (supported image limit: 1 GiB). The running root must be one
  of them. The inactive partition must be unmounted.
- One shared boot partition readable by the board's U-Boot `sysboot` command.
  It holds `/router-slots/A` and `/router-slots/B`, each with Image.gz, board.dtb
  and extlinux.conf. Keep enough space for both kernels/DTBs and the original
  boot files. The original boot files are not replaced by the updater.
- Shared, persistent staging storage, mounted at the same configured path in
  both slots and **separate from both root filesystems**. Each update requires
  `max_rootfs_bytes + 256 MiB` free beyond the existing immutable cache. Allow
  capacity for the old cache and new candidate, plus filesystem overhead; 4 GiB
  is a comfortable general allocation for 1 GiB images. The prepared kit uses
  about 2.46 GiB with a 768 MiB image limit. Startup storage support resolves GPT
  UUIDs and mounts staging before boot confirmation.
- A verified `/etc/fw_env.config` matching the bootloader's actual environment.
  Never guess offsets or copy offsets from another board. Back up and test the
  environment/recovery path, including power-loss behavior; a redundant environment
  is preferable. Incorrect environment offsets can damage boot firmware.
- U-Boot must support `sysboot`, `setexpr`, `saveenv`, `test`, `reset`, and have a
  valid `scriptaddr`. Confirm the U-Boot MMC device:partition for the shared boot
  filesystem. Linux MMC numbering is not a substitute for U-Boot numbering.
- Test the hardware watchdog across failed kernel boots. Set `watchdog_tested`
  true in the profile only after that test. The software counter cannot recover
  from a hung kernel unless a watchdog or external reset causes another boot.

Copy [the profile template](../config/system-slots.example.json), replace every
placeholder with the actual GPT partition UUIDs and boot device, and specify the
shared staging directory. Default health interfaces are `lan` and `wan`; tailor
them to the deployed network roles. They must be up before committing a trial.

Validate first on the board:

```sh
python3 /usr/lib/router-web/provision-system-updates.py --profile /root/system-slots.json
```

After reviewing the validated target and retaining serial/recovery access,
provision the boot hook using the currently working kernel and DTB paths:

```sh
python3 /usr/lib/router-web/provision-system-updates.py --profile /root/system-slots.json --kernel /ACTUAL/BOOT/PATH/Image.gz --dtb /ACTUAL/BOOT/PATH/board.dtb --apply
```

`--apply` writes active-slot boot files, saves the original environment to
`/router-slots/original-u-boot-environment.txt`, and changes U-Boot `bootcmd`.
It leaves `boot_tested` false. Cold-boot, verify the correct active root and router
services, and test recovery/watchdog behavior. Then mark the verified profile:

```sh
python3 /usr/lib/router-web/provision-system-updates.py --profile /root/system-slots.json --mark-boot-tested
```

The input profile must now contain your verified `watchdog_tested: true` assertion.
The tool verifies the installed boot hook and running slot before enabling OS
updates. The webpage reports whether that profile is ready. Preparation must be
validated separately on SD and eMMC boot layouts; their UUIDs and U-Boot device
numbers differ.

The boot hook uses the documented U-Boot
[extlinux/sysboot interface](https://docs.u-boot-project.org/en/latest/usage/pxe.html),
[persistent environment](https://docs.u-boot.org/en/latest/usage/environment.html)
and [setexpr arithmetic](https://docs.u-boot.org/en/stable/usage/cmd/setexpr.html).
Its software attempt counter avoids depending on CONFIG_BOOTCOUNT_LIMIT, but
still depends on a working persistent environment and watchdog/reset path.

## Build full or delta system firmware

Build a matching kernel, DTB and clean **ext4 root filesystem image**. Include the
current updater, dependencies, router-update-confirm/router-storage startup
scripts, the early environment UUID hook, and drivers
required for the board, storage, network and watchdog. Do not use a whole-disk
image, factory ZIP or mounted/live root partition as a delta base.

```sh
python3 openwrt/build-system-update.py --rootfs rootfs.ext4 --kernel Image.gz --dtb stm32mp257f-dk.dtb --generation 1 --version os-1 --private-key signing-private.pem --output os-1.rupdate --export-base release-1-base
python3 openwrt/build-system-update.py --rootfs rootfs-v2.ext4 --kernel Image-v2.gz --dtb stm32mp257f-dk-v2.dtb --generation 2 --version os-2 --base release-1-base --private-key signing-private.pem --output os-2-delta.rupdate --export-base release-2-base
```

Generation is a positive, increasing integer, committed only after a successful
boot. Each image independently uses a full compressed payload or a block delta,
whichever the builder estimates smaller. Root images larger than 8 MiB use 64 KiB
matching blocks. Keep filesystem layout/free blocks deterministic for better
delta efficiency; zero unused blocks in sanitized release images. Rebuilding a
filesystem with widespread block relocation can make its full compressed image
smaller than a delta. There is no guaranteed percentage or global minimum size.

The first system update should normally be full. After boot confirmation, the
router saves the exact pristine release images as future delta bases. Running
filesystems change continually and are never used as binary delta bases.
Application updates between system releases do not mutate the cached images.

The installer validates the board tag, hashes, ext4 image, gzip kernel header,
DTB board compatibility, partition size, free space and target mount state. It
preserves `/etc/config`, `/etc/router-web`, Dropbear identity and account files
in the inactive root. This supports compatible upgrades; the signer must ensure
that preserved configuration formats and kernel/modules are compatible with the
new OS. Bootloader updates and arbitrary cross-distribution migrations are outside
this updater's scope.

After root write/readback and boot-file staging, the environment selects the
inactive slot with three saved trial attempts. Boot confirmation checks the web
service and configured network interfaces for up to three minutes, commits the
generation/cache on success, and clears the trial flag. Failed boot health causes
a reboot. Exhausted attempts select the previous slot; confirmation there reports
failure. A failed kernel boot requires the tested watchdog/reset path to advance
the counter. Power-loss/bootloader failures must still be tested on the real kit.

## MQTT trigger and result

### IRMS dashboard HTTPS downloads (29 October 2026)

The dashboard on `http://52.64.103.203:3080` supports both download protocols.
Choose **Basic Information -> Firmware download -> HTTP (legacy) or HTTPS**
for each device. The choice is stored as `firmwareTransport` on its device record.
Devices without a choice default to HTTP for compatibility with existing modems;
`STM32-001` is explicitly set to HTTPS. Saving other device metadata without this
field preserves the protocol choice. The existing admin/group permissions apply.

Developer settings select the two download bases:

- `FIRMWARE_HTTP_URL=http://52.64.103.203:3080`
- `FIRMWARE_HTTPS_URL=https://serialcloud.ddnsfree.com/irms`

The backend appends `/download/<uploaded-filename>` to the selected base. HTTP
downloads are direct and do not redirect to HTTPS. Nginx proxies the isolated
HTTPS path to the IRMS download handler on local port 3080, using the existing
valid certificate. The existing `WEB_URL` stays unchanged for notification links.
`FIRMWARE_URL` is retained as a fallback for the HTTPS base. The router allowlist
includes `serialcloud.ddnsfree.com`; its updater still requires HTTPS.

The IRMS backend also keeps an upgrade pending for `result: accepted` or
nonterminal progress, and completes it on the final result. Reported failure
details are retained in the task result. Previously the initial acknowledgement
was incorrectly marked as an abnormal task.

Backend source is in `C:/Projects/irms-biz-open/core/task/`. Server configuration
and binary backups are under
`/opt/irms/backups/https-download-20261029-180807/`. The new backend passed task
handler tests, a Linux build and its live version health check. HTTPS retrieval
of the uploaded r21 artifact matched its SHA-256; the router verified the
signature and reconstructed its delta without installing. The router remained
on r20 after these checks. Retry the upgrade task to perform the actual test.

The subsequent mixed-fleet deployment is backed up at
`/opt/irms/backups/dual-firmware-20261029-185328/`. Backend task tests verify
legacy HTTP selection, explicit HTTPS selection and rejection of a mismatched
scheme. Desktop/mobile browser tests cover saving the selector, preserving
unsaved inline edits, failed saves, overlapping requests and navigation during
a save. Both live download URLs returned the exact uploaded artifact without
redirects. No firmware installation was triggered by these checks. Hard-refresh
the dashboard once to load the selector; selections apply to new upgrade tasks.

The dashboard entry HTML was subsequently changed to load
`index.firmware-selector.9d0ad1aefbeb.js`, avoiding reuse of the original cached
entry filename. An import map points existing chunks' runtime imports at the
same versioned module, so the app still loads a single Vue runtime. The previous
HTML is backed up at `/opt/irms/backups/selector-entry-20261029-191359/`.
A browser test loaded the publicly deployed HTML and all actual frontend
modules against local mock API responses: the selector rendered with HTTPS
selected, with one versioned runtime request and no original runtime request.
This checks the shipped module graph rather than an isolated selector preview;
it does not use the user's browser session. Adding `?ui=firmware-selector-2`
before the URL hash bypasses an older cached HTML response as well.

Both application and system bundles are accepted on either upgrade RX spelling:

```text
/RX/DEVICE-SERIAL/UPGRADE
/RX/DEVICE-SERIAL/EVENT/UPGRADE
```

Payload:

```json
{"firmware":"https://updates.example.com/release.rupdate"}
```

`{"patch":"https://updates.example.com/release-delta.rupdate"}` is also accepted.
The signed manifest, not that key, determines application/system scope and delta
encoding. `boot`, `openvpn` and arbitrary executable upgrade URLs are not accepted.
The normal MQTT login gate and retained-command rejection still apply.

The immediate response on the corresponding TX suffix has `result: accepted`
and a job ID. Application completion or OS boot confirmation enqueues a final
`result: succeed` or `result: fail`. An OS install may also publish an intermediate
`state: rebooting`. These completion events use the existing bounded MQTT outbox;
they do not have a protocol-defined persistent application acknowledgement. The
webpage/local status remains the authoritative local record.

## Validation performed

Python tests cover real OpenSSL signing/verification, tampering, application and
system delta round trips, missing bases, path restrictions, redirect/URL validation,
downgrade rejection, application rollback, mounted-slot guards, trial guards,
boot confirmation, simulated fallback and HTTP authentication/CSRF. Browser tests
cover desktop/mobile configuration, update submission and progress/error states.

The dev kit's completed hardware checks are recorded in
[A/B deployment status](ab-flash-status.md). Live application rollback after an
intentional install failure, production HTTPS/MQTT delivery, arbitrary cross-OS
configuration migration and power-interruption tests remain outside those checks.
Do not mark another board boot-tested based solely on the offline test suite.
