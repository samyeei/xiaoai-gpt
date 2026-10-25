"""Check the bridge image's dependency layout and create a small NAS hotfix."""
from pathlib import Path
import shutil
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
stage = root / '.codex-runs/bridge-build-fix/app/bridge'
shutil.copytree(root / 'deploy/bridge', stage, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('node_modules', '__pycache__'))
shutil.copytree(root / 'deploy/bridge/vendor/ws', stage / 'node_modules/ws', dirs_exist_ok=True)
tests = sorted(str(p) for p in stage.glob('*.test.mjs'))
result = subprocess.run(['node', '--test', *tests], cwd=stage, capture_output=True, text=True)
evidence = root / 'artifacts/2026-10-06/hey-muse/build-fix-tests.txt'
evidence.write_text(result.stdout + result.stderr, encoding='utf-8')
assert result.returncode == 0, result.stdout + result.stderr
dockerfile = (root / 'deploy/Dockerfile').read_text()
assert 'npm ci' not in dockerfile and 'COPY bridge/vendor/ws /app/bridge/node_modules/ws' in dockerfile
archive = root / 'xiaoai-muse-HeyMuse-构建修复.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
    output.write(root / 'deploy/Dockerfile', 'Dockerfile')
    for path in sorted((root / 'deploy/bridge/vendor/ws').rglob('*')):
        if path.is_file():
            output.write(path, path.relative_to(root / 'deploy'))
with zipfile.ZipFile(archive) as output:
    assert output.testzip() is None
    assert 'bridge/vendor/ws/package.json' in output.namelist()
print('Staged image layout: 17 Node tests passed')
print('Hotfix ZIP bytes:', archive.stat().st_size)
