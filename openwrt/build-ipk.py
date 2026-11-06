#!/usr/bin/env python3
"""Package the architecture-independent router scripts without a cross compiler.

Dependencies still come from the exact OpenWrt/ST firmware release. This builds
only the application IPK, not a kernel or firmware image.
"""
import argparse
from datetime import datetime
import gzip
import io
from pathlib import Path
import re
import tarfile


def archive(files, mtime=0):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        directories = sorted({str(parent).replace('\\', '/') for name, _, _ in files
                              for parent in Path(name).parents if str(parent) != '.'},
                             key=lambda name: (name.count('/'), name))
        for directory in directories:
            entry = tarfile.TarInfo('./' + directory + '/')
            entry.type, entry.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(entry)
        for name, content, mode in files:
            entry = tarfile.TarInfo('./' + name)
            entry.size, entry.mode = len(content), mode
            entry.uid = entry.gid = 0
            entry.mtime = mtime
            tar.addfile(entry, io.BytesIO(content))
    return gzip.compress(raw.getvalue(), mtime=0)


def build(output):
    root = Path(__file__).resolve().parents[1]
    makefile = (root / 'openwrt/Makefile').read_text()
    version = re.search(r'^PKG_VERSION:=(.+)$', makefile, re.M)[1]
    release = re.search(r'^PKG_RELEASE:=(.+)$', makefile, re.M)[1]
    metadata = {}
    exec((root / 'web/version_info.py').read_text(), metadata)
    assert metadata['VERSION'] == version + '-r' + release, 'Update version_info.py for this release'
    dependencies = re.search(r'^  DEPENDS:=(.+)$', makefile, re.M)[1].split()
    assert all(re.fullmatch(r'\+[a-z0-9+-]+', name) for name in dependencies)
    control = ('Package: stm32-lte-router\nVersion: ' + version + '-r' + release +
               '\nArchitecture: all\nDepends: ' + ', '.join(name[1:] for name in dependencies) +
               '\nSection: net\nDescription: STM32 LTE router settings and provisioning\n')
    data = []
    for name in ('serial_assignment.py', 'modbus_collection.py', 'modbus_settings.py', 'modbus.js', 'traffic_stats.py', 'mqtt_metrics.py', 'system_update.py', 'firmware_update.py', 'update_bundle.py', 'firmware.js', 'mqtt_events.py', 'mqtt_settings.py', 'mqtt.js', 'mqtt_client.py', 'mqtt_protocol.py', 'mqtt_data.py', 'mqtt_proxy.py', 'server.py', 'wifi.py', 'openwrt_backend.py', 'openvpn_client.py', 'modem_details.py', 'serial_tcp.py', 'at_tcp.py', 'version_info.py', 'port_forwarding.py', 'port-forwarding.js', 'dhcp_reservations.py', 'dhcp-reservations.js', 'ethernet.py', 'ethernet.js', 'index.html', 'app.js', 'style.css'):
        data.append(('usr/lib/router-web/' + name, (root / 'web' / name).read_bytes(), 0o644))
    for name in ('provision.py', 'initialize.py', 'provision-system-updates.py'):
        data.append(('usr/lib/router-web/' + name, (root / 'openwrt' / name).read_bytes(), 0o644))
    data += [('etc/init.d/router-web', (root / 'openwrt/router-web.init').read_bytes(), 0o755),
             ('etc/init.d/router-serial', (root / 'openwrt/router-serial.init').read_bytes(), 0o755),
             ('etc/init.d/router-traffic', (root / 'openwrt/router-traffic.init').read_bytes(), 0o755),
             ('etc/init.d/router-storage', (root / 'openwrt/router-storage.init').read_bytes(), 0o755),
             ('lib/preinit/09_router_storage', (root / 'openwrt/router-storage.preinit').read_bytes(), 0o644),
             ('etc/init.d/router-update-confirm', (root / 'openwrt/router-update-confirm.init').read_bytes(), 0o755),
             ('etc/init.d/router-modbus', (root / 'openwrt/router-modbus.init').read_bytes(), 0o755),
             ('etc/init.d/router-mqtt', (root / 'openwrt/router-mqtt.init').read_bytes(), 0o755),
             ('etc/init.d/router-at', (root / 'openwrt/router-at.init').read_bytes(), 0o755),
             ('etc/hotplug.d/openvpn/30-router', (root / 'openwrt/router-openvpn.hotplug').read_bytes(), 0o755),
             ('lib/upgrade/keep.d/stm32-lte-router', (root / 'openwrt/sysupgrade.keep').read_bytes(), 0o644)]
    package = archive([
        ('debian-binary', b'2.0\n', 0o644),
        ('control.tar.gz', archive([('control', control.encode(), 0o644)]), 0o644),
        # A release timestamp prevents Python from reusing a same-size .pyc from
        # an earlier package whose source files also had mtime zero.
        ('data.tar.gz', archive(data, mtime=int(datetime.fromisoformat(metadata['CREATED_AT']).timestamp())), 0o644),
    ])
    output.write_bytes(package)
    print(str(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
