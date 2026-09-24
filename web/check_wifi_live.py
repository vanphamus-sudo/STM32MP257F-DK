import http.cookiejar
import json
from pathlib import Path
import urllib.request
client=urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def request(path, data=None, csrf=''):
    req=urllib.request.Request('http://192.168.10.1/api/'+path,
        None if data is None else json.dumps(data).encode(),
        {'Content-Type':'application/json','X-CSRF-Token':csrf})
    with client.open(req,timeout=30) as response:
        return json.load(response)
password=Path('/var/lib/router-web/initial-password').read_text().strip()
csrf=request('login',dict(username='admin',password=password))['csrf']
before=request('status')['wifi']
assert before['state']=='enabled'
assert 'psk' not in before and 'password' not in before
result=request('wifi',dict(enabled=True,ssid=before['ssid'],channel=before['channel'],password=''),csrf)
assert result['wifi']['state']=='enabled'
request('logout',{},csrf)
print('PASS: authenticated hotspot status, no secret exposure, settings apply and AP readiness')
