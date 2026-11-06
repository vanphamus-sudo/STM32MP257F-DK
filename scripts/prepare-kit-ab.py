#!/usr/bin/env python3
"""Split this kit's oversized p9 around its existing 512 MiB filesystem.

Default is read-only. --apply writes GPT metadata only, preserving all original
partition starts/UUIDs and p1-p8 entries. Reboot before using the new partitions.
This is pinned to the recorded STM32 eMMC layout, not a generic partitioner.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import uuid
import zlib

DISK = Path('/dev/mmcblk0')
ROOT_UUID = '1376b394-4b0e-4cb4-a1e4-3b87b697588e'
SLOT_BYTES = 768 * 1024 * 1024


def checksum(header):
    struct.pack_into('<I', header, 16, 0)
    length = struct.unpack_from('<I', header, 12)[0]
    struct.pack_into('<I', header, 16, zlib.crc32(header[:length]))


def prepare(apply=False):
    assert 'root=PARTUUID=' + ROOT_UUID in Path('/proc/cmdline').read_text()
    assert os.stat('/').st_dev == os.makedev(179, 9)
    with (DISK.parent / 'mmcblk0p9').open('rb', buffering=0) as root:
        root.seek(1024)
        sb = root.read(1024)
    assert sb[56:58] == b'\x53\xef'
    fs_size = struct.unpack_from('<I', sb, 4)[0] * (1024 << struct.unpack_from('<I', sb, 24)[0])
    assert fs_size == 512 * 1024 * 1024 and fs_size < SLOT_BYTES
    with DISK.open('rb', buffering=0) as source:
        source.seek(512)
        primary = bytearray(source.read(512))
        assert primary[:8] == b'EFI PART'
        saved_crc = struct.unpack_from('<I', primary, 16)[0]
        copy = bytearray(primary)
        checksum(copy)
        assert struct.unpack_from('<I', copy, 16)[0] == saved_crc
        table_lba, count, size, crc = struct.unpack_from('<QIII', primary, 72)
        source.seek(table_lba * 512)
        table = bytearray(source.read(count * size))
        assert zlib.crc32(table) == crc
        backup_lba = struct.unpack_from('<Q', primary, 32)[0]
        source.seek(backup_lba * 512)
        secondary = bytearray(source.read(512))
        assert secondary[:8] == b'EFI PART'
    assert count >= 11 and size == 128
    original = bytes(table)
    entry = table[8*size:9*size]
    assert str(uuid.UUID(bytes_le=bytes(entry[16:32]))) == ROOT_UUID
    start, old_end = struct.unpack_from('<QQ', entry, 32)
    assert (start, old_end) == (6955008, 15268863)
    assert table[9*size:11*size] == bytes(2*size)
    slot_sectors = SLOT_BYTES // 512
    specifications = [('router-root-a', start, start+slot_sectors-1, ROOT_UUID),
                      ('router-root-b', start+slot_sectors, start+2*slot_sectors-1, str(uuid.uuid4())),
                      ('router-update', start+2*slot_sectors, old_end, str(uuid.uuid4()))]
    for index, (name, first, last, identifier) in enumerate(specifications, 8):
        new = bytearray(size)
        new[:16] = entry[:16]
        new[16:32] = uuid.UUID(identifier).bytes_le
        struct.pack_into('<QQ', new, 32, first, last)
        new[56:56+len(name.encode('utf-16le'))] = name.encode('utf-16le')
        table[index*size:(index+1)*size] = new
    assert table[:8*size] == original[:8*size]
    assert table[11*size:] == original[11*size:]
    for header in (primary, secondary):
        struct.pack_into('<I', header, 88, zlib.crc32(table))
        checksum(header)
    plan = dict(device=str(DISK), rootfs_bytes=fs_size, unchanged='p1-p8 and p9 start/UUID',
                partitions=[dict(number=i+9, name=n, start=s, end=e, bytes=(e-s+1)*512, uuid=u)
                            for i, (n,s,e,u) in enumerate(specifications)])
    if apply:
        backup = Path('/root/router-ab-gpt-backup')
        backup.mkdir(mode=0o700, exist_ok=False)
        (backup / 'table-before.bin').write_bytes(original)
        (backup / 'plan.json').write_text(json.dumps(plan, indent=2))
        os.sync()
        # Backup GPT first. An interrupted primary write retains a valid backup.
        with DISK.open('r+b', buffering=0) as target:
            target.seek(struct.unpack_from('<Q', secondary, 72)[0]*512)
            target.write(table)
            target.seek(backup_lba*512)
            target.write(secondary)
            os.fsync(target.fileno())
            target.seek(table_lba*512)
            target.write(table)
            target.seek(512)
            target.write(primary)
            os.fsync(target.fileno())
            for header, lba in ((primary, 1), (secondary, backup_lba)):
                target.seek(lba*512)
                assert target.read(512) == header
                target.seek(struct.unpack_from('<Q', header, 72)[0]*512)
                assert target.read(len(table)) == table
        plan['result'] = 'GPT written and read back; reboot required before formatting p10/p11'
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    print(json.dumps(prepare(parser.parse_args().apply), indent=2))
