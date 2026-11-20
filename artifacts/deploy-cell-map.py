"""Install the cell map web files with a backup and automatic rollback."""
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

STAGE = Path('/tmp/router-cell-map-deploy')
LIVE = Path('/usr/lib/router-web')
sys.path[:0] = [str(STAGE), str(LIVE)]
import server

server.OPENWRT = False
server.PORT = 80
suite = unittest.defaultTestLoader.loadTestsFromNames(['test_modem_details', 'test_server'])
if not unittest.TextTestRunner().run(suite).wasSuccessful():
    raise SystemExit('Staged tests failed; no live files changed.')

files = ['app.js', 'index.html', 'server.py', 'modem_details.py']
for name in ('server.py', 'modem_details.py'):
    compile((STAGE / name).read_text(), name, 'exec')
assert not Path('/etc/router-web/feature-pending.json').exists(), 'Confirm pending network changes first'
backup = Path('/root/router-before-cell-map-' + time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
for name in files:
    shutil.copy2(LIVE / name, backup / name)


def restart():
    subprocess.run(['/etc/init.d/router-web', 'restart'], check=True, timeout=30)


def get(path, method='GET', body=None, headers=None):
    connection = http.client.HTTPConnection('192.168.7.1', 8081, timeout=5)
    connection.request(method, path, body, dict({'Host': '192.168.7.1:8081'}, **(headers or {})))
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data


try:
    for name in files:
        temporary = LIVE / (name + '.cell-map-new')
        shutil.copy2(STAGE / name, temporary)
        temporary.replace(LIVE / name)
    restart()
    for attempt in range(20):
        try:
            status, html = get('/')
            if status == 200:
                break
        except OSError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError('Web service failed to start')
    assert b'id="open-modem-map"' in html
    status, script = get('/app.js')
    assert status == 200 and b"api('modem/location', {})" in script
    status, _ = get('/api/modem/location', 'POST', '{}', {'Content-Type': 'application/json'})
    assert status == 401, 'Location endpoint must require authentication'
    for name in files:
        assert (LIVE / name).read_bytes() == (STAGE / name).read_bytes()
    # Load the installed implementation, rather than the staged module cached by tests.
    import importlib.util
    spec = importlib.util.spec_from_file_location('installed_modem_details', LIVE / 'modem_details.py')
    modem = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modem)
    import openwrt_backend
    try:
        location = modem.locate(openwrt_backend)
        lookup = 'success (' + location['source'] + ')'
    except (ValueError, RuntimeError) as error:
        lookup = str(error)
    report = dict(deployed=True, backup=str(backup), web_status=200,
                  location_requires_login=True, live_cell_lookup=lookup,
                  hashes={name: hashlib.sha256((LIVE / name).read_bytes()).hexdigest() for name in files})
    (backup / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
except BaseException:
    for name in files:
        shutil.copy2(backup / name, LIVE / name)
    restart()
    raise
