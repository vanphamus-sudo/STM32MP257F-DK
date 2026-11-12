# Guided settings page (r37)

The router webpage now includes a beginner-oriented user guide. Open the page
and choose **System → Start here / user guide**, or read the guide beneath the
connection summary. The existing feature groups and controls remain available.

The page provides:

- A getting-started checklist: management access, connection checks, saving,
  confirming network changes and checking results.
- A plain-language glossary for LAN, WAN, IP addresses, subnets, MAC addresses,
  DHCP, DNS, gateways, VLANs, VPNs, certificates, NAT and data/speed units.
- Thirty-nine feature topics explaining the purpose, setup steps, illustrative
  values, success checks and troubleshooting.
- Explanations beside 149 fixed settings fields, plus help for the eight types
  of dynamically added Modbus device/register fields.
- A searchable topic index that includes individual setting names and accepts
  searches such as `wifi`, `keepalive`, `certificate` and `data allowance`.
- Read-only explanations for unavailable features without exposing or enabling
  their hidden settings controls.

Examples are descriptions, not presets. Opening help, following a topic link or
searching does not populate, apply or submit a configuration. Real server details,
keys, certificates, carrier settings and meter register maps must come from their
operators. The guide explains those dependencies, hardware limitations, reboot
requirements, confirmation windows and the exclusive nature of IP passthrough.

## Installation and validation — 12 November 2026

Installed r37 on the board's running root slot. The existing configuration was
verified unchanged, packaged files were hash-checked, active services restarted
successfully, and the firewall check passed. USB management and the new guide
script returned HTTP 200. No reboot or standby-slot update was performed.

Pre-upgrade r36 rollback backup:
`/root/router-before-r37-20261112-035100/`. The final same-release help refinement
checkpoint is `/root/router-before-r37-20261112-035346/`. Each contains the
application rollback IPK, configuration/application archive and installation
report. Directory names use the board clock.

Validation completed:

- 195 Python tests, with six platform-specific skips.
- Real browser viewports of 1440 and 390 pixels: help-topic/field coverage,
  accessible descriptions, search (including individual fields and punctuation
  variations), navigation/focus, unavailable-feature help, dynamic meter fields,
  unchanged example/unsaved values, unique identifiers and no horizontal overflow.
- Existing feature-form, Ethernet and USB browser checks.
- Visual review of the phone guide and on-board served HTML/script verification.

This changes the guidance and presentation. It does not enable passthrough,
change network addresses, configure servers or establish new hardware acceptance
results. End-to-end passthrough/client and physical recovery checks are still
required as documented in their feature guides.
