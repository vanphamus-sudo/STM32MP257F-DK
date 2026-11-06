# Software releases

| Version | Creation time (Australia/Sydney) | Change |
| --- | --- | --- |
| 1.0.0-r28 | 2026-11-06 (see version_info.py) | Automatically load Ethernet settings after sign-in so the port-mode selector is enabled without a sidebar click |
| 1.0.0-r27 | 2026-11-06 (see version_info.py) | Persistent serial port selector for TCP bridge, Modbus collection or Disabled; installed and verified with the COM1 simulator |
| 1.0.0-r26 | 2026-11-05 16:31:26 +11:00 | Always-visible Modbus serial settings with meter setup guidance |
| 1.0.0-r25 | 2026-11-05 (see version_info.py for creation time) | Modbus RTU multi-device CSV collection, retention, exports and scheduled FTP/FTPS uploads; installed and verified on the board |
| 1.0.0-r12 | 2026-10-26 17:32:25 +11:00 | LAN DHCP MAC-to-IP bindings with lease suggestions and conflict validation |
| 1.0.0-r11 | 2026-10-26 17:16:03 +11:00 | Optional WAN DMZ host with specific-forward priority and version 2 JSON import/export |
| 1.0.0-r10 | 2026-10-26 16:16:57 +11:00 | Port forwarding editor/API, ranges, source restrictions, WAN/VPN zones, NAT loopback and JSON import/export |
| 1.0.0-r7 | 2026-10-02 16:44:33 +10:00 | Pure data bridge on 5000; separate AT server on 11111 with reserved AT$ routing |
| 1.0.0-r6 | 2026-10-02 16:37:34 +10:00 | Shared version identity, webpage display and local AT$VERSION response |

`web/version_info.py` stores the immutable version and creation timestamp for a
release. Update both when creating a new release and add a row here. IPK builds
check that the metadata version matches the Makefile. Package and factory
builders include the same metadata file; restarting or installing a release
does not change its creation time.

The authenticated settings page displays the full version string. Its status
API exposes `software.version`, `software.created_at` and `software.string`.
The webpage AT console also accepts `AT$VERSION` and answers locally.

For r6, on the LTE TCP data bridge (port 5000), send the exact, uppercase command
`AT$VERSION` at the start of a line, terminated by CR, LF or CRLF. The reply is:

```text
STM32 Router 1.0.0-r6 | created 2026-10-02T16:37:34+10:00
OK
```

This reserved command does not reach the attached serial device. Other bytes
are forwarded. Split packets are supported; a partial reserved prefix is
forwarded after 0.5 seconds without more input to avoid holding ordinary serial
data indefinitely. Complete each version query without longer inter-byte gaps.
Single-client ownership and the 60-second idle policy remain in effect.

R6 was deployed to the dev kit on 2026-10-02 with a private backup at
`/root/router-before-version-20261002/config-and-app.tar.gz`. The version query
passed over public LTE TCP, including split packets. Seven on-board isolated
serial tests passed, including local interception and ordinary forwarding.
The webpage/API version and LTE services were checked after deployment.
