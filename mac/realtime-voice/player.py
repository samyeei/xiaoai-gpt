"""Fixed device PCM player; only project-owned SSH authentication."""
import asyncio,time
from pathlib import Path
class PlayerConfig:
 def __init__(self,root,mode='diagnostic',device_id='lx06-primary'):
  if mode not in ('diagnostic','managed'):raise ValueError('Invalid player auth mode')
  self.root=Path(root).resolve();self.mode=mode
  from devices import device_ip
  self.target=device_ip(self.root,device_id);self.device_id=device_id
 def command(self):
  a=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=3','-o','ConnectionAttempts=1','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(self.root/'.codex-runs/lx06-known-hosts'),'-o','GlobalKnownHostsFile=/dev/null','-o','HostKeyAlgorithms=+ssh-rsa']
  if self.mode=='diagnostic':a+=['-S',str(self.root/('.codex-runs/lx06-diagnostic/control' if self.device_id=='lx06-primary' else '.codex-runs/lx06-secondary-diagnostic/control')),'-o','ControlMaster=no','-o','ProxyCommand=/usr/bin/false']
  else:a+=['-F','/dev/null','-o','IdentitiesOnly=yes','-o','ControlMaster=no','-o','ControlPath=none','-o','PubkeyAcceptedAlgorithms=+ssh-rsa','-i',str(self.root/'mac/realtime-voice/private/device_rsa')]
  return a+['root@'+self.target,'aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000']
 async def preflight(self):
  cmd=self.command();p=await asyncio.create_subprocess_exec(*cmd,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
  try:
   _,diagnostic=await asyncio.wait_for(p.communicate(bytes(3840)),5)
   if p.returncode!=0:
    import sys
    print('player diagnostic: exit='+str(p.returncode),file=sys.stderr,flush=True)
    for line in diagnostic.decode(errors='replace').splitlines():
     if any(w in line for w in ('Permission denied','Operation not permitted','Host key verification','Load key','No such file','Bad configuration','Connection refused','Identity file','invalid format','no matching','Connection closed','Connection reset','not found','aplay','Read from socket','ssh_dispatch','ssh:','Bad owner','Unsupported','Timeout','No route','refused','denied','REMOTE HOST','known_hosts','not accessible','resolve','agent')):
      print('player diagnostic: '+line[:500],file=sys.stderr,flush=True)
    raise RuntimeError('player_unavailable')
  except BaseException:
   if p.returncode is None:p.kill();await p.wait()
   raise
class ActivityGate:
 def __init__(self):self.active=False;self.until=0
 def playing(self):self.active=True
 def drained(self,now):self.active=False;self.until=now+.4
 def can_listen(self,now):return not self.active and now>=self.until
class Player:
 def __init__(self,config):self.config=config;self.process=None;self.stderr_task=None;self.on_stderr=lambda data:None;self.on_write=lambda seconds:None
 async def read_stderr(self,process):
  while True:
   data=await process.stderr.readline()
   if not data:return
   self.on_stderr(data)
 async def finish_stderr(self):
  if self.stderr_task is not None:
   try:await asyncio.wait_for(self.stderr_task,1)
   except asyncio.TimeoutError:pass
   finally:self.stderr_task=None
 async def write(self,data):
  if self.process is None:
   self.process=await asyncio.create_subprocess_exec(*self.config.command(),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
   self.stderr_task=asyncio.create_task(self.read_stderr(self.process))
  started=time.monotonic();self.process.stdin.write(data);await asyncio.wait_for(self.process.stdin.drain(),3);self.on_write(time.monotonic()-started)
 async def drain(self):
  p=self.process
  if p is None:return
  p.stdin.close()
  try:
   await asyncio.wait_for(p.wait(),5)
   if p.returncode!=0:raise RuntimeError('player_unavailable')
  except BaseException:
   if p.returncode is None:p.kill();await p.wait()
   raise
  finally:
   await self.finish_stderr();self.process=None
 async def close(self):
  if self.process:
   p,self.process=self.process,None
   if p.returncode is None:p.terminate()
   try:await asyncio.wait_for(p.wait(),3)
   except asyncio.TimeoutError:p.kill();await p.wait()
   await self.finish_stderr()
