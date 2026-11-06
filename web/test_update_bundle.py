import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

import update_bundle as bundle

OPENSSL = shutil.which('openssl') or ('C:/Program Files/Git/usr/bin/openssl.exe' if Path('C:/Program Files/Git/usr/bin/openssl.exe').exists() else None)


@unittest.skipUnless(OPENSSL, 'OpenSSL is needed for signature integration tests')
class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, self.public = self.root / 'private.pem', self.root / 'public.pem'
        subprocess.run([OPENSSL, 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(self.private)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        subprocess.run([OPENSSL, 'pkey', '-in', str(self.private), '-pubout', '-out', str(self.public)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        self.control = 'Package: stm32-lte-router\nVersion: 1.0.0-r15\nArchitecture: all\n'
        # Distinct lines make literal replacement substantially larger than the delta.
        old = ''.join(f'key{i} = "value {i*i}"\n' for i in range(3000)).encode()
        self.files = {'usr/lib/router-web/server.py': (old, 0o644), 'etc/init.d/router-web': (b'service\n', 0o755)}
        self.old, self.new = self.root / 'old.ipk', self.root / 'new.ipk'
        bundle.write_ipk(self.old, self.control, self.files)
        target = dict(self.files)
        target['usr/lib/router-web/server.py'] = (old.replace(b'value 100"', b'new value"'), 0o644)
        bundle.write_ipk(self.new, self.control, target)
        self.target = target
        self.installed = self.root / 'installed'
        for name, (raw, mode) in self.files.items():
            path = self.installed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def test_signed_delta_roundtrip_smaller_than_full(self):
        delta, full = self.root / 'delta.rupdate', self.root / 'full.rupdate'
        bundle.create(self.new, delta, self.private, self.old, OPENSSL)
        bundle.create(self.new, full, self.private, openssl=OPENSSL)
        self.assertLess(delta.stat().st_size, full.stat().st_size / 2)
        payload = bundle.verify(delta, self.public, OPENSSL)
        rebuilt = self.root / 'rebuilt.ipk'
        bundle.reconstruct(payload, self.installed, rebuilt)
        self.assertEqual(bundle.read_ipk(rebuilt), (self.control, self.target))

    def test_tampering_and_wrong_key_rejected(self):
        artifact = self.root / 'update.rupdate'
        bundle.create(self.new, artifact, self.private, openssl=OPENSSL)
        raw = bytearray(artifact.read_bytes())
        raw[-5] ^= 1
        artifact.write_bytes(raw)
        with self.assertRaises(ValueError):
            bundle.verify(artifact, self.public, OPENSSL)

    def test_changed_base_aborts_before_package_is_written(self):
        artifact = self.root / 'update.rupdate'
        bundle.create(self.new, artifact, self.private, self.old, OPENSSL)
        (self.installed / 'usr/lib/router-web/server.py').write_bytes(b'edited locally')
        output = self.root / 'rebuilt.ipk'
        with self.assertRaises(ValueError):
            bundle.reconstruct(bundle.verify(artifact, self.public, OPENSSL), self.installed, output)
        self.assertFalse(output.exists())

    def test_full_package_needs_no_base(self):
        artifact = self.root / 'update.rupdate'
        bundle.create(self.new, artifact, self.private, openssl=OPENSSL)
        output = self.root / 'rebuilt.ipk'
        bundle.reconstruct(bundle.verify(artifact, self.public, OPENSSL), self.root / 'empty', output)
        self.assertEqual(bundle.read_ipk(output)[1], self.target)

    def test_signed_path_traversal_is_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(dict(format=1, scope='router-application', board='STM32MP257F-DK', control=self.control, files={'../../etc/shadow': {'size': 0}})))
        with self.assertRaises(ValueError):
            bundle.reconstruct(stream.getvalue(), self.installed, self.root / 'bad.ipk')


if __name__ == '__main__':
    unittest.main()
