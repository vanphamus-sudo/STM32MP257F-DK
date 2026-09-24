#!/bin/sh
# Run on the target after building and reviewing the modules.
set -eu
work=${1:-/usr/local/src/router-drivers}
test "$(uname -r)" = 6.6.129
expected=$(modinfo -F vermagic cdc_ncm)
for module in cdc-wdm cdc_mbim qmi_wwan; do
    test "$(modinfo -F vermagic "$work/$module.ko")" = "$expected"
done
install -d /lib/modules/6.6.129/extra/router
install -m 0644 "$work/cdc-wdm.ko" "$work/cdc_mbim.ko" "$work/qmi_wwan.ko" /lib/modules/6.6.129/extra/router/
depmod -a 6.6.129
modprobe cdc_wdm
modprobe cdc_mbim
modprobe qmi_wwan
install -m 0644 "$work/router-modem.conf" /etc/modules-load.d/router-modem.conf
