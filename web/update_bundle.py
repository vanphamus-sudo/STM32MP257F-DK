"""Signed application update format: per-file reuse or compressed replacement.

The manifest is signed together with all compressed file contents. Nothing is
extracted from an archive onto the filesystem. OS/block-device images are not
accepted by this format.
"""
import gzip
import difflib
import hashlib
import io
import json
from pathlib import PurePosixPath
import struct
import subprocess
import tarfile
import tempfile
import zipfile
import zlib
from pathlib import Path

MAGIC = b'RTRUPD1\n'
MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_SYSTEM_DOWNLOAD = 256 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
PACKAGE = 'stm32-lte-router'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_delta(old, new):
    # Match whole lines for text, fixed blocks for binary data/very large files.
    lines = len(new) < 1024 * 1024 and b'\0' not in new and b'\0' not in old
    blocksize = 65536 if max(len(old), len(new)) > 8 * 1024 * 1024 else 1024
    a = old.splitlines(keepends=True) if lines else [old[i:i+blocksize] for i in range(0, len(old), blocksize)]
    b = new.splitlines(keepends=True) if lines else [new[i:i+blocksize] for i in range(0, len(new), blocksize)]
    if len(a) > 20000 or len(b) > 20000:
        return None
    offsets = [0]
    for block in a:
        offsets.append(offsets[-1] + len(block))
    operations, literals, cursor = [], bytearray(), 0
    for match in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        if match.b > cursor:
            raw = b''.join(b[cursor:match.b])
            operations.append(['data', len(literals), len(raw)])
            literals.extend(raw)
        if match.size:
            operations.append(['copy', offsets[match.a], offsets[match.a + match.size] - offsets[match.a]])
        cursor = match.b + match.size
    return operations, bytes(literals)


def allowed(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and '..' not in path.parts and str(path) == name
            and (name.startswith('usr/lib/router-web/') or name in (
                'etc/init.d/router-web', 'etc/init.d/router-mqtt', 'etc/init.d/router-at',
                'etc/init.d/router-serial', 'etc/hotplug.d/openvpn/30-router',
                'etc/init.d/router-update-confirm',
                'etc/init.d/router-storage', 'lib/preinit/09_router_storage',
                'etc/init.d/router-traffic', 'etc/init.d/router-modbus',
                'lib/upgrade/keep.d/stm32-lte-router')))


def untar(raw):
    result = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for member in archive:
            if member.isdir():
                continue
            name = member.name.removeprefix('./')
            if not member.isfile() or name in result or member.size > MAX_EXPANDED:
                raise ValueError('Invalid package member')
            total += member.size
            if total > MAX_EXPANDED:
                raise ValueError('Package is too large')
            result[name] = (archive.extractfile(member).read(), member.mode & 0o777)
    return result


def read_ipk(path):
    outer = untar(Path(path).read_bytes())
    control = untar(outer['control.tar.gz'][0])
    # Maintainer scripts are not permitted in these remotely supplied packages.
    if set(control) != {'control'}:
        raise ValueError('Only script-free application packages are supported')
    metadata = control['control'][0].decode()
    if 'Package: ' + PACKAGE + '\n' not in metadata:
        raise ValueError('Wrong application package')
    data = untar(outer['data.tar.gz'][0])
    if not data or any(not allowed(name) for name in data):
        raise ValueError('Package contains paths outside the router application')
    return metadata, data


def tar_bytes(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, (raw, mode) in sorted(files.items()):
            member = tarfile.TarInfo('./' + name)
            member.size, member.mode = len(raw), mode
            archive.addfile(member, io.BytesIO(raw))
    return gzip.compress(stream.getvalue(), compresslevel=9, mtime=0)


def write_ipk(path, control, files):
    Path(path).write_bytes(tar_bytes({'debian-binary': (b'2.0\n', 0o644),
        'control.tar.gz': (tar_bytes({'control': (control.encode(), 0o644)}), 0o644),
        'data.tar.gz': (tar_bytes(files), 0o644)}))


def create(target, output, private_key, base=None, openssl='openssl'):
    control, files = read_ipk(target)
    base_files = read_ipk(base)[1] if base else {}
    manifest = dict(format=1, scope='router-application', board='STM32MP257F-DK',
                    control=control, files={})
    full = io.BytesIO()
    with zipfile.ZipFile(full, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for index, (name, (raw, mode)) in enumerate(sorted(files.items())):
            entry = dict(sha256=digest(raw), size=len(raw), mode=mode)
            if name in base_files and base_files[name][0] == raw:
                entry['reuse'] = True
            else:
                entry['payload'] = 'files/' + str(index)
                delta = file_delta(base_files[name][0], raw) if name in base_files else None
                if delta and len(zlib.compress(delta[1], 9)) + len(json.dumps(delta[0])) + 100 < len(zlib.compress(raw, 9)):
                    entry.update(base_sha256=digest(base_files[name][0]), operations=delta[0])
                    archive.writestr(entry['payload'], delta[1])
                else:
                    archive.writestr(entry['payload'], raw)
            manifest['files'][name] = entry
        archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True, separators=(',', ':')))
    payload = full.getvalue()
    with tempfile.TemporaryDirectory() as directory:
        source, signature = Path(directory) / 'payload', Path(directory) / 'signature'
        source.write_bytes(payload)
        subprocess.run([openssl, 'dgst', '-sha256', '-sign', str(private_key), '-out', str(signature), str(source)], check=True)
        signed = signature.read_bytes()
    Path(output).write_bytes(MAGIC + struct.pack('>I', len(signed)) + signed + payload)
    return dict(bytes=Path(output).stat().st_size, reused=sum('reuse' in entry for entry in manifest['files'].values()), files=len(files))


def verify(path, public_key, openssl='openssl'):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_SYSTEM_DOWNLOAD or raw[:8] != MAGIC or len(raw) < 12:
        raise ValueError('Not a supported signed router update')
    length = struct.unpack('>I', raw[8:12])[0]
    if not 64 <= length <= 8192 or len(raw) <= 12 + length:
        raise ValueError('Invalid update signature')
    signed, payload = raw[12:12+length], raw[12+length:]
    with tempfile.TemporaryDirectory() as directory:
        source, signature = Path(directory) / 'payload', Path(directory) / 'signature'
        source.write_bytes(payload)
        signature.write_bytes(signed)
        result = subprocess.run([openssl, 'dgst', '-sha256', '-verify', str(public_key),
                                 '-signature', str(signature), str(source)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        if result.returncode:
            raise ValueError('Update signature verification failed')
    return payload


def reconstruct(payload, root, output):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        if len(infos) > 256 or sum(info.file_size for info in infos) > MAX_EXPANDED:
            raise ValueError('Expanded update is too large')
        if len({info.filename for info in infos}) != len(infos):
            raise ValueError('Duplicate update entries')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 1 or manifest.get('scope') != 'router-application' or manifest.get('board') != 'STM32MP257F-DK':
            raise ValueError('Wrong update format or target')
        control = manifest['control']
        if not isinstance(control, str) or 'Package: ' + PACKAGE + '\n' not in control:
            raise ValueError('Wrong application metadata')
        files = {}
        for name, entry in manifest['files'].items():
            if not allowed(name) or type(entry['size']) is not int or not 0 <= entry['size'] <= MAX_EXPANDED:
                raise ValueError('Invalid application file')
            if entry.get('reuse') or 'operations' in entry:
                source = Path(root) / name
                if source.is_symlink() or not source.is_file():
                    raise ValueError('Delta base file missing: ' + name)
                raw = source.read_bytes()
                if 'operations' in entry:
                    if digest(raw) != entry['base_sha256']:
                        raise ValueError('Delta base hash mismatch: ' + name)
                    literals = archive.read(entry['payload'])
                    rebuilt = bytearray()
                    for operation in entry['operations']:
                        kind, start, length = operation
                        source_bytes = raw if kind == 'copy' else literals if kind == 'data' else None
                        if source_bytes is None or type(start) is not int or type(length) is not int or start < 0 or length < 0 or start + length > len(source_bytes) or len(rebuilt) + length > entry['size']:
                            raise ValueError('Invalid delta operation')
                        rebuilt.extend(source_bytes[start:start+length])
                    raw = bytes(rebuilt)
            else:
                raw = archive.read(entry['payload'])
            if len(raw) != entry['size'] or digest(raw) != entry['sha256']:
                raise ValueError('Delta base or target hash mismatch: ' + name)
            if entry['mode'] not in (0o644, 0o755):
                raise ValueError('Unsupported application file mode')
            files[name] = (raw, entry['mode'])
        if 'usr/lib/router-web/server.py' not in files:
            raise ValueError('Update does not contain the router application')
    write_ipk(output, control, files)
    return control, files
