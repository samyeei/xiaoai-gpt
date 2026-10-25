"""Package a tested ESP32 configuration and the reviewable NAS project."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
artifacts = root / 'artifacts/2026-10-06'
config = json.loads((root / 'deploy/config/bridge.json').read_text())
acceptance = json.loads((artifacts / 'api-acceptance.json').read_text())
checks = [item for item in acceptance if 'check' in item]
assert len(checks) >= 11 and all(item['passed'] for item in checks), 'Real ESP32 API acceptance must pass first'
device = json.loads((artifacts / 'device-final.json').read_text())['devices'][0]
elf = Path('D:/AI Job/mosaico/projects/muse_companion/build/muse_companion.elf')
assert device['firmware_sha256'] == hashlib.sha256(elf.read_bytes()).hexdigest(), 'Final device firmware does not match current build'
assert device['firmware_mode'] == 'normal' and device['connected'] and not device['cached']
manifest = dict(date='2026-10-06', device_id=device['device_id'], firmware_sha256=device['firmware_sha256'],
                boot_id=device['boot_id'], esp32_url=config['esp32_url'], real_esp32_api_verified=True,
                nas_deployed=False, lx06_conversation_verified=False, node_tests_passed=12)
(root / 'deploy/deployment-status.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
archive = root / 'xiaoai-muse-群晖部署包.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
    for path in sorted((root / 'deploy').rglob('*')):
        if path.is_file() and path.suffix != '.zip':
            output.write(path, path.relative_to(root / 'deploy'))
with zipfile.ZipFile(archive) as output:
    assert output.testzip() is None
    assert {'compose.yaml', 'Dockerfile', 'config/bridge.json', 'bridge/index.mjs'} <= set(output.namelist())
print('Package:', archive)
print('SHA256:', hashlib.sha256(archive.read_bytes()).hexdigest())
print('Contains the private LAN bridge key; do not share publicly.')
