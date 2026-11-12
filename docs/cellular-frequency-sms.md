# Cellular frequency, network selection and SMS (r38)

## r40: clickable bands and visible country controls

Installed on 12 November 2026 with settings preserved and no reboot. Package
hashes, service startup, firewall validation and USB web access passed.
Rollback backup: `/root/router-before-r40-20261112-060057/`.

The separate read-only frequency list and native multiple-selection control
were replaced with a single checkbox list. Clicking anywhere on a band row
toggles that band; multiple selections need no modifier key. Automatic clears
restrictions, and removing the last specific band restores Automatic. Saved
restrictions and unsaved edits remain intact during status refreshes.

MCC/MNC dropdowns now have their own visible fieldset, and Modem status links
directly to these settings. The live router supplied 220 MCC entries and 31
supported LTE bands during diagnosis. No missing directory data was found.

Validation includes actual browser pointer clicks on band checkboxes at 1440-
and 390-pixel viewports, verifying multiple selection and Automatic, plus
visibility/hit-testing of the MCC dropdown with the full country directory.
Phone screenshots were visually checked. All 209 Python tests passed (six
platform skips), and the feature-form and navigation/help browser checks passed.

## r39 selection and deletion controls

Installed on 12 November 2026 with settings and both existing stored SMS
messages preserved. Rollback backup: `/root/router-before-r39-20261112-054525/`.
Package hash checks, service startup, firewall validation and USB webpage/help
HTTP checks passed. No reboot or standby-slot update was performed.

Choose Australia (MCC 505) opens the MNC selector with the directory's Australian
network names and codes, including Telstra 01, Optus 02 and Vodafone 03.
Automatic registration remains the saved default unless explicitly changed.
The reference edition and availability limitations still apply.

LTE bands now use a selectable list of named bands with MHz ranges, rather
than requiring typed codes. Multiple bands are supported; on a computer use
Ctrl/Command-click. Automatic and specific restrictions are mutually exclusive.
Unsaved selections survive background status refreshes; Apply uses the existing
network confirmation/rollback mechanism.

Each displayed SMS has a numbered Delete button. Confirmation is required,
then only that message is removed and the inbox is refreshed. The API validates
an integer identifier and checks it belongs to the current modem before using
[ModemManager's deletion operation](https://www.freedesktop.org/software/ModemManager/man/latest/mmcli.1.html).
Existing authentication, CSRF protection and the SMS-enable setting apply.
No existing messages were deleted during deployment. Deletion behavior was
tested with mocked modem responses and browser fixtures, including cancellation
and the refreshed remaining-message list.

Validation: 209 Python tests passed with six platform skips, plus desktop/mobile
feature and navigation/help browser checks. Live read-only verification found
two readable stored messages with no failures and LTE band 28 at 778 MHz.

Installed on the running router on 12 November 2026. Existing settings were
verified unchanged, package files hash-checked, active services restarted and
the firewall check passed. No reboot or standby-slot update was performed.
Rollback backup: `/root/router-before-r38-20261112-053120/`.

The modem band display includes downlink/uplink ranges in MHz and, when the
reported LTE channel is valid, the current downlink frequency. The live modem
reported LTE band 3, downlink 1805–1880 MHz, uplink 1710–1785 MHz and current
downlink 1812.5 MHz. Supported LTE bands also have MHz reference labels in
Cellular settings. Unknown channels do not produce estimated frequencies.

Country/network-area (MCC) and operator (MNC) selectors show names and retain
leading zeros: Australia 505 plus Telstra 01 saves 50501. Automatic selection
remains available, alongside explicit custom codes. Selecting an entry does
not register the modem until the settings are saved. Current registration is
shown separately from saved automatic selection.

The offline directory has 220 MCC entries and 2,255 operator codes from
[ITU Operational Bulletin 1280, 15 November 2023](https://www.itu.int/dms_pub/itu-t/opb/sp/T-SP-E.212B-2023-PDF-E.pdf).
Its edition is shown in the UI; it is a reference directory, not a scan of
currently available networks. The modem's live operator name takes precedence
for its registered code. Source metadata and checksum accompany the JSON.
The generator consumes positioned PDF table text to retain wrapped names and
split numeric codes. LTE frequency mapping follows
[3GPP TS 36.101 via ETSI](https://www.etsi.org/deliver/etsi_ts/136100_136199/136101/15.06.00_60/ts_136101v150600p.pdf).

Read inbox previously expected nested JSON, while the modem returns the flat
`modem.messaging.sms` key. Both response forms are now handled. The live modem
had two stored messages: one received and one sent. Both were read successfully
without printing their contents. This verifies stored-message retrieval;
receipt of a new test message was not independently timed.

The inbox has immediate loading/error feedback, received-only/all-stored views,
a checked timestamp and automatic refresh every 15 seconds while open. Reading
does not delete messages or mark them read. Partial failures and oversized
inboxes are reported, and logout clears cached messages.

Validation: 207 Python tests completed successfully (six platform skips),
feature-form browser checks at desktop/mobile sizes, and full navigation/help
checks at actual 1440- and 390-pixel viewports. On-board validation confirmed
SMS retrieval, named network choices, MHz options, live frequency and HTTP 200
for the webpage and help script.
