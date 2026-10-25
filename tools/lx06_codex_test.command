#!/bin/bash
# Bounded Codex voice cutover; original address remains on the speaker.
set -euo pipefail
umask 077
task_root="$(cd "$(dirname "$0")/.." && pwd)"
mode="${1:-switch}"
case "$mode" in switch|rollback) ;; *) echo 'Usage: switch | rollback'; exit 2;; esac
if [ "$mode" = switch ]; then
  test "$(/usr/sbin/ipconfig getifaddr en0)" = 192.168.100.106
  "$HOME/.local/bin/node" --input-type=module - "$task_root" <<'JS'
import {readFileSync} from 'node:fs';
const root=process.argv[2],c=JSON.parse(readFileSync(root+'/mac/codex-service/private/config.json'));
const r=await fetch('http://127.0.0.1:4413/status',{headers:{Authorization:'Bearer '+c.admin_key},signal:AbortSignal.timeout(5000)});
if(!r.ok)throw Error('Mac manager unavailable');
const s=await r.json();
if(!s.codex?.ready||s.codex.pending||s.codex.waiting_user||!s.voice?.voice?.models_ready)throw Error('Codex or voice not idle/ready');
console.log('Mac Codex 与语音模型就绪。');
JS
fi
init_hash="$(shasum -a 256 "$task_root/.codex-runs/lx06-backups/backup.WQdJ2S/open-xiaoai-init.sh" | awk '{print $1}')"
echo '密码只在本机终端输入。此操作只切换连接地址并重新启动现有音箱客户端。'
ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=$task_root/.codex-runs/lx06-known-hosts" \
  -o HostKeyAlgorithms=+ssh-rsa root@192.168.100.186 \
  "sh -s -- $mode $init_hash" <<'REMOTE'
set -eu
mode="$1"; expected_init="$2"
server=/data/open-xiaoai/server.txt
before=/data/open-xiaoai/server.txt.before-mac-codex-20261007
target=ws://192.168.100.106:4399
expected_before=fe3f0966307bae363db7930de3a87355f49380e4ee67991913561dd33e72bf7f
test -x /data/open-xiaoai/client
test -f "$server"
command -v sha256sum >/dev/null
test "$(sha256sum /data/open-xiaoai/init.sh | awk '{print $1}')" = "$expected_init"
if [ "$mode" = switch ]; then
  if [ "$(cat "$server")" != "$target" ]; then
    test "$(sha256sum "$server" | awk '{print $1}')" = "$expected_before"
    if [ ! -e "$before" ]; then cp -p "$server" "$before"; fi
  fi
  test "$(sha256sum "$before" | awk '{print $1}')" = "$expected_before"
  cp -p "$server" "$server.mac-test.tmp"
  printf '%s\n' "$target" > "$server.mac-test.tmp"
  mv "$server.mac-test.tmp" "$server"
else
  test "$(sha256sum "$before" | awk '{print $1}')" = "$expected_before"
  test "$(cat "$server")" = "$target"
  cp -p "$before" "$server.mac-test.tmp"
  mv "$server.mac-test.tmp" "$server"
fi
# BusyBox firmware lacks nohup. Ignoring HUP survives exec and SSH logout.
sh -c 'trap "" HUP; exec sh /data/open-xiaoai/init.sh' > /tmp/mac-codex-client.log 2>&1 < /dev/null &
printf '连接地址操作完成：%s；等待 Mac 检查实际连接。\n' "$mode"
REMOTE
