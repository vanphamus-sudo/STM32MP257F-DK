# Modbus RTU collection and FTP upload

From release `1.0.0-r27`, use **System → Serial port assignment** to switch the
external converter between Modbus collection and the TCP serial bridge. The
selector stops the previous service and saves the choice for startup. Set up
the meter/register settings first; when TCP is active, save them with Collection
disabled, then select Modbus collection in Serial port assignment.

Implemented from `eSAM & Ultra eSAM MicroBMS Modbus Collection & Upload 0823.pdf`.
In the router settings page, open **System → Modbus collection**. The feature is
disabled initially. It requires the OpenWrt router package and a dedicated Linux
serial adapter connected to your meter(s). This adds software support; it does
not provision or flash an attached board.

Release `1.0.0-r25` includes this feature. Build the application package with
`python openwrt/build-ipk.py local/stm32-lte-router_1.0.0-r25_modbus_all.ipk`.
Copy that IPK to the board and install it with `opkg install /tmp/<package>.ipk`,
then restart `router-web`. The package builder also includes the new service in
factory images and OpenWrt source packages. A disabled example configuration is
in [modbus.example.json](../config/modbus.example.json).

1. Enter the router serial number, collection interval (1–1440 minutes), daily
   upload time in the router's local timezone, and retention (1–31 days). Keep
   the router clock/timezone synchronized; CSV timestamps are UTC with offsets.
2. Choose internal memory or a mounted USB drive. Internal files live under
   `/etc/router-web/modbus-data`. For USB, mount the drive at `/mnt/modbus` (or
   another direct mount under `/mnt`) before enabling. A FAT32 drive needs the
   target image's FAT/USB storage drivers and mount tools; an existing Linux
   filesystem mount also works. No formatting or automatic mounting is performed.
3. Set the serial device or `usb:vendor:product` selector, baud, parity, 8 data
   bits, stop bits and response timeout. The guide's example uses 9600/None/8/1.
   The adapter must provide the electrical interface and automatic RS485
   transmit direction. Do not select the board console or LTE modem. Ports in
   use by the serial bridge, MQTT serial proxy, getty or ModemManager cannot be
   shared; release that port first.
4. Enter the FTP hostname/IP (without `ftp://`), port (normally 21), username,
   password and an existing remote directory. FTP uses passive mode. Explicit
   FTPS is also available and verifies the server certificate with system CAs.
   A blank password on Apply preserves the saved password; it is never returned
   by the API or populated into the form. Change the username/password together
   when changing servers. SFTP and implicit FTPS are separate protocols and are
   not supported by this FTP client.
5. Add devices with unique IDs, names and 32-bit word order. Add each register's
   description, zero-based address, format, unit and read function (03 holding
   registers or 04 input registers). Decimal and `0x` hexadecimal IDs/addresses
   are accepted. Enable collection and Apply.

The guide lists IDs 0–255. ID 0 is a broadcast address and cannot return reads,
so the collector accepts 1–255. IDs 248–255 are accepted for legacy compatibility;
use 1–247 for standard equipment. See the
[Modbus serial specification](https://www.modbus.org/docs/Modbus_over_serial_line_V1_02.pdf).
Register addresses are protocol offsets, not 30001/40001 reference numbers.
FLOAT32, UINT16/32, INT16/32, BIN16/32 and HEX16/32 are supported. Big-endian
means ABCD for 32-bit values; little-endian means swapped words CDAB. Bytes
inside each 16-bit register remain MSB first. Match the meter's register map.
Limits are 32 devices, 128 registers per device and 512 registers in total.

Each device has its own CSV. Names contain the router serial, sanitized device
name, device ID, UTC creation timestamp and a unique suffix. A row contains the
sample timestamp, each register's value, and a separate error field per
register. Missing replies, CRC failures, meter exceptions and invalid numeric
values leave an empty value with an error; they do not become zero readings.
Headers include the description, unit, function and address. Free-text headers
are escaped when necessary for spreadsheet safety. This is a documented CSV
schema, not a claim of byte-for-byte compatibility with the eSAM export.

Files have three states visible under **Saved data**:

- **collecting**: still receiving samples; Export CSV downloads a snapshot.
- **pending**: sealed and queued for FTP.
- **uploaded**: FTP completed; a local copy remains until retention expiry.

At the daily upload time, current files become pending and new CSVs start on
the next scan. Uploading runs separately from serial polling. A failed FTP
attempt leaves files pending and retries after 60 seconds. The outbox and daily
rotation marker survive restarts. Restarting or applying settings seals existing
collecting files so a changed register map never reuses an old CSV header.
Pending files resume after restart. Disable stops both polling and uploading.
Changing storage locations leaves files at the old location; choose that
location again to inspect/resume its queue.

Transfers first write a `.part` remote file and rename it to `.csv` after
completion. The FTP account therefore needs upload, SIZE and rename permissions
(SIZE is optional if the server reports it unsupported). Immutable unique names
and remote size checks handle retries after a crash between remote completion
and local acknowledgement. Servers must allow replacement of an incomplete
`.part` file. Completed CSV files are never appended remotely.

Retention is measured from the CSV's last write. Expired sealed files are
removed after an upload attempt, including files still pending. Collecting files
are not pruned. The configurable 1–1024 MiB CSV storage limit defaults to 64 MiB;
collection stops writing at the limit rather than silently removing unexpired
data. Leave room for the filesystem and database in addition to that limit.
Choose enough retention and storage for expected outages. Errors and serial
TX/RX counters appear in the page; the latest 1,000 local files are listed.
Diagnostic mode logs RTU request/response hex in `logread -e router-modbus`.
FTP passwords and server reply bodies are excluded from diagnostic messages.

Configuration is `/etc/router-web/modbus.json` (mode 0600). CSVs and the SQLite
outbox index share the selected data directory. Do not modify the index or CSVs
while the service runs. The package includes `router-modbus`, a procd service;
Apply enables/disables its boot startup along with the feature. The existing
OpenWrt `python3` dependency supplies the standard library modules including
SQLite and FTP; no pip packages are required on the board.

Authenticated endpoints: `GET /api/modbus`, `POST /api/modbus` (JSON + CSRF),
and `GET /api/modbus/files/{id}` (CSV attachment). File IDs come from the listing;
filesystem paths are not accepted. The UI follows the existing router LAN-only
authentication and CSRF rules.

Validation on the development machine:

```powershell
python -m unittest discover -s web -p test_modbus.py -v
python -m unittest discover -s web -p test_server.py
node web/test_modbus_browser.cjs
```

Tests cover fragmented RTU frames, CRC/exceptions, numeric formats and word
order, configuration validation, multi-device CSVs, rotation/restart/retry,
retention/quota, a local passive FTP transfer, FTPS setup, interrupted uploads,
authentication/CSRF/export and the desktop/mobile settings editor. Physical
RS485/RS232 meters, removable media and a customer's FTP server still require
target-board commissioning.

Installed on the STM32MP257F-DK on 2026-11-05 as `1.0.0-r25`, replacing the
MQTT test B/r22 application. All 43 previous application files matched the saved
r22 test package before installation; all 47 r25 installed files matched the new
IPK afterward. Existing configuration and boot service selections were verified
unchanged. The active application services restarted and the authenticated live
status API reported r25 and the new Modbus panel. All 10 isolated Modbus tests
also passed on the board, including a local passive FTP transfer.

Private rollback backup on the board:
`/root/router-before-modbus-20261105-025029/` contains `rollback.ipk`,
`config-and-app.tar.gz` and verification records. The first installation attempt
automatically restored r22 after an HTTP check ran before web startup completed;
the successful retry waited for HTTP readiness. No reboot was performed.
Modbus remains disabled until the serial devices, register map and FTP server
are configured.
