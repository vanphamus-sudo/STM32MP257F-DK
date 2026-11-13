# USER1 reboot and Ethernet/USB recovery

## r42 deployment — 13 November 2026

Installed **1.0.0-r42** on the running board with settings preserved. Long USER1
recovery now saves IP passthrough as Off and clears pending feature rollback,
in addition to restoring Ethernet LAN and USB management. Application state is
included in the durable recovery journal and restored if recovery fails.

All 24 recovery/passthrough tests passed on the board using temporary fixtures;
the physical reset/reboot gesture was not exercised. Installed package files
matched build hashes, firewall validation passed, previously running services
restarted, and USB management returned HTTP 200. No reboot was performed and
the standby slot was not updated.

Rollback backup (board-clock name): `/root/router-before-r42-20261112-225756/`.
Package: `local/stm32-lte-router_1.0.0-r42_all.ipk`.

Release **1.0.0-r29** adds the `router-button` service. USER1 is **B5 / PC5**;
the indicator is **orange LD9 / PH6**. Both are active high.

| Gesture after Linux starts | Action |
| --- | --- |
| Less than 150 ms | Ignore contact bounce |
| Brief press; release before eight seconds | Reboot, retaining configuration |
| Hold until LD9 is solid (eight seconds), then release | Restore Ethernet LAN and USB management access and reboot |
| Continue holding after eight seconds | Wait for release; no additional erase |

LD9 flashes twice per second while holding, then stays on at eight seconds.
After recovery reboots, three flashes require `br-lan` at `192.168.10.1/24` and the USB interface at `192.168.7.1/24`.
This confirms address configuration, not end-to-end DHCP/browser access. Five
quick flashes indicate failure; inspect `logread -e router-button`. Otherwise
LD9 is off. The blue Linux heartbeat is unchanged.

Recovery restores untagged Ethernet LAN, removes the dedicated Ethernet WAN
interface, and resets the mode selector to LAN with default VLAN IDs 10/20.
It disables saved IP passthrough, removes its dedicated interface/firewall rules,
restores WAN NAT, and clears pending feature confirmation. The feature supervisor
is stopped before recovery to prevent concurrent network changes.
It sets **192.168.10.1/24**, enables DHCP at **192.168.10.50–200** with 12-hour
leases, removes custom LAN DHCP options, and restores the project's LAN
DHCP/DNS/settings/administration/ping firewall rules. Renew the PC's DHCP lease
and open **http://192.168.10.1:8081**.

Passwords, MQTT, VPN, LTE, Wi-Fi, static DHCP reservations, port forwards and
other application settings are preserved. This is access recovery, not a full
factory wipe. Missing dedicated LAN/WAN sections or an unknown Ethernet device
cause rejection. Arbitrary external LuCI/firewall customizations may still
interfere with access. Pending UCI edits cause rejection rather than silently
discarding changes. Avoid concurrent configuration edits during recovery.

## USB recovery added in r30

Long USER1 recovery also restores USB management at **192.168.7.1/24**,
re-enables USB DHCP at **192.168.7.100?150**, removes USB gateway/DNS
advertisements, and turns USB tethering **off**. SSH and the settings page at
**http://192.168.7.1:8081** are permitted. Reconnect USB to renew the PC lease.
The existing USB gadget and drivers are required; recovery restores their
network configuration rather than reinstalling hardware support.
See [USB tethering](usb-tethering.md) for the new settings option.

## Implementation

The controller uses evdev when firmware exposes gpio-keys and an orange LED
device. On the installed ST/OpenWrt image it listens to kernel-originated
`BTN_1` uevents from the existing GPIO button driver and exclusively exports PH6
for LD9. Controller numbers are resolved from labels; ST's `PH6` sysfs naming
is supported. No device-tree, bootloader or kernel replacement is needed.
A GPIO owned by another component is rejected. After abnormal termination,
an exported PH6 may require cleanup before restart; identify its owner first.

Recovery builds UCI candidates privately and saves timestamped originals under
`/etc/router-web/button-recovery-*`. A durable journal permits rollback after
interrupted writes. Firewall validation/write failures restore originals;
startup restores an interrupted transaction before networking (priority 18).
The web service is stopped during recovery. Actions are rejected while the
application/OS updater holds its lock. Functioning Linux/userspace is required;
this cannot reset a frozen processor.

**Do not hold USER1 while powering on or rebooting:** it has a bootloader USB
programming function. Use the gesture after Linux starts. A button already held
when this service starts is ignored; release and press again.

## Build and enable

```text
python openwrt/build-ipk.py local/stm32-lte-router_1.0.0-r29_button_all.ipk
```

Install the IPK on the board using `opkg install`, then:

```sh
/etc/init.d/router-button enable
/etc/init.d/router-button start
ubus call service list '{"name":"router-button"}'
logread -e router-button
```

The factory builder includes and enables the service; existing factory bundles
must be rebuilt. Both application packaging paths include the new files.
Older signed-update workers reject the new init-script path, so initial r28
installation uses local `opkg`; r29 permits subsequent packages with that path.

For a future PCB, adapt the GPIOs, polarity, LED and board-compatible check.
Retain a separate hardware-reset facility for a frozen processor.

## Deployment and validation — 6 November 2026

Installed r29 in the dev kit's **currently running root slot**, enabled the
service, and verified it running. Existing settings hashes were preserved;
the settings page returned HTTP 200. Backup of the previous application and
configuration: `/root/router-before-user1-20261106-042814/`.
The standby root slot and existing factory images were not updated.

149 Python tests ran successfully with five platform-specific skips. Live USER1 driver
and LD9 GPIO requests passed. Recovery ran against private copies of the board's
actual UCI settings without changing live configuration. Tests cover thresholds,
preservation of unrelated settings, kernel-event filtering, validation/write
rollback, and interrupted-transaction restoration.

Physical gestures, visual LED identification, reboot startup, and recovery from
actual Ethernet WAN/VLAN mode still need hardware acceptance testing. Keep USB
recovery connected for the first test: briefly press USER1, then after reboot
hold until LD9 is solid and release. Verify DHCP and browser access after each
reboot before relying on the feature unattended.

Hardware reference: [ST UM3385, sections 7.9 and 7.10](https://www.st.com/resource/en/user_manual/um3385-discovery-kit-with-stm32mp257f-mpu-stmicroelectronics.pdf).
