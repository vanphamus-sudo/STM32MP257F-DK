"""Install the narrow cellular UI change while preserving other live app edits."""
import ast
import base64
import json
from pathlib import Path
import subprocess

SSH = ['ssh', '-F', 'NUL', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
       '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=local/ddns-known-hosts',
       'root@192.168.7.1']


def remote(code):
    result = subprocess.run(SSH + ['python3 -'], input=code.encode(), capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError(result.stderr.decode())
    return result.stdout.decode()


live = json.loads(remote("from pathlib import Path\nimport json\nprint(json.dumps({n:Path('/usr/lib/router-web',n).read_text() for n in ('server.py','index.html','user-guide.js')}))\n"))
local_server = Path('web/server.py').read_text(encoding='utf-8')
target = live['server.py']
if 'import cellular_settings\n' not in target:
    assert 'import router_features\n' in target
    target = target.replace('import router_features\n', 'import router_features\nimport cellular_settings\n', 1)
    anchor = "        if self.path == '/api/ethernet' and OPENWRT:\n"
    start = local_server.index("        if self.path == '/api/cellular' and OPENWRT:\n")
    block = local_server[start:local_server.index(anchor, start)]
    assert anchor in target
    target = target.replace(anchor, block + anchor, 1)
    anchor = "        if self.path == '/api/logout':\n"
    start = local_server.index("        if self.path == '/api/cellular':\n")
    block = local_server[start:local_server.index(anchor, start)]
    assert anchor in target
    target = target.replace(anchor, block + anchor, 1)
if "'/cellular.js':" not in target:
    anchor = "                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),"
    assert anchor in target
    target = target.replace(anchor, anchor + "\n                  '/cellular.js': ('cellular.js', 'text/javascript; charset=utf-8'),", 1)
assert "'/api/account'" in target, 'Live server must support webpage credential changes'
ast.parse(target)
html = live['index.html']
if 'id="cellular-panel"' not in html:
    local_html = Path('web/index.html').read_text(encoding='utf-8')
    section = local_html[local_html.index('<section id="cellular-panel"'):local_html.index('<section id="account-panel"')]
    assert '<section id="account-panel"' in html
    html = html.replace('<section id="account-panel"', section + '<section id="account-panel"', 1)
    html = html.replace('</head>', '<script src="/cellular.js" defer></script></head>', 1)
    html = html.replace('<summary>Cellular</summary>', '<summary>Cellular</summary><a href="#cellular-panel">APN &amp; connection</a>', 1)
html = html.replace('href="#account-panel">Login details</a>', 'href="#account-panel">Webpage login</a>')
html = html.replace('<h2>Login details</h2>', '<h2>Webpage login</h2>')
guide = live['user-guide.js']
local_guide = Path('web/user-guide.js').read_text(encoding='utf-8')
if "'cellular-panel':" not in guide:
    start = local_guide.index("  'cellular-panel':")
    topic = local_guide[start:local_guide.index("  'account-panel':", start)]
    guide = guide.replace("  'account-panel':", topic + "  'account-panel':", 1)
if "'cellular-apn':" not in guide:
    start = local_guide.index("  'cellular-apn':")
    fields = local_guide[start:local_guide.index("  username:", start)]
    guide = guide.replace('const routerFieldHelp = {\n', 'const routerFieldHelp = {\n' + fields, 1)
payload = {'server.py': target, 'index.html': html, 'user-guide.js': guide,
           **{name: Path('web', name).read_text(encoding='utf-8') for name in ('cellular_settings.py', 'cellular.js')}}
files = {name: base64.b64encode(text.encode()).decode() for name, text in payload.items()}
code = "FILES=" + repr(files) + '\n'
code += '''from pathlib import Path
import ast, base64, shutil, time
root=Path('/usr/lib/router-web')
backup=Path('/root/router-before-cellular-settings-'+str(int(time.time())))
backup.mkdir()
for name, encoded in FILES.items():
    content=base64.b64decode(encoded)
    if name.endswith('.py'): ast.parse(content)
    path=root/name
    if path.exists(): shutil.copy2(path, backup/name)
    candidate=path.with_suffix('.new')
    candidate.write_bytes(content)
    candidate.chmod(0o644)
    candidate.replace(path)
print('Backup:', backup)
'''
print(remote(code))
result = subprocess.run(SSH + ['/etc/init.d/router-web restart'], capture_output=True, timeout=30)
if result.returncode:
    raise RuntimeError(result.stderr.decode())
print('Installed cellular settings and webpage login navigation; existing credentials preserved.')
