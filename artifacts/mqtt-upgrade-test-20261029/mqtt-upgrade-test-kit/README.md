# MQTT application upgrade test kit

Two test variants, A and B, differ only in application identity. Production
services, webpage behavior, MQTT telemetry and configuration formats are retained.
The router webpage software version and AT$VERSION identify the test variant;
MQTT DEVINFO/BASE.softver reports its numbered release.

The updater accepts only newer versions. Follow the four steps in order to test
A -> B -> A -> B without disabling downgrade protection. Replaying r21 after
r22 is deliberately rejected. These are application updates; they restart
services and do not switch the OS A/B slot or reboot the router.

| Step | Variant | Required base | Target | Bytes | Signed delta |
| --- | --- | --- | --- | --- | --- |
| 1 | A | 1.0.0-r20 | 1.0.0-r21 | 3619 | `router-test-A-r21.rupdate` |
| 2 | B | 1.0.0-r21 | 1.0.0-r22 | 3599 | `router-test-B-r22.rupdate` |
| 3 | A | 1.0.0-r22 | 1.0.0-r23 | 3600 | `router-test-A-r23.rupdate` |
| 4 | B | 1.0.0-r23 | 1.0.0-r24 | 3599 | `router-test-B-r24.rupdate` |

1. Host the four top-level `.rupdate` files on an HTTPS server with a valid
   certificate, port 443. The kit does not create or publish a download server.
2. In router System -> Remote updates, enable updates, paste the contents of
   `signing-public.pem`, and allow the download hostname (plus redirect hosts).
   Never upload the private signing key. The router was not reconfigured by this build.
3. Replace YOUR-UPDATE-HOST in `mqtt-commands.json` with that hostname.
   Publish the step's JSON payload to `/RX/STM32-001/UPGRADE` with retain OFF,
   using your authorized MQTT publishing account after the router has logged in.
4. Watch `/TX/STM32-001/UPGRADE` for `result: accepted` and then `result: succeed`.
   Check System -> Remote updates status and DEVINFO/BASE.softver before the next
   step. Broker acknowledgement alone does not prove installation succeeded.

The initial delta requires the exact installed r20 application files. A read-only
kit check confirmed all 43 files matched when this kit was prepared. Local edits
can invalidate a delta base. `full/` contains larger full A/r21 and B/r22 bundles
for base recovery, but full bundles still cannot downgrade an installed version.
The IPKs are build inputs for future deltas, not MQTT download payloads.

For additional cycles, run scripts/build-mqtt-upgrade-tests.py with the final
IPK as --base, --start-release 25 (or another newer unused release), an empty
--output directory, and the same local --private-key. Keep the key private.
All deltas were signature-verified and reconstructed against their preceding
application files; reconstructed metadata, modes and bytes matched the targets.
Actual MQTT installations are left for your test; no release was installed.
