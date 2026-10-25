"""Numeric output timing only; never retain audio, stderr text or transcripts."""
class OutputDiagnostics:
 def __init__(self):
  self.last_received=None;self.samples=0
  self.values=dict(frames=0,audio_ms=0,max_receive_gap_ms=0,receive_gaps_over_80ms=0,max_write_ms=0,receive_timeouts=0,player_starts=0,player_drains=0,player_underruns=0)
 def received(self,samples,now):
  if self.last_received is not None:
   gap=round(max(0,now-self.last_received)*1000)
   self.values['max_receive_gap_ms']=max(self.values['max_receive_gap_ms'],gap)
   if gap>80:self.values['receive_gaps_over_80ms']+=1
  self.last_received=now;self.samples+=samples;self.values['frames']+=1;self.values['audio_ms']=round(self.samples/48)
 def written(self,seconds):self.values['max_write_ms']=max(self.values['max_write_ms'],round(seconds*1000))
 def timeout(self):self.values['receive_timeouts']+=1
 def started(self):self.values['player_starts']+=1
 def drained(self):self.values['player_drains']+=1
 def player_stderr(self,data):self.values['player_underruns']+=data.lower().count(b'underrun')
 def snapshot(self):return dict(self.values)
