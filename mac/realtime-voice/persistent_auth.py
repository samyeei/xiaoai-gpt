"""Fixed-scope, reversible writable player authorization for the LX06."""
import asyncio,json,os,subprocess,time
from pathlib import Path
from player import PlayerConfig
from provision import authorized_line
OWN_SOURCE='/xiaoai-voice-auth/root'
def validate_key_location(location):
 if location!='HOME':raise ValueError('Firmware uses a fixed /etc key path; root binding refused')
def validate_root_state(entries,mount_source):
 if mount_source is not None:
  if mount_source!=OWN_SOURCE:raise ValueError('Another root mount exists')
 elif entries:raise ValueError('Root is not empty')
def validate_hook(existing):
 if existing is not None and existing!=HOOK:raise ValueError('Another startup hook exists')
ROOT_GATE=r'''set -eu
task_source=$(awk '$5=="/root" {print $4}' /proc/self/mountinfo)
if [ -n "$task_source" ]; then
 test "$task_source" = '/xiaoai-voice-auth/root'
 printf 'OWN_MOUNT\n'
else
 test -z "$(ls -A /root)"
 printf 'EMPTY\n'
fi
'''
STARTUP=r'''#!/bin/sh
# xiaoai-voice-auth v1: fixed player key and one existing client
set -eu
umask 077
task_dir=/data/xiaoai-voice-auth
# Prevent two concurrent startup invocations; Linux reboot clears /tmp.
mkdir /tmp/xiaoai-voice-auth-start.lock 2>/dev/null || exit 0
trap 'rmdir /tmp/xiaoai-voice-auth-start.lock' EXIT HUP INT TERM
task_source=$(awk '$5=="/root" {print $4}' /proc/self/mountinfo)
if [ -n "$task_source" ]; then
 test "$task_source" = '/xiaoai-voice-auth/root'
else
 test -z "$(ls -A /root)"
 test -s "$task_dir/root/.ssh/authorized_keys"
 mount -o bind "$task_dir/root" /root
fi
# Adopt the already-running task client, never start a duplicate or kill others.
for task_file in /proc/[0-9]*/cmdline; do
 [ -r "$task_file" ] || continue
 task_args=$(tr '\000' ' ' < "$task_file" 2>/dev/null) || continue
 if [ "$task_args" = '/data/open-xiaoai/client ws://192.168.100.106:4399 ' ]; then
  task_pid=${task_file#/proc/}; task_pid=${task_pid%/cmdline}
  printf '%s\n' "$task_pid" > "$task_dir/client.pid"
  exit 0
 fi
 case "$task_args" in /data/open-xiaoai/client\ *) exit 1;; esac
done
test -x /data/open-xiaoai/client
/data/open-xiaoai/client ws://192.168.100.106:4399 >/dev/null 2>&1 </dev/null &
printf '%s\n' "$!" > "$task_dir/client.pid"
'''
HOOK='#!/bin/sh\n# xiaoai-voice-auth v1 startup hook\nsh /data/xiaoai-voice-auth/start.sh\n'
ROLLBACK=r'''#!/bin/sh
# xiaoai-voice-auth v1 rollback: preserve current client and firmware
set -eu
task_source=$(awk '$5=="/root" {print $4}' /proc/self/mountinfo)
if [ "$task_source" = '/xiaoai-voice-auth/root' ]; then cd /; umount /root; fi
if [ -f /data/init.sh ] && cmp -s /data/init.sh /data/xiaoai-voice-auth/init-hook.sh; then
 mv /data/init.sh /data/xiaoai-voice-auth/init-hook.disabled
fi
'''
def remote(root,script,data=None):
 p=subprocess.run(PlayerConfig(root,'diagnostic').command()[:-1]+[script],input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12)
 if p.returncode:raise RuntimeError('Device operation failed; stopped without overwriting unrelated paths')
 return p.stdout
async def install(root):
 root=Path(root).resolve();private=root/'mac/realtime-voice/private';key=private/'device_rsa'
 if not key.exists():raise RuntimeError('Dedicated key missing')
 location=remote(root,"if strings /usr/sbin/dropbear | grep -Fxq /etc/dropbear/authorized_keys; then printf FIXED_ETC; else printf HOME; fi").decode()
 validate_key_location(location)
 line=authorized_line(key.with_suffix('.pub').read_text().strip())
 gate=remote(root,ROOT_GATE).decode().strip()
 if gate not in ('EMPTY','OWN_MOUNT'):raise RuntimeError('Root gate unconfirmed')
 validate_root_state([],OWN_SOURCE if gate=='OWN_MOUNT' else None)
 hook=remote(root,'if [ -e /data/init.sh ]; then cat /data/init.sh; fi').decode()
 validate_hook(hook if hook else None)
 setup=r'''set -eu
umask 077
IFS= read -r task_line
mkdir -p /data/xiaoai-voice-auth/root/.ssh
chmod 700 /data/xiaoai-voice-auth /data/xiaoai-voice-auth/root /data/xiaoai-voice-auth/root/.ssh
task_auth=/data/xiaoai-voice-auth/root/.ssh/authorized_keys
if [ -s "$task_auth" ]; then
 test "$(cat "$task_auth")" = "$task_line"
fi
printf '%s\n' "$task_line" > "$task_auth"
chmod 600 "$task_auth"
'''
 remote(root,setup,(line+'\n').encode())
 mounted=False
 try:
  if gate=='EMPTY':remote(root,'mount -o bind /data/xiaoai-voice-auth/root /root');mounted=True
  # Both requests create fresh non-multiplexed SSH authentication.
  managed=PlayerConfig(root,'managed');await managed.preflight()
  probe=subprocess.run(managed.command()[:-1]+['printf XIAOAI_PERMISSION_PROBE'],input=bytes(3840),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
  if probe.returncode or probe.stdout:raise RuntimeError('Forced player command unconfirmed')
  # Stage immutable candidate bodies, then refuse to replace any other hook.
  for path,body,mode in [('start.sh',STARTUP,'700'),('init-hook.sh',HOOK,'700'),('rollback.sh',ROLLBACK,'700')]:
   remote(root,f'umask 077; cat > /data/xiaoai-voice-auth/{path}; chmod {mode} /data/xiaoai-voice-auth/{path}',body.encode())
  remote(root,'set -eu; if [ -e /data/init.sh ]; then cmp -s /data/init.sh /data/xiaoai-voice-auth/init-hook.sh; else cp /data/xiaoai-voice-auth/init-hook.sh /data/init.sh; chmod 700 /data/init.sh; fi')
  remote(root,'sh /data/xiaoai-voice-auth/start.sh; sh /data/xiaoai-voice-auth/start.sh')
 except BaseException:
  if not hook:remote(root,'if [ -f /data/init.sh ] && cmp -s /data/init.sh /data/xiaoai-voice-auth/init-hook.sh; then mv /data/init.sh /data/xiaoai-voice-auth/init-hook.failed; fi')
  if mounted:remote(root,'cd /; umount /root')
  raise
 config=private/'player.json';config.write_text(json.dumps({'mode':'managed'}));config.chmod(0o600)
 report={'managed_player_auth_verified':True,'forced_command_verified':True,'diagnostic_mux_used_for_player':False,'root_binding_created':mounted,'startup_hook_installed':True,'startup_idempotence_exercised':True,'device_reboot_tested':False,'private_key_printed':False,'rollback':'/data/xiaoai-voice-auth/rollback.sh'}
 evidence=root/'.codex-runs/luka-continuous/persistent-player-auth.json';evidence.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 return report
if __name__=='__main__':print(json.dumps(asyncio.run(install(Path(__file__).resolve().parents[2])),ensure_ascii=False))
