"""Board-side guided manual update, with rollback; launcher supplies PACKAGE_HASH/EXPECTED."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

os.umask(0o077)
sys.path.insert(0, '/usr/lib/router-web')
import firmware_update

PACKAGE = Path('/tmp/stm32-lte-router_1.0.0-r41_all.ipk')


def run(*args):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
    if result.returncode:
        raise RuntimeError('Command failed: ' + args[0] + '\n' + result.stdout[-10000:])
    return result.stdout.strip()


def active():
    data = json.loads(run('ubus', 'call', 'service', 'list'))
    return {name for name, value in data.items() if any(i.get('running') for i in value.get('instances', {}).values())}


def settings():
    paths = list(Path('/etc/config').glob('*')) + list(Path('/etc/router-web').rglob('*'))
    return {str(p):p.read_bytes() for p in paths if p.is_file() and
            not any(part in ('modbus-data', 'mqtt-state', 'update-state') for part in p.parts) and
            p.name not in ('traffic-state.json', 'feature-accounting.json', 'feature-events.json')}


assert hashlib.sha256(PACKAGE.read_bytes()).hexdigest() == PACKAGE_HASH
previous_version = run('opkg', 'list-installed', 'stm32-lte-router')
assert any(v in previous_version for v in ('1.0.0-r40', '1.0.0-r41'))
assert not Path('/etc/router-web/feature-pending.json').exists(), 'Confirm pending networking changes first'
names = [name for name in ('router-features', 'router-modbus', 'router-mqtt', 'router-at',
         'router-serial', 'router-traffic', 'router-web', 'router-button') if name in active()]
backup = Path('/root/router-before-r41-' + time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
print('Backup:', backup, flush=True)
stopped = []
installed = False
try:
    for name in names:
        run('/etc/init.d/' + name, 'stop')
        stopped.append(name)
    before = settings()
    with tarfile.open(backup / 'configuration-and-app.tar.gz', 'w:gz') as archive:
        for name in ['/etc/config', '/etc/router-web', '/usr/lib/router-web', '/etc/rc.d'] + \
                [str(p) for p in Path('/etc/init.d').glob('router-*')]:
            archive.add(name, arcname=name.lstrip('/'))
    firmware_update.backup(backup / 'rollback.ipk')
    (backup / 'settings-hashes.json').write_text(json.dumps({p:hashlib.sha256(v).hexdigest() for p,v in before.items()}, indent=2))
    (backup / 'previous-services.json').write_text(json.dumps(names))
    installed = True
    install_args = ['opkg'] + (['--force-reinstall'] if '1.0.0-r41' in previous_version else []) + ['install', str(PACKAGE)]
    print(run(*install_args), flush=True)
    assert all(hashlib.sha256((Path('/') / p).read_bytes()).hexdigest() == digest for p,digest in EXPECTED.items())
    assert all(settings().get(p) == value for p,value in before.items()), 'Existing settings changed'
    print(run('fw4', 'check'), flush=True)
    for name in names:
        run('/etc/init.d/' + name, 'start')
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        if set(names) <= active():
            break
        time.sleep(.5)
    assert set(names) <= active(), 'Service failed to start'
    while True:
        try:
            connection = http.client.HTTPConnection('192.168.7.1', 8081, timeout=3)
            connection.request('GET', '/', headers={'Host':'192.168.7.1:8081'})
            response = connection.getresponse()
            html = response.read().decode()
            connection.close()
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.5)
    assert response.status == 200
    vpn = html.split('<summary>VPN</summary>', 1)[1].split('</details>', 1)[0]
    assert 'href="#openvpn-panel"' in vpn and 'href="#rf-feature-wireguard"' in vpn
    assert 'data-nav-group' in html and 'System</summary><a href="#router-features-panel"' not in html

    assert 'Start here: your router guide' in html and 'src="/user-guide.js"' in html
    connection = http.client.HTTPConnection('192.168.7.1', 8081, timeout=10)
    connection.request('GET', '/user-guide.js', headers={'Host':'192.168.7.1:8081'})
    help_response = connection.getresponse()
    help_script = help_response.read().decode()
    connection.close()
    assert help_response.status == 200 and 'routerManualTopics' in help_script and 'routerAdvancedFieldHelp' in help_script

    import router_features, openwrt_backend, modem_details
    inbox = router_features.sms({'action':'list'}, openwrt_backend)
    cellular = router_features.status(openwrt_backend)
    band = modem_details.collect(openwrt_backend)['band']
    assert cellular['cellular_choices']['countries']
    assert cellular['capabilities']['band_options']
    assert 'MHz' in band, 'Live modem frequency missing'
    print(json.dumps(dict(sms_total=inbox['total'], sms_readable=len(inbox['messages']),
                          sms_failed=inbox['failed'], band=band)), flush=True)
    assert all(settings().get(p) == value for p,value in before.items()), 'Settings changed after startup'
    report = dict(result='installed', version=run('opkg','list-installed','stm32-lte-router'),
                  backup=str(backup), settings_preserved=True, services=names,
                  usb_web_status=response.status, shared_vpn_group_verified=True, manual_help_http_status=help_response.status, guided_manual_verified=True,
                  rebooted=False, standby_slot_updated=False)
    (backup / 'result.json').write_text(json.dumps(report, indent=2))
    os.sync()
    print(json.dumps(report), flush=True)
except BaseException:
    if installed:
        for name in names:
            try:
                run('/etc/init.d/' + name, 'stop')
            except Exception:
                pass
        print(run('opkg', '--force-downgrade', 'install', str(backup / 'rollback.ipk')), flush=True)
        for p,value in before.items():
            Path(p).write_bytes(value)
    for name in stopped:
        try:
            run('/etc/init.d/' + name, 'start')
        except Exception:
            pass
    raise
