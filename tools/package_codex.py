"""Build a private, separate NAS update without changing the currently deployed files."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy'
OUTPUT = ROOT / 'artifacts/2026-10-07/codex-voice'


def build():
    config = json.loads((ROOT / 'mac/codex-service/private/config.json').read_text())
    bridge = json.loads((DEPLOY / 'config/bridge.json').read_text())
    bridge['codex'] = dict(url=f"http://{config['host']}:{config['port']}", key=config['key'], request_timeout_ms=900000)
    models = json.loads((DEPLOY / 'models/manifest.json').read_text())
    paths = [DEPLOY / 'models' / entry['path'] for entry in models]
    for path, entry in zip(paths, models):
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Model manifest mismatch: ' + entry['path'])
    paths += [DEPLOY / 'Dockerfile', DEPLOY / '.dockerignore', DEPLOY / 'README_HEY_MUSE.md', DEPLOY / 'README_CODEX.md',
              DEPLOY / 'models/manifest.json', DEPLOY / 'models/sources.json']
    for directory in ('bridge', 'voice'):
        paths += [p for p in (DEPLOY / directory).rglob('*') if p.is_file()
                  and 'node_modules' not in p.parts and '__pycache__' not in p.parts]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = OUTPUT / 'xiaoai-Codex-群晖更新包.zip'
    evidence = dict(date='2026-10-07', local_real_codex_reply_and_followup=True,
                    keywords_synthetic_only=True, nas_deployed=False, human_keyword_verified=False,
                    lx06_codex_conversation_verified=False, contains_private_bridge_keys=True)
    compose = (DEPLOY / 'compose.yaml').read_text().replace('local/xiaoai-muse:hey-muse-2026-10-06', 'local/xiaoai-codex:2026-10-07')
    compose = compose.replace('local/xiaoai-muse-voice:2026-10-06', 'local/xiaoai-codex-voice:2026-10-07')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as out:
        for path in sorted(set(paths)):
            out.write(path, path.relative_to(DEPLOY).as_posix())
        out.writestr('compose.yaml', compose)
        out.writestr('config/bridge.json', json.dumps(bridge, ensure_ascii=False, indent=2))
        out.writestr('evidence-status.json', json.dumps(evidence, indent=2))
    archive.chmod(0o600)
    with zipfile.ZipFile(archive) as check:
        assert check.testzip() is None
        names = set(check.namelist())
        assert {'compose.yaml', 'bridge/codex-client.mjs', 'bridge/vendor/ws/package.json', 'voice/keyword_routes.py',
                'voice/keywords.txt', 'models/asr/model.int8.onnx', 'config/bridge.json', 'README_CODEX.md'} <= names
        assert 'deployment-status.json' not in names
        packaged = json.loads(check.read('config/bridge.json'))
        assert packaged['esp32_url'] == bridge['esp32_url'] and packaged['key'] == bridge['key']
        assert packaged['codex']['key'] == config['key'] and 'admin_key' not in check.read('config/bridge.json').decode()
        assert not any('private/' in name or 'state.json' in name for name in names)
    report = dict(archive=str(archive), bytes=archive.stat().st_size,
                  sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), files=sorted(names), **evidence)
    (OUTPUT / 'package-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    build()
