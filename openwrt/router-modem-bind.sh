#!/bin/sh
# Linux 6.6 fallback for RG255C-GL (upstream QMI_QUIRK_SET_DTR ID).
# Borrow EC25's identical driver_info including SET_DTR, not generic new_id.
modprobe qmi_wwan || exit 1
mkdir /var/lock/router-modem-bind 2>/dev/null || exit 0
trap 'rmdir /var/lock/router-modem-bind' EXIT
for dev in /sys/bus/usb/devices/*; do
    [ "$(cat "$dev/idVendor" 2>/dev/null)" = 2c7c ] || continue
    [ "$(cat "$dev/idProduct" 2>/dev/null)" = 0316 ] || continue
    intf="$dev:1.3"
    [ -d "$intf" ] || continue
    [ -L "$intf/driver" ] && continue
    # Never let the dynamic vendor-class ID capture the serial interfaces.
    ready=0
    for attempt in 1 2 3 4 5; do
        if [ -L "$dev:1.0/driver" ] && [ -L "$dev:1.1/driver" ] && [ -L "$dev:1.2/driver" ]; then
            ready=1
            break
        fi
        sleep 1
    done
    [ "$ready" = 1 ] || continue
    [ "$(cat "$intf/bInterfaceProtocol")" = 50 ] || continue
    driver=/sys/bus/usb/drivers/qmi_wwan
    if printf '2c7c 0316 ff 2c7c 0125\n' > "$driver/new_id"; then
        # Existing binding stays; remove broad dynamic match immediately.
        printf '2c7c 0316\n' > "$driver/remove_id"
        logger -t router-modem 'RG255C-GL QMI binding applied'
    fi
done
