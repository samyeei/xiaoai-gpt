"""Use a temporary second client for four seconds; leave the installed client untouched."""
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.codex-runs/python-deps'))
import paramiko

c=paramiko.SSHClient()
c.load_system_host_keys()
c.load_host_keys(str(Path.home()/'.ssh/known_hosts'))
c.connect('192.168.100.186',username='root',password='open-xiaoai',timeout=5,look_for_keys=False,allow_agent=False)
pid=None
try:
    _,stdout,stderr=c.exec_command('cp /data/open-xiaoai/client /tmp/open-xiaoai-capture-probe && /tmp/open-xiaoai-capture-probe ws://192.168.100.154:4419 >/tmp/open-xiaoai-capture-probe.log 2>&1 &',timeout=5)
    time.sleep(1)
    _,stdout,_=c.exec_command("pidof open-xiaoai-capture-probe")
    pids=stdout.read().decode().split()
    assert len(pids)==1 and pids[0].isdigit(), 'Probe process not found'
    pid=pids[0]
    time.sleep(13)
finally:
    if pid:
        _,stdout,_=c.exec_command(f'kill {pid}; rm -f /tmp/open-xiaoai-capture-probe /tmp/open-xiaoai-capture-probe.log')
        stdout.channel.recv_exit_status()
    c.close()
print('Temporary capture client removed; installed NAS client unchanged.')
