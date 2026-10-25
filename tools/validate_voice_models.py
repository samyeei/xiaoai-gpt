"""Decode official fixtures and a local synthesized Hey Muse reference."""
import json
from pathlib import Path
import sys
import time
import wave
import numpy as np

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'deploy/voice'))
from engine import Models

def read(path):
    with wave.open(str(path)) as w:
        assert w.getnchannels()==1 and w.getsampwidth()==2 and w.getframerate()==16000
        return np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')

m=Models(root/'deploy/models')
results=[]
for language in ('zh','en'):
    samples=read(root/f'deploy/models/asr/test_wavs/{language}.wav')
    started=time.monotonic()
    text=m.transcribe(samples.astype(np.float32)/32768)
    results.append(dict(kind='official_asr_fixture',language=language,text=text,seconds=round(time.monotonic()-started,2)))
    assert text
    if language=='zh': assert '9点' in text and '5点' in text
    if language=='en': assert 'tribal' in text.lower() and 'boy' in text.lower()
reference=root/'artifacts/2026-10-06/hey-muse/hey-muse-reference.wav'
if reference.exists():
    samples=read(reference)
    stream=m.stream()
    hits=[]
    samples=np.concatenate([samples,np.zeros(16000,dtype=np.int16)])
    for offset in range(0,len(samples),320):
        keyword=m.keyword(stream,samples[offset:offset+320])
        if keyword: hits.append(keyword)
    results.append(dict(kind='synthetic_keyword_fixture',hits=hits))
    assert 'HEY_MUSE' in hits
out=root/'artifacts/2026-10-06/hey-muse/models-acceptance.json'
out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
