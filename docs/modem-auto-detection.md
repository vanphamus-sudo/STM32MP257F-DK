# Automatic Quectel modem selection

The router supports these USB devices:

| Module | USB ID | Data connection | Radio mode |
| --- | --- | --- | --- |
| RG255C-GL | 2c7c:0316 | QMI, interface 3; existing DTR binding workaround | Saved RG255C mode; first switch defaults to LTE/5G, preferring 5G |
| EM060K-GL | 2c7c:030b | Existing MBIM or QMI kernel driver | LTE only |
| RM520N-GL | 2c7c:0801 | Existing QMI kernel driver, interface 4 | Saved RM520N mode; first switch defaults to LTE/5G, preferring 5G |

The procd-managed `router-modem` service scans USB sysfs every five seconds.
It waits for a network interface, resolves the physical device path, and updates
`network.wan.device` when the modem moves between USB ports. Neither modem
numbers nor ttyUSB numbers are fixed. Existing driver bindings are retained.
If multiple supported modems are connected, the currently configured device wins;
without a matching configured device the service reports ambiguity instead of
arbitrarily switching uplinks.

Radio preferences are remembered per model in `/etc/router-web/modem-auto.json`.
When swapping from RG255C to EM060K, forced 5G is replaced with LTE and the
RG255C preference is retained for its return. RM520N has an independent mode
profile; a new RM520N profile enables 4G/5G with 5G preferred. Explicit saved
preferences are retained separately for each 5G model. APN, SIM PIN,
firewall, LAN and other user settings are preserved. Detection does not bypass
a SIM lock or guarantee mobile network registration.

Configuration changes are deferred while network edits are staged in UCI,
to avoid committing unrelated settings. Runtime selection is available in
`/var/run/router-modem-auto.json`. Start/stop with `/etc/init.d/router-modem`.
The service and USB binding hook are included by both package build paths.

Validation on 20 November 2026: transition tests cover both IDs, waiting for
driver readiness, port selection, ambiguous devices, removal, per-model radio
preferences, and pending UCI changes. The connected RG255C was detected live
with its existing 5G-only preference retained. Physical EM060K swap testing
still requires connecting that module; fixture tests do not establish live
EM060K data connectivity.

Subsequent physical EM060K-GL power-on verification passed: the service
automatically selected EM060K-GL and LTE-only mode, retained the RG255C
4G/5G profile, and WAN connected without manual configuration. Telstra LTE
band 3 was observed. Five Internet pings had no loss (42.6 ms mean), LAN DNS
answered, and interface-bound HTTPS returned 200. No USB disconnect appeared
in the boot log during this check.

RM520N-GL support was subsequently installed and verified on the connected
`2c7c:0801` device. All nine Linux detection/transition tests passed. The live
service selected RM520N-GL and saved its independent 4G/5G, 5G-preferred
profile while retaining both other profiles. No SIM was inserted during this
verification, so cellular connectivity was not tested. The development IPK
builder also completed successfully.
