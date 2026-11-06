"""Discover a single attached modem and keep netifd's device path current."""
import json
import subprocess
import time


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=25).strip()


def poll():
    modems = json.loads(run('mmcli', '-L', '-J')).get('modem-list', [])
    if len(modems) != 1:
        return
    device = json.loads(run('mmcli', '-m', modems[0], '-J'))['modem']['generic']['device']
    if not device.startswith('/sys/devices/'):
        return
    if run('uci', '-q', 'get', 'network.wan.device') != device:
        run('uci', 'set', 'network.wan.device=' + device)
        run('uci', 'commit', 'network')
        run('/etc/init.d/network', 'reload')


if __name__ == '__main__':
    while True:
        try:
            poll()
        except (subprocess.SubprocessError, ValueError, KeyError):
            pass  # ModemManager/modem may still be starting or unplugged.
        time.sleep(15)
