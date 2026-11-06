import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import system_update as system
import update_bundle as bundle
from test_update_bundle import OPENSSL


class SlotGuards(unittest.TestCase):
    def setUp(self):
        sync = patch.object(system.os, 'sync', create=True)
        sync.start()
        self.addCleanup(sync.stop)

    def test_missing_profile_blocks_system_updates(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(system, 'PROFILE', Path(directory) / 'missing'):
            with self.assertRaises(ValueError):
                system.profile()
            self.assertFalse(system.readiness()['ready'])

    def test_staging_budget_counts_only_new_images_beyond_existing_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            data = dict(staging_directory=directory, max_rootfs_bytes=768*1024*1024,
                        slots={'A': {'partuuid': 'a'}, 'B': {'partuuid': 'b'}})
            target = Mock()
            target.stat.return_value.st_rdev = -1
            with patch.object(system, 'device', return_value=target), \
                    patch.object(system.shutil, 'disk_usage', return_value=Mock(free=1100*1024*1024)):
                self.assertEqual(system.staging_directory(data), Path(directory))
            with patch.object(system, 'device', return_value=target), \
                    patch.object(system.shutil, 'disk_usage', return_value=Mock(free=900*1024*1024)):
                with self.assertRaises(ValueError):
                    system.staging_directory(data)

    def test_untested_profile_is_rejected_before_boot_environment_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'slots.json'
            path.write_text(json.dumps(dict(boot_tested=False, slots={'A': {}, 'B': {}})))
            with patch.object(system, 'PROFILE', path), patch.object(system, 'run') as run:
                with self.assertRaises(ValueError):
                    system.profile()
                run.assert_not_called()

    def test_mounted_inactive_slot_blocks_all_writes(self):
        data = dict(slots={'A': {'partuuid': 'a'}, 'B': {'partuuid': 'b'}})
        with patch.object(system, 'profile', return_value=data), patch.object(system, 'active_slot', return_value='A'), \
                patch.object(system, 'device', return_value=Path('/dev/fake')), \
                patch.object(system, 'run', side_effect=['A', '0']), \
                patch.object(system, 'mounted', return_value=['/somewhere']), patch.object(system, 'boot_mount') as mount:
            with self.assertRaisesRegex(ValueError, 'mounted'):
                system.install(b'payload', {}, Mock())
            mount.assert_not_called()

    def test_trial_boot_cannot_be_overwritten(self):
        data = dict(slots={'A': {'partuuid': 'a'}, 'B': {'partuuid': 'b'}})
        with patch.object(system, 'profile', return_value=data), patch.object(system, 'active_slot', return_value='A'), \
                patch.object(system, 'run', side_effect=['A', '1']), patch.object(system, 'device') as device:
            with self.assertRaisesRegex(ValueError, 'Confirm'):
                system.install(b'payload', {}, Mock())
            device.assert_not_called()

    def test_fallback_after_failed_boot_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            boot = Path(directory)
            (boot / 'router-slots').mkdir()
            pending = boot / 'router-slots/pending.json'
            pending.write_text(json.dumps(dict(slot='B', previous='A', generation=1, id='x', topic=None)))
            with patch.object(system, 'profile', return_value={}), patch.object(system, 'active_slot', return_value='A'), \
                    patch.object(system, 'boot_mount', return_value=(boot, False)), \
                    patch('firmware_update.STATE', boot / 'state'), patch.object(system, 'environment') as environment:
                system.confirm_boot()
            status = json.loads((boot / 'state/update-state/status.json').read_text())
            self.assertEqual(status['state'], 'failed')
            self.assertTrue(status['rolled_back'])
            self.assertFalse(pending.exists())
            environment.assert_not_called()

    def test_healthy_boot_commits_generation_and_immutable_delta_base(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            boot, staging = base / 'boot', base / 'staging'
            (boot / 'router-slots').mkdir(parents=True)
            candidate = staging / 'router-image-candidate-job1'
            candidate.mkdir(parents=True)
            hashes = {}
            for name in ('rootfs', 'kernel', 'dtb'):
                (candidate / (name + '.img')).write_bytes(name.encode())
                hashes[name] = bundle.digest(name.encode())
            pending = dict(slot='B', generation=2, version='test', id='job1', topic=None,
                           cache=str(candidate), image_hashes=hashes)
            (boot / 'router-slots/pending.json').write_text(json.dumps(pending))
            with patch.object(system, 'profile', return_value=dict(staging_directory=str(staging), health_interfaces=[])), \
                    patch.object(system, 'active_slot', return_value='B'), patch.object(system, 'boot_mount', return_value=(boot, False)), \
                    patch('firmware_update.STATE', base / 'state'), patch('firmware_update.healthy', return_value=True), \
                    patch.object(system, 'environment') as environment:
                system.confirm_boot()
            environment.assert_called_once()
            self.assertEqual(json.loads((boot / 'router-slots/state.json').read_text())['generation'], 2)
            self.assertEqual((staging / 'router-image-cache/rootfs.img').read_bytes(), b'rootfs')


@unittest.skipUnless(OPENSSL, 'OpenSSL required for signed system bundle tests')
class SystemBundleTests(unittest.TestCase):
    def test_full_and_block_delta_roundtrip_and_size(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            private, public = work / 'private.pem', work / 'public.pem'
            subprocess.run([OPENSSL, 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(private)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            subprocess.run([OPENSSL, 'pkey', '-in', str(private), '-pubout', '-out', str(public)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            spec = importlib.util.spec_from_file_location('system_builder', Path(__file__).resolve().parents[1] / 'openwrt/build-system-update.py')
            builder = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(builder)
            cache = work / 'base'
            cache.mkdir()
            original = os.urandom(1024 * 1024)
            target = original[:65536] + b'changed block' + original[65549:]
            (cache / 'rootfs.img').write_bytes(original)
            rootfs, kernel, dtb = [work / name for name in ('rootfs', 'kernel', 'dtb')]
            rootfs.write_bytes(target)
            kernel.write_bytes(b'kernel')
            dtb.write_bytes(b'dtb')
            args = SimpleNamespace(generation=1, version='test', base=cache, rootfs=rootfs, kernel=kernel, dtb=dtb,
                                   private_key=private, openssl=OPENSSL, export_base=None, output=work / 'delta.rupdate')
            builder.create(args)
            delta_size = args.output.stat().st_size
            payload = bundle.verify(args.output, public, OPENSSL)
            self.assertTrue(system.is_system(payload))
            rebuilt = work / 'rebuilt'
            rebuilt.mkdir()
            system.reconstruct(payload, cache, rebuilt)
            self.assertEqual((rebuilt / 'rootfs').read_bytes(), target)
            args.base = None
            args.output = work / 'full.rupdate'
            builder.create(args)
            self.assertLess(delta_size, args.output.stat().st_size / 10)
            (cache / 'rootfs.img').write_bytes(b'wrong base')
            with self.assertRaisesRegex(ValueError, 'base'):
                system.reconstruct(payload, cache, rebuilt)


if __name__ == '__main__':
    unittest.main()
