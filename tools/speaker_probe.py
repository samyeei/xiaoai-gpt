"""Read LX06 audio configuration through its already enabled SSH service."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.codex-runs/python-deps'))
import paramiko

root = Path(__file__).resolve().parents[1]
client = paramiko.SSHClient()
client.load_system_host_keys()
client.load_host_keys(str(Path.home() / '.ssh/known_hosts'))
client.connect('192.168.100.186', username='root', password='open-xiaoai', timeout=5, look_for_keys=False, allow_agent=False)
command = 'micocfg_model; df -h /data; cat /etc/asound.conf; arecord -l; ps | grep open-xiaoai | grep -v grep'
_, stdout, stderr = client.exec_command(command, timeout=10)
text = stdout.read().decode('utf-8', errors='replace')
errors = stderr.read().decode('utf-8', errors='replace')
directory = root / 'artifacts/2026-10-06/hey-muse'
directory.mkdir(parents=True, exist_ok=True)
(directory / 'speaker-baseline.txt').write_text(text + errors, encoding='utf-8')
print(text + errors)
client.close()
