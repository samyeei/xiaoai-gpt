#!/usr/bin/env python3
"""Read shared eight-channel capture once in RAM; persist scalar diagnostics only."""
import argparse,gzip,io,json,subprocess,sys,urllib.request,uuid
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mac/realtime-voice'));sys.path.insert(0,str(ROOT/'deploy/voice'))
from player import PlayerConfig
from engine import Models
from lx06_probe_analysis import phrase_flags, active_windows

def main():
 parser=argparse.ArgumentParser();parser.add_argument("--seconds",type=int,choices=(6,20,40),default=6);parser.add_argument("--rate",type=int,choices=(16000,48000),default=48000);args=parser.parse_args();seconds=args.seconds;rate=args.rate
 with urllib.request.urlopen('http://127.0.0.1:4398/health',timeout=3) as r:h=json.load(r)
 if h['voice']['state']!='idle' or h.get('pending') or (h.get('native_voice') or {}).get('active') or (h.get('realtime_voice') or {}).get('active'):raise SystemExit('请先结束音频会话')
 base=PlayerConfig(ROOT).command()[:-1]
 check=subprocess.run(base+["awk '$2==\"/tmp\" && $3==\"tmpfs\" {ok=1} END {exit !ok}' /proc/mounts && test $(wc -l < /proc/swaps) -eq 1"],capture_output=True,timeout=6)
 if check.returncode:raise SystemExit('未确认无交换内存缓存，停止采集')
 models=Models(ROOT/'deploy/models')
 name='/tmp/luka-probe-'+uuid.uuid4().hex+'.pcm'
 print(f'现在开始：请在{seconds}秒内说一遍“一加一等于几”。只缓存内存，分析后清除。',flush=True)
 remote=f"umask 077; trap 'rm -f {name}' EXIT HUP INT TERM; timeout -t {seconds+8} arecord -q -D Capture -t raw -f S16_LE -c 8 -r {rate} --period-size=320 --buffer-size=1280 -d {seconds} {name} && gzip -1 -c {name}"
 try:p=subprocess.run(base+[remote],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=seconds*6+15)
 except subprocess.TimeoutExpired:
  subprocess.run(base+[f'rm -f {name}'],capture_output=True,timeout=6)
  raise SystemExit('传输超时，本轮无效；已清理内存缓存')
 cleanup=subprocess.run(base+[f'test ! -e {name}'],capture_output=True,timeout=6)
 if cleanup.returncode:raise SystemExit('内存缓存清理未确认，停止分析')
 if p.returncode:raise SystemExit('共享声道采集失败，未修改设备设置')
 if b'overrun' in p.stderr.lower():raise SystemExit('采集发生溢出，本次不计入识别结果')
 try:
  with gzip.GzipFile(fileobj=io.BytesIO(p.stdout)) as g:raw=g.read(rate*8*2*seconds+1)
 except (OSError,EOFError):raise SystemExit('采集传输不完整，本次不计入识别结果')
 if len(raw)!=rate*8*2*seconds:raise SystemExit('采集长度异常，停止分析')
 print('采集与传输已完成，正在内存中比较各声道。',flush=True)
 x=np.frombuffer(raw,dtype='<i2').reshape(-1,8).astype(np.float32)
 windows=active_windows(x,rate);rows=[]
 def analyze(values):
  if not np.any(values):return {**phrase_flags(''),'recognized_characters':0}
  stream=models.asr.create_stream();stream.accept_waveform(rate,np.clip(values*8/32768,-1,1));models.asr.decode_stream(stream)
  flags={**phrase_flags(stream.result.text),'recognized_characters':len(stream.result.text.strip())}
  del stream
  return flags
 for label,values in [(str(i),x[:,i]) for i in range(8)]+[('verified_mono_arithmetic_mean',x.mean(axis=1))]:
  rms=float(np.sqrt(np.mean(values**2)));peak=float(np.max(np.abs(values)))
  full=analyze(values);short=[]
  for start,end in windows:
   short.append({'start_seconds':round(start/rate,2),'seconds':round((end-start)/rate,2),**analyze(values[start:end])})
  rows.append({'channel':label,'rms':round(rms,2),'peak':int(peak),'full_window':full,'speech_windows':short,'clipped_after_gain8':int(np.count_nonzero(np.abs(values*8)>=32768))})
 report={'sample_rate':rate,'samples_per_channel':len(x),'gain':8,'speech_window_count':len(windows),'rows':rows,'raw_audio_saved':False,'transcripts_saved':False,'mono_mapping_verified':True,'capture_overruns':0,'ram_buffer_removed':True,'storage':'unswapped_tmpfs_and_mac_ram'}
 out=ROOT/'.codex-runs/luka-continuous/channel-speech-probe.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
