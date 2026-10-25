"""Opus in-band FEC / PLC for missing RTP frames, scoped to this media child."""
import ctypes as C
from ctypes.util import find_library
from fractions import Fraction
from pathlib import Path
import av

def load_opus():
 roots=[Path(av.__file__).parent/'.dylibs',Path(av.__file__).parent.parent/'av.libs']
 candidates=[p for root in roots if root.is_dir() for p in sorted(root.glob('*opus*')) if p.is_file()]
 system=find_library('opus')
 if system:candidates.append(system)
 if not candidates:raise RuntimeError('opus_library_unavailable')
 lib=C.CDLL(str(candidates[0]))
 lib.opus_decoder_create.argtypes=[C.c_int,C.c_int,C.POINTER(C.c_int)];lib.opus_decoder_create.restype=C.c_void_p
 lib.opus_decoder_destroy.argtypes=[C.c_void_p];lib.opus_decoder_destroy.restype=None
 lib.opus_decode.argtypes=[C.c_void_p,C.c_void_p,C.c_int,C.POINTER(C.c_int16),C.c_int,C.c_int];lib.opus_decode.restype=C.c_int
 lib.opus_decoder_ctl.argtypes=[C.c_void_p,C.c_int];lib.opus_decoder_ctl.restype=C.c_int
 return lib
class RepairingOpusDecoder:
 def __init__(self,report=lambda stats:None,on_error=lambda:None):
  self.lib=load_opus();error=C.c_int();self.handle=self.lib.opus_decoder_create(48000,2,C.byref(error))
  if error.value or not self.handle:raise RuntimeError('opus_decoder_unavailable')
  self.expected=None;self.report=report;self.on_error=on_error;self.values={'fec_attempts':0,'plc_samples':0,'decoder_resets':0,'decoded_frames':0}
 def stats(self):return dict(self.values)
 def close(self):
  if getattr(self,'handle',None):self.lib.opus_decoder_destroy(self.handle);self.handle=None
 def __del__(self):self.close()
 def frame(self,data,pts,size=5760,fec=0):
  buf=(C.c_int16*(size*2))();packet=C.create_string_buffer(data) if data else None
  n=self.lib.opus_decode(self.handle,packet,len(data) if data else 0,buf,size,fec)
  if n<0:raise RuntimeError('opus_decode_failed')
  f=av.AudioFrame(format='s16',layout='stereo',samples=n);f.sample_rate=48000;f.pts=pts;f.time_base=Fraction(1,48000);f.planes[0].update(C.string_at(buf,n*4))
  return f
 def decode(self,encoded):
  try:return self.decode_frame(encoded)
  except Exception:
   self.on_error();raise
 def decode_frame(self,encoded):
  if not encoded.data:return []
  at=encoded.timestamp;out=[]
  if self.expected is not None and at<self.expected:return out
  gap=0 if self.expected is None else at-self.expected
  # RTP restarts / long idle must not allocate or synthesize seconds of audio.
  if gap>36000 or gap%120:
   self.lib.opus_decoder_ctl(self.handle,4028);self.expected=at;self.values['decoder_resets']+=1;gap=0
  changed=bool(gap)
  while gap>0:
   size=min(960,gap)
   if gap<=960:
    out.append(self.frame(encoded.data,self.expected,size,1));self.values['fec_attempts']+=1
   else:
    out.append(self.frame(None,self.expected,size));self.values['plc_samples']+=size
   self.expected+=size;gap-=size
  frame=self.frame(encoded.data,at);out.append(frame);self.expected=at+frame.samples;self.values['decoded_frames']+=len(out)
  if changed:self.report(self.stats())
  return out

def install_opus_repair(loop,emit):
 import aiortc.rtcrtpreceiver as receiver
 from aiortc.codecs import CODECS
 from aiortc.rtcrtpparameters import RTCRtcpFeedback
 # Only this process is patched; no dependency files or other applications change.
 original=receiver.get_decoder
 old=[(c,dict(c.parameters),list(c.rtcpFeedback)) for c in CODECS['audio'] if c.mimeType.lower()=='audio/opus']
 for codec,_,_ in old:
  if not any(f.type=='nack' and not f.parameter for f in codec.rtcpFeedback):codec.rtcpFeedback=[*codec.rtcpFeedback,RTCRtcpFeedback(type='nack')]
  codec.parameters={**codec.parameters,'useinbandfec':1,'minptime':10}
 def report(stats):
  try:loop.call_soon_threadsafe(emit,{'type':'opus_metrics',**stats})
  except RuntimeError:pass
 def failed():
  try:loop.call_soon_threadsafe(emit,{'type':'error','code':'media_failed'})
  except RuntimeError:pass
 def decoder(codec):return RepairingOpusDecoder(report,failed) if codec.mimeType.lower()=='audio/opus' else original(codec)
 # Fail before starting a call if the bundled native codec cannot be loaded.
 check=RepairingOpusDecoder();check.close();receiver.get_decoder=decoder
 def restore():
  receiver.get_decoder=original
  for codec,params,feedback in old:codec.parameters=params;codec.rtcpFeedback=feedback
 return restore
