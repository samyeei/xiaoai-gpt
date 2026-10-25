"""Bounded PCM16 framing and output normalization."""
from collections import deque
import math
import numpy as np
class PcmQueue:
 def __init__(self,max_frames=100):self.pending=bytearray();self.frames=deque();self.maximum=max_frames;self.input_frames=0;self.consumed_frames=0;self.discarded_frames=0;self.underruns=0
 def feed(self,data):
  if len(data)>64000:raise ValueError('Invalid PCM')
  if len(self.pending)+len(data)+len(self.frames)*640>self.maximum*640:raise BufferError('Audio overflow')
  self.pending.extend(data)
  while len(self.pending)>=640:self.frames.append(bytes(self.pending[:640]));del self.pending[:640];self.input_frames+=1
 def pop(self):
  if self.frames:self.consumed_frames+=1;return self.frames.popleft()
  self.underruns+=1;return None
 def clear(self):self.discarded_frames+=len(self.frames);self.pending.clear();self.frames.clear()
 def stats(self):return {'input_frames':self.input_frames,'consumed_frames':self.consumed_frames,'discarded_frames':self.discarded_frames,'underruns':self.underruns,'queued_frames':len(self.frames)}
def stereo48(samples,rate,gain=1):
 if rate<=0:raise ValueError('Invalid rate')
 if isinstance(gain,bool) or not isinstance(gain,(int,float)) or not math.isfinite(gain) or not .25<=gain<=8:raise ValueError('Invalid output gain')
 a=np.asarray(samples,dtype=np.float32).reshape(-1)
 if not len(a):return b''
 if rate!=48000:
  positions=np.arange(int(round(len(a)*48000/rate)))*rate/48000
  a=np.interp(positions,np.arange(len(a)),a)
 if gain!=1:
  peak=float(np.max(np.abs(a)))
  a=a*min(gain,1/peak) if peak else a
 scaled=np.clip(np.rint(a*32768),-32768,32767).astype('<i2')
 return np.column_stack((scaled,scaled)).tobytes()
