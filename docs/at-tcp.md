# LTE AT TCP server

## Remote AT auditing (r47)

TCP 11111 now emits structured `authpriv.notice` records tagged
`router-at-audit`. View them in **System → Local Log → Audit**; search for
`router-at-audit` to isolate these events. The live log windows and local file
capture include them. Native remote syslog forwards them when configured.

Events include connection open/close, single-client rejection, command receipt,
invalid/oversized command rejection, and command completion. Each has a UTC
timestamp, observed client IP/port, listener port and connection ID. Command
records include a per-connection command ID, outcome, elapsed milliseconds,
reply byte count and whether sending the reply completed. Close reasons
distinguish client closure, idle timeout, reply timeout and socket errors.
An observed IP identifies the network peer, not an authenticated person.

Parameterized command values are conservatively replaced with `[redacted]`,
including PIN/password changes, authentication setup and unknown vendor
setters. Invalid bytes and oversized payloads are never copied into audit
records. Raw modem replies are not recorded, since queries can return secrets;
the client still receives its normal reply. Results distinguish success,
modem errors, unavailable/busy conditions, invalid/oversized commands and
unknown router software commands. JSON escaping prevents forged multiline
audit entries.

Before forwarding a modem command, the service sets ModemManager's operational
log level to INFO, retaining its required `--debug` AT-access permission but
preventing a duplicate DEBUG trace of the raw command. If this privacy guard
cannot be applied, that modem command is rejected and the failure is audited.
Router software commands such as `AT$VERSION` do not access the modem.
This applies to TCP 11111; it does not add a dedicated audit trail to webpage
AT requests or direct serial/SSH modem access. Historical debug logs are not
rewritten.

Logging is bounded by the configured system buffer/file retention; it is not
an immutable archival trail. RAM logs are cleared on reboot unless persistent
file storage or remote syslog is configured.

Deployed **1.0.0-r47** on 20 November 2026. Package:
`local/stm32-lte-router_1.0.0-r47_all.ipk`; rollback backup:
`/root/router-before-r47-20261120-072002/` (suffix uses board UTC).
232 web tests passed with platform-specific skips. Socket tests covered
masking, success/failure, invalid/oversized requests, busy rejection and idle
timeout. Live checks verified ATI, version reporting, a harmless unsupported
vendor command, client metadata, local file capture and absence of its private
parameter from raw logs. LTE remained online. Existing settings were preserved;
no reboot or standby-slot update was performed.

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
