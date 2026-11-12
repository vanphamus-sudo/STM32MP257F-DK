"""Assemble a blank-eMMC CubeProgrammer bundle from the pinned local artifacts.

Run with Python 3 on Windows and portable e2fsprogs in local/image-tools.
Never opens a physical disk or connects to a board. Output stays under local/.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO)
TOOLS = REPO / 'local/image-tools'
WORK = REPO / 'local/router-factory-work'
OUT = REPO / 'local/router-factory-emmc'
ST = REPO / 'local/stm32mp2-openstlinux-6.6-yocto-scarthgap-mpu-v26.06.10/images/stm32mp2'
BASE = REPO / 'local/openwrt-flash'
sys.path[:0] = [str(REPO / 'openwrt'), str(REPO / 'web')]
from provision import configs, section


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def tool(name, *args, allowed=(0,)):
    env = os.environ.copy()
    env['MKE2FS_CONFIG'] = str(TOOLS / 'mke2fs.conf')
    p = subprocess.run([str(TOOLS / (name + '.exe')), *map(str, args)],
                       capture_output=True, env=env)
    text = (p.stdout + p.stderr).decode(errors='replace')
    if p.returncode not in allowed:
        raise RuntimeError(name + ': ' + text)
    return text


def debug(img, cmd, write=False):
    if '\n' in cmd:
        commands = WORK / 'debugfs-commands'
        commands.write_text(cmd + '\n', newline='\n')
        request = ['-f', str(commands)]
    else:
        request = ['-R', cmd]
    p = subprocess.run([str(TOOLS / 'debugfs.exe'), *(['-w'] if write else []),
                        *request, str(img)], capture_output=True)
    if p.returncode or any(x in p.stderr for x in
            (b'File not found', b'Command not found', b'while ', b'Usage:', b'not open')):
        raise RuntimeError(p.stderr.decode(errors='replace'))
    return p.stdout


def exists(img, path):
    try:
        debug(img, 'stat ' + path)
        return True
    except RuntimeError:
        return False


def remove(img, path):
    if exists(img, path):
        debug(img, 'rm ' + path, True)


def put(img, path, content, mode=0o644):
    content = content.encode() if isinstance(content, str) else content
    source = WORK / 'payload'
    source.write_bytes(content)
    remove(img, path)
    parent, name = path.rsplit('/', 1)
    debug(img, f'cd {parent or "/"}\nwrite {source.as_posix()} {name}', True)
    debug(img, f'set_inode_field {path} mode 0{(0o100000 | mode):o}', True)
    debug(img, f'set_inode_field {path} uid 0', True)
    debug(img, f'set_inode_field {path} gid 0', True)
    assert debug(img, 'cat ' + path) == content, path


def symlink(img, path, target):
    remove(img, path)
    parent, name = path.rsplit('/', 1)
    debug(img, f'cd {parent or "/"}\nsymlink {name} {target}', True)


def fresh(path, size_mb, label):
    with path.open('wb') as f:
        f.truncate(size_mb * 1024 * 1024)
    tool('mke2fs', '-q', '-F', '-t', 'ext4', '-L', label, path)


def scrub_free_blocks(img):
    # Drop the inherited journal, clear all unallocated blocks, then create a
    # new journal. dumpe2fs understands uninitialized group bitmap flags.
    tool('tune2fs', '-O', '^has_journal', img)
    tool('e2fsck', '-f', '-p', img, allowed=(0, 1))
    info = tool('dumpe2fs', img)
    blocksize = int(re.search(r'Block size:\s+(\d+)', info)[1])
    with img.open('r+b') as f:
        for ranges in re.findall(r'^\s+Free blocks: (.*)$', info, re.M):
            for entry in ranges.strip().split(', '):
                if not entry:
                    continue
                bounds = entry.split('-')
                start, end = int(bounds[0]), int(bounds[-1])
                f.seek(start * blocksize)
                length = (end - start + 1) * blocksize
                while length:
                    size = min(length, 1024 * 1024)
                    f.write(bytes(size))
                    length -= size
    tool('tune2fs', '-j', img)


def main():
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    root = OUT / 'router-rootfs.ext4'
    with gzip.open(BASE / 'router-openwrt-emmc-rootfs.img.gz', 'rb') as src, root.open('wb') as dst:
        shutil.copyfileobj(src, dst)
    assert sha(root) == 'fad6b30397e62a055698966d664e62d8a5b6c8a2785be24eb155ffc19e06005c'
    private = []
    gadget_before = debug(root, 'cat /etc/config/usbgadget').decode()
    private.extend(value.encode() for value in re.findall(
        r'option (?:serialnumber|host_addr|dev_addr)\s+[\"\x27]([^\"\x27]+)', gadget_before))
    for path in ('/etc/router-web/credentials.json', '/etc/dropbear/dropbear_rsa_host_key', '/etc/shadow'):
        data = debug(root, 'cat ' + path)
        if path.endswith('credentials.json'):
            private.append(json.loads(data)['hash'].encode())
        elif path.endswith('shadow'):
            private.append(data.split(b':')[1])
        else:
            private.append(data)
        remove(root, path)
    # Restore the upstream empty root password: set it from serial with passwd.
    put(root, '/etc/shadow', debug(BASE / 'rootfs.img', 'cat /etc/shadow'), 0o600)
    for path in ('/etc/urandom.seed', '/etc/machine-id', '/etc/uhttpd.key', '/etc/uhttpd.crt'):
        remove(root, path)
    for filename in ('cellular_info.py', 'mobile-networks.json', 'ip_passthrough.py', 'router_features.py', 'router_supervisor.py', 'router-features.js', 'user-guide.js', 'serial_assignment.py', 'modbus_collection.py', 'modbus_settings.py', 'modbus.js', 'traffic_stats.py', 'mqtt_metrics.py', 'system_update.py', 'firmware_update.py', 'update_bundle.py', 'firmware.js', 'mqtt_events.py', 'mqtt_settings.py', 'mqtt.js', 'mqtt_client.py', 'mqtt_protocol.py', 'mqtt_data.py', 'mqtt_proxy.py', 'server.py', 'wifi.py', 'openwrt_backend.py', 'openvpn_client.py', 'modem_details.py', 'serial_tcp.py', 'at_tcp.py', 'version_info.py', 'port_forwarding.py', 'port-forwarding.js', 'dhcp_reservations.py', 'dhcp-reservations.js', 'ethernet.py', 'recovery_button.py', 'ethernet.js', 'index.html', 'app.js', 'style.css'):
        put(root, '/usr/lib/router-web/' + filename, (REPO / 'web' / filename).read_bytes().replace(b'\r\n', b'\n'))
    for filename in ('initialize.py', 'provision.py', 'provision-system-updates.py', 'factory-initialize.py', 'factory-modem.py'):
        put(root, '/usr/lib/router-web/' + filename, (REPO / 'openwrt' / filename).read_bytes().replace(b'\r\n', b'\n'))
    put(root, '/etc/init.d/router-serial', (REPO / 'openwrt/router-serial.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    put(root, '/etc/init.d/router-features', (REPO / 'openwrt/router-features.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    symlink(root, '/etc/rc.d/S95router-features', '../init.d/router-features')
    symlink(root, '/etc/rc.d/K08router-features', '../init.d/router-features')
    put(root, '/etc/init.d/router-traffic', (REPO / 'openwrt/router-traffic.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    put(root, '/etc/init.d/router-button', (REPO / 'openwrt/router-button.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    symlink(root, '/etc/rc.d/S18router-button', '../init.d/router-button')
    symlink(root, '/etc/rc.d/K10router-button', '../init.d/router-button')
    symlink(root, '/etc/rc.d/S94router-traffic', '../init.d/router-traffic')
    symlink(root, '/etc/rc.d/K09router-traffic', '../init.d/router-traffic')
    put(root, '/etc/init.d/router-storage', (REPO / 'openwrt/router-storage.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    put(root, '/lib/preinit/09_router_storage', (REPO / 'openwrt/router-storage.preinit').read_bytes().replace(b'\r\n', b'\n'))
    put(root, '/etc/init.d/router-update-confirm', (REPO / 'openwrt/router-update-confirm.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    put(root, '/etc/init.d/router-modbus', (REPO / 'openwrt/router-modbus.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    put(root, '/etc/init.d/router-mqtt', (REPO / 'openwrt/router-mqtt.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    put(root, '/etc/init.d/router-at', (REPO / 'openwrt/router-at.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    put(root, '/etc/hotplug.d/openvpn/30-router', (REPO / 'openwrt/router-openvpn.hotplug').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    for name, content in configs('eth0', '/sys/devices/router-modem-not-yet-detected', 'usb0').items():
        put(root, '/etc/config/' + name, content, 0o600)
    gadget = section('gadget', 'g1', idVendor='0x1d6b', idProduct='0x0104', bcdUSB='0x200',
        bDeviceClass='0xEF', bDeviceSubClass='0x02', bDeviceProtocol='0x01', bcdDevice='0x100',
        manufacturer='STMicroelectronics', product='STM32 LTE Router', use='1',
        b_vendor_code='0xBC', qw_sign='MSFT100', UDC='48300000.usb')
    gadget += section('configuration', 'cfg1', configuration='Config 1: NCM', MaxPower='0', bmAttributes='0xC0', gadget='g1')
    gadget += section('function', 'eth1', function='ncm', configuration='cfg1', compatible_id='WINNCM')
    put(root, '/etc/config/usbgadget', gadget, 0o600)
    put(root, '/etc/uci-defaults/99-router-factory', '#!/bin/sh\n/usr/bin/python3 /usr/lib/router-web/factory-initialize.py\n', 0o755)
    put(root, '/etc/init.d/router-modem-discovery', '''#!/bin/sh /etc/rc.common
START=90
STOP=10
USE_PROCD=1
start_service() {
    procd_open_instance
    procd_set_param command /usr/bin/python3 /usr/lib/router-web/factory-modem.py
    procd_set_param respawn 3600 5 0
    procd_set_param stderr 1
    procd_close_instance
}
''', 0o755)
    symlink(root, '/etc/rc.d/S90router-modem-discovery', '../init.d/router-modem-discovery')
    symlink(root, '/etc/rc.d/K10router-modem-discovery', '../init.d/router-modem-discovery')
    put(root, '/etc/init.d/router-web', (REPO / 'openwrt/router-web.init').read_bytes().replace(b'\r\n', b'\n'), 0o755)
    put(root, '/lib/upgrade/platform.sh', '''REQUIRE_IMAGE_METADATA=1
platform_check_image() { echo "Use the STM32 router eMMC CubeProgrammer bundle." >&2; return 1; }
platform_do_upgrade() { echo "Stock SD sysupgrade is disabled for this eMMC layout." >&2; return 1; }
''')
    # Stock preinit tries SD partition 4, which is fip-b on this eMMC layout.
    put(root, '/lib/preinit/79_move_config', '# Factory eMMC image: no SD sysupgrade restore hook.\n')
    scrub_free_blocks(root)
    raw = root.read_bytes()
    assert all(value not in raw for value in private if value), 'Inherited secret remains in image'
    del raw, private
    print('Router filesystem sanitized and configured.', flush=True)

    boot = OUT / 'router-bootfs.ext4'
    fresh(boot, 64, 'bootfs')
    for name in ('Image.gz', 'stm32mp257f-dk.dtb'):
        dump = WORK / name
        debug(BASE / 'boot.img', f'dump /{name} {dump.as_posix()}')
        put(boot, '/' + name, dump.read_bytes())
    menu = '''DEFAULT Router
TIMEOUT 30
LABEL Router
  MENU LABEL STM32MP257F-DK OpenWrt LTE router
  KERNEL /Image.gz
  FDT /stm32mp257f-dk.dtb
  APPEND root=PARTLABEL=rootfs rootwait rw console=ttySTM0,115200n8 fw_devlink=on fw_devlink.sync_state=timeout
'''
    for directory in ('mmc1_extlinux', 'extlinux'):
        debug(boot, 'mkdir ' + directory, True)
        put(boot, '/' + directory + '/extlinux.conf', menu)
    fresh(OUT / 'empty-vendorfs.ext4', 16, 'vendorfs')
    fresh(OUT / 'empty-userfs.ext4', 16, 'userfs')
    source_layout = ST / 'flashlayout_st-image-weston/optee/FlashLayout_emmc_stm32mp257f-dk-optee.tsv'
    lines = []
    replacements = {'bootfs': boot.name, 'rootfs': root.name,
                    'vendorfs': 'empty-vendorfs.ext4', 'userfs': 'empty-userfs.ext4'}
    for line in source_layout.read_text().splitlines():
        if not line or line.startswith('#'):
            lines.append(line)
            continue
        fields = line.split('\t')
        name, binary = fields[2], fields[6]
        if name in replacements:
            fields[6] = replacements[name]
        elif binary != 'none':
            dest = OUT / binary
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ST / binary, dest)
        lines.append('\t'.join(fields))
    layout = OUT / 'FlashLayout_router_emmc_stm32mp257f-dk.tsv'
    layout.write_text('\n'.join(lines) + '\n', newline='\n')
    checks = {}
    for path in OUT.glob('*.ext4'):
        checks[path.name] = tool('e2fsck', '-f', '-n', path)
    for line in lines:
        if line and not line.startswith('#'):
            fields = line.split('\t')
            if fields[6] != 'none':
                assert (OUT / fields[6]).is_file()
    # Exact standard ST offsets, bootfs/rootfs fit their next partition boundary.
    assert boot.stat().st_size <= 0x04A00000 - 0x00A00000
    assert root.stat().st_size <= 0xD4400000 - 0x14400000
    (OUT / 'validation.json').write_text(json.dumps(dict(
        hardware_boot_tested=False, secret_scan_passed=True, filesystem_checks=checks,
        source_root_sha256='fad6b30397e62a055698966d664e62d8a5b6c8a2785be24eb155ffc19e06005c',
        openwrt='24.10.8 r29233-443ec4032a', kernel='6.6.144',
        boot_firmware='ST OpenSTLinux v26.06.10',
        layout='ST standard eMMC offsets; OpenWrt root on p8; no recovery OS'), indent=2) + '\n')
    shutil.copyfile(REPO / 'docs/factory-image.md', OUT / 'README.md')
    files = sorted(p for p in OUT.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    (OUT / 'SHA256SUMS').write_text(''.join(sha(p) + '  ' + p.relative_to(OUT).as_posix() + '\n' for p in files))
    archive = OUT.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(OUT))
    archive.with_suffix('.zip.sha256').write_text(sha(archive) + '  ' + archive.name + '\n')
    print(f'Built {archive} ({archive.stat().st_size:,} bytes)', flush=True)


if __name__ == '__main__':
    main()
