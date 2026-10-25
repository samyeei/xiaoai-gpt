"""Local-only calibration collector; no audio/transcripts in diagnostic reports."""
from collections import deque
import re,unicodedata
import numpy as np

def normalized_phrase(text):
 text=unicodedata.normalize('NFKC',str(text))
 return re.sub(r'[^\w]','',text)

def wake_phrase(text):
 return normalized_phrase(text) in {'嘿撸卡','嘿卢卡','黑撸卡','黑卢卡'}

def fixed_test_phrase_class(text):
 """Finite diagnostic hypotheses, never used as wake authorization."""
 text=normalized_phrase(text).lower()
 if not text:return 'empty'
 if wake_phrase(text):return 'allowed'
 if text in {'heyluka','heyluca','heylooka','heylucas'}:return 'english_name'
 if text in {'heylook','heylookat','heylookup'}:return 'english_attention'
 aliases={a+b+c for a in '嘿黑嗨' for b in '撸卢鲁路鹿露' for c in '卡咔咖'}
 if text in aliases:return 'chinese_homophone'
 if any(text==a*count for a in aliases for count in (2,3)):return 'repeated_chinese_homophone'
 return 'other'

class AsrWakeShadow:
 def __init__(self,pre_frames=5):
  if not isinstance(pre_frames,int) or not 1<=pre_frames<=25:raise ValueError('Pre-roll must be 1 to 25 frames')
  self.pre=deque(maxlen=pre_frames);self.frames=[];self.buffered_samples=0;self.speech=0;self.silence=0;self.waiting_quiet=False
  self.outcomes=deque(maxlen=8);self.processed=0;self.hits=0;self.english_candidate_hits=0;self.long_discarded=0;self.short_discarded=0;self.busy_samples=0;self.errors=0;self.max_decode_seconds=0
 def reset(self):self.pre.clear();self.frames.clear();self.buffered_samples=0;self.speech=0;self.silence=0
 def feed(self,samples):
  voiced=float(np.sqrt(np.mean(samples.astype(np.float32)**2)))>=60
  if self.waiting_quiet:
   self.silence=0 if voiced else self.silence+len(samples)
   if self.silence>=12800:self.waiting_quiet=False;self.reset()
   return None
  if not self.frames:
   self.pre.append(samples.copy())
   if not voiced:return None
   self.frames=list(self.pre);self.buffered_samples=sum(len(x) for x in self.frames);self.speech=len(samples)
  else:
   self.frames.append(samples.copy());self.buffered_samples+=len(samples)
   self.speech+=len(samples) if voiced else 0
  self.silence=0 if voiced else self.silence+len(samples)
  if self.buffered_samples>=64000:
   self.long_discarded+=1;self.reset();self.waiting_quiet=True;return None
  if self.silence>=12800:
   audio=np.clip(np.concatenate(self.frames).astype(np.float32)*8/32768,-1,1) if self.speech>=2400 else None
   if audio is None:self.short_discarded+=1
   self.reset();return audio
  return None
 def record_result(self,text,elapsed,audio=None):
  matched=wake_phrase(text);self.processed+=1;self.hits+=int(matched)
  normalized=normalized_phrase(text)
  english_candidate=normalized.lower() in {'heyluka','heyluca','heylooka'}
  self.english_candidate_hits+=int(english_candidate)
  outcome={'index':self.processed,'matched':matched,'normalized_characters':len(normalized),'latin_characters':len(re.findall(r'[A-Za-z]',normalized)),'han_characters':len(re.findall(r'[\u3400-\u9fff]',normalized)),'fixed_test_phrase_class':fixed_test_phrase_class(text)}
  outcome['english_candidate_matched']=english_candidate
  if audio is not None and len(audio):
   frames=audio[:len(audio)//320*320].reshape(-1,320)
   voiced=np.sqrt(np.mean(frames**2,axis=1))>=60*8/32768
   outcome.update(segment_seconds=round(len(audio)/16000,3),voiced_seconds=round(int(np.count_nonzero(voiced))*.02,3),peak_after_gain=round(float(np.max(np.abs(audio))),4))
  self.outcomes.append(outcome);self.max_decode_seconds=max(self.max_decode_seconds,elapsed)
 def stats(self):
  return {'asr_shadow_outcomes':list(self.outcomes),'asr_shadow_processed':self.processed,'asr_shadow_wakes':self.hits,'asr_shadow_english_candidate_wakes':self.english_candidate_hits,'asr_shadow_long_discarded':self.long_discarded,'asr_shadow_short_discarded':self.short_discarded,'asr_shadow_busy_samples':self.busy_samples,'asr_shadow_errors':self.errors,'asr_shadow_max_decode_seconds':round(self.max_decode_seconds,3)}
