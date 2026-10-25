"""Export only this bridge's LAN key through mosaico.py; never print it."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
workspace = Path('D:/AI Job/mosaico')
environment = dict(os.environ, PYTHONUTF8='1')
result = subprocess.run([sys.executable, '-X', 'utf8', 'mosaico.py', 'iris', 'rpc', '0x7e15', '2',
                         '--project', 'projects/muse_companion', '--device-id', '4553502d49524953010030eda0f459e6', '--json'],
                        cwd=workspace, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=20)
if result.returncode:
    raise SystemExit('Bridge RPC unavailable; inspect device status before retrying. No configuration written.')
data = json.loads(result.stdout)
response = data['response']
info = json.loads(base64.b64decode(response['payload_base64']))
if not info.get('ip') or len(info.get('key', '')) != 64:
    raise SystemExit('Bridge has no valid LAN address/key; no configuration written.')
config = dict(esp32_url=f"http://{info['ip']}:4397", key=info['key'], mode_timeout_ms=60000, request_timeout_ms=95000)
path = root / 'deploy/config/bridge.json'
path.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
info.pop('key')
out = root / 'artifacts/2026-10-06/bridge-info.json'
out.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
print(f"Private configuration saved: {path}")
print(json.dumps(info))
