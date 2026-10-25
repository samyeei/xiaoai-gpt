"""Agent-facing install lifecycle. Never serialize raw settings or exception text."""
import argparse, ipaddress, json, os, re, secrets, subprocess, sys
from pathlib import Path
from .core import InstallError, Journal, validate_settings, private_dir, atomic, encoded_json
from .environment import validate_platform, check_ports, discover, dependencies, make_runtime, port_open
from .lifecycle import configure, install_jobs, launch, labels, readiness, require_idle, await_ready
from .resources import prepare_models, ResourceError
from .device import Device

HINTS={
 'requires_apple_silicon_macos':'Use an Apple Silicon Mac for this installer. Other platforms are not supported yet.',
 'node_22_required_install_node_or_homebrew':'Install Node.js 22+ or Homebrew, then retry.',
 'codex_client_required_install_and_login':'Install the Codex client, sign in locally, then retry.',
 'codex_login_required_complete_in_terminal':'Complete your own Codex login in a trusted local terminal, then retry.',
 'device_interactive_auth_required':'Run ./install.sh install in a local terminal to verify the speaker fingerprint and enter its password.',
 'private_ipv4_required':'Supply --speaker and --mac-ip with your own distinct private LAN IPv4 addresses.',
 'ports_in_use_preserve_existing_service':'Existing service detected. Preserve it; inspect ownership before installing a second stack.',
 'end_conversation_first':'End the current conversation before stopping or uninstalling.',
 'speaker_or_services_not_ready':'Inspect private local service logs, network permissions and the installed speaker client protocol. Do not claim audio acceptance.',
 'pinned_dependency_install_failed':'A pinned dependency could not install. Check its platform/wheel availability locally; do not silently upgrade media packages.',
}

def run(args,input=None,interactive=False,timeout=30):
 try:
  return subprocess.run(args,input=input,stdout=None if interactive else subprocess.PIPE,stderr=None if interactive else subprocess.PIPE,timeout=timeout,check=False)
 except (OSError,subprocess.SubprocessError):raise InstallError('external_command_failed') from None

def infer_mac_ip(speaker):
 try:
  ipaddress.IPv4Address(speaker)
  result=run(['/sbin/route','-n','get',speaker])
  if result.returncode:return None
  interface=re.search(r'^\s*interface:\s*([A-Za-z][A-Za-z0-9_.-]{0,31})\s*$',result.stdout.decode(),re.M)
  if not interface:return None
  address=run(['/usr/sbin/ipconfig','getifaddr',interface[1]]).stdout.decode().strip()
  validate_settings({'speaker':speaker,'mac_ip':address})
  return address
 except (InstallError,ValueError):return None

def settings_for(args,j):
 result=dict(j.data.get('settings',{}))
 if args.settings:
  p=Path(args.settings)
  if p.is_symlink() or p.stat().st_mode&0o077:raise InstallError('settings_file_must_be_private')
  value=json.loads(p.read_text())
  if not isinstance(value,dict):raise InstallError('invalid_settings_file')
  result.update(value)
 for k,arg in [('speaker',args.speaker),('mac_ip',args.mac_ip),('node',args.node),('codex',args.codex)]:
  if arg:result[k]=arg
 if args.command=='install':
  for key,prompt in [('speaker','Speaker LAN IPv4 / 音箱IP: '),('mac_ip','Mac LAN IPv4 / Mac IP: ')]:
   if key=='mac_ip' and key not in result:
    inferred=infer_mac_ip(result.get('speaker',''))
    if inferred:result[key]=inferred
   if key not in result:
    if args.non_interactive or not sys.stdin.isatty():raise InstallError('private_ipv4_required')
    result[key]=input(prompt).strip()
  validate_settings(result)
 return result

def loaded_jobs(j):
 domain='gui/'+str(os.getuid())
 return [label for label in labels(j).values() if run(['/bin/launchctl','print',domain+'/'+label]).returncode==0]

def initial_conflicts(j):
 # Do not begin a transaction that would overwrite existing local identities.
 for relative in ('mac/codex-service/private/config.json','mac/installer/private/runtime.json','mac/installer/private/speakers.json','deploy/config/bridge.json','mac/unified-service/private/realtime-voice.json','mac/unified-service/private/asr-wake.json','mac/realtime-voice/private/player.json'):
  p=j.root/relative
  if (p.exists() or p.is_symlink()) and str(p) not in j.data['files']:raise InstallError('existing_file_requires_manual_migration')

def restore_attempt(j,device):
 # Check all conflicts first, and leave recovery material intact on any failure.
 j.check_rollback()
 if j.data.get('device',{}).get('key_line'):device.check_restore()
 # Missing health is not proof of inactivity. Preserve an uncertain live call.
 jobs=loaded_jobs(j)
 if jobs:require_idle(j)
 elif j.data.get('services_started'):
  if any(port_open(p) for p in (4398,4399,4400,4411,4412,4413,4417,4418,4419)):
   raise InstallError('cannot_confirm_owned_services_idle')
 backup=j.directory/'backups';private_dir(backup)
 atomic(backup/(secrets.token_hex(12)+'.json'),encoded_json(j.data))
 if jobs:launch(j,run,False)
 if j.data.get('device',{}).get('key_line'):device.restore()
 j.rollback();j.data.pop('services_started',None);j.data.pop('device',None);j.data.pop('recovery_required',None);j.save()

def perform(args,root,home):
 state_path=root/'mac/installer/private/state.json'
 if args.command in ('status','verify'):
  if not state_path.exists():return {'ok':True,'installed':False,'services_ready':False,'connected':False,'conversation_verified':False}
  j=Journal(root,home);return {'ok':True,'installed':bool(j.data['installed']),'phase':j.data['steps'][-1] if j.data['steps'] else 'not_started','recovery_required':bool(j.data.get('recovery_required')),**readiness(j)}
 if args.command=='doctor':
  validate_platform();options=settings_for(args,Journal(root,home));discover(options,run)
  return {'ok':True,'platform_supported':True,'codex_protocol_supported':True,'ports_available':not any(port_open(p) for p in (4398,4399,4400,4411,4412,4413,4417,4418,4419)),'installed':state_path.exists(),'conversation_verified':False}
 validate_platform();j=Journal(root,home)
 if args.command!='install' and not state_path.exists():raise InstallError('no_owned_installation')
 with j.lock():
  settings=settings_for(args,j)
  if args.command=='install':
   if j.data['installed']:
    if settings!=j.data['settings']:raise InstallError('installed_settings_change_requires_migration')
    if not readiness(j)['services_ready']:
     if loaded_jobs(j):raise InstallError('partial_service_failure_inspect_private_logs')
     check_ports();j.check_rollback();j.data['services_started']=True;j.save();launch(j,run,True)
    return {'ok':True,'installed':True,**await_ready(j)}
   if j.data.get('settings') and settings!=j.data['settings']:raise InstallError('resume_requires_original_settings')
   initial_conflicts(j)
   # An interrupted activation must be restored before reattempting.
   if j.data.get('services_started') or j.data.get('device',{}).get('route_write_intent'):
    if j.data.get('services_started'):
     j.check_rollback();launch(j,run,True)
    device=Device(j,settings,run);device.connect(interactive=not args.non_interactive and sys.stdin.isatty());restore_attempt(j,device)
   check_ports()
   resolved=discover(settings,run,install=True);j.data['settings']=resolved;j.save();device=Device(j,resolved,run)
   try:
    device.connect(interactive=not args.non_interactive and sys.stdin.isatty());device.prepare();j.step('device_snapshot')
    dependencies(j,run);prepare_models(root);j.step('models')
    runtime=make_runtime(j,resolved['node'],run);configure(j,{**resolved,'node':runtime});install_jobs(j,{**resolved,'node':runtime})
    # Durable intent permits cleanup even if launchctl is interrupted mid-start.
    j.data['services_started']=True;j.save();launch(j,run,True);device.activate();j.step('device_route')
    report=await_ready(j);j.data['installed']=True;j.step('installed')
    return {'ok':True,'installed':True,**report,'human_check':'Confirm tones, one question, a follow-up and spoken exit. Health is not proof of audible conversation.'}
   except (InstallError,ResourceError):
    try:restore_attempt(j,device)
    except Exception:j.data['recovery_required']=True;j.save();raise InstallError('installation_failed_recovery_required_use_same_checkout') from None
    raise
   finally:
    try:device.close()
    except Exception:pass
  if args.command=='start':
   if not j.data['installed']:raise InstallError('installation_not_complete_run_install')
   loaded=loaded_jobs(j)
   if len(loaded)==3:return {'ok':True,'installed':True,**await_ready(j)}
   if loaded:raise InstallError('partial_service_failure_inspect_private_logs')
   check_ports();j.check_rollback();j.data['services_started']=True;j.save();launch(j,run,True);return {'ok':True,'installed':True,**await_ready(j)}
  if args.command=='stop':
   if loaded_jobs(j):require_idle(j);launch(j,run,False)
   j.data['services_started']=False;j.save()
   return {'ok':True,'stopped':True,'installed':bool(j.data['installed'])}
  if args.command=='uninstall':
   if not j.data['installed'] and not j.data['files'] and not j.data.get('device'):
    return {'ok':True,'installed':False,'already_uninstalled':True}
   if loaded_jobs(j):require_idle(j)
   device=Device(j,settings,run);device.connect(interactive=not args.non_interactive and sys.stdin.isatty());restore_attempt(j,device);device.close()
   return {'ok':True,'installed':False,'restored':True,'private_backups_and_dependencies_retained':True}
 raise InstallError('unsupported_command')

def main(argv=None,root=None,home=None):
 parser=argparse.ArgumentParser(description='Xiaoai GPT Mac installer / 安装向导')
 parser.add_argument('command',nargs='?',default='install',choices=['doctor','install','status','verify','start','stop','uninstall'])
 for option in ('speaker','mac-ip','node','codex','settings'):parser.add_argument('--'+option)
 parser.add_argument('--non-interactive',action='store_true');parser.add_argument('--json',action='store_true')
 args=parser.parse_args(argv)
 root=Path(root or Path(__file__).resolve().parents[2]).resolve();home=Path(home or Path.home()).resolve()
 try:result=perform(args,root,home)
 except (InstallError,ResourceError) as error:
  code=str(error)
  # Fixed code only; no raw subprocess failures, addresses, settings or secrets.
  if not code.replace('_','').isalnum() or len(code)>120:code='installer_step_failed'
  result={'ok':False,'error':code,'hint':HINTS.get(code,'Inspect this step locally with your agent. Preserve private recovery files; do not post raw logs.'),'conversation_verified':False}
 except (OSError,ValueError,KeyError):result={'ok':False,'error':'invalid_local_state_or_input','conversation_verified':False}
 except KeyboardInterrupt:result={'ok':False,'error':'interrupted_resume_same_checkout','conversation_verified':False}
 except Exception:result={'ok':False,'error':'installer_internal_error_preserve_recovery_state','conversation_verified':False}
 print(json.dumps(result,ensure_ascii=False));return 0 if result.get('ok') else 1
