#!/bin/bash
# Read-only LX06 backup. Enter the speaker password in the local terminal.
set -euo pipefail
umask 077
task_root="$(cd "$(dirname "$0")/.." && pwd)"
backup_root="$task_root/.codex-runs/lx06-backups"
mkdir -p "$backup_root"
chmod 700 "$backup_root"
backup_dir="$(mktemp -d "$backup_root/backup.XXXXXX")"
socket_dir="$(mktemp -d "$backup_root/socket.XXXXXX")"
options=(-o ConnectTimeout=8 -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$task_root/.codex-runs/lx06-known-hosts"
  -o HostKeyAlgorithms=+ssh-rsa -o ControlMaster=auto
  -o ControlPersist=60 -o "ControlPath=$socket_dir/control")
cleanup() {
  ssh "${options[@]}" -O exit root@192.168.100.186 >/dev/null 2>&1 || true
  rmdir "$socket_dir" 2>/dev/null || true
}
trap cleanup EXIT
printf '只读取音箱配置，不修改地址或重启。密码请在本终端输入。\n'
ssh "${options[@]}" root@192.168.100.186 \
  'cat /data/open-xiaoai/server.txt' > "$backup_dir/server.txt"
test -s "$backup_dir/server.txt"
ssh "${options[@]}" root@192.168.100.186 \
  'if test -f /data/open-xiaoai/init.sh; then cat /data/open-xiaoai/init.sh; fi' \
  > "$backup_dir/open-xiaoai-init.sh"
ssh "${options[@]}" root@192.168.100.186 \
  'if test -f /data/init.sh; then cat /data/init.sh; fi' > "$backup_dir/data-init.sh"
printf '登录与只读备份成功：%s\n' "$backup_dir"
