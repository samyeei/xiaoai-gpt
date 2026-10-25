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
  case "${1:-install}" in
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
