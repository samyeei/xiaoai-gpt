"""Compare recognizers on the same RAM frame without emitting wakes."""
import numpy as np
class WakeCalibration:
 def __init__(self,baseline,candidate,max_samples=960000,variants=None):
  self.decoders={'baseline':baseline,'candidate':candidate,**(variants or {})};self.maximum=max_samples;self.samples=0
  self.counts={k+'_wakes':0 for k in self.decoders};self.max_rms=0;self.clipped=0
 def feed(self,samples):
  self.samples+=len(samples)
  if len(samples):
   self.max_rms=max(self.max_rms,float(np.sqrt(np.mean(samples.astype(np.float32)**2))))
   self.clipped+=int(np.count_nonzero(np.abs(samples.astype(np.int32))>=32767))
  for label,decode in self.decoders.items():
   if decode(samples)=='HEY_LUKA':self.counts[label+'_wakes']+=1
  return self.samples>=self.maximum
 def stats(self):return {**self.counts,'calibration_samples':self.samples,'calibration_complete':self.samples>=self.maximum,'max_rms':round(self.max_rms,1),'clip_samples':self.clipped}
