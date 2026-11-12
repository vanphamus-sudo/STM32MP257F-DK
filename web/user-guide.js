'use strict';
// Guidance is read-only: examples never populate or submit a setting.
const routerManualTopics = {
  'connection-details': ['Connection details', 'Status',
    'This is a read-only summary of the router. An IP address is a device address, like a house number on a network. The LTE address belongs to the mobile connection; the LAN and USB addresses let you manage this router locally.',
    ['Look for a connected LTE state and an LTE address.', 'Check uptime to see how long the router has been running. Use LAN clients to see devices that received an address.'],
    'A computer on the normal Ethernet LAN might have 192.168.10.100. The router settings page is 192.168.10.1:8081. USB management uses 192.168.7.1:8081.',
    'Connected status plus a successful website visit from your computer is a useful basic check.',
    'If LTE has no address, check the SIM, antennas and mobile service. Ask your installer to verify the carrier connection profile (APN); this page does not offer an APN editor.'],
  'lan-clients': ['Connected devices', 'Status',
    'A client is a computer, phone, meter or another router using this router. This table lists DHCP leases: addresses the router has lent to devices. A listed lease does not always mean the device is still connected.',
    ['Find your device by its name or MAC address.', 'Use MAC-to-IP bindings if a device must keep the same local address.'],
    'A meter named MainMeter may appear as 192.168.10.100 with MAC 02:11:22:33:44:55.',
    'Your computer should receive an address in the appropriate local network.',
    'A device with a manually assigned address may not appear. Reconnect the cable or renew its DHCP lease if it has no address.'],
  'traffic-panel': ['Traffic statistics', 'Status',
    'TX means data sent by the router; RX means data received. Totals survive ordinary restarts. The current rate tells you how busy a connection is now.',
    ['Read the SIM totals when checking cellular usage.', 'Use Internet → Data allowance for a monthly warning or cutoff.'],
    'A 5 MB download usually increases SIM RX. Sending a file increases SIM TX. WAN and SIM rows may describe the same traffic: do not add them together.',
    'Rates should change while a client downloads or uploads.',
    'Router counters can differ from the carrier bill. Use your carrier account for the official allowance and billing total.'],
  'lan-settings': ['LAN addresses, DHCP and DNS', 'Local network',
    'LAN means your local devices. DHCP automatically gives them addresses. DNS translates website names into Internet addresses. Most users can keep the supplied settings.',
    ['Choose the first and last addresses the router may lend to devices.', 'Choose how long a device keeps its address, then save. Reconnect clients if they need the new settings immediately.'],
    'On the supplied Ethernet LAN, first address 192.168.10.50 and last address 192.168.10.200 provide 151 addresses. A lease of 12 hours is a practical example. DNS accepts a comma-separated list, such as 1.1.1.1, 8.8.8.8; use resolvers approved by your network owner.',
    'A newly connected computer receives an address in the selected range and can open a website by name.',
    'The end address must be at least the start address. Do not use the router address 192.168.10.1 for a client.'],
  'dhcp-bindings': ['Keep a device address fixed', 'Local network',
    'A MAC-to-IP binding is a reservation: the router gives a particular device the same address each time. This is useful for a meter, printer or device receiving forwarded connections.',
    ['Choose a connected device or enter its MAC address from its label/network settings.', 'Choose an unused Ethernet LAN address, save the entry, then Apply bindings. Renew the device lease afterward.'],
    'Name MainMeter, MAC 02:11:22:33:44:55, reserved address 192.168.10.100. The MAC is only an example; use your device address.',
    'The device receives its reserved address after reconnecting.',
    'Avoid duplicate addresses. Some phones randomize their Wi-Fi MAC; a changing MAC cannot use the same reservation. This editor reserves Ethernet LAN addresses.'],
  'wifi-panel': ['Wi-Fi hotspot', 'Local network',
    'A hotspot lets phones and computers connect wirelessly. SSID is the Wi-Fi name you choose. The Wi-Fi password is separate from the router webpage login password.',
    ['Keep Ethernet or USB connected while changing Wi-Fi.', 'Choose a recognizable name and a password, apply, then reconnect wireless devices using the new details.'],
    'Wi-Fi name Site-Office; choose your own 8–63 character password. Supported channel choices are 1, 6 and 11 on 2.4 GHz. Wi-Fi clients use 192.168.20.x.',
    'Your chosen name appears in the phone/computer Wi-Fi list and the client can browse the Internet.',
    'Changing the name or password disconnects wireless clients. Do not enter the webpage login password unless you deliberately want to reuse it.'],
  'usb-panel': ['USB tethering and USB management', 'Local network',
    'USB provides a local management connection. Tethering additionally lets a connected computer use the router as an Internet gateway. Gateway means the device that sends traffic toward the Internet.',
    ['Use Off if USB is only for management and your computer should keep another Internet connection.', 'Use On to advertise the router as the USB Internet gateway. Save, reboot when ready, then reconnect USB or renew the computer lease.'],
    'A computer using office Ethernet for Internet can leave USB gateway Off and still open http://192.168.7.1:8081 to manage this router.',
    'The USB management page opens. With gateway On and an available uplink, the computer can also use router Internet.',
    'Saving alone does not renew the computer lease. If multiple Internet connections exist, the computer decides which gateway to prefer.'],
  'ethernet-panel': ['Choose the Ethernet port role', 'Internet',
    'LAN connects your local devices. WAN connects an upstream Internet service. Trunk mode carries separate tagged LAN and WAN networks over the same cable and needs a configured managed switch.',
    ['Use LAN for a computer or downstream local switch.', 'Use WAN for an upstream router, or ask your installer to set up LAN + WAN trunk mode. Save for the next reboot; keep USB management connected.'],
    'LAN: connect a laptop directly and receive 192.168.10.x. WAN: connect an office Internet router and let this board obtain an upstream DHCP address. Trunk example: LAN VLAN 10, WAN VLAN 20, with matching switch configuration.',
    'After reboot, clients or the upstream connection receive the expected addresses.',
    'WAN mode removes normal Ethernet LAN access. Do not choose trunk mode for an ordinary unconfigured switch.'],
  'ddns-panel': ['Dynamic DNS', 'Internet',
    'DDNS keeps a name pointing to your changing Internet address. You need an account and hostname from the selected DDNS provider. It does not itself open your firewall or make a private cellular address public.',
    ['Create the hostname with DynDNS or No-IP.', 'Enter its hostname and provider credentials/update key, enable DDNS and apply.'],
    'my-site.example.net illustrates a hostname. Replace it with the real hostname issued by your provider; the example will not connect to your router.',
    'The provider shows the current public address after an update.',
    'If the name is correct but remote access fails, check carrier NAT and the relevant firewall/VPN settings. Do not expose the management webpage simply to test DDNS.'],
  'port-forwarding-panel': ['Reach a local service from outside', 'Firewall',
    'Port forwarding directs a specific incoming connection to a local device. A port identifies a service. Use a reservation so that the destination device address stays fixed.',
    ['Confirm the service works locally and reserve its address.', 'Add a rule, stage it, then Apply all changes. Match the service protocol and restrict the source address where possible.'],
    'Example test service: incoming TCP port 8080 → LAN device 192.168.10.100, internal port 80. Use only a service you intend to make reachable. For a range, both ranges must contain the same number of ports.',
    'Test from a different Internet connection, such as a phone using mobile data rather than this router Wi-Fi.',
    'Carrier NAT can prevent all inbound access even with correct rules. The device also needs its own service/firewall configured and a return route through this router.'],
  'pf-dmz': ['DMZ host', 'Firewall',
    'This DMZ setting sends unmatched incoming IPv4 traffic to one local device. It is broad forwarding, not a separate protected network. Specific forwarding rules take priority.',
    ['Leave DMZ Off for ordinary use.', 'If a downstream router must receive unmatched traffic, reserve its local address, verify its firewall, then choose its zone and address.'],
    'A downstream firewall at 192.168.10.2 could be the DMZ host. This is different from IP passthrough: the downstream device still has a private LAN address.',
    'The downstream firewall receives permitted unsolicited traffic where the carrier allows it.',
    'Do not select an ordinary unprotected computer. DMZ cannot bypass carrier NAT and does not isolate the host from its own LAN.'],
  'openvpn-panel': ['OpenVPN client', 'VPN',
    'A VPN is an encrypted connection to another network, for example an office. This router is the client: an existing VPN server and its connection details are required.',
    ['Get the server address, port, protocol, VPN subnet and certificate files from the VPN administrator.', 'While disabled, import the CA certificate, client certificate and client private key, plus a TLS key if required.', 'Match the administrator settings, enable the client and apply.'],
    'Example only: server vpn.example.net, UDP port 1194, VPN subnet 10.87.0.0/24. These are not a working account. The actual server may use a different port, cipher or certificate policy.',
    'The state becomes connected and a local virtual IP appears. A LAN client can then test a permitted office device.',
    'Check router time and certificate expiry, and match TLS key mode/cipher/digest to the server. Ordinary Internet remains on the normal uplink in this managed client setup.'],
  'rf-feature-wireguard': ['WireGuard VPN', 'VPN',
    'WireGuard connects this router to one VPN peer, such as an office router. Keys identify the two ends. The private key stays on this router; give only its public key to the other end.',
    ['Ask the VPN administrator for the private key/address for this router, the peer public key and endpoint.', 'Enter the remote networks under Allowed networks and apply.', 'Confirm connectivity when prompted. Ask the administrator to arrange replies back to your LAN.'],
    'Office example: tunnel address 10.77.0.2/24; endpoint vpn.example.net on UDP 51820; remote network 10.88.0.0/24. A permitted office device might be 10.88.0.10. Keys must be real keys, not these examples.',
    'Service status shows the interface up and a recent handshake after traffic is exchanged.',
    'An interface being up does not prove the peer is reachable. Check keys, endpoint, allowed networks and return routing. 0.0.0.0/0 means all IPv4 destinations; do not use it for a simple office-only connection.'],
  'rf-feature-passthrough': ['IP passthrough', 'Internet',
    'This gives the LTE IPv4 address to one downstream router WAN port. That downstream router becomes responsible for its own firewall. LTE is handed off exclusively; Wi-Fi clients on this board, cloud telemetry and router VPNs cannot share it.',
    ['First verify USB management at 192.168.7.1:8081. Set Ethernet to LAN and connect LTE using IPv4.', 'Disable conflicting VPN, failover, watchdog, guest VLAN, IPv6, port-forward/DMZ, custom routing and flow-offload settings as the application requests.', 'Enter the downstream Ethernet WAN MAC, enable, then renew that router DHCP lease. Verify its Internet access before confirming the change through USB.'],
    'MAC 02:11:22:33:44:55 is a formatting example. Use the real WAN-port MAC. The client gets the carrier address with a /32 mask and gateway route through 192.168.40.1; it must understand DHCP classless routes.',
    'The downstream router receives the LTE address and can reach the Internet. This handoff still needs end-to-end acceptance testing on this project.',
    'Carrier NAT remains in place. If Internet fails, do not confirm; allow rollback or switch passthrough Off using USB. Renew the downstream lease after an LTE address change.'],
  'rf-feature-failover': ['Automatic WAN failover', 'Internet',
    'Failover uses wired Internet first and switches to LTE if the wired service fails its health checks. This is connection backup, not combining the speeds of two Internet services.',
    ['Configure and test Ethernet WAN or LAN + WAN trunk mode first.', 'Ensure LTE also works, enable failover, then test a controlled loss of wired Internet.'],
    'Primary ethernet_wan, backup wan (LTE). With three successful recovery checks required, Ethernet must pass three checks before the router returns to it.',
    'Service status shows the active uplink changing when the primary fails and recovering after stable checks.',
    'Existing sessions may reconnect during a switch. This implementation handles IPv4; it cannot be enabled while exclusive passthrough is active.'],
  'rf-feature-watchdog': ['Connection watchdog', 'Internet',
    'A watchdog checks whether LTE can reach the Internet and attempts recovery after repeated failures. It can reconnect LTE and eventually reset the modem.',
    ['Choose two different public addresses that answer ping on your carrier network.', 'Choose an interval and consecutive-failure count. Start with the supplied values, then enable only after normal connectivity is verified.'],
    'At 60-second checks and three failures, three failed checks trigger recovery. A 300-second base cooldown produces increasing delays between later attempts (the next wait after the first attempt is at least 600 seconds). Recovery is not guaranteed to take exactly three minutes.',
    'Event history records LTE failure, reconnect attempts and recovery.',
    'A reply from either target is considered healthy. Networks that block ping need suitable targets; otherwise a healthy connection could be restarted.'],
  'rf-feature-allowance': ['Monthly cellular data allowance', 'Internet',
    'This estimates how much cellular data you send and receive. It can warn at a percentage and optionally stop clients using LTE at the limit. Router-originated traffic can still consume data.',
    ['Find the allowance and billing day in your carrier account.', 'Enter the allowance in decimal MB, set the warning percentage and choose whether cutoff is wanted.'],
    'A 10 GB decimal allowance is 10000 MB. Warning 80 means warn after about 8000 MB. Billing day 15 starts a new cycle on the 15th at midnight UTC, not the router local midnight.',
    'Service status shows the current cycle, usage percentage and whether client cutoff is active.',
    'The first sample establishes a baseline and cannot reconstruct data used before this feature started. Carrier accounting is authoritative. Both upload and download count.'],
  'rf-feature-sqm': ['Traffic priority / smart queues', 'Internet',
    'SQM reduces the long delays that can occur when a busy connection queues too much data. It trades some peak transfer speed for better responsiveness; it does not increase LTE speed.',
    ['Measure a stable download and upload speed without other large transfers.', 'Ask your installer for the actual Linux WAN device name. Set shaping rates below the measured capacity, enable and compare responsiveness under load.'],
    'If a stable test gives 20 Mbit/s down and 5 Mbit/s up, 18000 kbit/s down and 4500 kbit/s up are illustrative starting rates. LTE capacity varies, so tune for your site.',
    'Calls and interactive traffic remain more responsive while another device transfers a large file.',
    'Do not enter a logical name such as wan if the field needs the underlying device. Rates set too low unnecessarily limit speed; rates above real capacity may not help.'],
  'rf-feature-ipv6': ['IPv6 Internet', 'Internet',
    'IPv6 is another Internet addressing system. This setting requests dual-stack LTE and a prefix: a block of IPv6 addresses the router can share with LAN clients.',
    ['Confirm that the carrier/APN supplies IPv6 and prefix delegation.', 'Enable IPv6, confirm the change and reconnect a LAN client to obtain its IPv6 settings.'],
    'An IPv6 client may receive an address containing colons rather than dots. The carrier supplies the actual address; there is no example prefix to type into this switch.',
    'The client has an IPv6 address and can reach an IPv6 destination.',
    'IPv4 may continue working even if the carrier supplies no delegated IPv6 prefix. IPv6 failover and IPv6 passthrough are not provided here.'],
  'rf-feature-guest': ['Isolated guest / device VLAN', 'Local network',
    'A VLAN is a separate network carried over a tagged Ethernet cable. This feature gives that network Internet, DHCP and DNS while blocking access to the normal LAN, Wi-Fi and management networks.',
    ['Ask your installer to configure Ethernet trunk mode and a matching managed switch.', 'Choose an unused VLAN number and a non-overlapping private /24 gateway address, then apply and confirm from management access.'],
    'VLAN 30 with gateway 192.168.30.1/24 creates a separate 192.168.30.x network. The switch must send this VLAN tagged toward the board and present it appropriately to guest devices.',
    'A guest receives its own subnet address and reaches the Internet but cannot reach normal LAN/USB devices.',
    'This does not create an extra Wi-Fi name. An ordinary unconfigured switch will not provide the required VLAN separation.'],
  'modem-panel': ['Read modem and SIM information', 'Cellular',
    'These read-only values help diagnose mobile service. IMEI identifies the modem; ICCID identifies the SIM; operator and cell identify the network connection.',
    ['Select Refresh to request current information.', 'When asking for help, describe the state and signal readings. Share SIM/device identifiers only with people who need them.'],
    'RSRP is signal strength; RSRQ and SINR describe signal quality. A less negative RSRP is generally stronger, and a higher SINR is generally cleaner. Compare trends at your own site.',
    'A registered/connected modem, usable signal and an LTE address indicate that the cellular connection is established.',
    'A SIM may need activation, PIN handling or a different carrier profile. Missing readings can also mean the modem does not report that measurement.'],
  'rf-feature-cellular': ['Operator, roaming and LTE bands', 'Cellular',
    'Automatic operator and band selection is usually simplest. Roaming allows registration on a partner network and can affect charges or service availability.',
    ['Leave Country / network area on Automatic and bands set to any unless your carrier/installer gives a reason to change them.', 'For manual selection, choose the named MCC country/area and MNC mobile network. Use Other only for exact supplied codes. Apply, test and confirm; simply selecting a name does not change the modem.'],
    'Australia is MCC 505; Telstra uses MNC 01 for the currently registered network. Keep the leading zero. any selects supported bands automatically. Select LTE bands 3 and 28 in the list for a specific restriction. The frequency reference explains each band in MHz; modem status shows its current downlink channel when available.',
    'The modem reconnects to the intended operator and still passes an Internet test.',
    'Choosing the wrong bands/operator can remove LTE service. Use USB for the change and let the confirmation timer roll back if connectivity is lost.'],
  'rf-feature-signal': ['Record LTE signal history', 'Cellular',
    'Signal recording collects measurements over time so you can compare antenna positions and see changes in radio conditions.',
    ['Choose a sample interval and maximum number of saved samples.', 'Enable recording, wait for samples, then open Status → Signal history.'],
    '300 seconds between samples with 288 samples is approximately one day of history. Samples are kept in memory and disappear at reboot.',
    'The graph and recent-sample table fill as measurements arrive.',
    'An empty trace may mean the modem cannot report that measurement. Changing signal conditions are only one possible cause of slow Internet.'],
  'rf-history': ['Understand the signal graph', 'Status',
    'The graph shows signal strength (RSRP), quality (RSRQ) and interference margin (SINR). Each coloured line has its own stated scale, so their heights are not directly comparable.',
    ['Read the scale note under the graph.', 'Use the table for actual values and compare the same measurement over time.'],
    'Compare RSRP before and after moving an antenna; do not compare the green RSRP line height directly with the blue SINR line height.',
    'Repeated samples show whether conditions improved consistently rather than for a single moment.',
    'History starts after recording is enabled and resets on reboot.'],
  'rf-feature-sms': ['SMS settings and alerts', 'Cellular',
    'SMS uses the modem and SIM rather than an Internet messaging app. The SIM plan and modem must support it. Sending messages may incur carrier charges.',
    ['Enable SMS access if supported.', 'Optionally enter an alert recipient, then use SMS inbox & sending to test a short message.'],
    '+61412345678 illustrates an Australian international telephone-number format. Replace it with the intended recipient. The optional alert number receives selected connectivity, recovery and allowance alerts when notifications are enabled.',
    'The modem accepts a test SMS for sending; delivery still depends on the carrier and recipient.',
    'SMS is not remote command control. Check balance, SMS support and number format if sending fails.'],
  'rf-sms-panel': ['Read, send and delete SMS', 'Cellular',
    'The inbox reads messages stored on the modem. Sending submits a short text through the SIM. To delete, match the SMS number to its Delete button and confirm. Deletion permanently removes that message from modem storage.',
    ['Enable SMS under SMS settings first, then open the inbox or choose Read inbox. It refreshes every 15 seconds while open.', 'Received only hides sent/draft messages; All stored shows every readable stored message. Reading does not delete messages or mark them unread/read.', 'For sending, enter the full telephone number and a short test message, then choose Send SMS.'],
    'Test message: Router connection test. This build accepts up to 160 characters from a restricted plain-text set; do not use commas, quotes or line breaks.',
    'The page reports submission to the modem. Check the recipient device for delivery.',
    'An empty inbox only means no messages were returned from modem storage; it does not show messages stored on another phone.'],
  'rf-feature-gnss': ['GNSS / GPS location', 'Cellular',
    'GNSS is satellite positioning, commonly called GPS. A compatible modem, firmware and antenna are required. Enabling this switch does not add location hardware.',
    ['Confirm support and antenna requirements with your installer.', 'Enable the receiver and allow time for a fix with a suitable view of the sky. Read results under System → Service status.'],
    'A fix reports latitude and longitude. You do not type coordinates into this enable switch.',
    'Location values appear after the receiver obtains a fix.',
    'Indoor placement or a missing antenna may prevent a fix. Location is excluded from downloaded support reports.'],
  'rf-hardware-panel': ['SIM slots and hardware options', 'Cellular',
    'These controls depend on what the connected modem reports. A second slot is offered only when the adapter reports multiple populated SIM slots. eSIM profile provisioning is not implemented.',
    ['Use the modem hardware documentation to identify slot numbers.', 'If slot switching is available, select the populated slot and expect the mobile connection to reconnect.'],
    'Slot 1 and slot 2 refer to physical SIM positions, not two separate Internet connections running together.',
    'Modem status shows the intended SIM/operator after reconnection.',
    'There is no automatic per-SIM failover here. An absent control means the required capability was not detected.'],
  'at-panel': ['AT command console', 'Cellular',
    'AT commands are low-level instructions to the modem. Most users do not need them. Some commands change or reset the modem, so use instructions supplied for this exact device.',
    ['For a simple response check, enter AT and send it.', 'Copy the response for your installer if troubleshooting; do not guess configuration/reset commands.'],
    'AT asks for a basic response. AT$VERSION reads the router software version and does not change modem settings. A separate installer-managed TCP AT service is also provided; it is not a general login service.',
    'A supported basic command returns OK or useful modem information.',
    'A timeout does not prove the command was never executed. Avoid repeatedly sending a command that could change the modem.'],
  'serial-assignment-panel': ['Choose how to use the serial port', 'Services',
    'The external USB serial converter can be used by one service at a time: a transparent TCP bridge, automatic Modbus collection, or neither.',
    ['Connect the converter appropriate for the equipment and note its device identifier.', 'Configure the chosen service, select it here and apply. Switching stops the previous service.'],
    'TCP bridge can let an authorized application exchange raw serial bytes through TCP port 5000. Modbus collection instead polls meters automatically. usb:067b:2303 is an example USB identifier, not a Windows COM name.',
    'The selected service reports running, with the other serial service stopped.',
    'The bridge uses 8 data bits, no parity and one stop bit. Set its speed to match the attached device; configure Modbus serial framing in the Modbus panel.'],
  'modbus-panel': ['Modbus meter collection and file uploads', 'Services',
    'Modbus RTU reads numbered values from industrial meters through a serial converter. You need the meter register map: it defines addresses, types, units and read functions. Guessing these can produce believable but incorrect readings.',
    ['Match the serial device, baud rate, parity and stop bits to the meter.', 'Add each meter ID, then add registers from its register map. Check word order for 32-bit values.', 'Set the collection interval, storage limits and FTP/FTPS destination, then apply and select Modbus collection under Serial port assignment.'],
    'Illustration only: meter ID 1; a register description Voltage; address 0; function 04; format FLOAT32; unit V. Use those values only if the meter manual specifies them. This editor uses zero-based addresses; a manual label such as 30001 may require conversion by the installer.',
    'Saved CSV files contain plausible readings, the error status is clear and completed files show uploaded after the scheduled time.',
    'Retention can delete expired files even if upload failed. Collection pauses at the storage limit. Upload time uses the local clock configured on the router; files close before upload. Missing USB storage stops USB-mode collection.'],
  'mqtt-panel': ['MQTT telemetry and remote management', 'Services',
    'MQTT sends router information to a server called a broker. This client uses IRMS MQTT V1.2, so a generic broker connection alone is not enough: the server must also handle the project application login/topics.',
    ['Get the broker hostname, port, device serial, credentials and certificate instructions from the service operator.', 'Keep TLS and hostname verification enabled unless the operator has documented a different trusted setup.', 'Apply and check both broker connection and IRMS application-login status.'],
    'mqtt.example.net with port 8883 illustrates a TLS broker. Use the actual address and port from your operator; a port number by itself does not guarantee TLS is available. Device serial SiteRouter01 must match the server registration.',
    'The client connects and the IRMS server acknowledges application login; telemetry then appears on the server.',
    'Check router time, credentials, certificate trust and hostname. Leave advanced JSON/proxy permissions unchanged unless your installer supplies exact settings.'],
  'rf-feature-alerts': ['Alerts and notifications', 'System',
    'The router records local events and can send selected alarms through its MQTT client. SMS connectivity/recovery/allowance notifications also need SMS enabled and an alert telephone number.',
    ['Use Event history first to understand the events being recorded.', 'Enable notifications and, if wanted, MQTT alarms. Configure the MQTT connection separately.'],
    'A weak-signal threshold of -110 dBm is an illustrative RSRP warning level. It is a notification threshold, not a command to reconnect the modem.',
    'New events appear locally and the configured remote service receives supported notifications.',
    'Remote MQTT delivery needs a working broker/application login. Local history remains bounded; it is not an unlimited audit archive.'],
  'rf-events-panel': ['Event history', 'Status',
    'Events describe changes such as startup, lost LTE, recovery attempts, cell changes, allowance warnings and configuration updates.',
    ['Compare the event time with when the problem happened.', 'Use Diagnostics & backup to download a support report if you need assistance.'],
    'An LTE failure followed by a reconnect event explains that recovery was attempted; it does not alone prove client Internet was restored.',
    'The history gives a short chronological account of recent changes.',
    'Only a bounded recent history is kept. Check router time if timestamps look wrong.'],
  'rf-tools': ['Diagnostics, backup and restore', 'System',
    'Diagnostics help narrow down a connection problem. A settings backup can restore this same board configuration. A support report contains diagnostic information with configuration secrets and GPS coordinates omitted.',
    ['Try Ping to an IP address, then DNS lookup of a hostname to distinguish reachability from name lookup.', 'Download a settings backup before a major change and store it securely.', 'Restore only a matching same-board backup with USB connected, then test and confirm connectivity within the displayed time limit.'],
    'Ping target 1.1.1.1 is an IP-address example. DNS lookup target example.com tests name lookup. Traceroute shows intermediate network hops; some networks do not answer every hop.',
    'The diagnostic returns a result, or the backup/report downloads as a JSON file.',
    'Settings backups contain Wi-Fi/VPN/MQTT secrets and are not encrypted. After restoring, restart affected data services as instructed; reapply OpenVPN settings if necessary. A ping failure alone can also mean ping is filtered.'],
  'account-panel': ['Webpage login details', 'System',
    'These credentials protect this management webpage. They are separate from Wi-Fi, MQTT, FTP, VPN and SIM credentials.',
    ['Enter your current password.', 'Choose the username and, if changing it, a new password twice. Save and sign in again.'],
    'Username site-admin illustrates an allowed name. Choose your own unique password; leaving the new-password boxes blank keeps the existing password.',
    'All existing webpage sessions sign out and your chosen credentials work for the next login.',
    'Do not use an example password from documentation. The current password is required even when only changing the username.'],
  'firmware-panel': ['Signed software updates', 'System',
    'Updates replace router software. Only releases signed by a configured trusted signing key are accepted. An application update changes the management/features package; an OS/kernel update also needs prepared and tested A/B boot slots.',
    ['Get the signing public key and allowed download hostnames from your installer.', 'Save the trust settings, then enter the exact HTTPS URL of a signed compatible update.', 'Start the update and follow its progress before interrupting power or trying another update.'],
    'https://updates.example.net/router-release.rupdate illustrates a signed-update URL. Allowed host updates.example.net is just the hostname. The example is not a real update download.',
    'Update status completes and the software version changes. The system can use rollback where the required recovery setup is provisioned.',
    'A normal IPK file is not the same as the signed update bundle expected here. Do not substitute a private signing key for the public key. OS updates do not automatically repartition an unprepared board.'],
  'rf-service-status': ['Service status', 'System',
    'This read-only diagnostic view reports what the feature supervisor is doing. A setting being enabled does not necessarily mean the connection or hardware is working.',
    ['Read the passthrough state, active uplink and VPN/allowance status relevant to your setup.', 'If there is an error, note it and use a support report rather than editing the displayed diagnostic text.'],
    'WireGuard interface up with no recent handshake means the interface exists but the peer connection is not yet confirmed.',
    'Enabled features have the expected state and current update times, without unexplained errors.',
    'This display is diagnostic data, not a settings editor. Some hardware-dependent values may be absent.'],
  'software-version': ['Software version', 'System',
    'This identifies the application release and when it was created. It helps an installer match your router to instructions and updates.',
    ['Include this version when requesting help.', 'Use Software updates for approved update bundles; do not infer that an OS/kernel update is needed from the application version alone.'],
    'r37 illustrates an application release number. The OpenWrt OS and Linux kernel have separate versions.',
    'The release matches the one your installer intended to install.',
    'After an update, refresh the page if an old version is still displayed.']
};

const routerFieldHelp = {
  username:'Management webpage account supplied by the router owner. This is not your Wi-Fi network name.',password:'Webpage login password. This may differ from the Wi-Fi password and other service accounts.',
  start:'First address DHCP may lend on the Ethernet LAN. Example: 192.168.10.50.', end:'Last address in that pool. Example: 192.168.10.200. It must not precede the first address.',
  lease:'How long a DHCP address is lent before renewal, in hours. Example: 12.', dns:'Resolvers used to look up Internet names. Enter up to three IPv4 addresses separated by commas, using resolvers approved by your network owner.',
  'dr-client':'Choosing a connected client copies its details into this reservation; otherwise enter its real MAC manually.', 'dr-mac':'Hardware address of the intended device, for example 02:11:22:33:44:55. Replace the example.', 'dr-ip':'Unused Ethernet LAN address to reserve, from 192.168.10.2 to 192.168.10.254.', 'dr-hostname':'Friendly label, for example MainMeter. It helps identify the device; it does not create a public Internet hostname.',
  'wifi-enabled':'On broadcasts the hotspot. Off disconnects wireless clients; keep another management connection available.', 'wifi-channel':'Radio channel: choose 1, 6 or 11. A nearby busy hotspot may make a different supported channel work better.', 'wifi-ssid':'The name people see in their Wi-Fi list, for example Site-Office.', 'wifi-password':'Your chosen Wi-Fi password, 8–63 characters. Blank keeps the saved password, except when the page asks you to re-enter it for a changed name.',
  'usb-enabled':'On advertises this router as the USB computer default gateway and DNS server. Off keeps USB management access without advertising it as the Internet gateway. Apply at reboot.',
  'eth-mode':'LAN serves local devices; WAN obtains an upstream address by DHCP; LAN + WAN needs matching VLAN tags on a managed switch.', 'eth-lan':'Tag for local-device traffic in trunk mode. Example: 10; it must differ from the WAN tag.', 'eth-wan':'Tag for upstream Internet traffic in trunk mode. Example: 20. The managed switch must use the same assignment.',
  'ddns-enabled':'Enable only after the provider account and hostname are ready.', 'ddns-provider':'Choose the service that issued your DDNS hostname.', 'ddns-hostname':'Your actual registered hostname, for example my-site.example.net (illustration only).', 'ddns-username':'Provider login or update username; this is not your router login.', 'ddns-password':'Provider password or update key. Blank keeps a saved secret where allowed; changing provider requires entering it again.',
  'account-username':'Webpage login name, 1–32 letters, numbers, dots, underscores or hyphens.', 'current-password':'Your existing webpage password, used to authorize the change.', 'new-password':'Choose your own password. Blank keeps the old one; the page accepts at least four characters, but a longer unique password is preferable.', 'confirm-password':'Type the same new password again. Leave both new-password boxes blank to keep the current one.',
  'firmware-enabled':'Allows signed remote updates after the trust settings are saved. It does not immediately install anything.', 'firmware-key':'Installer-provided public signing key in PEM format. This is not a TLS CA certificate or a private key.', 'firmware-hosts':'One approved download hostname per line, without https:// or a file path. Redirect hostnames must also be approved.', 'firmware-url':'Exact HTTPS address of an installer-provided signed bundle, not a normal IPK package or a generic OS image.',
  'serial-assignment-mode':'Choose one owner of the external serial port. TCP bridge and Modbus cannot use it simultaneously.', 'serial-assignment-device':'Linux device path or supported USB identifier from the installer; do not enter a Windows COM number.', 'serial-assignment-baud':'Bits per second, matching the connected device. Example: 9600 if its manual specifies 9600.', 'serial-assignment-port':'TCP listening port for the raw serial bridge. Example: 5000. This is a network port number, not a serial COM number.',
  'modbus-enabled':'Starts automatic meter collection when serial assignment permits it; configure and verify a meter first.', 'modbus-serial':'Identifier written with this router collection data, for example SiteRouter01.', 'modbus-interval_minutes':'Minutes between meter readings. Example: 1 collects every minute.', 'modbus-upload_time':'Daily file-closing/upload time according to the local clock configured on the router, for example 02:00.', 'modbus-retention_days':'How long files are retained. Expired files can be deleted even if they never uploaded.', 'modbus-max_storage_mb':'Maximum collection storage in MiB; collection pauses when full.', 'modbus-save_mode':'Internal memory or an already mounted USB drive. This does not format or mount a drive.', 'modbus-usb_mount':'Existing Linux mount path provided by the installer, for example /mnt/modbus.', 'modbus-debug':'Extra serial diagnostic logging for troubleshooting. Usually leave Off.',
  'modbus-port-device':'Serial converter identifier/path used for the meter bus. It must match Serial port assignment.', 'modbus-port-baud':'Serial speed from the meter manual. Every device on the bus must use a compatible speed.', 'modbus-port-parity':'Serial error-checking setting: none, even or odd. Match the meter exactly.', 'modbus-port-data_bits':'Number of data bits per serial character; this interface uses 8.', 'modbus-port-stop_bits':'End-of-character timing: one or two stop bits, matching the meter.', 'modbus-port-timeout_seconds':'Seconds to wait for a meter reply. A longer timeout does not correct a wrong address or wiring.',
  'modbus-ftp-host':'Upload server hostname/IP from the service operator, for example files.example.net.', 'modbus-ftp-port':'Server port. Standard FTP/explicit FTPS commonly uses 21; use the operator value.', 'modbus-ftp-username':'Upload account username, separate from the webpage login.', 'modbus-ftp-password':'Upload account password. Blank keeps an existing saved password.', 'modbus-ftp-directory':'Writable destination directory on that server, for example /site-a. Confirm permission with the server operator.', 'modbus-ftp-tls':'Explicit FTPS encrypts FTP when supported by the server. It is different from SFTP; this uploader does not offer SFTP.',
  'mqtt-enabled':'Starts this IRMS MQTT client with the saved connection details.', 'mqtt-serial':'Unique device serial registered on the IRMS server. Another device must not use the same identity.', 'mqtt-host':'Broker hostname or IP supplied by the operator, without an https:// prefix.', 'mqtt-port':'Broker TCP port supplied by the operator. 8883 is a TLS example; the actual server may use another port.', 'mqtt-username':'MQTT broker account username, not the webpage username.', 'mqtt-password':'MQTT broker account password; blank keeps the saved password.', 'mqtt-tls_enabled':'TLS encrypts the broker connection. The selected port must actually provide TLS.', 'mqtt-verify_hostname':'Checks that the broker certificate belongs to the hostname you entered. Keep enabled for normal certificate validation.', 'mqtt-ca_certificate':'Trusted CA certificate supplied by the broker operator if system trust is insufficient. Blank keeps the saved CA, or uses system trust if none is saved.', 'mqtt-clear_ca':'Explicitly remove the saved custom CA. Do not select this just to keep the current certificate.', 'mqtt-advanced':'Installer-supplied JSON for optional identity, data sources, proxies and handlers. Leave unchanged if you do not have exact instructions.',
  'openvpn-enabled':'On connects to the configured VPN server after required certificates are present.', 'openvpn-vpn_subnet':'VPN address range routed by this client, for example 10.87.0.0/24. Use the administrator value.', 'openvpn-remote':'Existing VPN server hostname or IPv4 address, for example vpn.example.net.', 'openvpn-port':'Server listening port, for example 1194 only if your server uses it.', 'openvpn-protocol':'UDP or TCP transport; it must match the server.', 'openvpn-cipher':'Encryption choice agreed with the server. Copy the VPN administrator setting rather than guessing.', 'openvpn-auth':'Authentication digest used by the VPN profile, not a username/password option. Match the server.', 'openvpn-keepalive':'Two space-separated seconds values. 10 120 means periodic 10-second pings and a 120-second timeout policy.', 'openvpn-nobind':'Lets the client choose a local source port; normally keep enabled unless the administrator specifies otherwise.', 'openvpn-tls_mode':'Extra TLS protection mode: none, tls-auth or tls-crypt. Select the mode matching the supplied TLS static key.', 'openvpn-server_fingerprint':'Trusted server SHA256 fingerprint supplied out of band by the administrator. Leave blank for the normal CA/server-purpose verification path.', 'openvpn-kind':'Select what the file actually is: CA certificate, client certificate, private key or optional TLS static key.', 'openvpn-file':'Import one unencrypted PEM file of the selected type, at most 16 KB. Keep private keys private.',
  'pf-dmz-enabled':'Broad forwarding of unmatched inbound IPv4 traffic. Leave Off unless a prepared downstream firewall needs it.', 'pf-dmz-zone':'Local network containing the DMZ device.', 'pf-dmz-ip':'Stable local address of the prepared downstream firewall/device, for example 192.168.10.2.', 'pf-import':'Imports the project forwarding-rule JSON format into the staged editor. Review and apply it; it is not a whole-router settings backup.', 'pf-name':'Human-readable label, for example Site web service.', 'pf-preset':'Convenience template for common port numbers; selecting one does not make a service safe or automatically start it.', 'pf-source_zone':'Where the incoming connection arrives. WAN / LTE normally means external traffic.', 'pf-protocol':'TCP, UDP or both, as required by the destination service.', 'pf-external_port':'Port outsiders connect to, for example 8080, or a range such as 8000-8010.', 'pf-internal_port':'Port the destination service actually listens on, for example 80. Ranges must have the same length.', 'pf-destination_zone':'Local network where the target device lives.', 'pf-destination_ip':'Reserved local device address, for example 192.168.10.100; it must remain stable.', 'pf-source_ip':'Optional permitted outside address/network. A /32 means one address; a /24 means a subnet. Blank allows any source that can reach the service.', 'pf-external_ip':'Optional match on a particular incoming destination IPv4 address; normally blank unless the installer requires it.', 'pf-enabled':'Whether this staged rule will be active when the whole list is applied.', 'pf-reflection':'Lets local clients use the external address to reach the forwarded service; this does not fix carrier NAT.',
  'at-command':'One supported modem command. AT is a basic check; AT$VERSION reads router software identity. Reset/configuration commands can disconnect LTE.', 'rf-tool':'Ping checks replies, DNS looks up a name, and traceroute examines the path through networks.', 'rf-target':'Hostname or IP for this diagnostic, for example example.com or 1.1.1.1. Do not paste a full website URL.', 'rf-restore':'Choose the same-board JSON settings backup downloaded by this router. It contains secrets and requires confirmation after restore.', 'rf-sms-number':'Recipient telephone number including country code; replace the example +61412345678.', 'rf-sms-text':'Up to 160 supported plain-text characters. Quotes, commas and line breaks are unsupported in this sender.', 'rf-sms-view':'Received only shows incoming/arriving messages. All stored also shows sent and draft messages. Neither view deletes or changes stored SMS.', 'rf-slot':'Physical populated SIM slot number reported by the modem, not an APN or a telephone number.',
  'rf-cellular-mcc':'MCC is the three-digit mobile country/area code, not an international telephone dialing prefix. Leave Automatic for normal operation.',
  'rf-cellular-band-select':'Automatic lets the modem use all supported bands. For a restriction, select one or more bands by name and MHz range; click or tap each band row to tick several bands. Apply, test and confirm. Restricting bands can disconnect LTE.',
  'rf-cellular-mnc':'MNC identifies the operator within the selected MCC. Choose the named network and preserve its two or three digits, including leading zeros.',
  'rf-cellular-custom-mcc':'Only for a code not in the directory: enter exactly three digits supplied by the carrier/installer.',
  'rf-cellular-custom-mnc':'Enter exactly two or three digits. 01 and 001 are different network codes; do not add or remove zeros.'
};

const routerAdvancedFieldHelp = {
  passthrough:{enabled:'Exclusive handoff of LTE to the selected Ethernet client. It stops shared LTE Internet for other clients and services on this board.',client_mac:'Real Ethernet WAN-port MAC of the downstream router. Format example: 02:11:22:33:44:55.'},
  watchdog:{enabled:'Allows the router to reconnect/reset LTE after repeated failed checks.',targets:'Two to four distinct public IPv4 addresses that answer ping. Separate with commas. One replying target is enough to count as healthy.',interval:'Seconds between checks, from 30 to 3600. Example: 60.',failures:'Consecutive failed checks before a recovery attempt. Example: 3.',cooldown:'Base wait in seconds; later recovery attempts wait longer. With 300, the next wait after the first attempt is at least 600 seconds.',reset_after:'Every Nth recovery attempt resets the modem rather than just reconnecting LTE. Example: 3.'},
  failover:{enabled:'Use wired Internet when healthy and LTE as backup.',primary:'Fixed logical Ethernet Internet interface for this implementation.',backup:'Fixed logical LTE interface, called wan.',recoveries:'Successful wired checks needed before returning from LTE. Example: 3 reduces rapid switching.'},
  allowance:{enabled:'Track the configured billing cycle and issue configured warnings.',limit_mb:'Decimal megabytes per cycle. Example: 10000 MB for a decimal 10 GB allowance.',warning_percent:'Percentage of allowance that triggers a warning. Example: 80.',billing_day:'Day of month from 1 to 28; the cycle boundary is midnight UTC on that day.',cutoff:'Blocks client forwarding over LTE at the limit. Router-originated traffic can still use data.'},
  alerts:{enabled:'Allows configured remote notifications; local event recording remains available.',mqtt:'Queue alarms through the configured IRMS MQTT connection.',weak_rsrp:'Signal-strength warning threshold in dBm. Example: -110. More negative generally means weaker signal.'},
  signal:{enabled:'Collect signal measurements for the graph.',interval:'Seconds between samples. Example: 300 means five minutes.',samples:'Maximum samples in memory. Example: 288 at five-minute intervals is about one day.'},
  wireguard:{enabled:'Start this one-peer WireGuard connection.',private_key:'The secret WireGuard key for this router. Blank keeps an existing saved key. Do not share it.',address:'This router tunnel address with prefix, for example 10.77.0.2/24.',peer_key:'The public key of the other VPN end, supplied by its administrator. This is not your own private key.',endpoint:'Peer Internet hostname or IPv4, without a port or URL prefix. Example: vpn.example.net.',port:'UDP port on the peer. Example: 51820 only if that peer uses it.',allowed_ips:'Remote address ranges assigned to this peer, separated by commas. Example: 10.88.0.0/24. 0.0.0.0/0 selects all IPv4 destinations.',keepalive:'Seconds between keepalive packets; 0 disables them. Example: 25 for a peer behind NAT when the administrator requires it.',access_lan:'Allows traffic from the peer into local Ethernet LAN devices. The peer must still route traffic correctly.'},
  guest:{enabled:'Create the isolated tagged Ethernet network; requires prepared trunk/switch configuration.',vlan:'Unused tag number from 1 to 4094, different from LAN/WAN tags. Example: 30.',subnet:'Guest gateway with /24 prefix, for example 192.168.30.1/24. It must not overlap another network.'},
  sqm:{enabled:'Enable CAKE shaping on the selected device.',interface:'Actual Linux WAN device from the installer, not a hostname or computer name.',download:'Download shaping rate in kbit/s, below usable connection capacity. Example: 18000 for an illustrative 20 Mbit/s link.',upload:'Upload shaping rate in kbit/s. Example: 4500 for an illustrative 5 Mbit/s link.'},
  ipv6:{enabled:'Request IPv4+IPv6 and a delegated LAN prefix. Carrier/APN support is required.'},
  cellular:{roaming:'Allow a partner mobile network; check your plan before enabling.',operator:'The named country/network selectors form this saved operator code; blank means automatic registration.',bands:'Use any for automatic selection. Select named LTE bands from the list, by clicking or tapping each checkbox row. The labels show MHz ranges.'},
  sms:{enabled:'Permit reading/sending through a compatible modem/SIM.',alert_number:'Optional recipient for selected alerts. Use country-code format and replace any example number.'},
  gnss:{enabled:'Enable raw GPS/GNSS collection if the modem supports it. An antenna and a fix are still required.'}
};

function guideNode(tag,text,parent){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(parent)parent.append(node);return node;}
function addTopicGuide(id,topic){
  const target=document.getElementById(id);if(!target)return;
  const [title,group,what,steps,example,check,fix]=topic;
  const aside=guideNode('aside');aside.className='setting-guide';aside.setAttribute('aria-label',title+' help');aside.dataset.manualTopic=id;
  guideNode('p',what,aside);
  const details=guideNode('details',undefined,aside);guideNode('summary','How to set this up · example · checks',details);
  const ol=guideNode('ol',undefined,details);steps.forEach(step=>guideNode('li',step,ol));
  for(const [label,content] of [['Example — replace these details with your own',example],['How to check',check],['If it does not work',fix]]){
    guideNode('h4',label,details);guideNode('p',content,details);
  }
  if(target.tagName==='DETAILS')target.querySelector('summary').after(aside);
  else if(id==='software-version')target.after(aside);
  else {const heading=target.querySelector('.section-head,h2,legend');if(heading)heading.after(aside);else target.prepend(aside);}
}
function addFieldGuide(input,text){
  if(!text||input.dataset.manualHelp)return;
  const label=input.closest('label');if(!label)return;
  const help=guideNode('small',text,label);help.className='field-guide';help.id='guide-field-'+(input.id||'dynamic-'+(++manualDynamicId));
  input.setAttribute('aria-describedby',((input.getAttribute('aria-describedby')||'')+' '+help.id).trim());input.dataset.manualHelp='true';
}
let manualDynamicId=0;
function manualSearchText(value){return value.toLowerCase().replace(/[^a-z0-9]/g,'');}
function explainDynamicMeterFields(){
  const deviceHelp={name:'Friendly meter name, for example MainMeter. Give each device a recognizable name.',id:'Modbus unit/slave ID set in the physical meter. Example: 1, if the meter is configured as unit 1.',data_mode:'Order of the two 16-bit words in a 32-bit value. Match the register map: ABCD or swapped words CDAB.'};
  const registerHelp={description:'Label written with the reading, for example Voltage.',address:'Zero-based register address from the meter map, in decimal or 0x hex. Ask your installer to convert 3xxxx/4xxxx manual labels correctly.',format:'Representation specified by the meter. FLOAT32 uses two 16-bit registers; choosing the wrong type can give incorrect readings.',unit:'Display/export unit label, for example V. This does not convert or scale the measured number.',function:'03 reads holding registers; 04 reads input registers. Use the function specified in the meter register map.'};
  document.querySelectorAll('#modbus-devices [data-field]').forEach(input=>addFieldGuide(input,deviceHelp[input.dataset.field]));
  document.querySelectorAll('#modbus-devices [data-register]').forEach(input=>addFieldGuide(input,registerHelp[input.dataset.register]));
}
function buildRouterManual(){
  Object.entries(routerManualTopics).forEach(([id,topic])=>addTopicGuide(id,topic));
  Object.entries(routerFieldHelp).forEach(([id,text])=>{const input=document.getElementById(id);if(input)addFieldGuide(input,text);});
  for(const [section,fields] of Object.entries(routerAdvancedFieldHelp))for(const [name,text] of Object.entries(fields)){
    const input=document.getElementById('rf-'+section+'-'+name);if(input)addFieldGuide(input,text);
  }
  const list=document.getElementById('manual-topic-list');
  for(const [id,[title,group]] of Object.entries(routerManualTopics)){
    const target=document.getElementById(id);
    const fields=Array.from(target.querySelectorAll('.field-guide')).map(help=>help.id+' '+help.textContent).join(' ');
    const item=guideNode('li',undefined,list);item.dataset.search=manualSearchText(routerManualTopics[id].flat().join(' ')+' '+fields);
    const a=guideNode('a',title,item);a.href='#'+id;guideNode('small',' · '+group,item);
    a.addEventListener('click',event=>{
      const target=document.getElementById(id);
      if(target?.closest('[hidden]')){
        event.preventDefault();const preview=document.getElementById('manual-topic-preview');preview.replaceChildren();preview.hidden=false;
        guideNode('h3',title,preview);guideNode('p','These controls are not currently available on this router. This explanation is for reference; it does not enable the feature.',preview);
        const help=target.querySelector('[data-manual-topic]');if(help){const copy=help.cloneNode(true);copy.querySelector('details').open=true;preview.append(copy);}
        else guideNode('p',routerManualTopics[id][2],preview);
        preview.tabIndex=-1;preview.focus();
      }else openNavigationTarget(a.hash);
    });
  }
  document.getElementById('manual-search').addEventListener('input',event=>{
    const query=manualSearchText(event.target.value.trim());let count=0;
    for(const item of list.children){item.hidden=!item.dataset.search.includes(query);if(!item.hidden)count++;}
    document.getElementById('manual-search-result').textContent=count+' help topics found. Some settings appear only when supported by this router.';
  });
  const devices=document.getElementById('modbus-devices');if(devices){explainDynamicMeterFields();new MutationObserver(explainDynamicMeterFields).observe(devices,{childList:true,subtree:true});}
}
buildRouterManual();
