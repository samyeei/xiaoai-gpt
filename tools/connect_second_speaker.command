#!/bin/bash
# Establish a temporary local admin connection; do not change speaker configuration.
set -euo pipefail
umask 077
task_root="$(cd "$(dirname "$0")/.." && pwd)"
task_control="$task_root/.codex-runs/lx06-secondary-diagnostic/control"
mkdir -p "$(dirname "$task_control")"
chmod 700 "$(dirname "$task_control")"
echo '连接小爱音箱 192.168.100.181，仅建立管理连接，不切换音箱。'
echo '首次出现设备指纹提示时请核对，确认后输入 yes；密码只在此终端输入，不会显示。'
if /usr/bin/ssh -S "$task_control" -O check root@192.168.100.181 >/dev/null 2>&1; then
  echo '管理连接已经可用。'
else
  /usr/bin/ssh -M -S "$task_control" -o ControlPersist=8h -o ConnectTimeout=8 \
    -o "UserKnownHostsFile=$task_root/.codex-runs/lx06-known-hosts" \
    -o StrictHostKeyChecking=ask -o HostKeyAlgorithms=+ssh-rsa \
    -o PubkeyAcceptedAlgorithms=+ssh-rsa -fN root@192.168.100.181
  echo '登录完成。请回到聊天告诉 Codex。'
fi
read -r -p '按回车关闭此窗口。' task_reply
