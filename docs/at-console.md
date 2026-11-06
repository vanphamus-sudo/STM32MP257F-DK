# LTE AT command console

Application package `1.0.0-r4` adds an authenticated AT console with a command
input and response area. Examples are `AT`, `ATI`, `AT+CSQ` and `AT+CEREG?`.
Reset and configuration commands may disconnect LTE or change modem settings.
Commands must be one line of 2–256 printable ASCII characters starting with AT.

The POST endpoint `/api/modem/at` requires the existing session, Host/Origin
validation and CSRF token. Commands are serialized through ModemManager,
passed as a single subprocess argument without a shell, with a 10-second
ModemManager timeout and a 15-second subprocess deadline. Responses are limited
to 8192 characters and rendered as text. The application does not keep command
history on disk. The modem is selected from the configured UCI WAN device,
so modem rediscovery does not require a fixed modem index or serial-port name.

On the dev kit, both AT ports are owned by ModemManager. A harmless `AT` request
through `mmcli` currently returns `Operation only allowed in debug mode`.
With the user's explicit approval, `--debug` was added to the ModemManager
startup arguments and the service restarted on 2026-10-02. LTE reconnected,
and application r4 is deployed. The customized init script is included in
`/etc/sysupgrade.conf`; a ModemManager package upgrade may require checking
that the flag is still present. Existing INFO startup logging was retained,
and the running daemon's log level was explicitly set back to INFO.

The prepared package is `local/stm32-lte-router_1.0.0-r4_all.ipk`.
All 32 local tests and JavaScript syntax validation passed. Live authenticated
API tests passed for `AT` and `AT+CSQ` (response `+CSQ: 28,99`), unauthenticated
and missing-CSRF rejection, and multiline-command rejection. ModemManager
strips the final OK terminator, so a successful bare AT may show `response: ''`.
The console asset, LTE connection, firewall and DHCP services were verified.
The private pre-change backup is stored on the board at
`/root/router-before-at-20261002/config-and-app.tar.gz`. No physical reboot
was performed; persistence was checked through the startup configuration.

ModemManager exposes its debug option and logging settings separately in its
[context implementation](https://github.com/linux-mobile-broadband/ModemManager/blob/main/src/mm-context.c).
