"""Fresh-checkout walkthrough: real installer logic, simulated OS/device boundaries.

No real SSH, launchctl, pip, account, network, ports or audio. Device shell
transactions execute locally against rewritten paths under a TemporaryDirectory.
"""
import base64, contextlib, hashlib, io, json, os, plistlib, shlex, shutil, subprocess, sys, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from . import cli, environment, lifecycle, resources
from .core import Journal
from .device import Device, FORCED

SCHEMA={'oneOf':[{'properties':{'method':{'enum':['thread/realtime/start']},'params':{'$ref':'#/definitions/Params'}}}],
 'definitions':{'Params':{'properties':{'version':{'$ref':'#/definitions/Version'},'transport':{'$ref':'#/definitions/Transport'},'voice':{'$ref':'#/definitions/Voice'}}},'Version':{'enum':['v3']},'Transport':{'oneOf':[{'properties':{'type':{'enum':['webrtc']},'sdp':{'type':'string'}}}]},'Voice':{'enum':['maple']}}}

class FreshMachine:
 def __init__(self,root,home):
  self.root=root;self.home=home;self.osroot=root.parent/'simulated OS';self.osroot.mkdir()
  self.bin=self.osroot/'bin';self.bin.mkdir();self.remote=self.osroot/'speaker';self.remote.mkdir();self.remote_home=self.remote/'root';self.remote_home.mkdir()
  self.data=self.remote/'data/open-xiaoai';self.data.mkdir(parents=True)
  (self.data/'client').write_bytes(b'start_recording run_shell get_version');(self.data/'client').chmod(0o700)
  (self.data/'init.sh').write_text('#!/bin/sh\nprintf restarted >> "$SIM_REMOTE_ROOT/restarts"\n')
  (self.data/'server.txt').write_bytes(b'ws://previous.invalid:4399\n')
  (self.remote_home/'.ssh').mkdir();(self.remote_home/'.ssh/authorized_keys').write_bytes(b'ssh-rsa ORIGINAL original-key\n')
  self.initial_route=(self.data/'server.txt').read_bytes();self.initial_keys=(self.remote_home/'.ssh/authorized_keys').read_bytes()
  self.calls=[];self.jobs={};self.connected=False;self.pcm=True;self.active=False;self.fail_pip=False;self.login=True;self.busy_ports=False;self.interrupt_route=False
  for name in ('node','codex'):
   p=self.bin/name;p.write_bytes(b'fake executable');p.chmod(0o700)
  self.settings={'speaker':'192.168.100.10','mac_ip':'192.168.100.20','node':str(self.bin/'node'),'codex':str(self.bin/'codex')}
  # Tiny test archives exercise real archive trust/promotion without downloads.
  self.archives={};manifest=[];sources=[]
  for kind in ('kws','asr'):
   payload=(kind+' test model').encode();out=io.BytesIO()
   with tarfile.open(fileobj=out,mode='w:bz2') as tf:
    member=tarfile.TarInfo('model/model.bin');member.size=len(payload);tf.addfile(member,io.BytesIO(payload))
   url='https://example.invalid/'+kind+'.tar.bz2';self.archives[url]=out.getvalue()
   sources.append({'kind':kind,'source':url,'archive_sha256':hashlib.sha256(out.getvalue()).hexdigest()})
   manifest.append({'path':kind+'/model.bin','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
  (root/'deploy/models/sources.json').write_text(json.dumps(sources));(root/'deploy/models/manifest.json').write_text(json.dumps(manifest))
  self._tool('sha256sum',"import hashlib,sys; p=sys.argv[1]; print(hashlib.sha256(open(p,'rb').read()).hexdigest()+'  '+p)")
  self._tool('base64',"import base64,sys; b=sys.stdin.buffer.read();sys.stdout.buffer.write(base64.b64decode(b) if '-d' in sys.argv else base64.b64encode(b)+b'\\n')")
  self._tool('micocfg_model',"print('LX06')")
  self._tool('aplay',"import sys;sys.stdin.buffer.read()")
 def _tool(self,name,body):
  p=self.bin/name;p.write_text('#!'+sys.executable+'\n'+body+'\n');p.chmod(0o700)
 def result(self,args,code=0,out=b''):return subprocess.CompletedProcess(args,code,out,b'')
 def shell(self,script,data=None):
  for source,target in [('/data/open-xiaoai',self.data),('/tmp/xiaoai-gpt-client.log',self.remote/'client.log')]:
   script=script.replace(source,shlex.quote(str(target)))
  env={'PATH':str(self.bin)+':/usr/bin:/bin','HOME':str(self.remote_home),'SIM_REMOTE_ROOT':str(self.remote)}
  return subprocess.run(['/bin/sh','-c',script],input=data,capture_output=True,env=env,timeout=5)
 def run(self,args,input=None,interactive=False,timeout=30):
  args=list(map(str,args));self.calls.append(args)
  if args[0]==str(self.bin/'brew'):
   prefix=self.osroot/'brew node22';node=prefix/'bin/node'
   if args[1:]==['install','node@22']:
    node.parent.mkdir(parents=True,exist_ok=True);node.write_bytes(b'fake brew node');node.chmod(0o700);self.settings['node']=str(node);return self.result(args)
   if args[1:]==['--prefix','node@22']:return self.result(args,out=(str(prefix)+'\n').encode())
   raise AssertionError('Unexpected brew command')
  if args[0]=='ssh-keygen':
   key=Path(args[args.index('-f')+1]);key.write_bytes(b'PRIVATE TEST KEY');key.with_suffix('.pub').write_text('ssh-rsa QUJDREVGR0g= fixture\n');return self.result(args)
  if args[0]=='ssh':
   if '-O' in args:
    socket=Path(args[args.index('-S')+1])
    if args[args.index('-O')+1]=='exit':socket.unlink(missing_ok=True)
    return self.result(args)
   if '-fN' in args:
    known=Path(next(v.split('=',1)[1] for v in args if v.startswith('UserKnownHostsFile=')))
    if not known.read_bytes():
     if not interactive:return self.result(args,255)
     known.write_bytes(b'FIXTURE_USER_VERIFIED_HOST\n')
    socket=Path(args[args.index('-S')+1]);socket.touch();return self.result(args)
   if '-i' in args:
    # Emulate server-side forced command only for the installed public key.
    key=Path(args[args.index('-i')+1]);public=key.with_suffix('.pub').read_text().split()[1]
    keys=(self.remote_home/'.ssh/authorized_keys').read_text()
    if FORCED+' ssh-rsa '+public+' xiaoai-realtime-voice' not in keys:return self.result(args,1)
    return self.shell('aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000',input)
   response=self.shell(args[-1],input)
   if self.interrupt_route and 'DEVICE_CAS_ROUTE' in args[-1]:
    self.interrupt_route=False;raise KeyboardInterrupt()
   if 'DEVICE_RESTART' in args[-1]:self.connected=(self.data/'server.txt').read_text().strip()==('ws://'+self.settings['mac_ip']+':4399')
   return response
  if args[0]=='/bin/launchctl':
   operation=args[1];target=args[-1];label=target.split('/')[-1]
   if operation=='print':return self.result(args,0 if label in self.jobs else 1)
   if operation=='bootstrap':
    value=plistlib.loads(Path(target).read_bytes());self.jobs[value['Label']]=value
   elif operation=='bootout':self.jobs.pop(label,None)
   elif operation=='kickstart':
    if label not in self.jobs:return self.result(args,1)
   else:raise AssertionError('unexpected launchctl operation')
   return self.result(args)
  if args[1:3]==['-m','venv']:
   p=Path(args[3])/'bin/python';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fake venv python');return self.result(args)
  if args[1:3]==['-m','pip']:
   if self.fail_pip:self.fail_pip=False;return self.result(args,1)
   return self.result(args)
  if args[0]=='/usr/bin/codesign':
   if '-d' in args:return self.result(args,out=plistlib.dumps({'com.apple.security.cs.allow-jit':True}))
   app=Path(args[-1])
   if '--force' in args:
    p=app/'Contents/_CodeSignature/CodeResources';p.parent.mkdir();p.write_bytes(b'fake signature');return self.result(args)
   if '--verify' in args:return self.result(args,0 if (app/'Contents/_CodeSignature/CodeResources').is_file() else 1)
  if args[0]==self.settings['node'] and args[1:]==['--version']:return self.result(args,out=b'v22.22.2\n')
  if args[0]==self.settings['codex']:
   if args[1:]==['login','status']:return self.result(args,0 if self.login else 1)
   if args[1:3]==['app-server','generate-json-schema']:
    (Path(args[-1])/'schema.json').write_text(json.dumps(SCHEMA));return self.result(args)
  raise AssertionError('Unexpected external command: '+args[0])
 def fetch(self,port,path,key=''):
  if len(self.jobs)!=3:raise OSError('simulated controls offline')
  if port==4398:return {'pending':False,'voice':{'state':'idle','speaker_connected':self.connected,'models_ready':True,'audio_frames':20 if self.pcm else 0},'native_voice':None,'realtime_voice':{'active':self.active}}
  if port==4413:return {'codex':{'ready':True}}
  if port in (4417,4418):return {'active':self.active}
  raise AssertionError('Unexpected endpoint')
 def download(self,url,destination):destination.write_bytes(self.archives[url])

class FreshUserSimulation(unittest.TestCase):
 def setUp(self):
  self.real_node=shutil.which('node')
  self.temp=tempfile.TemporaryDirectory(prefix='xiaoai-fresh-');self.addCleanup(self.temp.cleanup)
  base=Path(self.temp.name).resolve();self.root=base/'新用户 workspace/xiaoai-gpt';self.root.mkdir(parents=True);self.home=base/'home 新用户';self.home.mkdir()
  # Copy tracked source only: never inherit developer private files or runtimes.
  source=Path(__file__).resolve().parents[2]
  files=subprocess.check_output(['git','ls-files','-z'],cwd=source).decode().split('\0')
  for name in filter(None,files):
   p=source/name
   if p.is_file():target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  self.fake=FreshMachine(self.root,self.home);stack=contextlib.ExitStack();self.addCleanup(stack.close)
  fake=self.fake
  class ScopedDevice(Device):
   def __init__(self,*args,**kwargs):
    super().__init__(*args,**kwargs);self.socket_dir=fake.osroot/'sockets'/self.journal.data['id'];self.socket=self.socket_dir/'control'
  # External boundary substitutions only; no lifecycle/config/dependency helper mocks.
  stack.enter_context(patch.object(cli,'Device',ScopedDevice))
  stack.enter_context(patch.object(cli,'run',fake.run))
  stack.enter_context(patch.object(environment,'port_open',lambda _:fake.busy_ports))
  stack.enter_context(patch.object(cli,'port_open',lambda _:fake.busy_ports))
  # check_ports captures its probe as a default argument: emulate the socket API.
  socket_mock=MockSocket(fake)
  stack.enter_context(patch.object(environment.socket,'socket',return_value=socket_mock))
  stack.enter_context(patch.object(environment.shutil,'which',lambda name:str(fake.bin/name) if (fake.bin/name).exists() else None))
  stack.enter_context(patch.object(environment.platform,'system',return_value='Darwin'))
  stack.enter_context(patch.object(environment.platform,'machine',return_value='arm64'))
  stack.enter_context(patch.object(environment.platform,'mac_ver',return_value=('15.0.1',('','',''),'arm64')))
  stack.enter_context(patch.object(resources,'_download',fake.download))
  stack.enter_context(patch.object(lifecycle,'fetch_json',fake.fetch))
  # readiness captures fetch_json as a default too; preserve real function body.
  original=lifecycle.readiness
  stack.enter_context(patch.object(cli,'readiness',lambda j:original(j,fake.fetch)))
  stack.enter_context(patch.object(lifecycle,'readiness',lambda j:original(j,fake.fetch)))
 def command(self,command='install',interactive=True,omit_node=False):
  args=[command,'--json']
  if not interactive:args.append('--non-interactive')
  if command=='install':
   for name,value in self.fake.settings.items():
    if name=='node' and omit_node:continue
    args += ['--'+name.replace('_','-'),value]
  out=io.StringIO()
  with contextlib.redirect_stdout(out),patch.object(sys.stdin,'isatty',return_value=interactive):code=cli.main(args,root=self.root,home=self.home)
  return code,json.loads(out.getvalue())
 def test_fresh_install_stop_start_uninstall_reinstall(self):
  before={p:(self.root/'config'/p).read_bytes() for p in ('assistant.json','wake-words.json','voice-commands.json')}
  code,report=self.command();self.assertEqual(code,0,report);self.assertTrue(report['pcm_received']);self.assertFalse(report['conversation_verified']);self.assertEqual(len(self.fake.jobs),3)
  state=Journal(self.root,self.home).data;key=state['key']
  self.assertEqual(self.command()[0],0)
  self.assertEqual(self.command('stop')[0],0);self.assertFalse(self.fake.jobs)
  self.assertEqual(self.command('start')[0],0)
  self.assertEqual(self.command('stop')[0],0)
  code,report=self.command('uninstall');self.assertEqual(code,0,report);self.assertEqual((self.fake.data/'server.txt').read_bytes(),self.fake.initial_route);self.assertEqual((self.fake.remote_home/'.ssh/authorized_keys').read_bytes(),self.fake.initial_keys)
  code,report=self.command();self.assertEqual(code,0,report);self.assertEqual(Journal(self.root,self.home).data['key'],key)
  self.assertEqual({p:(self.root/'config'/p).read_bytes() for p in before},before)
 def test_generated_configuration_passes_real_node_validators(self):
  if not self.real_node:self.skipTest('Node validation runs in the separate Node CI job')
  code,report=self.command();self.assertEqual(code,0,report)
  source=lambda name:json.dumps((self.root/name).as_uri())
  script=f"import {{loadConfig}} from {source('mac/codex-service/config.mjs')}; import {{loadRuntime}} from {source('mac/runtime-config.mjs')}; import {{loadSpeakers}} from {source('deploy/bridge/speakers.mjs')}; import {{loadPreset}} from {source('mac/codex-service/preset.mjs')}; loadConfig();loadRuntime({json.dumps(str(self.root))});loadSpeakers();loadPreset();console.log('CONFIG_VALID');"
  env={**os.environ,'SPEAKERS_CONFIG':str(self.root/'mac/installer/private/speakers.json')}
  result=subprocess.run([self.real_node,'--input-type=module','-e',script],env=env,capture_output=True,text=True,timeout=10)
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'CONFIG_VALID')
 def test_pip_installation_never_falls_back_to_native_builds(self):
  code,report=self.command();self.assertEqual(code,0,report)
  installs=[args for args in self.fake.calls if args[1:4]==['-m','pip','install']]
  self.assertEqual(len(installs),2)
  self.assertTrue(all('--only-binary=:all:' in args for args in installs))
 def test_failed_dependency_install_can_resume(self):
  self.fake.fail_pip=True;code,report=self.command();self.assertEqual(code,1);self.assertEqual(report['error'],'pinned_dependency_install_failed')
  self.assertFalse(self.fake.jobs);self.assertEqual((self.fake.data/'server.txt').read_bytes(),self.fake.initial_route)
  code,report=self.command();self.assertEqual(code,0,report)
 def test_occupied_ports_block_without_device_access(self):
  self.fake.busy_ports=True;code,report=self.command();self.assertEqual(code,1,report);self.assertEqual(report['error'],'ports_in_use_preserve_existing_service');self.assertFalse(any(c[0]=='ssh' for c in self.fake.calls))
 def test_missing_login_blocks_before_device_access(self):
  self.fake.login=False;code,report=self.command();self.assertEqual(code,1,report);self.assertEqual(report['error'],'codex_login_required_complete_in_terminal');self.assertFalse(any(c[0]=='ssh' for c in self.fake.calls))

 def test_missing_pcm_restores_previous_device_route(self):
  self.fake.pcm=False;clock=[0]
  def advance(seconds):clock[0]+=max(46,seconds)
  with patch.object(lifecycle.time,'monotonic',side_effect=lambda:clock[0]),patch.object(lifecycle.time,'sleep',side_effect=advance):
   code,report=self.command()
  self.assertEqual(code,1,report);self.assertEqual(report['error'],'speaker_or_services_not_ready')
  self.assertFalse(self.fake.jobs);self.assertEqual((self.fake.data/'server.txt').read_bytes(),self.fake.initial_route)
  self.assertEqual((self.fake.remote_home/'.ssh/authorized_keys').read_bytes(),self.fake.initial_keys)
 def test_active_conversation_prevents_stop_and_uninstall(self):
  code,report=self.command();self.assertEqual(code,0,report);self.fake.active=True
  for action in ('stop','uninstall'):
   code,report=self.command(action);self.assertEqual(code,1,report);self.assertEqual(report['error'],'end_conversation_first');self.assertEqual(len(self.fake.jobs),3)

 def test_first_use_requires_fingerprint_then_can_continue(self):
  code,report=self.command(interactive=False);self.assertEqual(code,1,report);self.assertEqual(report['error'],'device_interactive_auth_required')
  self.assertFalse(self.fake.jobs);self.assertEqual((self.fake.data/'server.txt').read_bytes(),self.fake.initial_route)
  code,report=self.command(interactive=True);self.assertEqual(code,0,report)
 def test_missing_node_is_prepared_through_existing_brew(self):
  (self.fake.bin/'node').unlink();(self.fake.bin/'brew').write_bytes(b'fake brew');(self.fake.bin/'brew').chmod(0o700)
  code,report=self.command('doctor');self.assertEqual(code,1,report)
  code,report=self.command(omit_node=True);self.assertEqual(code,0,report)
  self.assertTrue(any(c[1:]==['install','node@22'] for c in self.fake.calls))
 def test_interruption_after_remote_route_write_resumes(self):
  self.fake.interrupt_route=True;code,report=self.command();self.assertEqual(code,1,report);self.assertEqual(report['error'],'interrupted_resume_same_checkout')
  self.assertNotEqual((self.fake.data/'server.txt').read_bytes(),self.fake.initial_route)
  code,report=self.command();self.assertEqual(code,0,report);self.assertTrue(report['installed'])

class MockSocket:
 def __init__(self,fake):self.fake=fake
 def __enter__(self):return self
 def __exit__(self,*_):pass
 def settimeout(self,_):pass
 def connect_ex(self,_):return 0 if self.fake.busy_ports else 111

class BootstrapSimulation(unittest.TestCase):
 def test_readonly_commands_never_download_python_with_leading_flags(self):
  with tempfile.TemporaryDirectory(prefix='xiaoai-bootstrap-') as directory:
   root=Path(directory);binary=root/'bin';binary.mkdir();(binary/'dirname').symlink_to('/usr/bin/dirname')
   log=root/'uv.log';uv=binary/'uv'
   uv.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$SIM_UV_LOG"\nif [ "$1" = run ]; then exit 42; fi\nexit 1\n');uv.chmod(0o700)
   script=Path(__file__).resolve().parents[2]/'install.sh'
   for args in [('doctor',),('--json','doctor'),('--non-interactive','--json','status'),('--settings','doctor','--json','verify'),('install','--help')]:
    with self.subTest(args=args):
     log.unlink(missing_ok=True)
     result=subprocess.run(['/bin/bash',str(script),*args],env={'PATH':str(binary),'HOME':str(root),'SIM_UV_LOG':str(log)},capture_output=True,text=True,timeout=5)
     self.assertNotIn('run --no-project',log.read_text());self.assertEqual(result.returncode,1)
     self.assertEqual(json.loads(result.stdout)['error'],'python_3_12_not_cached')

if __name__=='__main__':unittest.main()
