#!/bin/sh
# On-demand IPv4 LTE activation through ModemManager. Run on the board as root.
set -eu
exec python3 "$(dirname "$0")/connect-lte.py" "$@"
