#!/usr/bin/env python3
"""Same RAM-only LX06 audio: compare onset retention and language, never text/audio reports."""
import argparse,gzip,io,json,subprocess,sys,time,urllib.request,uuid
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mac/realtime-voice'));sys.path.insert(0,str(ROOT/'deploy/voice'))
from player import PlayerConfig
from engine import Models
from asr_wake_shadow import AsrWakeShadow

def compare(pcm,recognize_auto,recognize_zh):
 reports={}
 for label,pre,recognize in [('auto_pre100',5,recognize_auto),('auto_pre500',25,recognize_auto),('zh_pre500',25,recognize_zh)]:
  collector=AsrWakeShadow(pre_frames=pre);segments=[]
  for start in range(0,len(pcm)-319,320):
   clip=collector.feed(pcm[start:start+320])
   if clip is not None:
    started=time.monotonic()
    try:
     text=recognize(clip);collector.record_result(text,time.monotonic()-started,clip);del text
     if len(segments)<60:segments.append({**collector.stats()["asr_shadow_outcomes"][-1],"end_seconds":round((start+320)/16000,3)})
    except Exception:collector.errors+=1
  reports[label]={**collector.stats(),"segments":segments}
 return reports

def main():
 import sherpa_onnx
 parser=argparse.ArgumentParser();parser.add_argument("--targets",type=int,choices=(3,10,20),default=3);parser.add_argument("--distance-m",type=float,default=1);args=parser.parse_args()
 with urllib.request.urlopen('http://127.0.0.1:4398/health',timeout=4) as r:h=json.load(r)
 v=h['voice']
 if not v.get('speaker_connected') or v.get('worker_state')!='idle' or h.get('pending') or (h.get('realtime_voice') or {}).get('active') or (h.get('native_voice') or {}).get('active'):raise SystemExit('音箱未就绪或正在会话，未启动采集')
 base=PlayerConfig(ROOT).command()[:-1]
 if not (ROOT/'.codex-runs/lx06-diagnostic/control').exists():raise SystemExit('诊断连接已超时，请重新连接；未启动采集')
 check=subprocess.run(base+["awk '$2==\"/tmp\" && $3==\"tmpfs\" {ok=1} END {exit !ok}' /proc/mounts && test $(wc -l < /proc/swaps) -eq 1"],capture_output=True,timeout=6)
 if check.returncode:raise SystemExit('诊断连接或无交换内存检查未通过，未启动采集')
 models=Models(ROOT/'deploy/models')
 zh=sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(ROOT/'deploy/models/asr/model.int8.onnx'),tokens=str(ROOT/'deploy/models/asr/tokens.txt'),num_threads=1,provider='cpu',language='zh',use_itn=True)
 def recognize_zh(audio):
  stream=zh.create_stream();stream.accept_waveform(16000,audio);zh.decode_stream(stream);return stream.result.text.strip()
 # Pause only the task wake listener for this bounded test; capture stays available.
 config=json.loads((ROOT/'mac/codex-service/private/config.json').read_text())
 request=urllib.request.Request('http://127.0.0.1:4398/calibrate',data=b'{}',headers={'Authorization':'Bearer '+config['admin_key'],'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(request,timeout=5) as r:cal=json.load(r)
 seconds=60 if args.targets>=10 else 40;name='/tmp/luka-compare-'+uuid.uuid4().hex+'.pcm'
 remote=f"umask 077; trap 'rm -f {name}' EXIT HUP INT TERM; timeout -t {seconds+8} arecord -q -D noop -t raw -f S32_LE -c 1 -r 16000 -d {seconds} {name} && gzip -1 -c {name}"
 print(f'现在开始：{seconds}秒内说{args.targets}次“嘿，撸卡”，每次间隔'+('两秒' if args.targets>=10 else '五秒')+'，最后再说一次“请解释卢卡这个名字”。本轮不回应。',flush=True)
 try:p=subprocess.run(base+[remote],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=seconds+80)
 except subprocess.TimeoutExpired:
  subprocess.run(base+[f'rm -f {name}'],capture_output=True,timeout=6);raise SystemExit('采集传输超时，本轮无效')
 removed=subprocess.run(base+[f'test ! -e {name}'],capture_output=True,timeout=6)
 if removed.returncode:raise SystemExit('内存清除未确认，停止分析')
 if p.returncode or b'overrun' in p.stderr.lower():raise SystemExit('采集失败或溢出，本轮无效')
 with gzip.GzipFile(fileobj=io.BytesIO(p.stdout)) as g:raw=g.read(seconds*16000*4+1)
 if len(raw)!=seconds*16000*4:raise SystemExit('音频长度不符，本轮无效')
 x=np.frombuffer(raw,dtype='<i4');low16_nonzero=int(np.count_nonzero(x & 65535))
 if low16_nonzero:raise SystemExit('S32映射不符合既有验证，停止分析')
 pcm=(x>>16).astype(np.int16)
 print('内存采集已完成并清除音箱缓存，正在三组离线识别。',flush=True)
 report={'evidence':'same_audio_onset_language_comparison','expected_target_attempts':args.targets,'distance_m':args.distance_m,'expected_negative_attempts':1,'attempt_count_confirmed':False,'calibration_id':cal['session_id'],'capture_seconds':seconds,'sample_rate':16000,'samples':len(pcm),'capture_overruns':0,'ram_buffer_removed':True,'recording_saved':False,'transcripts_saved':False,'low16_nonzero':low16_nonzero,'variants':compare(pcm,models.transcribe,recognize_zh)}
 del raw,x,pcm,p
 out=ROOT/'.codex-runs/luka-continuous';ident=uuid.uuid4().hex;report['report_id']=ident
 for path in [out/'human-wake-language-comparison.json',out/f'human-wake-language-{ident}.json']:path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
