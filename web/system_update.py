"""A/B OS/kernel updates for an explicitly provisioned STM32 boot profile.

No partition is created/resized and no bootloader firmware is flashed here.
The local profile and U-Boot environment must be provisioned and boot-tested.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import time
import zipfile

import update_bundle as bundle

PROFILE = Path('/etc/router-web/system-slots.json')
MAX_IMAGE = 1024 * 1024 * 1024
# Software boot-attempt counter, independent of CONFIG_BOOTCOUNT_LIMIT.
BOOT_COMMAND = ('if test "${router_trial}" = "1"; then '
    'if test "${router_tries}" = "0"; then setenv router_slot ${router_previous}; '
    'setenv router_trial 0; else setexpr router_tries ${router_tries} - 1; fi; saveenv; fi; '
    'sysboot mmc ${router_bootdev} any ${scriptaddr} /router-slots/${router_slot}/extlinux.conf; reset')


def run(*args, timeout=120):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=timeout).strip()


def profile():
    if not PROFILE.exists():
        raise ValueError('OS updates need a provisioned and boot-tested A/B slot profile')
    data = json.loads(PROFILE.read_text())
    if data.get('boot_tested') is not True or data.get('watchdog_tested') is not True or set(data.get('slots', {})) != {'A', 'B'}:
        raise ValueError('A/B boot profile has not been verified')
    for identifier in [data.get('boot_partuuid', '')] + [slot.get('partuuid', '') for slot in data['slots'].values()]:
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', identifier):
            raise ValueError('Configure GPT partition UUIDs for boot and both root slots')
    if len({data['boot_partuuid'].lower(), *(slot['partuuid'].lower() for slot in data['slots'].values())}) != 3:
        raise ValueError('A/B root slots must be different partitions')
    if not re.fullmatch(r'[0-9]+:[0-9]+', data.get('uboot_bootdev', '')):
        raise ValueError('Invalid U-Boot boot device/partition')
    if run('fw_printenv', '-n', 'bootcmd', timeout=5) != BOOT_COMMAND or run('fw_printenv', '-n', 'router_ab_ready', timeout=5) != '1':
        raise ValueError('U-Boot A/B fallback is not provisioned')
    if run('fw_printenv', '-n', 'router_bootdev', timeout=5) != data['uboot_bootdev']:
        raise ValueError('U-Boot boot device does not match the local profile')
    return data


def readiness():
    try:
        data = profile()
        return dict(ready=True, slots={name: slot['partuuid'] for name, slot in data['slots'].items()})
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return dict(ready=False, reason=str(error) if isinstance(error, ValueError) else 'A/B boot tools are unavailable')


def is_system(payload):
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            info = archive.getinfo('manifest.json')
            if info.file_size > 4 * 1024 * 1024:
                raise ValueError('System manifest is too large')
            return json.loads(archive.read(info)).get('scope') == 'router-system'
    except zipfile.BadZipFile:
        return False


def device(partuuid):
    matches = run('blkid', '-t', 'PARTUUID=' + partuuid, '-o', 'device').splitlines()
    if len(matches) != 1:
        raise ValueError('Partition UUID does not identify exactly one device')
    target = Path(matches[0]).resolve(strict=True)
    if not stat.S_ISBLK(target.stat().st_mode):
        raise ValueError('Slot must be a block partition')
    # Reject whole disks, including an accidental whole-device UUID match.
    if not (Path('/sys/class/block') / target.name / 'partition').is_file():
        raise ValueError('Slot is not a partition')
    return target


def mounted(device_path):
    dev = device_path.stat().st_rdev
    identifier = f'{os.major(dev)}:{os.minor(dev)}'
    return [line.split()[4].replace('\\040', ' ') for line in Path('/proc/self/mountinfo').read_text().splitlines()
            if line.split()[2] == identifier]


def active_slot(data):
    root_device = os.stat('/').st_dev
    matches = [name for name, slot in data['slots'].items() if device(slot['partuuid']).stat().st_rdev == root_device]
    if len(matches) != 1:
        raise ValueError('Running root is not exactly one configured A/B slot')
    return matches[0]


def staging_directory(data):
    staging = Path(data['staging_directory'])
    if not staging.is_absolute() or not staging.is_dir():
        raise ValueError('Provision a shared staging filesystem for system images')
    roots = {device(slot['partuuid']).stat().st_rdev for slot in data['slots'].values()}
    if staging.stat().st_dev in roots:
        raise ValueError('Staging storage must be separate from both root slots')
    maximum = data.get('max_rootfs_bytes', MAX_IMAGE)
    if type(maximum) is not int or not 64 * 1024 * 1024 <= maximum <= MAX_IMAGE:
        raise ValueError('Configure a supported maximum root image size')
    # The existing immutable cache is already excluded from free space. The
    # reconstructed images move into the candidate cache on the same filesystem.
    required = maximum + 256 * 1024 * 1024
    if shutil.disk_usage(staging).free < required:
        raise ValueError('Insufficient staging space for the configured root image limit')
    return staging


def boot_mount(data):
    target = device(data['boot_partuuid'])
    paths = mounted(target)
    if len(paths) > 1:
        raise ValueError('Boot filesystem has multiple mount points')
    if paths:
        return Path(paths[0]), False
    directory = Path('/mnt/router-update-boot')
    directory.mkdir(exist_ok=True, parents=True)
    run('mount', str(target), str(directory))
    return directory, True


def prepare_storage():
    """Resolve GPT identities each boot; MMC Linux numbering is not stable."""
    if not PROFILE.exists():
        return
    data = json.loads(PROFILE.read_text())
    identifier = data.get('environment_partuuid')
    if identifier:
        target = device(identifier)
        link = Path('/dev/disk/by-partuuid') / identifier
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink(missing_ok=True)
        link.symlink_to(target)
    identifier = data.get('staging_partuuid')
    if identifier:
        target = device(identifier)
        directory = Path(data['staging_directory'])
        directory.mkdir(parents=True, exist_ok=True)
        paths = mounted(target)
        if paths and str(directory) not in paths:
            raise ValueError('Staging partition is mounted somewhere else')
        if not paths:
            run('mount', '-o', 'noatime', str(target), str(directory))


def file_hash(path, length=None):
    digest = hashlib.sha256()
    with path.open('rb', buffering=0) as source:
        while length is None or length > 0:
            raw = source.read(1024 * 1024 if length is None else min(length, 1024 * 1024))
            if not raw:
                if length:
                    raise ValueError('Short image read')
                break
            digest.update(raw)
            if length is not None:
                length -= len(raw)
    return digest.hexdigest()


def reconstruct(payload, cache, work):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        if len(infos) > 8 or len({i.filename for i in infos}) != len(infos) or sum(i.file_size for i in infos) > MAX_IMAGE + 128 * 1024 * 1024:
            raise ValueError('Invalid system bundle size')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 1 or manifest.get('scope') != 'router-system' or manifest.get('board') != 'STM32MP257F-DK':
            raise ValueError('Wrong system update target')
        if type(manifest.get('generation')) is not int or not 1 <= manifest['generation'] <= 2147483647:
            raise ValueError('Invalid system generation')
        if set(manifest.get('images', {})) != {'rootfs', 'kernel', 'dtb'}:
            raise ValueError('System update requires rootfs, matching kernel and DTB')
        for name, entry in manifest['images'].items():
            size = entry['size']
            if type(size) is not int or not 0 < size <= (MAX_IMAGE if name == 'rootfs' else 64 * 1024 * 1024):
                raise ValueError('Invalid image size')
            target = work / name
            if 'operations' in entry:
                base = cache / (name + '.img')
                if not base.is_file() or file_hash(base) != entry['base_sha256']:
                    raise ValueError('Exact immutable delta base is unavailable; send a full system bundle')
                literals = archive.read(entry['payload'])
                with base.open('rb') as source, target.open('wb') as output:
                    total = 0
                    base_size = base.stat().st_size
                    for kind, start, length in entry['operations']:
                        if type(start) is not int or type(length) is not int or min(start, length) < 0 or total + length > size:
                            raise ValueError('Invalid image delta range')
                        if kind == 'copy' and start + length <= base_size:
                            source.seek(start)
                            remaining = length
                            while remaining:
                                raw = source.read(min(remaining, 1024 * 1024))
                                if not raw:
                                    raise ValueError('Short delta base read')
                                output.write(raw)
                                remaining -= len(raw)
                        elif kind == 'data' and start + length <= len(literals):
                            output.write(literals[start:start+length])
                        else:
                            raise ValueError('Invalid image delta operation')
                        total += length
            else:
                with archive.open(entry['payload']) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
            if target.stat().st_size != size or file_hash(target) != entry['sha256']:
                raise ValueError('Reconstructed system image hash mismatch')
    return manifest


def environment(values, directory):
    request = directory / 'environment.txt'
    request.write_text(''.join(key + ' ' + str(value) + '\n' for key, value in values.items()))
    run('fw_setenv', '-s', str(request))
    for key, value in values.items():
        if run('fw_printenv', '-n', key) != str(value):
            raise ValueError('Boot environment readback failed')


def install(payload, job, phase):
    import firmware_update as updates
    data = profile()
    active = active_slot(data)
    inactive = 'B' if active == 'A' else 'A'
    if run('fw_printenv', '-n', 'router_slot') != active or run('fw_printenv', '-n', 'router_trial') != '0':
        raise ValueError('Confirm the current boot before installing another OS update')
    target = device(data['slots'][inactive]['partuuid'])
    if mounted(target):
        raise ValueError('Inactive root slot is mounted; refusing to overwrite it')
    staging = staging_directory(data)
    boot, unmount_boot = boot_mount(data)
    root_mount = None
    try:
        state_path = boot / 'router-slots/state.json'
        state = updates.load(state_path, dict(generation=0))
        cache = staging / 'router-image-cache'
        cache.mkdir(exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix='router-system-', dir=staging) as directory:
            work = Path(directory)
            manifest = reconstruct(payload, cache, work)
            if manifest['images']['rootfs']['size'] > data.get('max_rootfs_bytes', MAX_IMAGE):
                raise ValueError('Root image exceeds the provisioned image size limit')
            if manifest['generation'] <= state['generation']:
                raise ValueError('System update generation is not newer than the committed release')
            with (work / 'rootfs').open('rb') as image:
                image.seek(1080)
                magic = image.read(2)
            if magic != b'\x53\xef':
                raise ValueError('Root image is not ext4')
            with (work / 'kernel').open('rb') as kernel:
                if kernel.read(2) != b'\x1f\x8b':
                    raise ValueError('Expected a gzip ARM64 kernel image')
            dtb = (work / 'dtb').read_bytes()
            if dtb[:4] != b'\xd0\x0d\xfe\xed' or b'st,stm32mp257f-dk\0' not in dtb:
                raise ValueError('DTB does not identify the STM32MP257F-DK')
            run('e2fsck', '-f', '-n', str(work / 'rootfs'), timeout=300)
            import fcntl
            with target.open('rb', buffering=0) as handle:
                capacity = struct.unpack('Q', fcntl.ioctl(handle, 0x80081272, bytes(8)))[0]
            if (work / 'rootfs').stat().st_size > capacity:
                raise ValueError('Root image is larger than the inactive partition')
            if shutil.disk_usage(boot).free < (work / 'kernel').stat().st_size + (work / 'dtb').stat().st_size + 1024 * 1024:
                raise ValueError('Insufficient space for the inactive boot files')
            phase('installing', version=manifest.get('version', ''), slot=inactive)
            with (work / 'rootfs').open('rb') as source, target.open('r+b', buffering=0) as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
                os.fsync(output.fileno())
            if file_hash(target, (work / 'rootfs').stat().st_size) != manifest['images']['rootfs']['sha256']:
                raise ValueError('Inactive root slot readback failed')
            run('tune2fs', '-U', 'random', str(target))
            # Never mount below TemporaryDirectory: exception cleanup must not
            # recursively delete the mounted inactive filesystem.
            root_mount = Path('/mnt/router-update-root')
            root_mount.mkdir(exist_ok=True, parents=True)
            if os.path.ismount(root_mount):
                root_mount = None
                raise ValueError('Update root mount point is already in use')
            run('mount', str(target), str(root_mount))
            if not (root_mount / 'etc/openwrt_release').is_file() or not (root_mount / 'sbin/init').exists() or not (root_mount / 'etc/init.d/router-update-confirm').is_file():
                raise ValueError('Target OS lacks OpenWrt/init/update confirmation support')
            # Preserve network, credentials and identity; never copy the old kernel/modules.
            for relative in ('etc/config', 'etc/router-web', 'etc/dropbear', 'etc/passwd', 'etc/shadow', 'etc/group', 'etc/machine-id', 'etc/fw_env.config'):
                source, destination = Path('/') / relative, root_mount / relative
                if destination.is_symlink() or not destination.parent.resolve().is_relative_to(root_mount.resolve()):
                    raise ValueError('Target config path escapes the inactive root')
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True,
                                    ignore=shutil.ignore_patterns('update-state', 'mqtt-state'))
                elif source.is_file():
                    shutil.copy2(source, destination)
            link = root_mount / 'etc/rc.d/S99router-update-confirm'
            link.unlink(missing_ok=True)
            link.symlink_to('../init.d/router-update-confirm')
            if data.get('staging_partuuid'):
                if not (root_mount / 'etc/init.d/router-storage').is_file():
                    raise ValueError('Target OS lacks stable storage startup support')
                link = root_mount / 'etc/rc.d/S12router-storage'
                link.unlink(missing_ok=True)
                link.symlink_to('../init.d/router-storage')
            if Path('/etc/rc.d/S94router-traffic').exists():
                if not (root_mount / 'etc/init.d/router-traffic').is_file():
                    raise ValueError('Target OS lacks persistent traffic accounting')
                link = root_mount / 'etc/rc.d/S94router-traffic'
                link.unlink(missing_ok=True)
                link.symlink_to('../init.d/router-traffic')
            os.sync()
            run('umount', str(root_mount))
            root_mount = None
            slot_dir = boot / 'router-slots' / inactive
            slot_dir.mkdir(parents=True, exist_ok=True)
            for name, filename in [('kernel', 'Image.gz'), ('dtb', 'board.dtb')]:
                temporary = slot_dir / (filename + '.new')
                shutil.copyfile(work / name, temporary)
                temporary.replace(slot_dir / filename)
                if file_hash(slot_dir / filename) != manifest['images'][name]['sha256']:
                    raise ValueError('Inactive boot file readback failed')
            config = ('DEFAULT router\nTIMEOUT 10\nLABEL router\n  KERNEL /router-slots/' + inactive + '/Image.gz\n'
                      '  FDT /router-slots/' + inactive + '/board.dtb\n  APPEND root=PARTUUID=' + data['slots'][inactive]['partuuid'] +
                      ' rootwait rw console=ttySTM0,115200n8 fw_devlink=on fw_devlink.sync_state=timeout\n')
            (slot_dir / 'extlinux.conf').write_text(config)
            # Keep immutable bases separate from the mounted (mutable) root filesystem.
            candidate_cache = staging / ('router-image-candidate-' + job['id'])
            candidate_cache.mkdir(mode=0o700)
            for name in ('rootfs', 'kernel', 'dtb'):
                shutil.move(work / name, candidate_cache / (name + '.img'))
            updates.atomic(boot / 'router-slots/pending.json', dict(slot=inactive, previous=active,
                generation=manifest['generation'], version=manifest.get('version', ''),
                id=job['id'], topic=job.get('topic'), cache=str(candidate_cache),
                image_hashes={name: entry['sha256'] for name, entry in manifest['images'].items()}))
            os.sync()
            environment(dict(router_previous=active, router_slot=inactive, router_tries=3, router_trial=1), work)
            phase('rebooting', version=manifest.get('version', ''), slot=inactive)
            os.sync()
            subprocess.Popen(['/sbin/reboot'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return dict(result='accepted', state='rebooting', generation=manifest['generation'])
    finally:
        if root_mount is not None:
            run('umount', str(root_mount))
        if unmount_boot:
            run('umount', str(boot))


def confirm_boot():
    import firmware_update as updates
    data = profile()
    current = active_slot(data)
    boot, unmount_boot = boot_mount(data)
    try:
        pending_path = boot / 'router-slots/pending.json'
        pending = updates.load(pending_path, None)
        if not pending:
            return
        if current != pending['slot']:
            result = dict(result='fail', error='Boot attempts exhausted; previous system selected', rolled_back=True)
        else:
            deadline = time.monotonic() + 180
            interfaces = data.get('health_interfaces', ['lan', 'wan'])
            healthy = False
            while time.monotonic() < deadline:
                try:
                    healthy = updates.healthy(['router-web']) and all(json.loads(run('ubus', 'call', 'network.interface.' + name, 'status')).get('up') for name in interfaces)
                except (OSError, ValueError, subprocess.SubprocessError):
                    healthy = False
                if healthy:
                    break
                time.sleep(5)
            if not healthy:
                run('/sbin/reboot')
                raise ValueError('Boot health check failed; rebooting unconfirmed trial')
            candidate = Path(pending['cache'])
            expected = Path(data['staging_directory']) / ('router-image-candidate-' + pending['id'])
            if candidate != expected:
                raise ValueError('Invalid pending image cache path')
            cache = Path(data['staging_directory']) / 'router-image-cache'
            cache.mkdir(exist_ok=True)
            for name in ('rootfs', 'kernel', 'dtb'):
                source = candidate / (name + '.img')
                if source.is_file():
                    source.replace(cache / (name + '.img'))
                if file_hash(cache / (name + '.img')) != pending['image_hashes'][name]:
                    raise ValueError('Committed delta base hash mismatch')
            if candidate.exists():
                candidate.rmdir()
            updates.atomic(boot / 'router-slots/state.json', dict(generation=pending['generation'], slot=current, version=pending['version']))
            with tempfile.TemporaryDirectory() as directory:
                environment(dict(router_trial=0, router_previous=current), Path(directory))
            result = dict(result='succeed', version=pending['version'], generation=pending['generation'])
        updates.atomic(updates.STATE / 'update-state/status.json', dict(state='succeeded' if result['result'] == 'succeed' else 'failed', **result))
        if pending.get('topic') in ('UPGRADE', 'EVENT/UPGRADE'):
            updates.atomic(updates.STATE / 'mqtt-state/outbox' / (pending['id'] + '.json'), dict(topic=pending['topic'], data=result))
        pending_path.unlink()
        os.sync()
    finally:
        if unmount_boot:
            run('umount', str(boot))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--confirm-boot', action='store_true')
    group.add_argument('--prepare-storage', action='store_true')
    args = parser.parse_args()
    prepare_storage() if args.prepare_storage else confirm_boot()
