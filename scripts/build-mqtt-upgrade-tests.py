#!/usr/bin/env python3
"""Build signed A/B application test variants without modifying production source."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import update_bundle as bundle


def build(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Use an empty output directory to preserve previous releases')
    (out / 'ipk').mkdir()
    (out / 'full').mkdir()
    public = out / 'signing-public.pem'
    subprocess.run([args.openssl, 'pkey', '-in', str(args.private_key), '-pubout', '-out', str(public)], check=True)
    control, previous_files = bundle.read_ipk(args.base)
    prefix = 'usr/lib/router-web/version_info.py'
    original = previous_files[prefix][0].decode()
    created = datetime.now(timezone(timedelta(hours=11))).isoformat(timespec='seconds')
    previous_ipk = args.base
    entries = []
    for offset, variant in enumerate(('A', 'B', 'A', 'B')):
        release = args.start_release + offset
        version = '1.0.0-r' + str(release)
        identity = re.sub(r"^VERSION = .*?$", 'VERSION = ' + repr(version), original, flags=re.M)
        identity = re.sub(r"^CREATED_AT = .*?$", 'CREATED_AT = ' + repr(created), identity, flags=re.M)
        identity = re.sub(r'^VERSION_STRING = .*?$',
                          "VERSION_STRING = 'STM32 Router ' + VERSION + ' | MQTT upgrade test " + variant + " | created ' + CREATED_AT",
                          identity, flags=re.M)
        metadata = {}
        exec(compile(identity, 'version_info.py', 'exec'), metadata)
        assert metadata['VERSION'] == version
        assert 'MQTT upgrade test ' + variant in metadata['info']()['string']
        assert metadata['at_response']().endswith(b'\r\nOK\r\n')
        files = dict(previous_files)
        files[prefix] = (identity.encode(), previous_files[prefix][1])
        target_control = re.sub(r'^Version: .+$', 'Version: ' + version, control, flags=re.M)
        stem = 'router-test-' + variant + '-r' + str(release)
        ipk = out / 'ipk' / (stem + '.ipk')
        bundle.write_ipk(ipk, target_control, files)
        delta = out / (stem + '.rupdate')
        result = bundle.create(ipk, delta, args.private_key, previous_ipk, args.openssl)
        payload = bundle.verify(delta, public, args.openssl)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root'
            for name, (raw, mode) in previous_files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            rebuilt = Path(directory) / 'rebuilt.ipk'
            bundle.reconstruct(payload, root, rebuilt)
            assert bundle.read_ipk(rebuilt) == (target_control, files)
        if offset < 2:
            full = out / 'full' / (stem + '-full.rupdate')
            bundle.create(ipk, full, args.private_key, openssl=args.openssl)
            bundle.verify(full, public, args.openssl)
        entries.append(dict(step=offset + 1, variant=variant, version=version,
                            base_version=re.search(r'^Version: (.+)$', control, re.M)[1],
                            file=delta.name, bytes=result['bytes'], reused_files=result['reused'],
                            total_files=result['files'], sha256=hashlib.sha256(delta.read_bytes()).hexdigest()))
        control, previous_files, previous_ipk = target_control, files, ipk
    manifest = dict(board='STM32MP257F-DK', scope='router-application',
                    initial_base=str(args.base.name), created_at=created, sequence=entries)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    commands = [dict(step=e['step'], topic='/RX/STM32-001/UPGRADE', retain=False,
                     payload=dict(patch='https://YOUR-UPDATE-HOST/' + e['file'])) for e in entries]
    (out / 'mqtt-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    rows = '\n'.join('| {step} | {variant} | {base_version} | {version} | {bytes} | `{file}` |'.format(**e) for e in entries)
    readme = '''# MQTT application upgrade test kit

Two test variants, A and B, differ only in application identity. Production
services, webpage behavior, MQTT telemetry and configuration formats are retained.
The router webpage software version and AT$VERSION identify the test variant;
MQTT DEVINFO/BASE.softver reports its numbered release.

The updater accepts only newer versions. Follow the four steps in order to test
A -> B -> A -> B without disabling downgrade protection. Replaying r21 after
r22 is deliberately rejected. These are application updates; they restart
services and do not switch the OS A/B slot or reboot the router.

| Step | Variant | Required base | Target | Bytes | Signed delta |
| --- | --- | --- | --- | --- | --- |
ROWS

1. Host the four top-level `.rupdate` files on an HTTPS server with a valid
   certificate, port 443. The kit does not create or publish a download server.
2. In router System -> Remote updates, enable updates, paste the contents of
   `signing-public.pem`, and allow the download hostname (plus redirect hosts).
   Never upload the private signing key. The router was not reconfigured by this build.
3. Replace YOUR-UPDATE-HOST in `mqtt-commands.json` with that hostname.
   Publish the step's JSON payload to `/RX/STM32-001/UPGRADE` with retain OFF,
   using your authorized MQTT publishing account after the router has logged in.
4. Watch `/TX/STM32-001/UPGRADE` for `result: accepted` and then `result: succeed`.
   Check System -> Remote updates status and DEVINFO/BASE.softver before the next
   step. Broker acknowledgement alone does not prove installation succeeded.

The initial delta requires the exact installed r20 application files. A read-only
kit check confirmed all 43 files matched when this kit was prepared. Local edits
can invalidate a delta base. `full/` contains larger full A/r21 and B/r22 bundles
for base recovery, but full bundles still cannot downgrade an installed version.
The IPKs are build inputs for future deltas, not MQTT download payloads.

For additional cycles, run scripts/build-mqtt-upgrade-tests.py with the final
IPK as --base, --start-release 25 (or another newer unused release), an empty
--output directory, and the same local --private-key. Keep the key private.
All deltas were signature-verified and reconstructed against their preceding
application files; reconstructed metadata, modes and bytes matched the targets.
Actual MQTT installations are left for your test; no release was installed.
'''.replace('ROWS', rows)
    (out / 'README.md').write_text(readme, encoding='utf-8')
    with zipfile.ZipFile(out / 'mqtt-upgrade-test-kit.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.iterdir()):
            if path.is_file() and path.suffix != '.zip':
                archive.write(path, path.name)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start-release', type=int, default=21)
    parser.add_argument('--openssl', default=shutil.which('openssl') or 'C:/Program Files/Git/usr/bin/openssl.exe')
    build(parser.parse_args())
