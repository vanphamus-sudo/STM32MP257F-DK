# LTE TCP serial bridge

## Select the serial port service

Release `1.0.0-r27` adds **System → Serial port assignment** in the router UI.
Choose **TCP serial bridge**, **Modbus collection**, or **Disabled**, then Apply.
The selector stops both services before starting the selected one, saves their
enabled flags and boot selections, and preserves their other settings. It restores
the previous configuration if applying the switch fails. The external converter
defaults to `usb:067b:2303`; both services use the selected device.

TCP baud rate and listening port are configurable in this panel. TCP uses 8N1;
Modbus uses its baud/parity/stop-bit settings in the Modbus panel. Save a valid
meter/register configuration before selecting Modbus. Enabling Modbus through its
own settings is rejected while the TCP bridge is enabled.

Installed and tested on 2026-11-06: switched through the authenticated API to TCP
at 9600 baud, read the COM1 simulator's 240 V register through TCP port 5000,
then switched back to Modbus and verified collection resumed with zero read errors.
The router remains in Modbus mode. Its previous TCP baud setting (115200) is
preserved; select 9600 for TCP tests with the current simulator.

Rollback backup: `/root/router-before-serial-assignment-20261106-021134/`.
All 48 installed package files were verified; existing configuration and boot
service selections were preserved during installation. No reboot was performed.

Prepared application r5 includes a binary TCP-to-serial bridge and a procd
service named `router-serial`. It forwards raw bytes without framing or text
conversion. Exactly one client owns the stream; additional connections close
immediately without receiving or sending serial data. A connection is dropped
after 60 seconds without data in either direction. Reconnection is permitted
after disconnect or idle expiry. Bounded 64 KiB buffers provide backpressure.

The user requested LTE access through a USB-to-serial converter. The connected
converter is a Prolific PL2303 (`067b:2303`). Its missing driver was installed
from the saved firmware's exact 6.6.144 target repository, and it enumerated as
`/dev/ttyUSB4`. The bridge's `usb:067b:2303` selector identifies that converter
independently of ttyUSB numbering and refuses ambiguous multiple converters.
It refuses kernel consoles and ports already owned by another process.
The LTE modem ports remain separate.

Proposed configuration at `/etc/router-web/serial-tcp.json`:

```json
{"enabled":true,"device":"usb:067b:2303","baud":115200,"listen":"0.0.0.0","port":5000,"idle_seconds":60}
```

Serial format is 8N1 without hardware/software flow control. Other supported
baud rates: 1200, 2400, 4800, 9600, 19200, 38400, 57600 and 230400.
The service holds exclusive serial access, retries via procd after device loss,
and restores terminal settings when stopped normally. It discards stale serial
input and queued output when assigning a new client. No payloads are logged.

The user explicitly approved activation on 2026-10-02. Application r5 is
installed, the WAN TCP 5000 rule is active, and `router-serial` is enabled at
startup. Exclusive converter access, firewall validation, service activity and
public LTE connectivity were verified. A second remote connection was rejected.
The live 60-second idle disconnect and subsequent reconnection both passed.
The private pre-change backup is on the board at
`/root/router-before-serial-tcp-20261002/config-and-app.tar.gz`.
The WAN input policy otherwise remains REJECT. LTE and the authenticated
settings/AT APIs remained operational after deployment.

This raw bridge has no TLS or application authentication; clients with access
to its TCP port can send bytes directly to the attached serial equipment.
Connect with a TCP client to the router's public IPv4/DDNS hostname on port
5000 after activation. Clients must handle their own device protocol.

Validation: 33 local tests passed, with four Linux tests skipped on Windows.
All five serial-bridge tests passed on the board using pseudo-terminals:
configuration validation, binary forwarding both ways, second-client rejection,
idle expiry/reconnect, activity renewal, and queued output on TCP shutdown.
Public WAN reachability was verified after activation. Tests send no bytes to
the attached serial equipment; physical equipment communication is not yet
verified. No physical reboot was performed.
