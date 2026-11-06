# LTE AT TCP server

R7 restores TCP port 5000 to a fully transparent data bridge. Every byte,
including `AT$VERSION`, is sent to the external USB serial device. There is
no command parsing on that port. Existing one-client and idle policies remain.

The separate AT server is prepared for TCP port 11111. It accepts ASCII AT
commands terminated by CR, LF or CRLF, handles split packets and multiple lines,
limits commands to 256 characters, and returns the response to the sending
client. It supports one client at a time and a 60-second idle timeout. Ordinary
AT commands use ModemManager's serialized API to the LTE module.

All case-insensitive `AT$` prefixes are reserved for router software and never
reach the LTE module. `AT$VERSION` returns the version string and `OK`.
Unknown reserved commands return `ERROR: UNKNOWN SOFTWARE COMMAND`.
The authenticated webpage AT API uses the same reservation policy.

R7 is installed on the dev kit. Following the user's explicit approval on
2026-10-02, the 11111 listener, WAN firewall rule and automatic startup were
enabled. Port 5000 remains a pure data bridge. Clients on 11111 can change or
reset the LTE module, which can disrupt connectivity. The activation script
is `local/install-at-tcp.py` and package is
`local/stm32-lte-router_1.0.0-r7_all.ipk`.

Validation: 36 local tests passed, with five Linux tests skipped on Windows.
Six data-bridge and three AT-server tests passed on the board using isolated
loopback sockets and pseudo-terminals. These cover pure forwarding of reserved
strings on port 5000, reserved-command interception on the AT service, modem
response formatting, split/coalesced lines, single-client rejection and idle
expiry. Live public-LTE checks passed for `AT$VERSION`, `AT$UNKNOWN`, and
`AT+CSQ` (response `+CSQ: 25,99`), as well as second AT-client rejection.
The existing data port remained reachable. No physical reboot was performed.

The deployment backup is on the router at
`/root/router-before-port-split-20261002/config-and-app.tar.gz`.
The pre-activation backup is
`/root/router-before-at-tcp-20261002/config-and-app.tar.gz`.
