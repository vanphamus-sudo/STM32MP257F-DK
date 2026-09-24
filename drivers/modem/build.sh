#!/bin/sh
# Run on the board with the ST sources and extracted kernel-devsrc described below.
set -eu
work=${1:-/usr/local/src/router-drivers}
kernel=$(uname -r)
build="$work/devsrc/usr/lib/modules/$kernel/build"
test "$(cat "$build/include/config/kernel.release")" = "$kernel"
test -s "$build/Module.symvers"
for source in cdc-wdm.c cdc_mbim.c qmi_wwan.c; do
    test -s "$work/$source"
done
make -C "$build" CC=aarch64-ostl-linux-gcc HOSTCC=aarch64-ostl-linux-gcc olddefconfig </dev/null
make -C "$build" -j2 CC=aarch64-ostl-linux-gcc HOSTCC=aarch64-ostl-linux-gcc scripts modules_prepare </dev/null
make -C "$build" M="$work" -j2 CC=aarch64-ostl-linux-gcc HOSTCC=aarch64-ostl-linux-gcc modules
for module in cdc-wdm cdc_mbim qmi_wwan; do
    modinfo -F vermagic "$work/$module.ko"
done
