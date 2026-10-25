"""Offline checks for pinned model downloads and archive handling."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.installer import resources
from tools.installer.resources import ResourceError, prepare_models


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ResourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'deploy/models').mkdir(parents=True)
        self.payload = b'trusted model bytes'
        self.archive = self.make_archive([('model-root/model.bin', self.payload, None)])
        self.write_manifests(self.archive)

    def make_archive(self, entries):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:bz2') as tar:
            for name, content, kind in entries:
                info = tarfile.TarInfo(name)
                if kind in ('symlink', 'hardlink'):
                    info.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
                    info.linkname = 'elsewhere'
                    tar.addfile(info)
                else:
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))
        return output.getvalue()

    def write_manifests(self, archive, archive_hash=None):
        sources = [{'kind': 'kws', 'source': 'https://example.invalid/model.tar.bz2',
                    'archive_sha256': archive_hash or sha(archive)}]
        manifest = [{'path': 'kws/model.bin', 'bytes': len(self.payload),
                     'sha256': sha(self.payload)}]
        (self.root / 'deploy/models/sources.json').write_text(json.dumps(sources))
        (self.root / 'deploy/models/manifest.json').write_text(json.dumps(manifest))

    def downloader(self, archive):
        def download(_url, destination):
            destination.write_bytes(archive)
        return download

    def test_trusted_download_and_resume_without_second_download(self):
        calls = []
        def download(url, destination):
            calls.append(url)
            destination.write_bytes(self.archive)
        self.assertEqual({'models_verified': True}, prepare_models(self.root, download))
        self.assertEqual(self.payload, (self.root / 'deploy/models/kws/model.bin').read_bytes())
        self.assertEqual({'models_verified': True}, prepare_models(self.root, lambda *_: self.fail('download on resume')))
        self.assertEqual(1, len(calls))

    def test_hash_mismatch_cannot_extract(self):
        self.write_manifests(self.archive, archive_hash='0' * 64)
        with self.assertRaises(ResourceError) as caught:
            prepare_models(self.root, self.downloader(self.archive))
        self.assertEqual('archive_hash_mismatch', caught.exception.code)
        self.assertFalse((self.root / 'deploy/models/kws').exists())

    def test_unsafe_archive_members_are_rejected(self):
        for entries in ([('model-root/../escape', b'x', None)],
                        [('/absolute/model.bin', b'x', None)],
                        [('model-root/model.bin', self.payload, None),
                         ('model-root/link', b'', 'symlink')],
                        [('model-root/model.bin', self.payload, None),
                         ('model-root/link', b'', 'hardlink')],
                        [('model-root/model.bin', self.payload, None),
                         ('model-root/model.bin', self.payload, None)]):
            with self.subTest(entries=entries):
                archive = self.make_archive(entries)
                self.write_manifests(archive)
                with self.assertRaises(ResourceError):
                    prepare_models(self.root, self.downloader(archive))
                self.assertFalse((self.root / 'deploy/models/kws').exists())

    def test_corrupt_existing_model_is_never_clobbered(self):
        destination = self.root / 'deploy/models/kws'
        destination.mkdir()
        (destination / 'model.bin').write_bytes(b'valuable but wrong')
        with self.assertRaises(ResourceError) as caught:
            prepare_models(self.root, lambda *_: self.fail('should not download'))
        self.assertEqual('existing_model_invalid', caught.exception.code)
        self.assertEqual(b'valuable but wrong', (destination / 'model.bin').read_bytes())

    def test_cache_parent_symlink_cannot_redirect_download(self):
        outside = self.root / 'outside-cache'
        outside.mkdir()
        (self.root / '.codex-runs').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ResourceError):
            prepare_models(self.root, lambda *_: self.fail('download crossed symlink'))
        self.assertEqual([], list(outside.iterdir()))

    def test_models_parent_symlink_cannot_redirect_model_install(self):
        outside = self.root / 'outside-models'
        outside.mkdir()
        models = self.root / 'deploy/models'
        for filename in ('sources.json', 'manifest.json'):
            (outside / filename).write_bytes((models / filename).read_bytes())
        for child in models.iterdir():
            child.unlink()
        models.rmdir()
        models.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ResourceError):
            prepare_models(self.root, self.downloader(self.archive))
        self.assertFalse((outside / 'kws').exists())

    def test_destination_created_during_download_is_not_overwritten(self):
        destination = self.root / 'deploy/models/kws'
        def download(_url, target):
            target.write_bytes(self.archive)
            destination.mkdir()
            (destination / 'note.txt').write_text('other owner')
        with self.assertRaises(ResourceError) as caught:
            prepare_models(self.root, download)
        self.assertEqual('existing_model_invalid', caught.exception.code)
        self.assertEqual('other owner', (destination / 'note.txt').read_text())
        self.assertFalse((destination / 'model.bin').exists())

    def test_empty_destination_created_at_promotion_is_not_replaced(self):
        destination = self.root / 'deploy/models/kws'
        original_promote = resources._promote_atomic
        created_inode = []
        def race_promote(source, target):
            destination.mkdir()
            created_inode.append(destination.stat().st_ino)
            return original_promote(source, target)
        with patch('tools.installer.resources._promote_atomic', side_effect=race_promote):
            with self.assertRaises(ResourceError) as caught:
                prepare_models(self.root, self.downloader(self.archive))
        self.assertEqual('existing_model_invalid', caught.exception.code)
        self.assertEqual(created_inode, [destination.stat().st_ino])
        self.assertEqual([], list(destination.iterdir()))

    def test_interrupt_before_or_after_atomic_promotion_never_leaves_partial_model(self):
        destination = self.root / 'deploy/models/kws'
        with patch('tools.installer.resources._promote_atomic', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                prepare_models(self.root, self.downloader(self.archive))
        self.assertFalse(destination.exists())
        original_promote = resources._promote_atomic
        def promote_then_interrupt(source, target):
            original_promote(source, target)
            raise KeyboardInterrupt
        with patch('tools.installer.resources._promote_atomic', side_effect=promote_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                prepare_models(self.root, self.downloader(self.archive))
        self.assertEqual(self.payload, (destination / 'model.bin').read_bytes())
        self.assertEqual({'models_verified': True}, prepare_models(self.root, lambda *_: self.fail('download on resume')))


if __name__ == '__main__':
    unittest.main()
