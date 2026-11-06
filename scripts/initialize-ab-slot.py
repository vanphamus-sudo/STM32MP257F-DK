#!/usr/bin/env python3
"""Initialize a blank inactive slot from a frozen snapshot of this router.

Default is read-only. Run on the kit after its A/B boot hook has been tested.
Only the explicitly configured unmounted inactive root partition is written.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, '/usr/lib/router-web')
import system_update as system


def initialize(apply=False):
    data = system.profile()
    active = system.active_slot(data)
    inactive = 'B' if active == 'A' else 'A'
    source_device = system.device(data['slots'][active]['partuuid'])
    target_device = system.device(data['slots'][inactive]['partuuid'])
    if system.mounted(target_device):
        raise ValueError('Inactive slot must be unmounted')
    if subprocess.run(['blkid', '-s', 'TYPE', '-o', 'value', str(target_device)], capture_output=True).stdout:
        raise ValueError('Inactive slot already has a filesystem; refusing to overwrite it')
    staging = system.staging_directory(data)
    with source_device.open('rb', buffering=0) as source:
        source.seek(1024)
        sb = source.read(1024)
    if sb[56:58] != b'\x53\xef':
        raise ValueError('Active root is not ext4')
    length = struct.unpack_from('<I', sb, 4)[0] * (1024 << struct.unpack_from('<I', sb, 24)[0])
    if length > data.get('max_rootfs_bytes', system.MAX_IMAGE):
        raise ValueError('Active filesystem exceeds the configured image limit')
    with target_device.open('rb', buffering=0) as target:
        capacity = struct.unpack('Q', fcntl.ioctl(target, 0x80081272, bytes(8)))[0]
    if capacity < length:
        raise ValueError('Inactive slot is too small')
    plan = dict(active=active, inactive=inactive, target=str(target_device), snapshot_bytes=length)
    if not apply:
        return plan
    boot, unmount = system.boot_mount(data)
    cache = staging / 'router-image-cache'
    cache.mkdir(exist_ok=True, mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix='router-initial-snapshot-', dir='/tmp') as directory:
            image = Path(directory) / 'rootfs.img'
            source = source_device.open('rb', buffering=0)
            destination = image.open('wb', buffering=0)
            root_fd = os.open('/', os.O_RDONLY)
            def timeout(*_):
                raise TimeoutError('Root freeze exceeded 45 seconds')
            signal.signal(signal.SIGALRM, timeout)
            frozen = False
            os.sync()
            try:
                signal.alarm(45)
                fcntl.ioctl(root_fd, 0xC0045877, 0)
                frozen = True
                remaining = length
                while remaining:
                    raw = source.read(min(remaining, 4*1024*1024))
                    if not raw:
                        raise ValueError('Short active-root snapshot read')
                    destination.write(raw)
                    remaining -= len(raw)
            finally:
                if frozen:
                    fcntl.ioctl(root_fd, 0xC0045878, 0)
                signal.alarm(0)
                os.close(root_fd)
                source.close()
                destination.close()
            # Normalize only the offline snapshot, never the mounted source.
            result = subprocess.run(['e2fsck', '-p', '-f', str(image)], capture_output=True, text=True)
            if result.returncode not in (0, 1):
                raise ValueError('Offline snapshot filesystem check failed: ' + result.stdout[-500:])
            expected = system.file_hash(image)
            with image.open('rb') as source, target_device.open('r+b', buffering=0) as destination:
                shutil.copyfileobj(source, destination, 1024*1024)
                os.fsync(destination.fileno())
            if system.file_hash(target_device, length) != expected:
                raise ValueError('Inactive slot readback hash mismatch')
            system.run('tune2fs', '-U', 'random', '-L', 'router-root-' + inactive.lower(), str(target_device))
            shutil.copyfile(image, cache / 'rootfs.img')
            (cache / 'rootfs.img').chmod(0o600)
            origin, target = boot / 'router-slots' / active, boot / 'router-slots' / inactive
            target.mkdir(parents=True, exist_ok=True)
            for name, filename in [('kernel', 'Image.gz'), ('dtb', 'board.dtb')]:
                shutil.copyfile(origin / filename, target / filename)
                shutil.copyfile(origin / filename, cache / (name + '.img'))
            configuration = (origin / 'extlinux.conf').read_text()
            configuration = configuration.replace('/router-slots/' + active + '/', '/router-slots/' + inactive + '/')
            configuration = configuration.replace(data['slots'][active]['partuuid'], data['slots'][inactive]['partuuid'])
            (target / 'extlinux.conf').write_text(configuration)
            plan.update(rootfs_sha256=expected, cache=str(cache), result='inactive slot cloned and read back; boot selection unchanged')
            (staging / 'initial-slot-baseline.json').write_text(json.dumps(plan, indent=2))
            os.sync()
    finally:
        if unmount:
            system.run('umount', str(boot))
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    print(json.dumps(initialize(parser.parse_args().apply), indent=2))
