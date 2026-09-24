# QMI/MBIM modules for the installed ST kernel

Target: OpenSTLinux v26.06.10, Linux 6.6.129, aarch64, MODVERSIONS enabled.
This builds optional modules without replacing the kernel image or device tree.

Installed and load-tested on the board on 2026-09-23. The modules passed normal
kernel symbol/version checks. `cdc_mbim` bound to the modem, creating `/dev/cdc-wdm0`
and network interface `wwu1u1i8`; ModemManager discovered Quectel EM060K-GL as modem 0.
QMI loaded successfully but a QMI data connection was not tested because the modem
currently uses MBIM. LTE data connectivity and reboot persistence are not yet tested.

Source: ST's Linux tag `v6.6-stm32mp-r3.1`, commit
`548f960c059bc4b9165cb69895fd67551f6061ca` in
https://github.com/STMicroelectronics/linux . Files are unchanged:

- `drivers/usb/class/cdc-wdm.c`
- `drivers/net/usb/cdc_mbim.c`
- `drivers/net/usb/qmi_wwan.c`

Local source files are staged in `local/modem-driver-source/` (ignored by Git).
Retain the source files' SPDX licenses when distributing source or binaries.
The project Makefile exposes the omitted modules' header declarations for this
external build; it does not modify the running kernel configuration.

The ST 6.2.1 feed's `kernel-devsrc_1.0-r0_arm64.deb` contains matching configuration,
generated headers and Module.symvers. Its declared dependencies include unavailable
development packages. Instead of forcing a broken package installation, the archive
was downloaded and extracted as build data under `/usr/local/src/router-drivers/devsrc`.
Archive SHA256 from the package index:
`a3a88ec304470da8c6e2dbaa5bbf4c7aaaa900197c2811caba051c6e8c236caf`.

Native tools installed through apt: gcc, make, binutils, libc6-dev, flex, bison, bc,
libgcc-s-dev, and their dependencies. Compiler is `aarch64-ostl-linux-gcc` 13.4.0,
matching the running kernel's compiler. The partial devsrc tree requires olddefconfig
and architecture header generation before external module compilation. Compare its
resulting configuration with `/proc/config.gz`; do not assume compatibility after
a kernel or package-feed update.

Place the three sources and this Makefile in `/usr/local/src/router-drivers/`,
then run `sh build.sh /usr/local/src/router-drivers`. Loading must use normal
modprobe version/symbol checks; never force-load a mismatched module.

The modules install to `/lib/modules/6.6.129/extra/router/` with `depmod` metadata.
`router-modem.conf` in `/etc/modules-load.d/` requests their loading on boot.
For a repeat installation, copy that file into the build workspace and run
`sh install.sh /usr/local/src/router-drivers`. This script is kernel-specific.
The local `local/modem-driver-artifacts/` folder contains the built modules,
build logs and symbol-version table for this installation.

Rollback (disconnect the modem first and stop any cellular data session): unload
`qmi_wwan`, `cdc_mbim`, then `cdc_wdm`; remove only the three project modules in
`/lib/modules/6.6.129/extra/router/` and `/etc/modules-load.d/router-modem.conf`,
then run `depmod -a 6.6.129`. No kernel-image rollback is needed.

The connected EM060K-GL (2c7c:030b) exposes MBIM on USB interfaces 8/9.
QMI is provided for another supported modem composition; it is not expected to
bind simultaneously to the modem's MBIM data function. No modem firmware or USB
composition change is part of this driver installation.
