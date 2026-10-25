"""Scalar-only diagnostics. No recordings or transcripts are retained."""
import numpy as np
class WakeDiagnostics:
 def __init__(self):
  self.peak=0.;self.clips=0;self.label=None;self.detected=None
 def feed(self,samples):
  values=samples.astype(np.float32)
  if len(values):self.peak=max(self.peak,float(np.sqrt(np.mean(values**2))))
  self.clips+=int(np.count_nonzero((samples==32767)|(samples==-32768)))
 def wake(self,label,at_ms):self.label=label;self.detected=at_ms
 def snapshot(self,state):
  result=dict(rms_window_peak=round(self.peak,1),clip_samples=self.clips,worker_state=state,wake_keyword=self.label,wake_detected_at_ms=self.detected)
  self.peak=0.;self.clips=0
  return result
