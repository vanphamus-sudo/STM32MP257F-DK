"""Run on the board with PACKAGE_HASH, TARGET_HASH and EXPECTED supplied by launcher."""
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time

os.umask(0o077)
sys.path.insert(0, '/usr/lib/router-web')
import firmware_update

PACKAGE = Path('/tmp/stm32-lte-router_1.0.0-r35_all.ipk')
TARGET = Path('/usr/share/router-packages/target-repository.tar.gz')


def run(*args, timeout=120):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(args) + '\n' + result.stdout[-12000:])
    return result.stdout.strip()


def active():
    services = json.loads(run('ubus', 'call', 'service', 'list'))
    return {name for name, data in services.items()
            if any(i.get('running') for i in data.get('instances', {}).values())}


def settings():
    paths = list(Path('/etc/config').glob('*'))
    paths += [p for p in Path('/etc/router-web').rglob('*') if p.is_file() and
              not any(part in ('modbus-data', 'mqtt-state', 'update-state') for part in p.parts)
              and p.name not in ('traffic-state.json', 'feature-accounting.json', 'feature-events.json')]
    return {str(p):p.read_bytes() for p in paths if p.is_file()}


assert hashlib.sha256(PACKAGE.read_bytes()).hexdigest() == PACKAGE_HASH
assert hashlib.sha256(TARGET.read_bytes()).hexdigest() == TARGET_HASH
assert not Path('/etc/router-web/feature-pending.json').exists(), 'Resolve pending network change first'
assert '1.0.0-r33' in run('opkg', 'list-installed', 'stm32-lte-router'), 'Unexpected installed version'
backup = Path('/root/router-before-r35-' + time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
print('Backup directory:', backup, flush=True)
before_active = active()
managed = [name for name in ('router-features', 'router-modbus', 'router-mqtt', 'router-at',
           'router-serial', 'router-traffic', 'router-web', 'router-button') if name in before_active]
server = None
stopped = False
installed = False
try:
    with tempfile.TemporaryDirectory(prefix='router-r35-deps-') as temporary:
        repository = Path(temporary)
        with tarfile.open(TARGET) as archive:
            for member in archive:
                leaf = Path(member.name).name
                if member.isfile() and (leaf.endswith('.ipk') or leaf in ('Packages', 'Packages.gz', 'Packages.sig')):
                    (repository / leaf).write_bytes(archive.extractfile(member).read())
        index = (repository / 'Packages').read_text()
        kernel = run('opkg', 'list-installed', 'kernel').split(' - ', 1)[1]
        for name in ('kmod-wireguard', 'kmod-sched-cake'):
            entry = next(e for e in index.split('\n\n') if e.startswith('Package: ' + name + '\n'))
            assert kernel in entry, 'Kernel ABI mismatch: ' + name
        # The archive is byte-identical to the original pinned host artifact.
        # opkg validates individual package hashes against this trusted index.
        run('usign', '-V', '-m', str(repository / 'Packages'), '-x', str(repository / 'Packages.sig'), '-P', '/etc/opkg/keys')
        (Path('/var/opkg-lists') / 'router_r35_kernel').write_bytes((repository / 'Packages.gz').read_bytes())
        (Path('/var/opkg-lists') / 'router_r35_kernel.sig').write_bytes((repository / 'Packages.sig').read_bytes())
        server = subprocess.Popen(['python3', '-m', 'http.server', '18081', '--bind', '127.0.0.1',
                                   '--directory', str(repository)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            try:
                connection = http.client.HTTPConnection('127.0.0.1', 18081, timeout=1)
                connection.request('HEAD', '/Packages')
                response = connection.getresponse()
                response.read()
                connection.close()
                if response.status == 200:
                    break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('Temporary local dependency repository did not start')
        conf = repository / 'opkg.conf'
        # opkg still reads /etc/opkg/*.conf with -f, but architecture declarations
        # must also be explicit in this temporary primary configuration.
        conf.write_text(Path('/etc/opkg.conf').read_text() + '\n' + run('opkg', 'print-architecture') +
                        '\nsrc/gz router_r35_kernel http://127.0.0.1:18081\n')
        command = ['opkg', '-f', str(conf), 'install', 'ip-full', 'tc-full', 'iptables-nft', str(PACKAGE)]
        print(run('opkg', '-f', str(conf), '--noaction', 'install', 'ip-full', 'tc-full', 'iptables-nft', str(PACKAGE)), flush=True)
        for name in managed:
            run('/etc/init.d/' + name, 'stop', timeout=60)
        stopped = True
        before = settings()
        with tarfile.open(backup / 'configuration-and-app.tar.gz', 'w:gz') as archive:
            paths = ['/etc/config', '/etc/router-web', '/usr/lib/router-web', '/etc/rc.d',
                     '/usr/lib/opkg/status']
            paths += [str(p) for p in Path('/etc/init.d').glob('router-*')]
            for path in paths:
                archive.add(path, arcname=path.lstrip('/'))
        firmware_update.backup(backup / 'rollback.ipk')
        (backup / 'settings-hashes.json').write_text(json.dumps({p:hashlib.sha256(v).hexdigest() for p,v in before.items()}, indent=2))
        (backup / 'previous-services.json').write_text(json.dumps(managed))
        (backup / 'previous-packages.txt').write_text(run('opkg', 'list-installed'))
        installed = True
        print(run(*command, timeout=240), flush=True)
        for name, digest in EXPECTED.items():
            assert hashlib.sha256((Path('/') / name).read_bytes()).hexdigest() == digest, name
        after = settings()
        assert all(after.get(p) == value for p,value in before.items()), 'Existing settings changed during package install'
        print(run('fw4', 'check'), flush=True)
        print(run('python3', '-m', 'compileall', '-q', '/usr/lib/router-web'), flush=True)
        for name in managed:
            run('/etc/init.d/' + name, 'start', timeout=60)
        run('/etc/init.d/router-features', 'enable')
        run('/etc/init.d/router-features', 'start')
        required = set(managed) | {'router-features'}
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if required <= active() and Path('/tmp/router-features.json').exists():
                break
            time.sleep(.5)
        assert required <= active(), 'An application service failed to start'
        runtime = json.loads(Path('/tmp/router-features.json').read_text())
        assert runtime.get('passthrough', {}).get('state') == 'disabled', runtime
        assert not runtime.get('error') and not runtime.get('feature_errors'), runtime
        responses = {}
        for path in ('/', '/router-features.js', '/api/features'):
            connection = http.client.HTTPConnection('192.168.7.1', 8081, timeout=8)
            connection.request('GET', path, headers={'Host':'192.168.7.1:8081'})
            response = connection.getresponse()
            body = response.read()
            responses[path] = response.status
            connection.close()
            assert response.status == (401 if path.startswith('/api/') else 200), path
            if path == '/router-features.js':
                assert b'IP passthrough' in body
        after = settings()
        assert all(after.get(p) == value for p,value in before.items()), 'Existing settings changed after startup'
        os.sync()
        report = dict(result='installed', version=run('opkg','list-installed','stm32-lte-router'),
                      backup=str(backup), running_services=sorted(required),
                      existing_settings_preserved=True, responses=responses,
                      passthrough='disabled', rebooted=False, standby_slot_updated=False)
        (backup / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
except BaseException:
    if installed:
        for name in set(managed) | {'router-features'}:
            if Path('/etc/init.d/' + name).exists():
                try:
                    run('/etc/init.d/' + name, 'stop', timeout=60)
                except Exception:
                    pass
        if Path('/etc/init.d/router-features').exists():
            run('/etc/init.d/router-features', 'disable')
        print(run('opkg', '--force-downgrade', 'install', str(backup / 'rollback.ipk')), flush=True)
        for name, value in before.items():
            Path(name).write_bytes(value)
        print('Previous application and settings restored.', flush=True)
    if stopped:
        for name in managed:
            try:
                run('/etc/init.d/' + name, 'start', timeout=60)
            except Exception:
                pass
    raise
finally:
    if server:
        server.terminate()
        server.wait(timeout=5)
    (Path('/var/opkg-lists') / 'router_r35_kernel').unlink(missing_ok=True)
    (Path('/var/opkg-lists') / 'router_r35_kernel.sig').unlink(missing_ok=True)
