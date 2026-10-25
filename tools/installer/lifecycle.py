"""Generated local settings, user launchd jobs and bounded readiness checks."""
import json, os, plistlib, shlex, time, urllib.request
from pathlib import Path
from .core import InstallError, encoded_json, private_dir

def labels(j):return {name:'org.xiaoaigpt.'+j.data['id']+'.'+name for name in ('native','realtime','unified')}
def configure(j,settings):
 root=j.root;registry={'version':1,'mode':'single','devices':[{'id':'lx06-primary','ip':settings['speaker']},{'id':'lx06-secondary','ip':'192.168.100.254' if settings['speaker']!='192.168.100.254' else '192.168.100.253'}]}
 values={
 'mac/installer/private/speakers.json':registry,
 'mac/installer/private/runtime.json':{'version':1,'node':settings['node'],'bridge_host':settings['mac_ip'],'labels':labels(j),'muse_enabled':False},
 'mac/codex-service/private/config.json':{'cwd':str(root),'executable':settings['codex'],'host':'127.0.0.1','port':4411,'control_port':4412,'key':j.data['key'],'admin_key':j.data['admin_key']},
 'deploy/config/bridge.json':{'mode_timeout_ms':60000,'request_timeout_ms':95000},
 'mac/unified-service/private/realtime-voice.json':{'enabled':True,'idle_seconds':60,'max_session_seconds':900},
 'mac/unified-service/private/asr-wake.json':{'enabled':True},
 'mac/realtime-voice/private/player.json':{'mode':'managed'},
 }
 for relative,data in values.items():
  p=root/relative
  if 'private' in p.parts:private_dir(p.parent)
  j.write(p,encoded_json(data))
 j.step('configuration')

def job_plists(j,settings):
 scripts={'native':'mac/native-voice/supervisor.mjs','realtime':'mac/realtime-voice/service.mjs','unified':'mac/unified-service/index.mjs'};result={}
 for kind,label in labels(j).items():
  logs=j.home/'Library/Logs/xiaoai-gpt'/j.data['id']/kind
  value={'Label':label,'ProgramArguments':[settings['node'],str(j.root/scripts[kind])],'WorkingDirectory':str(j.root),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,'ExitTimeOut':60,'Umask':63,'EnvironmentVariables':{'PATH':str(Path(settings['node']).parent)+':/usr/bin:/bin:/usr/sbin:/sbin','SPEAKERS_CONFIG':str(j.root/'mac/installer/private/speakers.json')},'StandardOutPath':str(logs/'stdout.log'),'StandardErrorPath':str(logs/'stderr.log')}
  result[label]=plistlib.dumps(value)
 return result

def install_jobs(j,settings):
 for label,data in job_plists(j,settings).items():
  values=plistlib.loads(data);logs=Path(values['StandardOutPath']).parent;owner=logs/'.xiaoai-owner'
  j.allowed(owner)
  if logs.exists() and str(owner) not in j.data['files'] and str(logs) not in j.data.get('log_dirs',[]):raise InstallError('foreign_log_directory')
  j.write(owner,(j.data['id']+'\n').encode())
  private_dir(logs)
  if str(logs) not in j.data.get('log_dirs',[]):j.data.setdefault('log_dirs',[]).append(str(logs));j.save()
  j.write(j.home/'Library/LaunchAgents'/f'{label}.plist',data)
 shortcut=j.home/'Desktop'/('Start Xiaoai GPT '+j.data['id']+'.command')
 script='#!/bin/bash\nset -e\ncd '+shlex.quote(str(j.root))+'\n./install.sh start\nprintf "\\nPress Enter to close. "\nread -r task_reply\n'
 j.write(shortcut,script.encode(),mode=0o700);j.step('jobs')

def launch(j,run,start):
 domain='gui/'+str(os.getuid())
 for label in (labels(j).values() if start else reversed(list(labels(j).values()))):
  target=domain+'/'+label;p=j.home/'Library/LaunchAgents'/f'{label}.plist'
  loaded=run(['/bin/launchctl','print',target]).returncode==0
  if start:
   if not p.exists():raise InstallError('owned_job_missing')
   if not loaded and run(['/bin/launchctl','bootstrap',domain,str(p)]).returncode:raise InstallError('job_start_failed')
   if run(['/bin/launchctl','kickstart',target]).returncode:raise InstallError('job_start_failed')
  elif loaded and run(['/bin/launchctl','bootout',target]).returncode:raise InstallError('job_stop_failed')

def fetch_json(port,path,key=''):
 req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',headers={'Authorization':'Bearer '+key} if key else {})
 with urllib.request.urlopen(req,timeout=3) as res:
  return json.load(res)

def busy(bridge):
 voice=bridge.get('voice') or {};realtime=bridge.get('realtime_voice') or {};native=bridge.get('native_voice') or {}
 return bool(bridge.get('pending') or bridge.get('conversation_owner') or voice.get('state') not in (None,'idle','offline') or realtime.get('active') or native.get('active'))

def readiness(j,fetch=fetch_json):
 try:
  b=fetch(4398,'/health','');m=fetch(4413,'/status',j.data['admin_key']);r=fetch(4418,'/status',j.data['admin_key']);n=fetch(4417,'/status',j.data['admin_key'])
  v=b.get('voice',{});connected=bool(v.get('speaker_connected'));ready=bool(v.get('models_ready') and m.get('codex',{}).get('ready'))
  frames=v.get('audio_frames',0);pcm_received=type(frames) is int and frames>0
  return {'services_ready':ready,'connected':connected,'pcm_received':pcm_received,'active':busy(b) or bool(r.get('active')) or bool(n.get('active')),'conversation_verified':False}
 except Exception:return {'services_ready':False,'connected':False,'pcm_received':False,'active':False,'conversation_verified':False}

def require_idle(j):
 # An unknown port owner is never treated as our own idle service.
 try:
  fetch_json(4413,'/status',j.data['admin_key'])
  b=fetch_json(4398,'/health');r=fetch_json(4418,'/status',j.data['admin_key']);n=fetch_json(4417,'/status',j.data['admin_key'])
 except Exception:raise InstallError('cannot_confirm_owned_services_idle') from None
 if busy(b) or r.get('active') or n.get('active'):raise InstallError('end_conversation_first')

def await_ready(j,seconds=45):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  s=readiness(j)
  if s['services_ready'] and s['connected'] and s['pcm_received']:return s
  time.sleep(1)
 raise InstallError('speaker_or_services_not_ready')
