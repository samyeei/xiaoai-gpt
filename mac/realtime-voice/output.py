"""Own playback prebuffer, drain confirmation and input gating for one output turn."""
import asyncio,time
import numpy as np
from pcm import stereo48
class OutputSink:
 def __init__(self,player,gate,queue,emit,gain=1,buffer_ms=600):
  self.player=player;self.gate=gate;self.queue=queue;self.emit=emit;self.silent=0;self.gain=gain
  if isinstance(buffer_ms,bool) or not isinstance(buffer_ms,int) or not 100<=buffer_ms<=3000:raise ValueError("Invalid playback buffer")
  # Bounded startup reserve absorbs both RTP jitter and cumulative supply deficits.
  # Only the beginning of each turn is held; later PCM flows without pacing sleeps.
  self.pending=bytearray();self.prebuffer_bytes=buffer_ms*192;self.active=False;self.started=False
 async def feed(self,samples):
  peak=int(np.max(np.abs(samples.astype(np.int32)))) if len(samples) else 0
  audible=peak>10
  if audible and not self.active:
   self.active=True;self.gate.playing();self.queue.clear();self.emit({'type':'playing'})
  if self.active:
   data=stereo48(samples.astype(np.float32)/32768,48000,gain=self.gain)
   if self.started:await self.player.write(data)
   else:
    self.pending.extend(data)
    if len(self.pending)>=self.prebuffer_bytes:await self.flush()
   self.silent=0 if audible else self.silent+len(samples)
   if self.silent>=24000:await self.drain()
  return peak
 async def flush(self):
  if self.pending:
   await self.player.write(bytes(self.pending));self.pending.clear();self.started=True
 async def drain(self):
  if not self.active:return
  # A short answer must play even if it ends before the startup buffer fills.
  await self.flush();await self.player.drain()
  self.gate.drained(time.monotonic());self.queue.clear();self.silent=0;self.active=False;self.started=False
  await asyncio.sleep(.4);self.emit({'type':'listening'})
