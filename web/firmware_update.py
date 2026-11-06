"""Signed remote application updates and provisioned A/B OS updates."""
import argparse
import contextlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

import update_bundle as bundle

STATE = Path('/etc/router-web')
ROOT = Path('/')
TMP = Path('/tmp')
BUSY = ('queued', 'downloading', 'verifying', 'installing', 'checking', 'rolling-back')


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.new')
    with temporary.open('w', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def current():
    return load(STATE / 'update.json', dict(enabled=False, public_key='', allowed_hosts=[]))


def status():
    config = current()
    state = load(STATE / 'update-state/status.json', dict(state='idle'))
    if state.get('state') in BUSY:
        try:
            with locked():
                state = dict(state, state='interrupted', error='Update worker stopped. Inspect the installed application before retrying.')
                atomic(STATE / 'update-state/status.json', state)
        except ValueError:
            pass
    import system_update
    return dict(available=True, enabled=config['enabled'], public_key=config['public_key'],
                allowed_hosts=config['allowed_hosts'], job=state, system=system_update.readiness())


def settings(data):
    if set(data) != {'enabled', 'public_key', 'allowed_hosts'} or type(data['enabled']) is not bool:
        raise ValueError('Supply enabled, public_key and allowed_hosts')
    hosts = data['allowed_hosts']
    if not isinstance(hosts, list) or len(hosts) > 16 or any(not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', host) for host in hosts):
        raise ValueError('Enter up to 16 download hostnames, without URLs or ports')
    key = data['public_key']
    if not isinstance(key, str) or len(key) > 8192:
        raise ValueError('Invalid update signing public key')
    if key:
        result = subprocess.run(['openssl', 'pkey', '-pubin', '-noout'], input=key, text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if result.returncode:
            raise ValueError('Enter a PEM public key, not a private key or certificate')
    if data['enabled'] and (not key or not hosts):
        raise ValueError('Configure a signing public key and allowed download host before enabling updates')
    with locked():
        atomic(STATE / 'update.json', dict(data, allowed_hosts=[host.lower() for host in hosts]))
    return status()


def check_url(url, hosts):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise ValueError('Invalid update URL')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.hostname.lower() not in hosts:
        raise ValueError('Use an HTTPS URL on an allowed download host')
    try:
        if parsed.port not in (None, 443):
            raise ValueError('Update downloads use HTTPS port 443')
    except ValueError:
        raise ValueError('Update downloads use HTTPS port 443') from None
    return url


@contextlib.contextmanager
def locked():
    import fcntl
    path = STATE / 'update-state/lock'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another update is already in progress') from None
        yield handle


def submit(data, topic=None):
    config = current()
    if not config['enabled']:
        raise ValueError('Remote updates are disabled on the router webpage')
    if len(data) != 1 or next(iter(data)) not in ('firmware', 'patch'):
        raise ValueError('Supply one firmware or patch HTTPS URL')
    url = check_url(next(iter(data.values())), config['allowed_hosts'])
    with locked() as lock:
        job = dict(id=uuid.uuid4().hex, url=url, topic=topic, config=config)
        job_path = STATE / 'update-state/job.json'
        atomic(job_path, job)
        atomic(STATE / 'update-state/status.json', dict(state='queued', id=job['id']))
        # Run a private snapshot, independent of files being replaced and MQTT/web restarts.
        worker = Path(tempfile.mkdtemp(prefix='router-updater-', dir='/tmp'))
        for name in ('firmware_update.py', 'update_bundle.py', 'system_update.py'):
            shutil.copyfile(Path(__file__).parent / name, worker / name)
        try:
            subprocess.Popen([sys.executable, str(worker / 'firmware_update.py'), '--job', str(job_path),
                              '--lock-fd', str(lock.fileno())], pass_fds=(lock.fileno(),), start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            shutil.rmtree(worker)
            atomic(STATE / 'update-state/status.json', dict(state='failed', error='Could not start update worker'))
            raise
    return dict(result='accepted', id=job['id'], message='Signed firmware update queued')


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, request, response, code, message, headers, url):
        check_url(url, self.hosts)
        return super().redirect_request(request, response, code, message, headers, url)


def download(url, path, hosts):
    check_url(url, hosts)
    opener = urllib.request.build_opener(Redirects(hosts))
    deadline = time.monotonic() + 300
    with opener.open(url, timeout=15) as response, path.open('wb') as output:
        total = 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > bundle.MAX_SYSTEM_DOWNLOAD or time.monotonic() > deadline:
                raise ValueError('Update download exceeds size or time limit')
            output.write(chunk)


def command(*args, timeout=120):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=timeout)


def active_services():
    data = json.loads(command('ubus', 'call', 'service', 'list'))
    return [name for name in ('router-web', 'router-mqtt', 'router-modbus', 'router-at', 'router-serial')
            if any(instance.get('running') for instance in data.get(name, {}).get('instances', {}).values())]


def services(names, action):
    for name in names:
        command('/etc/init.d/' + name, action, timeout=45 if name == 'router-modbus' else 20)


def backup(path):
    control = (ROOT / 'usr/lib/opkg/info/stm32-lte-router.control').read_text()
    files = {}
    listing = (ROOT / 'usr/lib/opkg/info/stm32-lte-router.list').read_text().splitlines()
    for entry in listing:
        name = entry.lstrip('/')
        source = ROOT / name
        if source.is_file():
            if not bundle.allowed(name) or source.is_symlink():
                raise ValueError('Installed application has unsupported files')
            files[name] = (source.read_bytes(), source.stat().st_mode & 0o777)
    if not files:
        raise ValueError('Cannot create application rollback backup')
    bundle.write_ipk(path, control, files)
    return control


def version(control):
    match = re.search(r'^Version: ([A-Za-z0-9.+~_-]+)$', control, re.M)
    if not match:
        raise ValueError('Missing package version')
    return match[1]


def healthy(names):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if set(names) <= set(active_services()):
            if 'router-web' not in names:
                return True
            try:
                connection = http.client.HTTPConnection('192.168.10.1', 8081, timeout=2)
                connection.request('GET', '/', headers={'Host': '192.168.10.1:8081'})
                response = connection.getresponse()
                response.read()
                connection.close()
                if response.status == 200:
                    return True
            except OSError:
                pass
        time.sleep(1)
    return False


def perform(job):
    state_path = STATE / 'update-state/status.json'
    def phase(name, **extra):
        atomic(state_path, dict(state=name, id=job['id'], **extra))
    installed, stopped, names = False, False, []
    with tempfile.TemporaryDirectory(prefix='router-update-', dir=TMP) as directory:
        work = Path(directory)
        rollback = STATE / 'update-state/rollback.ipk'
        try:
            phase('downloading')
            artifact, package, key = work / 'update.rupdate', work / 'update.ipk', work / 'public.pem'
            download(job['url'], artifact, job['config']['allowed_hosts'])
            phase('verifying')
            key.write_text(job['config']['public_key'])
            payload = bundle.verify(artifact, key)
            import system_update
            if system_update.is_system(payload):
                return system_update.install(payload, job, phase)
            control, files = bundle.reconstruct(payload, ROOT, package)
            required = sum(len(raw) for raw, _ in files.values()) * 3 + 16 * 1024 * 1024
            if shutil.disk_usage(ROOT).free < required or shutil.disk_usage(TMP).free < required:
                raise ValueError('Insufficient space for update and rollback')
            previous = backup(rollback)
            newer = subprocess.run(['opkg', 'compare-versions', version(control), '>', version(previous)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if newer.returncode:
                raise ValueError('Update must be newer than the installed version')
            names = active_services()
            phase('installing', version=version(control))
            stopped = True
            services(names, 'stop')
            installed = True  # opkg can partially modify files before reporting failure.
            command('opkg', 'install', str(package))
            services(names, 'start')
            stopped = False
            phase('checking', version=version(control))
            if not healthy(names):
                raise ValueError('Application health check failed')
            for name, (raw, mode) in files.items():
                if bundle.digest((ROOT / name).read_bytes()) != bundle.digest(raw):
                    raise ValueError('Installed application hash check failed')
            phase('succeeded', version=version(control))
            return dict(result='succeed', version=version(control))
        except Exception as error:
            rolled_back = False
            if installed:
                phase('rolling-back')
                try:
                    for name in names:
                        try:
                            services([name], 'stop')
                        except Exception:
                            pass
                    command('opkg', '--force-downgrade', 'install', str(rollback))
                    services(names, 'start')
                    rolled_back = healthy(names)
                    stopped = False
                except Exception:
                    for name in names:
                        try:
                            services([name], 'start')
                        except Exception:
                            pass
            elif stopped:
                try:
                    services(names, 'start')
                except Exception:
                    pass
            # Do not expose download query strings/credentials in errors.
            message = str(error)[:200] if isinstance(error, ValueError) else type(error).__name__
            phase('failed', error=message, rolled_back=rolled_back)
            return dict(result='fail', error=message, rolled_back=rolled_back)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--lock-fd', type=int, required=True)
    args = parser.parse_args()
    time.sleep(1)  # Allow the accepting HTTP/MQTT reply to leave before service restart.
    try:
        job = load(args.job, {})
        result = perform(job)
        if job.get('topic') in ('UPGRADE', 'EVENT/UPGRADE'):
            atomic(STATE / 'mqtt-state/outbox' / (uuid.uuid4().hex + '.json'), dict(topic=job['topic'], data=dict(result, id=job['id'])))
    finally:
        os.close(args.lock_fd)
        args.job.unlink(missing_ok=True)
        worker = Path(__file__).resolve().parent
        if worker.parent == Path('/tmp') and worker.name.startswith('router-updater-'):
            shutil.rmtree(worker)


if __name__ == '__main__':
    main()
