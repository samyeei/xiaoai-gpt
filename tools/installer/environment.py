"""Bounded local prerequisites and separately owned runtimes; no account output."""
import json, os, platform, plistlib, shutil, socket, subprocess, sys, tempfile
from pathlib import Path
from .core import InstallError, private_dir, sha
PORTS=(4398,4399,4400,4411,4412,4413,4417,4418,4419)
def validate_platform(system=None,machine=None):
 if (system or platform.system())!='Darwin' or (machine or platform.machine())!='arm64':raise InstallError('requires_apple_silicon_macos')
 if sys.version_info[:2]!=(3,12):raise InstallError('requires_python_3_12')

def port_open(port):
 with socket.socket() as s:
  s.settimeout(.15);return s.connect_ex(('127.0.0.1',port))==0

def check_ports(probe=port_open):
 if any(probe(p) for p in PORTS):raise InstallError('ports_in_use_preserve_existing_service')

def schema_support(text):
 try:document=json.loads(text) if isinstance(text,str) else text
 except (ValueError,TypeError):return False
 if not isinstance(document,dict):return False
 definitions=document.get('definitions',{})
 if not isinstance(definitions,dict):return False
 def nodes(value):
  if isinstance(value,dict):
   yield value
   for child in value.values():yield from nodes(child)
  elif isinstance(value,list):
   for child in value:yield from nodes(child)
 def resolved(property_schema):
  for item in nodes(property_schema):
   reference=item.get('$ref')
   if isinstance(reference,str) and reference.startswith('#/definitions/'):
    target=definitions.get(reference.removeprefix('#/definitions/'))
    if isinstance(target,dict):yield target
 def enum_contains(schema,value):
  return any(value in item.get('enum',[]) for item in nodes(schema) if isinstance(item.get('enum'),list))
 for request in nodes(document):
  properties=request.get('properties')
  if not isinstance(properties,dict) or not enum_contains(properties.get('method',{}),'thread/realtime/start'):continue
  for params in resolved(properties.get('params',{})):
   fields=params.get('properties',{})
   if not isinstance(fields,dict) or not all(name in fields for name in ('version','transport','voice')):continue
   if not any(enum_contains(value,'v3') for value in resolved(fields['version'])):continue
   if not any(enum_contains(value,'webrtc') and any('sdp' in item.get('properties',{}) for item in nodes(value) if isinstance(item.get('properties'),dict)) for value in resolved(fields['transport'])):continue
   if not any(any(isinstance(item.get('enum'),list) and item['enum'] for item in nodes(value)) for value in resolved(fields['voice'])):continue
   return True
 return False

def discover(settings,run,install=False):
 node=settings.get('node') or shutil.which('node')
 if not node:
  brew=shutil.which('brew')
  if install and brew:
   if run([brew,'install','node@22'],timeout=1200).returncode:raise InstallError('node_install_failed')
   prefix=run([brew,'--prefix','node@22']).stdout.decode().strip();node=str(Path(prefix)/'bin/node')
  else:raise InstallError('node_22_required_install_node_or_homebrew')
 codex=settings.get('codex') or shutil.which('codex')
 if not codex:
  app=Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')
  if app.is_file():codex=str(app)
 if not codex:raise InstallError('codex_client_required_install_and_login')
 for path in (node,codex):
  if not Path(path).is_absolute() or not os.access(path,os.X_OK):raise InstallError('executable_unavailable')
 version=run([node,'--version']).stdout.decode().strip()
 try:major=int(version.lstrip('v').split('.')[0])
 except ValueError:raise InstallError('node_version_unavailable') from None
 if major<22:raise InstallError('node_22_or_later_required')
 if run([codex,'login','status'],timeout=15).returncode:raise InstallError('codex_login_required_complete_in_terminal')
 with tempfile.TemporaryDirectory(prefix='xiaoai-schema-') as folder:
  if run([codex,'app-server','generate-json-schema','--experimental','--out',folder],timeout=30).returncode:raise InstallError('codex_experimental_schema_unavailable')
  if not any(schema_support(p.read_text()) for p in Path(folder).rglob('*.json')):raise InstallError('codex_realtime_v3_webrtc_unsupported')
 return {**settings,'node':str(Path(node).resolve()),'codex':str(Path(codex).resolve())}

def dependencies(j,run):
 root=j.root
 for name,requirements in [('mac-voice-env','deploy/voice/requirements.txt'),('realtime-voice-env','mac/realtime-voice/requirements.txt')]:
  env=root/'.codex-runs'/name
  j.allowed(env)
  if env.is_symlink():raise InstallError('foreign_python_environment')
  if not env.exists():
   if name not in j.data.get('environments',[]):j.data.setdefault('environments',[]).append(name);j.save()
   if run([sys.executable,'-m','venv',str(env)],timeout=90).returncode:raise InstallError('python_environment_failed')
  elif name not in j.data.get('environments',[]):raise InstallError('existing_python_environment_requires_migration')
  python=env/'bin/python'
  if not python.exists() and run([sys.executable,'-m','venv',str(env)],timeout=90).returncode:raise InstallError('python_environment_failed')
  if run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(root/requirements)],timeout=1200).returncode:raise InstallError('pinned_dependency_install_failed')
  if run([str(python),'-m','pip','check'],timeout=30).returncode:raise InstallError('dependency_validation_failed')
 modules=root/'deploy/bridge/node_modules';target=modules/'ws'
 if modules.is_symlink():raise InstallError('foreign_node_modules')
 if target.is_symlink() and target.resolve()==(root/'deploy/bridge/vendor/ws').resolve():pass
 elif target.exists() or target.is_symlink():raise InstallError('foreign_ws_dependency')
 else:modules.mkdir(exist_ok=True);target.symlink_to('../vendor/ws')
 j.step('dependencies')

def make_runtime(j,source,run):
 app=j.home/'Applications'/('Xiaoai GPT '+j.data['id']+'.app');binary=app/'Contents/MacOS/node'
 j.allowed(app)
 owned=j.data.get('runtime_bundle')==str(app) or str(binary) in j.data['files']
 if app.exists() and not owned:raise InstallError('foreign_runtime_bundle')
 if owned and binary.exists() and run(['/usr/bin/codesign','--verify','--strict',str(app)]).returncode==0:
  tracked=[(Path(name),record) for name,record in j.data['files'].items() if Path(name).is_relative_to(app)]
  if str(binary) not in j.data['files'] or any(p.is_symlink() or not p.is_file() or sha(p.read_bytes()) not in (record['after'],record.get('pending')) for p,record in tracked):raise InstallError('runtime_bundle_changed_externally')
  return str(binary)
 # Sign only an isolated copy, then journal every signed artifact before promotion.
 with tempfile.TemporaryDirectory(prefix='xiaoai-runtime-') as temp:
  stage=Path(temp)/app.name;(stage/'Contents/MacOS').mkdir(parents=True)
  shutil.copyfile(source,stage/'Contents/MacOS/node');(stage/'Contents/MacOS/node').chmod(0o700)
  info={'CFBundleExecutable':'node','CFBundleIdentifier':'org.xiaoaigpt.'+j.data['id']+'.runtime','CFBundleName':'Xiaoai GPT','CFBundlePackageType':'APPL','CFBundleVersion':'1','LSUIElement':True,'NSLocalNetworkUsageDescription':'Connect to your XiaoAI speaker on the local network.'}
  (stage/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
  result=run(['/usr/bin/codesign','-d','--entitlements',':-',source]);entitlements={}
  try:entitlements=plistlib.loads(result.stdout)
  except Exception:entitlements={'com.apple.security.cs.allow-jit':True}
  entfile=Path(temp)/'entitlements.plist';entfile.write_bytes(plistlib.dumps(entitlements))
  if run(['/usr/bin/codesign','--force','--sign','-','--options','runtime','--entitlements',str(entfile),str(stage)]).returncode:raise InstallError('runtime_signing_failed')
  if not owned:j.data['runtime_bundle']=str(app);j.save()
  for p in stage.rglob('*'):
   if p.is_symlink():raise InstallError('runtime_symlink_refused')
   if p.is_file():j.write(app/p.relative_to(stage),p.read_bytes(),mode=0o700 if p.name=='node' else 0o600)
 if run(['/usr/bin/codesign','--verify','--strict',str(app)]).returncode:raise InstallError('runtime_signature_failed')
 return str(binary)
