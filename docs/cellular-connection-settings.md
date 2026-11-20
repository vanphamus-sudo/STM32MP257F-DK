# Cellular connection and webpage login settings

Open http://192.168.10.1:8081/ or USB management at
http://192.168.7.1:8081/ and sign in.

Under **Cellular → APN & connection**, configure the APN, cellular username,
password, authentication (None/PAP/CHAP/either) and IPv4/IPv6/dual-stack type.
Applying saves `network.wan` through the existing backed-up UCI transaction
and reconnects WAN. Ethernet/USB management remains available. The API reports
that reconnect started; confirm registration and Internet access in Network
overview. A provider rejection is not automatically rolled back.

Blank password preserves a saved password; the separate clear option removes
it. Saved passwords are never returned by GET. The installed netifd service
does not escape credential separators, so commas, quotes and backslashes are
rejected. Credentials otherwise pass as individual subprocess/UCI arguments.
Authentication and CSRF checks protect the new `/api/cellular` endpoint.
Pending router feature network changes block applying these settings.

Under **System → Webpage login**, change the management username and password
using the current password. New password confirmation is required; blank new
password fields keep the existing password. Saving revokes existing sessions.
This existing workflow was verified and made more discoverable; installation
does not change the user's credentials.

Installed on the running board on 20 November 2026. The targeted installer
preserves unrelated live app changes and backs up changed files under
`/root/router-before-cellular-settings-<timestamp>/`. Existing Telstra values
were applied unchanged through the new backend; WAN reconnected with IPv4 and
IPv6, and three Internet pings passed without loss. Tests passed for cellular
validation/secret handling, HTTP auth/CSRF/session revocation, and desktop/mobile
form behavior and navigation/help. The development package builder passed.

Packaged and deployed as **1.0.0-r45**, created 20 November 2026 at 17:39 AEDT.
Artifact: `local/stm32-lte-router_1.0.0-r45_all.ipk`; deployment record:
`local/r45-install-result.txt`. Rollback backup on the board:
`/root/router-before-r45-20261120-064039/` (directory suffix uses board UTC).
Package file hashes and configuration preservation passed. All previously
running router services restarted, firewall validation passed, and TCP 11111
`AT$VERSION` reported r45. Final Internet ping and HTTPS passed. This updates
the active installation; no reboot or standby root-slot update was performed.
