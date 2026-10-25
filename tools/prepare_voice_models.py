"""Download pinned official models; extract only regular files into private staging."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    'kws': ('kws-models', 'sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'),
    'asr': ('asr-models', 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17'),
}

def download(item):
    kind, (release, name) = item
    url = f'https://github.com/k2-fsa/sherpa-onnx/releases/download/{release}/{name}.tar.bz2'
    staging = ROOT / '.codex-runs/models'
    staging.mkdir(parents=True, exist_ok=True)
    archive = staging / (name + '.tar.bz2')
    if not archive.exists():
        temporary = archive.with_suffix('.partial')
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(archive)
    dest = ROOT / 'deploy/models' / kind
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        for member in source:
            relative = Path(*Path(member.name).parts[1:])
            if not member.isfile() or relative.is_absolute() or '..' in relative.parts:
                continue
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as stream, target.open('wb') as output:
                import shutil
                shutil.copyfileobj(stream, output)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(kind, 'downloaded and extracted', flush=True)
    return dict(kind=kind, source=url, archive_sha256=digest)

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=2) as pool:
        manifest = list(pool.map(download, MODELS.items()))
    (ROOT / 'deploy/models/sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
