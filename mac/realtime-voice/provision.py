"""Provision one command-restricted player key through the task's SSH mux."""
import asyncio,base64,json,os,re,subprocess
from pathlib import Path
from player import PlayerConfig
FORCED='command="aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty'
def authorized_line(public):
 if '\n' in public or '\r' in public:raise ValueError('Invalid public key')
 fields=public.strip().split()
 if len(fields)<2 or fields[0]!='ssh-rsa' or not re.fullmatch(r'[A-Za-z0-9+/=]{8,8192}',fields[1]):raise ValueError('Invalid public key')
 try:base64.b64decode(fields[1],validate=True)
 except Exception:raise ValueError('Invalid public key') from None
 return FORCED+' '+fields[0]+' '+fields[1]+' xiaoai-realtime-voice'
INSTALL='''set -eu
umask 077
IFS= read -r task_line
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
task_auth="$HOME/.ssh/authorized_keys"
touch "$task_auth"
chmod 600 "$task_auth"
cp -p "$task_auth" "$task_auth.xiaoai-backup-$(date +%Y%m%d%H%M%S)"
if grep -Fqx "$task_line" "$task_auth"; then printf 'EXISTING\\n'; else
 if [ -s "$task_auth" ] && [ "$(tail -c1 "$task_auth")" ]; then printf '\\n' >> "$task_auth"; fi
 printf '%s\\n' "$task_line" >> "$task_auth"
 printf 'ADDED\\n'
fi
'''
REMOVE='''set -eu
IFS= read -r task_line
task_auth="$HOME/.ssh/authorized_keys"
task_tmp="$task_auth.xiaoai-remove.$$"
umask 077
awk -v k="$task_line" '$0 != k' "$task_auth" > "$task_tmp"
cat "$task_tmp" > "$task_auth"
rm -f "$task_tmp"
'''
async def provision(root):
 root=Path(root).resolve();diagnostic=PlayerConfig(root,'diagnostic');await diagnostic.preflight()
 writable=subprocess.run(diagnostic.command()[:-1]+['test -w "$HOME"'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,check=False)
 if writable.returncode:raise RuntimeError('音箱密钥目录位于只读固件，保留诊断连接；未修改固件。')
 private=root/'mac/realtime-voice/private';private.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(private,0o700);key=private/'device_rsa'
 if not key.exists():subprocess.run(['ssh-keygen','-q','-t','rsa','-b','3072','-N','','-C','xiaoai-realtime-voice','-f',str(key)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 os.chmod(key,0o600);line=authorized_line(key.with_suffix('.pub').read_text().strip())
 def remote(script):
  result=subprocess.run(diagnostic.command()[:-1]+[script],input=(line+'\n').encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=8,check=False)
  if result.returncode:raise RuntimeError('Device key update failed')
  return result.stdout
 installed=remote(INSTALL)
 if installed not in (b'ADDED\n',b'EXISTING\n'):raise RuntimeError('Device update unconfirmed')
 try:
  managed=PlayerConfig(root,'managed');await managed.preflight()
  restriction=subprocess.run(managed.command()[:-1]+['printf XIAOAI_PERMISSION_PROBE'],input=bytes(3840),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=8,check=False)
  if restriction.returncode!=0 or restriction.stdout:raise RuntimeError('Forced player command not enforced')
 except BaseException:
  if installed==b'ADDED\n':remote(REMOVE)
  raise RuntimeError('Device rejected restricted player key; candidate entry removed') from None
 config=private/'player.json';config.write_text(json.dumps({'mode':'managed'}));os.chmod(config,0o600)
 return {'managed_player_auth_verified':True,'private_key_printed':False,'restricted_command_verified_by_playback':True}
