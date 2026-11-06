# Live MQTT telemetry and traffic statistics — r18

**RSSI fix in r19:** both slots now run r19. SIM messages include the live `rssi`
string in dBm, extracted from the serving-cell response (with ModemManager RSSI
as fallback). The earlier parser and SIM field whitelist both omitted it. A live
`DEVINFO/SIM1` publish containing `"rssi":"-49"` was broker-acknowledged after
deployment. This field extends the original PDF's SIM field list. Configuration
and accumulated traffic counters were preserved. Regression suite: 127 tests run,
five Linux serial tests skipped on Windows.

Router application **1.0.0-r18** is installed in both eMMC root slots. Slot A
remains active; the existing MQTT broker settings and router configuration were
preserved. The live client received broker acknowledgements for the populated
DEVINFO messages, including the new TRAFFIC message.

## Real device data

All MQTT topic prefixes remain `/TX/{configured-serial}/`.

| Suffix | Source |
| --- | --- |
| DEVINFO/HEARTBEAT | Kernel uptime in seconds. |
| DEVINFO/BASE | Installed software version, configured hardware identity, measured CPU/memory usage, active network/SIM/interface and available GPS coordinates. |
| DEVINFO/SIM1 or SIM2 | Active SIM identifiers, operator, modem firmware, connected bearer address/duration, CSQ, serving cell, area code, active band, RSRP/RSRQ/SINR and measured traffic. |
| DEVINFO/WAN | netifd connection/address/protocol, current link and interval traffic. |
| DEVINFO/LAN | Actual LAN bridge members and their carrier/speed/duplex. Empty port configuration now discovers the real member ports instead of publishing blank LAN1. |
| DEVINFO/WLAN | Hotspot address/status, AP mode, live channel and hostapd client count. |
| DEVINFO/NET_QUALITY | Three ICMP probes bound to the WAN interface: average round-trip delay, loss percentage and mean absolute difference between successive round-trip samples as jitter. |
| DEVINFO/CLIENT_LIST | Active DHCP leases with real IP/MAC values. No LAN port scan is performed; undiscovered TCP/UDP port arrays remain empty. |
| DEVINFO/GPS | Configured local GPS provider or ModemManager's actual fix. No coordinates are invented when there is no fix. |
| DEVINFO/TRAFFIC | Persistent cumulative TX/RX byte counters, current-boot counters and measured bytes/second for WAN, active SIM, LAN and WLAN. |

Serving-cell metrics use read-only `AT+CSQ` and `AT+QENG="servingcell"` through
ModemManager; they do not take over a serial port or alter the modem connection.
The mapping follows the [Quectel EM06xK command manual](https://forums.quectel.com/uploads/short-url/zwVbq0bdsIXR1qTexLq478k8enT.pdf).
For LTE, the legacy `lac` field carries the real **TAC** because LTE does not
provide a GSM LAC. Unknown `FFFE` values are not published as a real area code.
The active radio band is measured, rather than reporting the modem's list of all
supported bands. Modem observations are cached for up to 20 seconds.

The kit has one active SIM and no reported GPS fix. Its unused SIM, CDMA-only
SID/BID/NID, unavailable SNR, GPS and unmapped GPIO values remain unavailable;
they are not replaced with dummy values. Connected modem off-time is `"0"`;
historical off-time is not fabricated when disconnected.

NET_QUALITY samples are cached for 60 seconds. The default target is `1.1.1.1`;
set `"quality_target":"your-host.example"` in the MQTT webpage's Advanced JSON
to change it. A configured `network_quality_file` still overrides the built-in
probe, and `gps_file` still overrides ModemManager GPS.

## Traffic accounting

`router-traffic` runs independently of MQTT, so disconnecting or disabling MQTT
does not stop counting. It samples every five seconds and records:

- `total_tx_bytes`, `total_rx_bytes`: cumulative measured interface traffic.
- `boot_tx_bytes`, `boot_rx_bytes`: current kernel interface counters.
- `tx_bytes_per_second`, `rx_bytes_per_second`: rate over the last sample interval.
- `device`, `available`: actual counter source and whether it is present.

These come from the [Linux network interface byte counters](https://www.kernel.org/doc/html/latest/networking/statistics.html).
TX means sent **by the router** on that interface; RX means received by it.
For WAN/SIM this means upload/download respectively. LAN directions are from
the router's perspective too. Counts include router-generated traffic, such as
MQTT and probes; they are not carrier billing measurements.

WAN and SIM1 currently both describe `wwan0`. Their records are alternative views
of the same traffic and **must not be added together**. LAN and WLAN are also
separate interface views, not additional uplink consumption.

The first sample includes the real counters already accumulated in the current
boot. Earlier boots before accounting was installed cannot be recovered. The
collector handles process restarts, device counter resets, new boot IDs and
interface reassignment without treating a new device's old traffic as new WAN
usage.

On this A/B kit, checkpoints are shared at:

```text
/mnt/update-storage/router-traffic/state.json
```

Both slots use that file. Checkpoints occur every five minutes and on graceful
service shutdown. An abrupt power loss can lose traffic after the last durable
checkpoint. `/tmp/router-traffic.json` is refreshed every five seconds for the
webpage and MQTT; stale samples include their age. The state directory is private
and files have mode 0600. A non-A/B installation uses
`/etc/router-web/traffic-state.json` instead.

The existing V1.2 `flowtx`/`flowrx` fields remain **interval KB** (1024 bytes per KB),
not lifetime totals. Each topic has its own persisted interval cursor, so an MQTT
process restart does not repeat the entire boot's traffic. A new measurement
history initially reports its measured totals once; later reports give the
difference since that topic's preceding sample. Use TRAFFIC cumulative counters
for router usage statistics, rather than adding overlapping WAN/SIM intervals.
MQTT delivery is QoS 1, not an exactly-once accounting protocol.

The webpage's **Traffic statistics** section shows totals and rates in binary
units. It reports a stale recorder sample as “Last recorded sample”.

TRAFFIC is an extension to the supplied V1.2 PDF. It publishes every 180 seconds
and supports `{"get":""}` on `/RX/{serial}/DEVINFO/TRAFFIC`. Existing PDF topics
retain their documented fields/types. Subscriber/server software must subscribe
to this extra topic to display the cumulative counters.

## Diagnostics and validation

The MQTT settings panel now distinguishes broker connection, rejected subscription
and waiting-for-IRMS-login states. Telemetry and remote operations still use the
existing IRMS application-login handshake. Broker subscription permissions may
allow the router to publish TX messages while denying an observer's TX wildcard
subscription; a rejected observer subscription is not evidence of failed publish.

Private, volatile diagnostics on the kit:

```text
/tmp/router-mqtt-status.json
/tmp/router-mqtt-samples.json
```

They report queued/broker-acknowledged messages and the most recently queued
payload for each topic. Samples include SIM identifiers, have mode 0600, and must
not be exposed publicly. A broker acknowledgement does not prove that a remote
dashboard has consumed or displayed the packet.

Validation completed on the kit:

- Broker acknowledged populated BASE, SIM1, WAN, LAN, WLAN, NET_QUALITY and TRAFFIC,
  plus the other scheduled topics.
- Real WAN RX increased after a small interface-bound ICMP test.
- Traffic recorder stop/start preserved totals with exactly the expected raw
  counter deltas, without reset or double counting.
- MQTT reconnect retained interval cursors and did not replay boot traffic.
- SIM1 contained live CSQ, active band, cell/TAC, signal metrics, identifiers,
  modem version, bearer uptime and traffic values.
- 126 Python tests ran successfully, with five Linux serial tests skipped on
  Windows. Desktop/mobile MQTT and traffic display checks passed.

Local verification record: `local/mqtt-r18-verification.json`. A private deployment
backup is on shared storage under `/mnt/update-storage/deploy-r18/`.

## Live RSSI on the IRMS device detail page (r20)

The router publishes modem RSSI in `DEVINFO/SIM1.rssi` as a string in dBm.
An unavailable SIM produces no SIM telemetry message; publishing an all-empty
SIM2 record previously reset the IRMS device's global CSQ signal to zero.

The dashboard at port 3080 now displays the latest SIM RSSI in Basic Information
and Running Information. Visible tabs fetch the device snapshot every 15 seconds;
the router's configured SIM publish interval still controls telemetry freshness.
Refreshes preserve Basic Information edits, ignore responses for a previous
device, and stop on unmount. Historical GPS readings remain historical.

Release r20 was installed in both A/B slots with all 14 router configuration
files unchanged. Verification found broker-acknowledged RSSI `-54 dBm`, matching
the dashboard database, with global CSQ restored to 29. All 128 Python tests
passed (five platform-specific skips); dashboard helper checks, JavaScript syntax
checks, and both modified Vue script/template compilation checks passed.

Dashboard source changes are in `C:/Projects/irms-vue-master/src`. The deployed
static assets have a rollback copy at
`/opt/irms/backups/rssi-20261029-151801/`. Existing browser sessions require one
hard refresh to load the updated components.
