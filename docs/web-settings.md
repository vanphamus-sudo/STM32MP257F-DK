# Board settings page

Open **http://192.168.10.1** from an Ethernet LAN client. Sign in as `admin` with
the default password `admin`. The initial password can also be
retrieved over the existing root USB SSH connection from
`/var/lib/router-web/initial-password` until login details are changed.
It is not stored in this repository.

Under **Account → Login details**, enter your username and current password.
To change your password, enter a new password of 4–256 characters and confirm it;
leave both new password fields blank to change only the username. Usernames accept
1–32 letters, numbers, dots, underscores or hyphens. Saving signs out all sessions;
sign in again with the updated details. The new password is stored only as a salted
hash, and the plaintext installation password file is removed. Login details persist
on disk independently of whether the web service starts automatically at boot.

The page shows LTE state/operator/signal, WAN address, service status, uptime and
DHCP clients. You can change the DHCP range within 192.168.10.2–254, lease time
(1–168 hours), and up to three upstream IPv4 DNS servers. LAN/USB addresses,
LTE APN, firewall policy and boot settings are not editable in this version.

The **Wi-Fi hotspot** section controls the hotspot on/off state, SSID, password
and channel (1, 6 or 11). It uses WPA2-Personal, 2.4 GHz, and country AU (Australia).
Wi-Fi passphrases require 8–63 printable ASCII characters; this differs from the
web-login password minimum. Leave the password blank to keep it; changing the
SSID also requires entering the Wi-Fi password because the derived key depends
on the SSID. The API never returns the key or password. Wi-Fi changes restart the
hotspot and may disconnect clients. Use Ethernet to turn a disabled hotspot on.

Initial SSID: `STM32-LTE`. The generated initial Wi-Fi password is stored root-only
at `/usr/local/lib/router/initial-wifi-password` until changed through the page.
Wi-Fi clients receive 192.168.20.50–200, gateway/DNS 192.168.20.1, with LTE NAT.
They can access this page at **http://192.168.10.1**. Wi-Fi-to-Ethernet/USB forwarding
is blocked, and wireless client isolation is enabled. Ethernet DHCP settings do
not change the fixed Wi-Fi address pool. Both pools share the configured DNS upstreams.

Hotspot service: `router-hotspot`. It is active for the current session, not enabled
at boot. Configuration is under `/usr/local/lib/router` (`wifi.json`, `hostapd.conf`,
`wifi-dhcp.conf`). The original DHCP/firewall files are backed up under
`/var/lib/router-web/before-wifi`. No router boot or LTE retry services were enabled.

Apply validates the input, checks the generated dnsmasq configuration, saves a
backup to `/var/lib/router-web/dnsmasq.previous`, and restarts dnsmasq. A failed
restart restores the old configuration and attempts to restart it. Existing
clients keep their leases until renewal. USB management stays at 192.168.7.1.

The service binds only to 192.168.10.1:80. The firewall allows HTTP only from
192.168.10.0/24 on end0 and 192.168.20.0/24 on wlan0. This is HTTP for a trusted local network; login uses
PBKDF2 password hashing, expiring HttpOnly/SameSite sessions,
login throttling, Host/Origin checks and CSRF tokens. No external assets or
Internet services are needed by the page.

Files live under `/usr/local/lib/router-web`; the systemd unit is
`router-web.service`. It is active but **not enabled at boot**. The earlier
approval block on router boot persistence is still unresolved. No boot or LTE
retry services were enabled as part of adding this page.

To stop the page on the board: `systemctl stop router-web`. To start it for the
current router session: `systemctl start router-web`. Logs are available with
`journalctl -u router-web`. For DNS/DHCP recovery over USB:

```sh
cp /var/lib/router-web/dnsmasq.previous /usr/local/lib/router/dnsmasq.conf
systemctl restart dnsmasq
```

Validation completed on the board: four isolated test cases covering invalid
settings, backup/rollback, login, session logout, Host/Origin and CSRF boundaries;
real API login/status/save/logout, with the existing configuration reapplied;
Chrome desktop/mobile login, dashboard and save, with no JavaScript errors or
page overflow. Screenshots are in `logs/router-web-{login,desktop,mobile}.png`.
The browser test used an SSH tunnel because the development PC is separate from
the directly connected LAN test PC. No physical reboot was performed.
