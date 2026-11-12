"""Install r30 without rebooting or changing saved network configuration."""
from datetime import datetime
import glob
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=90).strip()

backup = Path('/root/router-before-usb-tethering-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
configs = {p: Path('/etc/config', p).read_bytes() for p in ('network', 'dhcp', 'firewall', 'usbgadget')}
paths = ['/usr/lib/router-web', '/etc/router-web', '/etc/config'] + glob.glob('/etc/init.d/router-*')
paths += glob.glob('/usr/lib/opkg/info/stm32-lte-router.*') + ['/usr/lib/opkg/status']
with tarfile.open(backup / 'application-and-config.tar.gz', 'w:gz') as archive:
    for path in paths:
        if Path(path).exists():
            archive.add(path, arcname=path.lstrip('/'))
(backup / 'installed-version.txt').write_text(run('opkg', 'list-installed', 'stm32-lte-router'))
print('Backup:', backup, flush=True)
services = json.loads(run('ubus', 'call', 'service', 'list'))
active = [name for name in ('router-web', 'router-button', 'router-at')
          if any(i.get('running') for i in services.get(name, {}).get('instances', {}).values())]
try:
    for name in active:
        run('/etc/init.d/' + name, 'stop')
    print(run('opkg', 'install', '/tmp/stm32-lte-router_1.0.0-r30_all.ipk'), flush=True)
    for package, original in configs.items():
        assert Path('/etc/config', package).read_bytes() == original, 'Configuration changed: ' + package
    print(run('fw4', 'check'), flush=True)
finally:
    for name in active:
        print(name, run('/etc/init.d/' + name, 'start'), flush=True)
print(run('opkg', 'list-installed', 'stm32-lte-router'))
print('Configuration unchanged; no reboot; tethering not enabled.')
