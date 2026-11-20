# Quectel RG255C-GL on the STM32MP257F-DK

The connected module reports USB ID `2c7c:0316`, firmware
`RG255CGLABR01A04M4G`. Its serial interfaces 0–2 use `option`; interface 3
uses `qmi_wwan`, providing `cdc-wdm0` and `wwan0`.

The installed OpenWrt Linux 6.6.144 driver lacks this USB ID. Upstream Linux
uses `QMI_QUIRK_SET_DTR(0x2c7c, 0x0316, 3)`:
https://raw.githubusercontent.com/torvalds/linux/master/drivers/net/usb/qmi_wwan.c

`openwrt/router-modem-bind.sh` supplies a runtime ID using the existing EC25
driver information, including its DTR behavior. It waits for the serial
interfaces to bind before adding the ID, then immediately removes the broad
dynamic match while retaining the bound data interface. Existing upstream
bindings are left alone. No kernel replacement or modem firmware change is
needed. The init script runs before networking, and the USB hotplug hook
handles later enumeration/reconnection. All three files are included by both
package builders.

Installed paths:

- `/usr/sbin/router-modem-bind`
- `/etc/init.d/router-modem` (enabled at S19)
- `/etc/hotplug.d/usb/30-router-modem`

WAN retains `modemmanager`, APN `telstra.extranet`, IPv4, and the modem's
physical sysfs device path ending in `1-1.1`. ModemManager needs to probe QMI
after binding; a serial-only discovery can incorrectly report GSM support.
Restarting ModemManager after the first manual binding resolved that discovery.
The QMI firmware model string is `334`; USB descriptors and ATI identify the
actual model as RG255C-GL.

On 20 November 2026, initial live tests passed: five Internet pings, no loss,
30.3 ms mean; DNS through 192.168.10.1; HTTPS 200 through wwan0. Telstra LTE
band 7 was observed. 5G registration was not established by these tests.

The reboot test passed: interface 3 bound automatically and WAN connected
without a manual `ifup`. After reboot, ten Internet pings had no loss and
20.9 ms mean latency; a 10 MB HTTPS download returned 200 in 1.65 seconds
(approximately 48.5 Mbit/s). LAN DNS answered on 192.168.10.1. No USB
disconnect was logged during this boot/test. These are short functional
checks, not sustained performance or electrical qualification.

LAN forwarding and masquerade rules are present. No physical LAN client had
a DHCP lease during final validation, so end-to-end PC forwarding remains
unverified. An isolated-client test could not run because this kernel lacks
the veth device type; its temporary namespace was removed.

Rollback: disable `/etc/init.d/router-modem`, remove its USB hotplug hook,
and reboot. The stock driver modules and modem firmware are unchanged.

At the user's subsequent request, 5G-only operation was saved using
`network.wan.allowedmode=5g` and `AT+QNWPREFCFG="mode_pref",NR5G`.
Readback confirmed both settings and ModemManager reported allowed mode 5g.
The modem remained searching, packet service detached, and WAN failed to
connect. LTE fallback is disabled intentionally; Internet access is down.
To restore automatic LTE/5G selection, clear the WAN allowedmode override,
set modem mode preference to AUTO, and reconnect WAN.
