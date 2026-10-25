#!/bin/bash
# Inspect this checkout before execution; no downloaded shell scripts or sudo.
set -euo pipefail
umask 077
task_root="$(cd "$(dirname "$0")" && pwd -P)"
if command -v python3.12 >/dev/null 2>&1; then
  exec python3.12 "$task_root/tools/install.py" "$@"
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys;raise SystemExit(sys.version_info[:2] != (3,12))' 2>/dev/null; then
  exec python3 "$task_root/tools/install.py" "$@"
elif command -v uv >/dev/null 2>&1; then
  # Options may precede the subcommand. Do not download Python for a read-only
  # request such as '--json doctor', and do not mistake an option value for it.
  task_command=install
  task_command_seen=0
  task_expect_value=0
  for task_arg in "$@"; do
    if [ "$task_expect_value" = 1 ]; then
      task_expect_value=0
      continue
    fi
    case "$task_arg" in
      --speaker|--mac-ip|--node|--codex|--settings) task_expect_value=1 ;;
      --help|-h) task_command=--help; break ;;
      doctor|status|verify|install|start|stop|uninstall)
        if [ "$task_command_seen" = 0 ]; then
          task_command="$task_arg"
          task_command_seen=1
        fi
        ;;
    esac
  done
  case "$task_command" in
    doctor|status|verify|--help|-h)
      if task_python="$(uv python find --offline 3.12 2>/dev/null)"; then
        exec "$task_python" "$task_root/tools/install.py" "$@"
      fi
      printf '%s\n' '{"ok":false,"error":"python_3_12_not_cached","hint":"Read-only checks require an installed Python 3.12. Installation may prepare one through uv."}'
      exit 1
      ;;
  esac
  exec uv run --no-project --python 3.12 python "$task_root/tools/install.py" "$@"
else
  printf '%s\n' '{"ok":false,"error":"python_3_12_or_uv_required","hint":"Install Python 3.12 or uv locally, then retry. No services were changed."}'
  exit 1
fi
