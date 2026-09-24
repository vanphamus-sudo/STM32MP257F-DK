# Initial inspection: 2026-09-23

- Read the saved VS Code/Copilot discussion from `AI helper.docx`.
- No source project existed in this directory before this starter was added.
- Windows reports ST-Link Debug and Bridge with OK status.
- ST-Link virtual serial ports: COM6 (first) and COM7 (second).
- Both ports could be opened at 115200 8N1. Neither returned output during
  a short probe after sending Enter. This does not establish whether Linux is booted.
- No STM32 USB network adapter was listed in the Windows network adapter inventory.
- Git, OpenSSH and Git Bash are installed. WSL has no installed Linux distribution.
- BSP release, boot media, board power state, Linux console mapping, interface names,
  SSH address and target packages are still unconfirmed.
- User selected Quectel EM060K-GL, Telstra SIM, APN `telstra.extranet`.
  Modem attachment, USB carrier, enumeration and data connection remain unverified.
- No board firmware, network settings or installed services were changed.

Next hardware milestone: capture a Linux console and run `scripts/board-status.sh`.

User follow-up: no screen and no microSD card inserted. An existing eMMC Linux
installation has not been confirmed. Prepare bootable OpenSTLinux media before
continuing router deployment; a display is not required for serial-console use.

User has no microSD card available. Continue with onboard eMMC as the intended
installation target. STM32CubeProgrammer is installed at
`C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin`.
No eMMC writes have been performed. Next prerequisite: USB data connection to
CN15 in forced USB boot mode; CN21 supplies power/ST-Link console access.
The matching OpenSTLinux image and its DK eMMC layout still need to be obtained
and checked before flashing. Existing eMMC contents remain unknown.

After the user connected the second USB cable, CubeProgrammer v2.19.0 still
reported no STM32 DFU device. Windows lists only ST-Link USB interfaces, all with
healthy drivers; no STM32 DFU or USB error device was listed. Next check: reset
with CN15 connected and confirm boot switch positions, data cable and board power.

Resolved after user moved the second cable to another PC USB socket: CubeProgrammer
now detects USB1, DFU in HS Mode, device ID 0x0505, revision 0x2000, serial
001A00254C42501400313951. Windows reports the DFU interface healthy. Keep the
current wiring and forced USB boot settings. No flash writes performed.
No OpenSTLinux image archive was found in the project or user's Downloads folder.

Package subsequently supplied by user: FLASH-stm32mp2-openstlinux-6.6-yocto-scarthgap-mpu-v26.06.10.tar.gz
(687152696 bytes). Extracted successfully under `local/` after checking archive
member paths. SHA256 recorded for reproducibility (not compared to a vendor digest):
`836B4BF62EF33295CDA928B342DD44BAD2D5F28567E554DCBEBB825F6C3BBA5E`.
Selected `flashlayout_st-image-weston/optee/FlashLayout_emmc_stm32mp257f-dk-optee.tsv`.
All 12 referenced binary entries exist and are nonempty. Persistent entries target
mmc1, including boot1/boot2, firmware metadata and Linux filesystem partitions.
USB1 still identifies serial 001A00254C42501400313951. Ready for user confirmation
to overwrite eMMC; no flash operation has been executed.

User authorized flashing with "Go ahead". Executed the prepared board-specific
eMMC flash using CubeProgrammer v2.19.0 after rechecking the single DFU target's
serial. The process exited with code 0 and reported "Flashing service completed
successfully". All image programming stages through userfs (partition 0x13)
completed successfully. OpenSTLinux v26.06.10 is now programmed to eMMC.
Independent readback verification was not performed. Linux boot is not yet
confirmed; next physical step is power down and select BOOT0=0, BOOT1=1,
BOOT2=0, BOOT3=0, then power on and check the serial console.

Linux boot confirmed after user selected eMMC and powered on. COM6 provides a
root shell. OS is OpenSTLinux Weston v26.06.10 (Yocto scarthgap 5.0.17), kernel
6.6.129. Root filesystem reports 2.8 GB total, 2.1 GB available.
Interfaces: end0 DOWN, wlan0 DOWN, usb0 UP at 192.168.7.1/24. Windows detects
UsbNcm Host Device (Ethernet 2) at 192.168.7.114/24. Board has no default route.
systemd-networkd is active. NetworkManager, ModemManager, dnsmasq and nftables
services are inactive; nmcli/mmcli/dnsmasq/nft commands were not found.
apt, apt-get, dpkg, Dropbear, Python3, curl and wget are available. An ST package
feed file exists at /etc/apt/sources.list.d/packages.openstlinux.st.com.list;
its availability has not been tested. lsusb lists only root hub and onboard USB hub,
not the EM060K-GL. Next requirements: modem attached to board USB host and Internet
access or offline packages. Router templates now use end0 and permit SSH over usb0.

Ethernet connected and working: end0 192.168.40.102/24, gateway 192.168.40.250,
DNS 192.168.40.5. ST apt index refresh succeeded using the configured HTTP feed
at packages.openstlinux.st.com/6.2.1 (main, updates, untested).
The package simulation found nftables 1.0.9, dnsmasq 2.90, ModemManager 1.22.0,
NetworkManager/nmcli 1.46.6 in untested; 15 new packages, no removals/upgrades.
EM060K-GL still absent from lsusb.

Installation was NOT executed: automatic approval review rejected the command
that would write NetworkManager unmanaged-interface configuration for end0,
usb0 and wlan0, mask dnsmasq/nftables/NetworkManager/wait-online services, and
install the packages. Stated concern: persistent service/security changes exceed
general project authorization and could disrupt networking or weaken protection.
Explicit user approval requested for these changes. Existing networking remains
unchanged; apt index refresh is the only completed package-management change.

User explicitly approved package installation and preserving networkd ownership,
with NetworkManager/DHCP/firewall inactive. Installation completed and
`dpkg --audit` returned no issues. Installed nftables, dnsmasq, modemmanager,
networkmanager and networkmanager-nmcli with dependencies. Two post-install scripts
initially failed while trying to enable masked units; repaired with temporary
ConditionPathExists guards and `dpkg --configure -a` (exit 0), then disabled and
re-masked affected services. Final verified state:

- systemd-networkd and ModemManager active.
- NetworkManager, dnsmasq and nftables inactive and masked; NM wait-online masked.
- /etc/NetworkManager/conf.d/90-router-preserve-links.conf marks end0, usb0 and
  wlan0 unmanaged by NM. Existing networkd configuration retained.
- dnsmasq and NetworkManager have 90-router-staging.conf service drop-ins requiring
  /run/router-services-approved. Remove these staging guards only when activating
  tested service configuration; unmasking alone will not start them.
- Ethernet address/default route retained; USB management address remains configured.
- nft list ruleset succeeds and is empty. No router firewall or DHCP was activated.
- EM060K-GL enumerates as 2c7c:030b with ttyUSB0-3 bound to option driver.
- No modem network/control interface appeared; mmcli -L reports no modems.
- qmi_wwan and cdc_mbim are absent. /proc/config.gz has CONFIG_USB_USBNET=m but
  no enabled CONFIG_USB_NET_QMI_WWAN, CONFIG_USB_NET_CDC_MBIM or CONFIG_USB_WDM.
  The matching ST apt feed search has no qmi-wwan/cdc-mbim/cdc-wdm modules.

Next LTE task: determine the modem's current USB composition and provide compatible
kernel driver support (or evaluate another supported modem composition). Do not
claim LTE connected or reconfigure Ethernet as LAN yet.

QMI/MBIM driver request completed:

- Obtained ST Linux sources at v6.6-stm32mp-r3.1, commit
  548f960c059bc4b9165cb69895fd67551f6061ca. Built unchanged cdc-wdm.c,
  cdc_mbim.c and qmi_wwan.c as external modules with matching kernel-devsrc headers,
  configuration and Module.symvers. Development archive checksum matches ST index.
- kernel-devsrc could not be installed normally due to unavailable libmpc-dev and
  openssl-dev dependencies; extracted only as build data under /usr/local/src/router-drivers.
  Compiler/build tool packages installed normally, with clean dpkg audit afterward.
- Compiler matches running kernel: GCC 13.4.0. Normal kernel compatibility checks
  passed; no force-loading. All three modules load successfully on kernel 6.6.129.
- Installed to /lib/modules/6.6.129/extra/router; depmod resolves dependencies.
  /etc/modules-load.d/router-modem.conf requests loading at boot (reboot not tested).
- MBIM driver binds to USB interface 8, creates /dev/cdc-wdm0 and wwu1u1i8.
  mmcli discovers Quectel EM060K-GL at modem 0, quectel plugin, cdc_mbim driver,
  Telstra_Australia_Commercial carrier configuration. Modem state is disabled;
  no cellular connection was initiated. QMI runtime load passed but its data path
  was not tested because modem composition is MBIM.
- systemd-networkd remains active; Ethernet Internet and USB management addresses
  retained. NetworkManager/dnsmasq/nftables remain inactive and masked.
- Reproducible scripts/notes in drivers/modem. Built .ko files and logs copied to
  local/modem-driver-artifacts. Router firewall template WAN updated to wwu1u1i8.

LTE connection verified on user's request:

- Ethernet DHCP address changed to 192.168.40.53. SSH verified with the same saved
  board host key; Ethernet still uses gateway 192.168.40.250, metric 10.
- NetworkManager was temporarily activated for LTE, but ST's package lacks the WWAN
  plugin and the feed has no networkmanager-wwan package. Its router-lte profile was
  created with autoconnect off but cannot activate with this build. NetworkManager
  was stopped and masked again; dnsmasq and nftables remain inactive/masked.
- Connected directly through ModemManager with APN telstra.extranet, IPv4. Modem
  reports connected, LTE access technology, home registration on Telstra (50501).
- Applied the data bearer's static IPv4 settings to wwu1u1i8, with LTE default route
  metric 700. Carrier DNS configured through systemd-resolved. Ethernet remains the
  preferred general Internet path; interface-bound tests specifically used LTE.
- Verified 3/3 ICMP replies from 1.1.1.1, HTTPS over LTE, carrier-DNS resolution
  scoped to wwu1u1i8, and HTTPS https://example.com returning HTTP 200 over LTE.
- /etc/systemd/network/10-router-wwan.network leaves only WWAN links unmanaged;
  Ethernet/USB management remains under systemd-networkd.
- scripts/connect-lte.sh and connect-lte.py are deployed to
  /usr/local/src/router-drivers on the board. Repeated invocation succeeds on the
  existing bearer and derives IP/gateway/DNS dynamically. This is an on-demand
  connection; automatic reconnect/reboot persistence of LTE activation is not set up.
- NetworkManager staging guard was renamed to .conf.disabled during its attempted
  activation; the service remains held by its restored mask. Its inactive profile
  and no-auto-default/DNS configuration remain staged for possible future use.

LTE speed test completed on 2026-09-23 using Cloudflare HTTPS endpoints, with curl
explicitly bound to wwu1u1i8 and proxies disabled. All four transfers returned HTTP
200, exact expected payload sizes, and the LTE local address. Two 25 MB downloads
measured 51.46 and 55.32 Mbps; aggregate 53.32 Mbps. Two 8 MB uploads measured
12.82 and 23.80 Mbps; aggregate 16.67 Mbps. Ping to 1.1.1.1: 38.03 ms average,
5/5 replies, no observed loss. Total bulk payload 66 MB plus protocol overhead.
These are short single-stream results, not a maximum-capacity multi-stream test.
Raw measurements: logs/lte-speedtest-20260923.json; reusable script:
scripts/lte-speedtest.py.

Router activation preparation on 2026-09-24 (PC date):

- User authorized changing Ethernet to 192.168.10.1/24 with DHCP and LTE NAT.
- Verified SSH over USB 192.168.7.1 against the saved board host key using
  HostKeyAlias=192.168.40.102. Ethernet is still 192.168.40.53/24 with an
  upstream DHCP router; physical isolation has been requested before activation.
- Reconnected LTE with the deployed helper; interface-bound HTTPS returned 200.
- dnsmasq configuration syntax check passed. USB already runs networkd's DHCP
  server; retain its configuration and permit USB DHCP in the router firewall.
- nftables validation failed: kernel CONFIG_NF_TABLES_INET and
  CONFIG_NF_TABLES_IPV4 are disabled. Installed legacy iptables 1.8.10 and kernel
  modules support an alternative without rebuilding the kernel.
- Added config/router-iptables.rules, config/router-ip6tables.rules, and
  config/10-router-lan.network. Both legacy restore --test --noflush checks
  passed on the board; existing legacy rules were empty. Files staged in /tmp.
- No LAN address, firewall rules, forwarding, or DHCP service activation performed.
  Await Ethernet connection to an isolated client/switch. NetworkManager remains
  inactive; systemd-networkd plus ModemManager is the working management stack.
- Still required: backup/rollback setup, apply firewall and LAN, activate dnsmasq,
  verify a client lease and LTE forwarding, then integrate persistent services.

Router activation after user confirmed Ethernet isolation:

- User clarified that a separate test PC is connected directly to board Ethernet.
- Ran scripts/activate-router.sh. Legacy IPv4/IPv6 firewall rules and dnsmasq
  validation passed; enabled live forwarding, changed end0 to 192.168.10.1/24,
  and started router-firewall and dnsmasq. USB 192.168.7.1 remained reachable.
- Backups: /var/lib/router/backup-before-activation. Manual recovery:
  sh /usr/local/lib/router/rollback.sh. Five-minute rollback timer was cancelled
  after live services and continued USB access were verified.
- Observed DHCP request/reply exchange and lease 192.168.10.119 for the test PC.
  Observed DNS requests, 157 NAT flows and bidirectional LTE forwarded traffic
  (about 38 MB inbound at the check). Browser confirmation requested but pending.
- NetworkManager and nftables remain inactive/masked. The active firewall service
  is router-firewall, using legacy iptables. LTE remains on ModemManager/helper.
- Staged config/router-lte.service and router-lte.timer; systemd unit validation
  passed. scripts/enable-router-startup.sh was copied to /tmp but NOT executed:
  automatic approval review rejected persistent firewall/DHCP startup and recurring
  LTE reconnection as beyond explicit authorization for current-session activation.
  Explicit approval is needed for that step. Do not bypass this rejection.
- dnsmasq and router-firewall remain disabled for boot; LAN network file persists.
  Thus live routing works, but reboot persistence is incomplete and untested.

Web settings page added at user request:

- Deployed web/server.py and local HTML/CSS/JS to /usr/local/lib/router-web;
  router-web.service is active and binds only 192.168.10.1:80. Added a scoped
  end0/192.168.10.0/24 HTTP allow rule to live and stored legacy firewall rules.
- Login is admin plus a generated random password stored root-only under
  /var/lib/router-web/initial-password. PBKDF2 hash is in credentials.json.
  Password is not in project source. Session and request protections implemented.
- UI supports live LTE/signal, services, addresses and client status, plus DHCP
  range/lease time and upstream DNS editing. Validation, backup and failed-restart
  rollback implemented. Other board settings are currently read-only.
- Four unit/integration tests passed on target, JavaScript syntax check passed,
  deployed API smoke test passed, and real Chrome desktop/mobile login and save
  passed with no JS errors or horizontal page overflow. Existing DHCP/DNS settings
  were reapplied unchanged during the checks; client lease and LTE remained active.
- Browser screenshots saved under logs/router-web-*.png. Documentation:
  docs/web-settings.md. Browser used USB SSH tunnel; end0 HTTP rule is installed.
- No boot services or LTE retry timer enabled. router-web is active but disabled
  for boot, retaining the prior approval boundary. Reboot remains untested.

Web login customization added at user request:

- Added Account / Login details form for username and password changes with
  current-password verification, password confirmation and request throttling.
- Existing credentials without a username field remain compatible as admin.
  Username-only changes retain the password hash; password changes generate a
  fresh salt. Credential writes are atomic and mode 0600. All sessions are revoked
  after saving, and the obsolete initial-password file is removed.
- Tests use temporary credentials; the user's current login was not changed.
- Deployed and restarted router-web. Five tests passed, including old/new login,
  username-only changes and revoking two sessions. Live API smoke check passed
  after socket startup; Chrome verified the account form rejects a wrong current
  password, with no JS errors or desktop/mobile page overflow.

User requested a four-character minimum and default admin/admin login:

- Updated server and browser validation to 4–256 characters (blank still keeps
  the current password). Fresh installs now initialize admin/admin, without
  overwriting existing credentials on routine installation.
- Explicitly reset the live board login to admin/admin and restarted router-web,
  clearing existing sessions. Four-character acceptance/three-character rejection
  test passed; live admin/admin login and deployed HTML minimum verified.

Wi-Fi hotspot enabled at user request (2026-09-24):

- Confirmed brcmfmac supports AP mode and hostapd 2.10 is installed. User chose
  hotspot mode to share LTE. Created WPA2/CCMP SSID STM32-LTE on channel 6,
  country AU, wlan0 192.168.20.1/24. Initial password was supplied to user and is
  stored root-only at /usr/local/lib/router/initial-wifi-password until changed.
- router-hotspot.service is active but disabled for boot. No boot or LTE retry
  services were enabled. Wi-Fi DHCP pool is 192.168.20.50–200 with 12-hour leases;
  Wi-Fi DHCP options override Ethernet options via the wifi tag. LTE NAT/return
  traffic and local DNS/HTTP are allowed; Ethernet/USB forwarding stays blocked.
- Added hotspot name, password, channel and on/off settings to the web page.
  Wi-Fi password must be 8–63 ASCII characters; web login remains minimum four.
  Stored derived PSK is never sent by the API. SSID changes require the password
  again. Failed apply attempts restore the previous hostapd configuration/state.
- hostapd_cli uses a writable shared client socket directory /var/lib/router-web
  so status/apply verification works inside router-web's filesystem isolation.
- Two hotspot validation/rollback tests passed. Deployed authenticated status
  and apply test passed. Chrome desktop/mobile hotspot panel check passed without
  JavaScript errors or page overflow. DNS settings save preserves Wi-Fi DHCP include.
- User connected a Wi-Fi client and explicitly confirmed both http://192.168.10.1
  and Internet access work. Ethernet and USB management were preserved.
- Source: web/wifi.py, config/router-hotspot.service, config/wifi-dhcp.conf and
  scripts/install-router-wifi.py. Documentation: docs/web-settings.md.

Local validation: Git Bash shell syntax check and PowerShell parser check passed.
Target nftables/dnsmasq validation and end-to-end routing have not been run because
Linux access is not established and these tools are not available on this host.
