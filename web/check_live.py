"""Run on the board to verify the deployed API using the local admin credential."""
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.request

url = 'http://192.168.10.1'
client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def request(path, data=None, csrf=None):
    headers = {}
    if data is not None:
        headers = {'Content-Type': 'application/json', 'Origin': url}
    if csrf:
        headers['X-CSRF-Token'] = csrf
    req = urllib.request.Request(url + path, None if data is None else json.dumps(data).encode(), headers)
    with client.open(req, timeout=30) as response:
        return json.load(response)


try:
    request('/api/status')
    raise AssertionError('Status was exposed without login')
except urllib.error.HTTPError as error:
    assert error.code == 401
password = Path('/var/lib/router-web/initial-password').read_text().strip()
csrf = request('/api/login', dict(username='admin', password=password))['csrf']
before = request('/api/status')
assert before['services']['dnsmasq'] == 'active'
saved = request('/api/settings', before['settings'], csrf)
after = request('/api/status')
assert saved['settings'] == before['settings'] == after['settings']
assert after['services']['dnsmasq'] == 'active'
assert after['addresses']['end0'] == ['192.168.10.1']
request('/api/logout', {}, csrf)
print(json.dumps(dict(result='PASS: login, live status, unchanged settings apply, DNS/DHCP restart, logout',
    clients=after['leases'], modem=after['modem'], services=after['services'])))
