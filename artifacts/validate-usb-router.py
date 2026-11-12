"""Run on OpenWrt: test uploaded application against private UCI copies only."""
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile

package = Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix='usb-validation-') as tmp:
    root = Path(tmp)
    with tarfile.open(package) as outer:
        raw = outer.extractfile('./data.tar.gz').read()
    app = root / 'app'
    app.mkdir()
    with tarfile.open(fileobj=io.BytesIO(raw)) as data:
        for member in data:
            if member.isfile() and member.name.startswith('./usr/lib/router-web/'):
                (app / Path(member.name).name).write_bytes(data.extractfile(member).read())
    sys.path.insert(0, str(app))
    import openwrt_backend as platform
    import usb_tethering as usb
    import recovery_button as button
    from server import atomic_write
    live = {p: (Path('/etc/config') / p).read_bytes() for p in ('network', 'dhcp', 'firewall')}
    config = root / 'config'
    config.mkdir()
    for p in Path('/etc/config').iterdir():
        if p.is_file():
            shutil.copyfile(p, config / p.name)
    platform.CONFIG = config
    platform.STATE = root / 'state'
    platform.STATE.mkdir()
    original_run = platform.run

    def values(package):
        result = {}
        for line in original_run('uci', '-c', str(config), '-X', 'show', package).splitlines():
            key, raw = line.split('=', 1)
            parts = key.split('.')
            entries = shlex.split(raw)
            if len(parts) == 2:
                result[parts[1]] = {'.type': entries[0]}
            elif len(parts) == 3:
                result[parts[1]][parts[2]] = entries[0] if len(entries) == 1 else entries
        return result

    platform.values = values
    library = root / 'fw4.uc'
    library.write_text(Path('/usr/share/ucode/fw4.uc').read_text().replace(
        'uci.cursor()', 'uci.cursor(' + json.dumps(str(config)) + ')'))
    template = root / 'main.uc'
    template.write_text(Path('/usr/share/firewall4/main.uc').read_text())
    (root / 'templates').symlink_to('/usr/share/firewall4/templates')

    def validate():
        generated = subprocess.check_output(['utpl', '-S', '-L', str(root), str(template)],
                                            env=dict(os.environ, ACTION='print'), text=True)
        subprocess.run(['nft', '-c', '-f', '-'], input=generated, text=True, check=True)
        return generated

    def run(*args):
        if args == ('fw4', 'check'):
            validate()
            return ''
        return original_run(*args)

    platform.run = run
    for enabled in (True, False):
        usb.apply(dict(enabled=enabled, revision=usb.revision(platform)), platform, atomic_write)
        settings = values('dhcp')['management']['dhcp_option']
        assert settings == (['3,192.168.7.1', '6,192.168.7.1'] if enabled else ['3', '6'])
        rules = validate()
        management_chain = rules.split('chain forward_management {', 1)[1].split('\n\t}', 1)[0]
        assert ('jump accept_to_wan' in management_chain) == enabled, management_chain
        print('PASS private UCI and nftables validation: tethering', enabled)
    # Recover after a saved enabled state, with USB address and DHCP disabled.
    usb.apply(dict(enabled=True, revision=usb.revision(platform)), platform, atomic_write)
    for package, option, value in [('network', 'management.disabled', '1'),
                                    ('network', 'management.ipaddr', '10.99.0.1'),
                                    ('dhcp', 'management.ignore', '1')]:
        original_run('uci', '-c', str(config), 'set', package + '.' + option + '=' + value)
        original_run('uci', '-c', str(config), 'commit', package)
    button.recover(platform, atomic_write)
    assert values('network')['management']['ipaddr'] == '192.168.7.1'
    assert values('network')['management']['disabled'] == '0'
    assert values('dhcp')['management']['ignore'] == '0'
    assert values('dhcp')['management']['dhcp_option'] == ['3', '6']
    assert not usb.status(platform)['enabled']
    validate()
    print('PASS private UCI recovery: USB address, DHCP, management-only firewall restored')
    for p, content in live.items():
        assert (Path('/etc/config') / p).read_bytes() == content
    print('PASS live network/DHCP/firewall unchanged')
