#!/usr/bin/env python3
"""Provision pre-existing A/B partitions; never creates or resizes partitions.

Run on the board from a verified recovery setup. Default mode only validates.
--apply changes U-Boot bootcmd; --mark-boot-tested is a separate post-boot step.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, '/usr/lib/router-web')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import firmware_update as updates
import system_update as system


def main(args):
    data = json.loads(args.profile.read_text())
    if set(data['slots']) != {'A', 'B'} or len({data['boot_partuuid'], data['slots']['A']['partuuid'], data['slots']['B']['partuuid']}) != 3:
        raise ValueError('Use three distinct boot/root partition UUIDs')
    active = system.active_slot(data)
    inactive = 'B' if active == 'A' else 'A'
    if system.mounted(system.device(data['slots'][inactive]['partuuid'])):
        raise ValueError('Inactive root slot must be unmounted')
    staging = system.staging_directory(data)
    import re
    if not re.fullmatch(r'[0-9]+:[0-9]+', data['uboot_bootdev']):
        raise ValueError('Provide the U-Boot MMC device:partition for the shared bootfs')
    # Readable U-Boot environment is mandatory; never guess fw_env.config offsets.
    environment = system.run('fw_printenv')
    boot, unmount = system.boot_mount(data)
    try:
        if args.mark_boot_tested:
            if system.run('fw_printenv', '-n', 'bootcmd') != system.BOOT_COMMAND or system.run('fw_printenv', '-n', 'router_slot') != active:
                raise ValueError('The expected A/B boot hook is not active')
            data['boot_tested'] = True
            updates.atomic(system.PROFILE, data)
            system.profile()
            print('A/B profile marked boot-tested. Remote OS updates can now be enabled.')
            return
        if not args.apply:
            print(json.dumps(dict(active_slot=active, inactive_slot=inactive, boot_mount=str(boot), action='validation only; no boot files/environment changed')))
            return
        if not args.kernel or not args.dtb:
            raise ValueError('--apply requires the currently working --kernel and --dtb files')
        backup = boot / 'router-slots/original-u-boot-environment.txt'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise ValueError('Boot provisioning backup already exists; review it before provisioning again')
        backup.write_text(environment)
        os.chmod(backup, 0o600)
        slot = boot / 'router-slots' / active
        slot.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.kernel, slot / 'Image.gz')
        shutil.copyfile(args.dtb, slot / 'board.dtb')
        config = ('DEFAULT router\nTIMEOUT 30\nLABEL router\n  KERNEL /router-slots/' + active + '/Image.gz\n'
                  '  FDT /router-slots/' + active + '/board.dtb\n  APPEND root=PARTUUID=' + data['slots'][active]['partuuid'] +
                  ' rootwait rw console=ttySTM0,115200n8 fw_devlink=on fw_devlink.sync_state=timeout\n')
        (slot / 'extlinux.conf').write_text(config)
        data['boot_tested'] = False
        updates.atomic(system.PROFILE, data)
        updates.atomic(boot / 'router-slots/state.json', dict(generation=0, slot=active))
        os.sync()
        with tempfile.TemporaryDirectory() as directory:
            system.environment(dict(router_slot=active, router_previous=active, router_trial=0,
                router_tries=0, router_bootdev=data['uboot_bootdev'], router_ab_ready=1,
                bootcmd=system.BOOT_COMMAND), Path(directory))
        print('Boot hook installed. Cold-boot and test recovery from serial, then run --mark-boot-tested. OS updates remain blocked until then.')
    finally:
        if unmount:
            system.run('umount', str(boot))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--kernel', type=Path)
    parser.add_argument('--dtb', type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true')
    group.add_argument('--mark-boot-tested', action='store_true')
    main(parser.parse_args())
