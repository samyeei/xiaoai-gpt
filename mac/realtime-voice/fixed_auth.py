"""Preserve firmware keys while binding a single project-owned player key file."""
import asyncio,json,subprocess
from pathlib import Path
from player import PlayerConfig
from provision import authorized_line
from persistent_auth import remote,validate_hook,HOOK,STARTUP as ROOT_STARTUP
SOURCE='/xiaoai-voice-auth/authorized_keys'
GATE=r'''set -eu
task_source=$(awk '$5=="/etc/dropbear/authorized_keys" {print $4}' /proc/self/mountinfo)
if [ -n "$task_source" ]; then
 test "$task_source" = '/xiaoai-voice-auth/authorized_keys'
 printf OWN_MOUNT
else
 test -f /etc/dropbear/authorized_keys
 printf ORIGINAL
fi
'''
SETUP=r'''set -eu
umask 077
IFS= read -r task_line
task_dir=/data/xiaoai-voice-auth
mkdir -p "$task_dir"
chmod 700 "$task_dir"
if [ -e "$task_dir/original-authorized_keys" ]; then
 cmp -s /etc/dropbear/authorized_keys "$task_dir/original-authorized_keys"
else
 cp -p /etc/dropbear/authorized_keys "$task_dir/original-authorized_keys"
 chmod 600 "$task_dir/original-authorized_keys"
fi
sha256sum "$task_dir/original-authorized_keys" | awk '{print $1}' > "$task_dir/original.sha256"
# Build the exact candidate, preserve every original byte, and refuse foreign edits.
task_tmp="$task_dir/authorized_keys.candidate"
cat "$task_dir/original-authorized_keys" > "$task_tmp"
if ! grep -Fqx "$task_line" "$task_tmp"; then
 if [ -s "$task_tmp" ] && [ "$(tail -c1 "$task_tmp")" ]; then printf '\n' >> "$task_tmp"; fi
 printf '%s\n' "$task_line" >> "$task_tmp"
fi
if [ -e "$task_dir/authorized_keys" ]; then
 cmp -s "$task_tmp" "$task_dir/authorized_keys"
 rm "$task_tmp"
else
 mv "$task_tmp" "$task_dir/authorized_keys"
fi
chmod 600 "$task_dir/authorized_keys" "$task_dir/original.sha256"
'''
STARTUP=r'''#!/bin/sh
# xiaoai-voice-auth v2: preserve firmware keys; bind only one key file
set -eu
umask 077
task_dir=/data/xiaoai-voice-auth
mkdir /tmp/xiaoai-voice-auth-start.lock 2>/dev/null || exit 0
trap 'rmdir /tmp/xiaoai-voice-auth-start.lock' EXIT HUP INT TERM
task_source=$(awk '$5=="/etc/dropbear/authorized_keys" {print $4}' /proc/self/mountinfo)
if [ -n "$task_source" ]; then
 test "$task_source" = '/xiaoai-voice-auth/authorized_keys'
else
 task_hash=$(sha256sum /etc/dropbear/authorized_keys | awk '{print $1}')
 test "$task_hash" = "$(cat "$task_dir/original.sha256")"
 test -s "$task_dir/authorized_keys"
 mount -o bind "$task_dir/authorized_keys" /etc/dropbear/authorized_keys
fi
'''+'# Adopt the already-running'+ROOT_STARTUP.split('# Adopt the already-running',1)[1]
ROLLBACK=r'''#!/bin/sh
# xiaoai-voice-auth v2 rollback; retain client and original firmware
set -eu
task_source=$(awk '$5=="/etc/dropbear/authorized_keys" {print $4}' /proc/self/mountinfo)
if [ "$task_source" = '/xiaoai-voice-auth/authorized_keys' ]; then
 cd /; umount /etc/dropbear/authorized_keys
fi
if [ -f /data/init.sh ] && cmp -s /data/init.sh /data/xiaoai-voice-auth/init-hook.sh; then
 mv /data/init.sh /data/xiaoai-voice-auth/init-hook.disabled
fi
'''
async def install(root):
 root=Path(root).resolve();private=root/'mac/realtime-voice/private'
 line=authorized_line((private/'device_rsa.pub').read_text().strip())
 gate=remote(root,GATE).decode()
 if gate not in ('ORIGINAL','OWN_MOUNT'):raise RuntimeError('Key file mount unconfirmed')
 hook=remote(root,'if [ -e /data/init.sh ]; then cat /data/init.sh; fi').decode()
 validate_hook(hook if hook else None)
 mounted=False
 try:
  if gate=='ORIGINAL':
   remote(root,SETUP,(line+'\n').encode())
   remote(root,'mount -o bind /data/xiaoai-voice-auth/authorized_keys /etc/dropbear/authorized_keys');mounted=True
  else:
   remote(root,'cmp -s /etc/dropbear/authorized_keys /data/xiaoai-voice-auth/authorized_keys')
  managed=PlayerConfig(root,'managed');await managed.preflight()
  p=subprocess.run(managed.command()[:-1]+['printf XIAOAI_PERMISSION_PROBE'],input=bytes(3840),capture_output=True,timeout=8)
  if p.returncode or p.stdout:raise RuntimeError('Forced command not verified')
  for name,body in [('start.sh',STARTUP),('init-hook.sh',HOOK),('rollback.sh',ROLLBACK)]:
   remote(root,f'set -eu; umask 077; cat > /data/xiaoai-voice-auth/{name}; chmod 700 /data/xiaoai-voice-auth/{name}',body.encode())
  remote(root,'set -eu; if [ -e /data/init.sh ]; then cmp -s /data/init.sh /data/xiaoai-voice-auth/init-hook.sh; else cp /data/xiaoai-voice-auth/init-hook.sh /data/init.sh; chmod 700 /data/init.sh; fi')
  remote(root,'set -eu; sh /data/xiaoai-voice-auth/start.sh; sh /data/xiaoai-voice-auth/start.sh')
 except BaseException:
  if not hook:remote(root,'if [ -f /data/init.sh ] && cmp -s /data/init.sh /data/xiaoai-voice-auth/init-hook.sh; then mv /data/init.sh /data/xiaoai-voice-auth/init-hook.failed; fi')
  if mounted:remote(root,'cd /; umount /etc/dropbear/authorized_keys')
  raise
 p=private/'player.json';p.write_text(json.dumps({'mode':'managed'}));p.chmod(0o600)
 report=dict(managed_player_auth_verified=True,forced_command_verified=True,original_keys_preserved=True,diagnostic_mux_used_for_player=False,startup_hook_installed=True,startup_idempotence_exercised=True,device_reboot_tested=False,rollback='/data/xiaoai-voice-auth/rollback.sh')
 (root/'.codex-runs/luka-continuous/persistent-player-auth.json').write_text(json.dumps(report,indent=2))
 return report
if __name__=='__main__':print(json.dumps(asyncio.run(install(Path(__file__).resolve().parents[2]))))
