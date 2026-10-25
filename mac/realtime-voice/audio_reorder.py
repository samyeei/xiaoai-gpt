"""Bounded RTP audio ordering; preserve healthy Opus packets while awaiting NACK."""
import time
from aiortc.jitterbuffer import JitterFrame
class AudioPacketBuffer:
 def __init__(self,clock=time.monotonic):
  self.clock=clock;self.expected=None;self.packets={};self.arrivals={};self.started=False;self.last_arrival=None;self.first_arrival=None
  self.received=0;self.delivered=0;self.skipped=0;self.late=0;self.resets=0
 def stats(self):return {'reorder_received':self.received,'reorder_delivered':self.delivered,'reorder_skipped':self.skipped,'reorder_late':self.late,'reorder_resets':self.resets,'reorder_queued':len(self.packets)}
 def add(self,packet):
  self.received+=1;seq=packet.sequence_number;now=self.clock()
  if self.expected is None:self.expected=seq
  delta=(seq-self.expected)%65536
  if delta>=32768:self.late+=1;return False,None
  if delta>=64:
   self.packets.clear();self.arrivals.clear();self.expected=seq;self.started=False;self.first_arrival=None;self.resets+=1
  self.packets[seq]=packet;self.arrivals.setdefault(seq,now);self.last_arrival=now
  if self.first_arrival is None:self.first_arrival=now
  if not self.started:
   if len(self.packets)<4 and now-self.first_arrival<.06:return False,None
   self.started=True
  return False,self.pop(now)
 def pop(self,now):
  if not self.packets:return None
  if self.expected not in self.packets:
   gap=min((seq-self.expected)%65536 for seq in self.packets);next_seq=(self.expected+gap)%65536
   # Each hole's deadline starts when the following packet arrived, not when
   # earlier holes finish. Multiple losses must not accumulate extra waits.
   if now-self.arrivals[next_seq]<.24:return None
   self.skipped+=gap;self.expected=next_seq
  packet=self.packets.pop(self.expected);self.arrivals.pop(self.expected);self.expected=(self.expected+1)%65536;self.delivered+=1
  return JitterFrame(data=packet._data,timestamp=packet.timestamp)
 def flush_due(self,now):
  if self.first_arrival is None:return []
  if not self.started:
   if now-self.first_arrival<.06:return []
   self.started=True
  frames=[]
  while self.packets:
   frame=self.pop(now)
   if frame is None:break
   frames.append(frame)
  return frames

def configure_audio_reorder(pc):
 result=[]
 for transceiver in pc.getTransceivers():
  if transceiver.kind!='audio':continue
  receiver=transceiver.receiver
  codec=next((c for c in receiver._RTCRtpReceiver__codecs.values() if c.mimeType.lower()=='audio/opus'),None)
  if codec is not None:
   existing=receiver._RTCRtpReceiver__jitter_buffer
   if isinstance(existing,AudioPacketBuffer):continue
   buffer=AudioPacketBuffer();origin=getattr(existing,'_origin',None)
   pending=[p for p in getattr(existing,'_packets',[]) if p is not None]
   if origin is not None:
    for packet in sorted(pending,key=lambda p:(p.sequence_number-origin)%65536):
     buffer.packets[packet.sequence_number]=packet;buffer.arrivals[packet.sequence_number]=buffer.clock()
    buffer.expected=origin;buffer.received=len(pending);buffer.started=bool(pending);buffer.first_arrival=buffer.last_arrival=buffer.clock()
   receiver._RTCRtpReceiver__jitter_buffer=buffer;result.append((receiver,buffer,codec))
 return result

def flush_audio_reorder(configured,now):
 for receiver,buffer,codec in configured:
  if not receiver._RTCRtpReceiver__decoder_thread:continue
  for frame in buffer.flush_due(now):
   frame.timestamp=receiver._RTCRtpReceiver__timestamp_mapper.map(frame.timestamp)
   receiver._RTCRtpReceiver__decoder_queue.put((codec,frame))
