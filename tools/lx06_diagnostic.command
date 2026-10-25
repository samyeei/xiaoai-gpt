#!/bin/bash
# Task-owned connection only; no speaker configuration changes.
set -euo pipefail
umask 077
task_root="$(cd "$(dirname "$0")/.." && pwd)"
socket_dir="$task_root/.codex-runs/lx06-diagnostic"
mkdir -p "$socket_dir"
chmod 700 "$socket_dir"
options=(-o ConnectTimeout=8 -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$task_root/.codex-runs/lx06-known-hosts"
  -o HostKeyAlgorithms=+ssh-rsa -S "$socket_dir/control")
if ssh "${options[@]}" -O check root@192.168.100.186 >/dev/null 2>&1; then
  echo '本任务诊断连接已建立。'
  exit 0
fi
echo '请输入音箱密码，仅建立本任务专用连接，不改配置。连接将在空闲10分钟后退出。'
ssh "${options[@]}" -M -o ControlPersist=600 -fN root@192.168.100.186
ssh "${options[@]}" -O check root@192.168.100.186
echo '诊断连接成功；告诉 Codex“诊断已连接”。'
