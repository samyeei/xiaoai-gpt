"""Preserve decoded RTP time instead of concatenating across omitted frames."""
import numpy as np
class PcmTimeline:
 def __init__(self):
  self.expected=None;self.gaps=0;self.padding=0;self.resets=0
 def reset(self):self.expected=None
 def align(self,samples,pts,time_base):
  if pts is None or time_base is None:self.reset();return samples
  at=round(pts*time_base*48000)
  if self.expected is None:self.expected=at
  gap=at-self.expected
  if abs(gap)>36000:
   self.resets+=1;self.expected=at;gap=0
  if gap>0:
   self.gaps+=1;self.padding+=gap
   result=np.concatenate((np.zeros(gap,dtype=np.int16),samples))
  elif gap<0:result=samples[min(-gap,len(samples)):]
  else:result=samples
  self.expected=max(self.expected,at+len(samples))
  return result
 def stats(self):return {'timeline_gaps':self.gaps,'timeline_gap_ms':round(self.padding/48),'timeline_resets':self.resets}
