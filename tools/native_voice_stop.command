#!/bin/zsh
set -e
TASK_ROOT="${0:A:h:h}"
cd "$TASK_ROOT"
/Users/YOUR_USER/.local/bin/node --input-type=module - <<'JS'
import {readFileSync} from 'node:fs';
try {
  const config = JSON.parse(readFileSync('mac/codex-service/private/config.json', 'utf8'));
  const response = await fetch('http://127.0.0.1:4417/stop', {
    method:'POST', headers:{Authorization:'Bearer '+config.admin_key, 'Content-Type':'application/json'},
    body:'{}', signal:AbortSignal.timeout(5000),
  });
  if (!response.ok) throw Error('stop rejected');
  console.log('已请求停止音频转接；服务会恢复启动前的输入和输出。');
} catch {
  console.error('停止服务暂不可用，请在 Codex 中报告此状态。');
  process.exitCode = 1;
}
JS
