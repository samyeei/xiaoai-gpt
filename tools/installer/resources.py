"""Prepare model weights using the repository's pinned archive and file hashes."""

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request


class ResourceError(Exception):
    """A safe, stable error code without URLs, paths, or third-party messages."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _relative(name):
    if not isinstance(name, str) or not name or '\\' in name or name.startswith('/'):
        raise ResourceError('unsafe_archive')
    parts = name.rstrip('/').split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise ResourceError('unsafe_archive')
    return PurePosixPath(*parts)


def _owned_dir(root, directory, create=False):
    """Reject symlinked or non-directory components below the canonical root."""
    try:
        parts = directory.relative_to(root).parts
    except ValueError:
        raise ResourceError('unsafe_path') from None
    current = root
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if not create:
                raise ResourceError('unsafe_path') from None
            try:
                current.mkdir()
            except FileExistsError:
                raise ResourceError('unsafe_path') from None
            mode = current.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise ResourceError('unsafe_path')


def _trusted_file(path):
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _load_trust(root):
    try:
        base = root / 'deploy/models'
        _owned_dir(root, base)
        if not all(_trusted_file(base / name) for name in ('sources.json', 'manifest.json')):
            raise ValueError()
        sources = json.loads((base / 'sources.json').read_text(encoding='utf-8'))
        manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
        if not isinstance(sources, list) or not isinstance(manifest, list) or not sources or not manifest:
            raise ValueError()
        source_map = {}
        for source in sources:
            kind = source['kind']
            if (not isinstance(kind, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', kind)
                    or kind in source_map or not _hash(source['archive_sha256'])
                    or not isinstance(source['source'], str)
                    or not source['source'].startswith('https://')):
                raise ValueError()
            source_map[kind] = source
        expected = {kind: {} for kind in source_map}
        for item in manifest:
            relative = _relative(item['path'])
            if (len(relative.parts) < 2 or relative.parts[0] not in expected
                    or relative.parts[1:] in expected[relative.parts[0]]
                    or type(item['bytes']) is not int or item['bytes'] < 0
                    or not _hash(item['sha256'])):
                raise ValueError()
            expected[relative.parts[0]][relative.parts[1:]] = item
        if any(not entries for entries in expected.values()):
            raise ValueError()
        return source_map, expected
    except (OSError, ValueError, TypeError, KeyError, ResourceError) as exc:
        raise ResourceError('trust_manifest_invalid') from None


def _verify(directory, expected):
    for parts, item in expected.items():
        path = directory.joinpath(*parts)
        if (any(directory.joinpath(*parts[:index]).is_symlink()
                for index in range(1, len(parts) + 1)) or not path.is_file()):
            return False
        if path.stat().st_size != item['bytes'] or _digest(path) != item['sha256']:
            return False
    return True


def _download(url, destination):
    with urllib.request.urlopen(url, timeout=60) as response, destination.open('wb') as output:
        shutil.copyfileobj(response, output)


def _extract(archive, destination):
    try:
        with tarfile.open(archive, mode='r:bz2') as source:
            members = source.getmembers()
            seen = set()
            roots = set()
            files = []
            for member in members:
                path = _relative(member.name)
                roots.add(path.parts[0])
                if not member.isfile() and not member.isdir():
                    raise ResourceError('unsafe_archive')
                if len(path.parts) == 1:
                    if not member.isdir() or () in seen:
                        raise ResourceError('unsafe_archive')
                    seen.add(())
                    continue
                relative = path.parts[1:]
                if relative in seen:
                    raise ResourceError('unsafe_archive')
                seen.add(relative)
                if member.isfile():
                    files.append((member, relative))
            if len(roots) != 1:
                raise ResourceError('unsafe_archive')
            for member, relative in files:
                target = destination.joinpath(*relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = source.extractfile(member)
                if stream is None:
                    raise ResourceError('unsafe_archive')
                with stream, target.open('xb') as output:
                    shutil.copyfileobj(stream, output)
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise ResourceError('unsafe_archive') from None


def _promote_atomic(staging, destination):
    """Move a complete directory into place without replacing any destination."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == 'darwin':
            rename = libc.renamex_np
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            result = rename(os.fsencode(staging), os.fsencode(destination), 0x4)  # RENAME_EXCL
        elif sys.platform.startswith('linux'):
            rename = libc.renameat2
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                               ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            result = rename(-100, os.fsencode(staging), -100,
                            os.fsencode(destination), 0x1)  # RENAME_NOREPLACE
        else:
            raise ResourceError('atomic_promotion_unavailable')
    except AttributeError:
        raise ResourceError('atomic_promotion_unavailable') from None
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise ResourceError('existing_model_invalid')
        raise ResourceError('atomic_promotion_failed')


def prepare_models(root: Path, download=None):
    """Verify or install pinned models; never replace an existing model directory."""
    try:
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError()
    except (OSError, ValueError):
        raise ResourceError('unsafe_path') from None
    _owned_dir(root, root / 'deploy/models')
    sources, expected = _load_trust(root)
    downloads = root / '.codex-runs/installer-downloads'
    fetch = download or _download
    for kind, source in sources.items():
        destination = root / 'deploy/models' / kind
        _owned_dir(root, destination.parent)
        if destination.exists() or destination.is_symlink():
            try:
                valid = destination.is_dir() and not destination.is_symlink() and _verify(destination, expected[kind])
            except OSError:
                valid = False
            if not valid:
                raise ResourceError('existing_model_invalid')
            continue
        try:
            _owned_dir(root, downloads, create=True)
            archive = downloads / (source['archive_sha256'] + '.tar.bz2')
            if archive.is_symlink():
                raise ResourceError('unsafe_path')
            if not archive.exists():
                with tempfile.NamedTemporaryFile(dir=downloads, suffix='.partial', delete=False) as temporary:
                    partial = Path(temporary.name)
                try:
                    fetch(source['source'], partial)
                    if _digest(partial) != source['archive_sha256']:
                        raise ResourceError('archive_hash_mismatch')
                    _owned_dir(root, downloads)
                    partial.replace(archive)
                finally:
                    partial.unlink(missing_ok=True)
            if archive.is_symlink() or _digest(archive) != source['archive_sha256']:
                raise ResourceError('archive_hash_mismatch')
            _owned_dir(root, downloads)
            with tempfile.TemporaryDirectory(dir=downloads, prefix='extract-') as staging_name:
                staging = Path(staging_name) / kind
                staging.mkdir()
                _extract(archive, staging)
                if not _verify(staging, expected[kind]):
                    raise ResourceError('model_hash_mismatch')
                _owned_dir(root, destination.parent)
                if destination.exists() or destination.is_symlink():
                    raise ResourceError('existing_model_invalid')
                _promote_atomic(staging, destination)
        except ResourceError:
            raise
        except Exception as exc:
            raise ResourceError('resource_io_failed') from None
    return {'models_verified': True}
