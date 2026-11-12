# Stable webpage refresh (r41)

Installed on the running router on 12 November 2026. Configuration was verified
unchanged, package hashes matched, services restarted successfully, the firewall
check passed and the USB webpage/help script returned HTTP 200. No reboot or
standby-slot update was performed. Rollback backup:
`/root/router-before-r41-20261112-061941/`.

Periodic status updates previously replaced unchanged text nodes and rebuilt
the client, traffic, VPN-certificate and Modbus-file lists. SMS polling also
replaced a potentially long inbox with a short loading message until its reply
arrived. Those changes disrupted the browser's scroll anchoring.

The status renderer now keeps unchanged text and list elements in place.
Changed lists are built off-screen and replaced in one operation. MQTT,
firmware and Modbus labels also avoid replacing unchanged text. Polling keeps
the current SMS messages visible, preserves unchanged delete controls, and puts
the checked time and read errors in a separate reserved status area. Background
polls do not change the Read inbox button while waiting. Manual initial reads
still provide loading feedback; failures retain any previously loaded messages.
Logout clears cached inbox data and its rendering signature.

This preserves the browser's normal scrolling behavior without forcing the
scroll position back after a user scrolls. Settings, network selection, SMS
sending/deletion and the refresh interval retain their existing behavior.

Validation:

- Real browser viewports at 1440 and 390 pixels: four repeated status refreshes
  preserve scroll position, input focus, unsaved MCC selection and unchanged
  text/table nodes. A changed client name still appears.
- Delayed SMS polling preserves the scroll position and current inbox both
  while the response is pending and after it arrives. Unchanged message text
  and delete buttons remain the same elements.
- Feature, traffic, Modbus, MQTT, firmware and navigation/help browser checks.
- All 209 Python tests passed, with six platform-specific skips.
