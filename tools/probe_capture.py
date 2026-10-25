"""Bounded shared ALSA capture; never opens the native hardware exclusively."""
from pathlib import Path
import sys
import array
import math
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.codex-runs/python-deps'))
import paramiko

client = paramiko.SSHClient()
client.load_system_host_keys()
client.load_host_keys(str(Path.home() / '.ssh/known_hosts'))
client.connect('192.168.100.186', username='root', password='open-xiaoai', timeout=5, look_for_keys=False, allow_agent=False)
try:
    _, stdout, stderr = client.exec_command('arecord -q -D noop -t raw -f S32_LE -r 16000 -c 1 -d 3', timeout=8)
    data = stdout.read()
    error = stderr.read().decode(errors='replace')
    code = stdout.channel.recv_exit_status()
    samples = array.array('i', data)
    rms = math.sqrt(sum(x*x for x in samples) / max(1, len(samples)))
    result = {'exit_code': code, 'bytes':len(data), 'samples':len(samples), 'rms_s32':rms,
              'peak_s32':max((abs(x) for x in samples), default=0), 'stderr':error}
    directory = Path(__file__).resolve().parents[1] / 'artifacts/2026-10-06/hey-muse'
    (directory / 'capture-s32.raw').write_bytes(data)
    import json
    (directory / 'capture-probe.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
finally:
    client.close()
