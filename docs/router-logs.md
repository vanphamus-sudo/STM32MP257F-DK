# Local, remote and live logs (r46)

Open http://192.168.10.1:8081/ and sign in. Under **System**, choose
**Local Log** or **Remote Log**.

From r47, Audit includes structured TCP 11111 command and connection events
tagged `router-at-audit`, with parameter masking and result status. See
[remote AT auditing](at-tcp.md) for scope, privacy and retention details.

Local Log provides Message (all syslog), Application (userspace excluding
security records), Kernel (dmesg for the current buffer) and Audit (existing
authentication/audit records) categories. Audit does not install or enable a
separate kernel audit subsystem. Choose a source, filter by plain text, pause
updates, follow new entries, or download the displayed records. Live updates
run every two seconds while the viewer is visible. **Open live window** opens
an independently controlled window for the selected category; browser popup
permission may be required. All windows require the authenticated session.

The current board has its original 128 KiB memory buffer and an enabled
1 MiB rotating RAM log file at `/var/log/router/messages.log`. RAM records are
cleared at reboot. The local settings can select persistent internal storage
at `/root/router-logs/messages.log`; this consumes flash writes. Native OpenWrt
logread retains one rotated file. The viewer reads the current file only,
bounded to its last 256 KiB, or up to 1000 recent buffer records. Kernel buffer
timestamps are relative to boot; syslog timestamps follow the router clock.

Remote Log configures outgoing syslog to an IPv4/IPv6 address or hostname,
port and UDP/TCP transport. The collector must already accept syslog. It is
not a router-side log receiver. Neither transport encrypts records. Native
remote forwarding is independent of viewer filters and masking. No collector
was supplied, so remote forwarding remains off until configured by the user.

The authenticated GET `/api/logs` endpoint validates source/category, line
count and search. Saved-log reads use only the two managed file locations.
The viewer renders plain text, masks known cellular passwords/PINs and common
textual secret assignments, and clears records on logout. Masking is best
effort; diagnostic logs can still include identifiers or encoded protocol
data. GET/POST `/api/logs/settings` provides logging settings; saving requires
CSRF and a backed-up `system` UCI transaction. The committed CLI view is read
to avoid rpcd's stale loaded configuration. Applying restarts the native log
service and may clear the memory buffer. Successful live polling is excluded
from HTTP access logging to avoid filling the same buffer being viewed.

Deployed as **1.0.0-r46** on 20 November 2026. Artifact:
`local/stm32-lte-router_1.0.0-r46_all.ipk`. Final deployment backup:
`/root/router-before-r46-20261120-070850/` (suffix uses board UTC).
Existing network and login settings were preserved. No reboot or standby-slot
update was performed.

Validation passed: 227 web tests and 13 OpenWrt tests (platform-specific skips),
desktop/mobile form and help navigation, standalone popup, authentication/CSRF,
all four installed log categories, bounded file reads and secret masking.
Native memory/file capture and UDP/TCP forwarding were verified against
temporary loopback collectors; the original configuration was restored after
testing, then the RAM file was enabled. External collector delivery remains
untested. AT version reported r46, LTE ping had no loss and HTTPS passed.
