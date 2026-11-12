#!/bin/sh
# Copy this repository's current sources into an OpenWrt build tree.
set -eu
[ "$#" -eq 1 ] || { echo "Usage: $0 /path/to/openwrt-build-tree" >&2; exit 1; }
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tree=$(CDPATH= cd -- "$1" && pwd)
[ -f "$tree/include/package.mk" ] || { echo 'Not an OpenWrt build tree' >&2; exit 1; }
dest="$tree/package/stm32-lte-router"
mkdir -p "$dest/src"
cp "$repo/openwrt/Makefile" "$repo/openwrt/router-web.init" "$repo/openwrt/router-serial.init" "$repo/openwrt/router-at.init" "$repo/openwrt/router-mqtt.init" "$repo/openwrt/router-modbus.init" "$repo/openwrt/router-update-confirm.init" "$repo/openwrt/router-storage.init" "$repo/openwrt/router-traffic.init" "$repo/openwrt/router-features.init" "$repo/openwrt/router-button.init" "$repo/openwrt/router-storage.preinit" "$repo/openwrt/router-openvpn.hotplug" "$repo/openwrt/sysupgrade.keep" "$dest/"
for file in cellular_info.py mobile-networks.json ip_passthrough.py router_features.py router_supervisor.py router-features.js user-guide.js usb_tethering.py usb-tethering.js serial_assignment.py modbus_collection.py modbus_settings.py modbus.js traffic_stats.py mqtt_metrics.py system_update.py firmware_update.py update_bundle.py firmware.js mqtt_events.py mqtt_settings.py mqtt.js mqtt_client.py mqtt_protocol.py mqtt_data.py mqtt_proxy.py server.py wifi.py openwrt_backend.py openvpn_client.py modem_details.py serial_tcp.py at_tcp.py version_info.py port_forwarding.py port-forwarding.js dhcp_reservations.py dhcp-reservations.js ethernet.py recovery_button.py ethernet.js index.html app.js style.css; do
    cp "$repo/web/$file" "$dest/src/"
done
cp "$repo/openwrt/provision.py" "$repo/openwrt/initialize.py" "$repo/openwrt/provision-system-updates.py" "$dest/src/"
echo "Package prepared in $dest. Select Network -> stm32-lte-router in menuconfig."
