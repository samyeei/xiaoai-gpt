#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
/Users/YOUR_USER/.local/bin/node --input-type=module - <<'JS'
import {loadConfig} from './mac/codex-service/config.mjs';
const {admin_key}=loadConfig();const r=await fetch('http://127.0.0.1:4418/stop',{method:'POST',headers:{Authorization:'Bearer '+admin_key,'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(25000)});if(!r.ok)throw Error('Stop failed');const s=await r.json();console.log(s.active?'清理尚未结束。':'连续语音已停止。');
JS
