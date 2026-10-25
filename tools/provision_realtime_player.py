#!/usr/bin/env python3
import asyncio,json,sys,os,subprocess,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'mac/realtime-voice'))
from provision import provision
if __name__=='__main__':
 try:
  with urllib.request.urlopen('http://127.0.0.1:4398/health',timeout=3) as r:health=json.load(r)
  if health.get('pending') or (health.get('native_voice') or {}).get('active') or (health.get('realtime_voice') or {}).get('active') or health.get('voice',{}).get('state')!='idle':raise RuntimeError('请先结束当前音频会话')
  result=asyncio.run(provision(root))
  subprocess.run(['launchctl','kickstart','-k','gui/'+str(os.getuid())+'/com.LOCAL_USER.xiaoai-realtime-voice'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  print(json.dumps(result,ensure_ascii=False))
 except Exception as e:raise SystemExit(str(e))
