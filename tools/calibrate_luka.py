#!/usr/bin/env python3
"""60 second shadow comparison; records scalar counts, never recordings."""
import argparse,json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--distance-m",type=float);parser.add_argument("--asr-smoke",action="store_true");args=parser.parse_args()
 config=json.loads((ROOT/'mac/codex-service/private/config.json').read_text())
 request=urllib.request.Request('http://127.0.0.1:4398/calibrate',data=b'{}',headers={'Authorization':'Bearer '+config['admin_key'],'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(request,timeout=5) as r:result=json.load(r)
 print('现在开始：60秒内在一米处说3次“嘿，撸卡”，每次之间停5秒；然后停5秒，说一次“请解释卢卡这个名字”。本轮只统计，不播唤醒提示。' if args.asr_smoke else '校准已开始，请在60秒内用平常音量说20次“嘿（四声），撸（一声）卡（三声）”，每次间隔约2秒。校准期间不播唤醒提示。',flush=True)
 samples=[];deadline=time.monotonic()+65
 while time.monotonic()<deadline:
  time.sleep(1)
  with urllib.request.urlopen('http://127.0.0.1:4398/health',timeout=3) as r:voice=json.load(r)['voice']
  if voice.get('calibration',{}).get('calibration_id')==result['session_id']:samples.append({'state':voice.get('worker_state'),'stats':voice['calibration'],'rms':voice.get('rms',0),'rms_window_peak':voice.get('rms_window_peak',0),'clip_samples':voice.get('clip_samples',0)})
  if samples and samples[-1]['stats'].get('calibration_complete'):break
 report={'evidence':'human_live_shadow','complete':bool(samples and samples[-1]['stats'].get('calibration_complete')),'stats':samples[-1]['stats'] if samples else {},'expected_attempts':3 if args.asr_smoke else 20,'expected_negative_attempts':1 if args.asr_smoke else 0,'asr_smoke':args.asr_smoke,'attempt_count_confirmed':False,'recording_saved':False,'distance_m':args.distance_m,'max_observed_rms':max((s['rms_window_peak'] for s in samples),default=0),'clipped_samples_observed':sum(s['clip_samples'] for s in samples)}
 out=ROOT/'.codex-runs/luka-continuous';out.mkdir(parents=True,exist_ok=True)
 (out/'human-shadow-calibration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));(out/('human-shadow-'+result['session_id']+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
