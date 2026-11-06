"""One-time per-board initialization, run by uci-defaults before networking."""
import hashlib
from pathlib import Path
import secrets
import subprocess

from initialize import initialize
from server import atomic_write


def uci(*args):
    return subprocess.check_output(['uci', *args], text=True, timeout=20).strip()


def main():
    state = Path('/etc/router-web')
    if (state / 'factory-initialized').exists():
        return
    initialize(state)
    serial = Path('/proc/device-tree/serial-number').read_text().rstrip('\0')
    uci('set', 'usbgadget.g1.serialnumber=' + serial)
    for name in ('host_addr', 'dev_addr'):
        mac = bytearray(hashlib.sha256((serial + name).encode()).digest()[:6])
        mac[0] = (mac[0] & 0xfc) | 2
        uci('set', 'usbgadget.eth1.' + name + '=' + ':'.join(f'{x:02x}' for x in mac))
    uci('commit', 'usbgadget')
    subprocess.run(['/sbin/wifi', 'config'], check=True, timeout=30)
    radios = [line.split('=', 1)[0].split('.', 1)[1]
              for line in uci('show', 'wireless').splitlines()
              if line.endswith('=wifi-device')]
    if not radios:
        raise RuntimeError('No Wi-Fi radio detected; initialization will retry on next boot')
    radio = radios[0]
    for line in uci('show', 'wireless').splitlines():
        if line.endswith('=wifi-iface'):
            uci('set', line.split('=', 1)[0] + '.disabled=1')
    keyfile = state / 'initial-wifi-password'
    if not keyfile.exists():
        atomic_write(keyfile, secrets.token_urlsafe(18) + '\n')
    values = {
        radio + '.disabled': '0', radio + '.country': 'AU', radio + '.band': '2g',
        radio + '.channel': '6', radio + '.htmode': 'HT20',
        'router_ap': 'wifi-iface', 'router_ap.device': radio,
        'router_ap.network': 'hotspot', 'router_ap.mode': 'ap',
        'router_ap.ssid': 'STM32-LTE', 'router_ap.encryption': 'psk2',
        'router_ap.key': keyfile.read_text().strip(), 'router_ap.isolate': '1',
        'router_ap.disabled': '0',
    }
    for name, value in values.items():
        uci('set', 'wireless.' + name + '=' + value)
    uci('commit', 'wireless')
    atomic_write(state / 'configured', '1\n')
    atomic_write(state / 'factory-initialized', '1\n')


if __name__ == '__main__':
    main()
