#!/usr/bin/env python3
"""Sign a matching ext4 rootfs + kernel + DTB, optionally as block deltas."""
import argparse
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import update_bundle as bundle


def create(args):
    manifest = dict(format=1, scope='router-system', board='STM32MP257F-DK',
                    generation=args.generation, version=args.version, images={})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in ('rootfs', 'kernel', 'dtb'):
            raw = getattr(args, name).read_bytes()
            entry = dict(size=len(raw), sha256=bundle.digest(raw), payload=name)
            source = args.base / (name + '.img') if args.base else None
            delta = None
            if source and source.is_file():
                old = source.read_bytes()
                delta = bundle.file_delta(old, raw)
            if delta and len(zlib.compress(delta[1], 9)) + len(json.dumps(delta[0])) + 100 < len(zlib.compress(raw, 9)):
                entry.update(base_sha256=bundle.digest(old), operations=delta[0])
                archive.writestr(name, delta[1])
            else:
                archive.writestr(name, raw)
            manifest['images'][name] = entry
        archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True, separators=(',', ':')))
    payload = stream.getvalue()
    if len(payload) + 8192 > bundle.MAX_SYSTEM_DOWNLOAD:
        raise ValueError('Compressed system update exceeds the 256 MiB download limit')
    with tempfile.TemporaryDirectory() as directory:
        source, signature = Path(directory) / 'payload', Path(directory) / 'signature'
        source.write_bytes(payload)
        subprocess.run([args.openssl, 'dgst', '-sha256', '-sign', str(args.private_key), '-out', str(signature), str(source)], check=True)
        signed = signature.read_bytes()
    args.output.write_bytes(bundle.MAGIC + struct.pack('>I', len(signed)) + signed + payload)
    if args.export_base:
        args.export_base.mkdir(parents=True, exist_ok=True)
        for name in ('rootfs', 'kernel', 'dtb'):
            import shutil
            shutil.copyfile(getattr(args, name), args.export_base / (name + '.img'))
    print(json.dumps(dict(bytes=args.output.stat().st_size, delta_images=[name for name, entry in manifest['images'].items() if 'operations' in entry])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('rootfs', 'kernel', 'dtb', 'private-key', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--generation', type=int, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--base', type=Path, help='Previous immutable image directory (rootfs.img/kernel.img/dtb.img)')
    parser.add_argument('--export-base', type=Path)
    parser.add_argument('--openssl', default='openssl')
    create(parser.parse_args())
