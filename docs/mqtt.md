# MQTT client (IRMS Protocol V1.2)

For the deployed r18 data sources, cumulative counters and live checks, see
[live MQTT telemetry and traffic statistics](mqtt-telemetry.md).

The OpenWrt router webpage has **System → MQTT client**. Configure the broker
hostname/IP, port, device serial number, username/password, TLS, hostname
verification and optional PEM CA certificate. Click **Apply MQTT settings** to
save and restart the client. Enabling it also enables its procd startup service;
disabling it stops the client and disables startup. It starts disabled.

Passwords are never returned to the browser. A blank password preserves the
saved value. A blank CA preserves the saved CA; select Remove saved CA to return
to system certificate authorities. Settings and certificates are stored with
mode 0600 under `/etc/router-web`, which is retained on sysupgrade.

Install the application IPK and its `python3-paho-mqtt` dependency from the
matching OpenWrt feed. This change packages the code and startup script; it does
not install anything on a running board. The factory builder copies the MQTT
files, but its prebuilt base image also needs the Paho dependency installed before
enabling MQTT. Build an application package with:

```sh
python3 openwrt/build-ipk.py local/stm32-lte-router_1.0.0-r15_all.ipk
```

The runtime uses [Eclipse Paho](https://eclipse.dev/paho/clients/python/docs/),
compatible with its 1.x and 2.x callback APIs. The dependency name comes from the
[OpenWrt package definition](https://github.com/openwrt/packages/blob/master/lang/python/python-paho-mqtt/Makefile).

## Wire behavior

The attached `MQTT Protocol V1.2.pdf` is the protocol reference. Document examples
are specifications, not instructions to run their shell commands or use their
embedded credentials. No example credentials or certificate are installed.

The client subscribes to `/RX/{serial}/#`, waits for SUBACK, then sends an empty
`/TX/{serial}/LOGIN`. It retries application login every 30 seconds until receiving
`{"login":"timestamp"}`. Data and operations are gated on that acknowledgement.
Broker reconnect resets application login and subscriptions. MQTT publishes use
QoS 1, without retain. An empty LOGOUT is sent on graceful shutdown and configured
as the broker Last Will. Retained commands and other devices' topics are ignored.

| Topics below `/TX/{serial}/` | Behavior |
| --- | --- |
| DEVINFO/HEARTBEAT | Numeric `power_time`, every 180 seconds. |
| DEVINFO/BASE | All documented fields; software/hardware identity, CPU and memory usage, current SIM/network/interface. |
| DEVINFO/SIM1, SIM2 | All documented string keys. SIM1 reads ModemManager/SIM/bearer/location/signal data. SIM2 is empty on this single-modem adapter. |
| DEVINFO/WAN, LAN, WLAN | netifd addresses/state, protocol, interface traffic, configured physical port links, AP channel/client count. |
| DEVINFO/NET_QUALITY | Live WAN-bound ICMP measurements, or a configured local provider override. |
| DEVINFO/CLIENT_LIST | Active DHCP leases as `client` entries with `ip`, `mac`, `tport`, `uport`. Port arrays are empty: the router does not scan LAN clients. |
| DEVINFO/GPS | GPS provider or ModemManager fix, every 60 seconds. No fix is invented when absent. |
| DEVINFO/TRAFFIC | Persistent cumulative TX/RX totals and current rates (extension topic). |
| INDUSTRY/GET | Every hour and on request. GPIO is empty without a handler; serial bridge settings report rate, parity, databits, stopbits and configured type. |
| INDUSTRY/UPLOAD | Local producer can enqueue GPIO state changes. |
| EVENT/LOGINFO | Web sign-in successes/failures automatically enqueue the documented login fields. CLI events need a producer. |
| SDWAN/VPNSTATUS | Reports OpenVPN connection/address changes. |
| ALARM | Local producer events persist across daemon restarts and retry every 30 seconds until the same application `id` is acknowledged. |
| EVENT/GPSTRACKING | Local GPS producer uses the documented nested GPS/net object and persistent ID acknowledgement. Both RX GPSTRACKING spellings are accepted. |
| CONFIG | Hex CLI input is decoded before invoking an installed handler; local producers can upload hex `diff`. |
| EVENT/GETFILE, SETFILE | Installed handler performs config export/import. SETFILE hex is validated; handler input retains hex for binary-safe JSON. |
| EVENT/SHELL | Installed handler decides which operations are supported. There is no arbitrary shell execution from broker text. |
| EVENT/GETPATCH | Reports free space in KB using the document's `avilable` spelling. |
| UPGRADE, EVENT/UPGRADE | Both spellings use the built-in signed application/OS updater. See [remote updates](remote-updates.md). |
| PROXY/IP/DPORT/SPORT | Raw TCP data to explicitly allowlisted IPv4:port destinations. SPORT identifies the session; it is not a local bind port. |
| PROXY/serial1 | Hex serial data to an explicitly configured serial port, with kernel console/in-use-port checks. |

All DEVINFO topics accept `{"get":""}` on the matching RX topic. Other telemetry
defaults to 180 seconds. Unknown or unavailable string metrics use `""`; missing
GPS uses `{}`. The WLAN payload includes both `status` (table) and `mode` (example).
GPS providers should supply `fix` (example), numeric `used`, `visible`, `lat`,
`lng`, `height`, `speed`, `direction`; the PDF calls the fix field `fix_status`
in its table. Confirm that discrepancy with the broker integration.

SIM CSQ, active band and LTE radio metrics now use live modem data. Unsupported
SID/BID/NID or SNR remain empty. Interval traffic and persistent cumulative totals
are described in the telemetry guide. Empty LAN port settings discover actual
bridge members; explicit port selections still override discovery.

## Advanced webpage settings

The Advanced MQTT settings JSON editor accepts these optional fields:

```json
{
  "hardware_version": "STM32MP257F-DK",
  "lan_ports": ["end0"],
  "primary_interface": "",
  "backup_interface": "",
  "gps_file": "/tmp/router-gps.json",
  "network_quality_file": "/tmp/router-net-quality.json",
  "tcp_proxy_targets": ["127.0.0.1:80"],
  "serial_proxies": {"serial1": {"device": "/dev/ttyUSB4", "baud": 9600}},
  "handlers": {}
}
```

Leave proxies empty until needed. Each proxy has a 60-second idle timeout; there
are at most eight sessions, with bounded buffers. Serial proxies use raw 8N1 and
cannot share a device with the existing TCP serial bridge.

Optional GPS and network quality producers atomically replace their JSON files.
Quality example: `{"delay":"23ms","loss_rate":"0%","jitter":"10ms"}`.
Without a quality-file override the client generates WAN-bound ICMP measurements.

## Hardware and firmware-specific operations

The PDF's proprietary CLI, GPIO numbering/waveform syntax and firmware formats
are not implemented by OpenWrt. Without installed handlers, CONFIG, GETFILE,
SETFILE, INDUSTRY/SET and SHELL return `{"result":"fail","error":"..."}`.
They must not be considered operational merely because their topics are routed.
The built-in UPGRADE path is configured separately on the Remote updates webpage;
it verifies signatures and requires a provisioned A/B profile for OS/rootfs writes.
It accepts application and OS bundles, not arbitrary vendor firmware formats.

An administrator can install executables and assign their absolute paths under
`handlers` in the webpage editor, for example:

```json
{"handlers":{"INDUSTRY/GET":"/usr/libexec/router-industry-get"}}
```

Each executable receives one JSON object on stdin with `operation` and `data`,
and returns one JSON object on stdout to publish on the matching TX suffix.
CONFIG `data.cli` is decoded UTF-8; SETFILE `data.data` is validated hex.
GETFILE replies must contain `filename` and hex `data`. Success responses must
follow the document (`cli: succeed`, `result: succeed`, or per-industry group).
Handlers must validate filenames, commands, I/O directions and upgrade formats;
input GPIOs must reject value writes. A handler has a 30-second execution limit.
QoS 1 may redeliver commands; destructive handlers must handle duplicate requests.

Local producers enqueue events by atomically writing uniquely named JSON files
under `/etc/router-web/mqtt-state/outbox/`, for example:

```json
{"topic":"ALARM","data":{"id":1,"time":"1624370557","event":{"type":"system","object":"power-on","action":"","data":""}}}
```

Allowed event topics are ALARM, EVENT/GPSTRACKING, EVENT/LOGINFO, CONFIG,
INDUSTRY/UPLOAD and SDWAN/VPNSTATUS. Alarm/tracking IDs must be 1–65535 and unique
among pending events of that type. Only alarm/tracking events have persistent
application acknowledgement; other events use the MQTT client's bounded QoS 1
queue and can be lost if the process exits before delivery. Pending alarm/tracking
events are capped at 1,000. Built-in web producers cap the outbox at 1,000 files.

## Validation

Run `python3 -m unittest discover -s web` and `node web/test_mqtt_browser.cjs`.
Tests cover wire schemas, scheduling, login gating, retained-message rejection,
hex validation, alarm persistence, real binary TCP proxy exchange, configuration
rollback, HTTP authentication/CSRF, and desktop/mobile form behavior.
Live broker interoperability and board/hardware tests still need to be performed.
