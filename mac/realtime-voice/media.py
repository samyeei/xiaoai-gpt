"""Headless WebRTC media. PCM and transcripts are never persisted."""
import asyncio,json,sys,time
from fractions import Fraction
from pathlib import Path
import numpy as np
import av
from aiortc import RTCPeerConnection,RTCSessionDescription,AudioStreamTrack
from websockets.asyncio.server import serve
from websockets.http11 import Response
from websockets.datastructures import Headers
from pcm import PcmQueue
from output import OutputSink
from output_diagnostics import OutputDiagnostics
from opus_repair import install_opus_repair
from audio_reorder import configure_audio_reorder,flush_audio_reorder
from aiortc.rtcrtpreceiver import NackGenerator
from aiortc.sdp import SessionDescription
from player import PlayerConfig,Player,ActivityGate
from transport import candidate_summary,watch_task

def emit(event):print(json.dumps(event,ensure_ascii=False),flush=True)
class Uplink(AudioStreamTrack):
 def __init__(self,queue,gate):super().__init__();self.queue=queue;self.gate=gate;self.enabled=False;self.output_enabled=False;self.started=None;self.timestamp=0;self.last_activity=0;self.last_metric=0;self.max_rms=0
 async def recv(self):
  if self.started is None:self.started=time.monotonic()
  else:self.timestamp+=320
  await asyncio.sleep(max(0,self.started+self.timestamp/16000-time.monotonic()))
  raw=self.queue.pop() if self.enabled and self.gate.can_listen(time.monotonic()) else None
  if raw is None:raw=bytes(640)
  elif np.max(np.abs(np.frombuffer(raw,dtype='<i2').astype(np.int32)))>160 and time.monotonic()-self.last_activity>=1:
   self.last_activity=time.monotonic();emit({'type':'activity'})
  if self.enabled and self.gate.can_listen(time.monotonic()):
   values=np.frombuffer(raw,dtype='<i2').astype(np.float32);self.max_rms=max(self.max_rms,float(np.sqrt(np.mean(values**2))))
   if time.monotonic()-self.last_metric>=1:
    emit({'type':'input_metrics',**self.queue.stats(),'rms_window_peak':round(self.max_rms,1)});self.last_metric=time.monotonic();self.max_rms=0
  frame=av.AudioFrame(format='s16',layout='mono',samples=320);frame.sample_rate=16000;frame.pts=self.timestamp;frame.time_base=Fraction(1,16000);frame.planes[0].update(raw)
  return frame
def failure_code(phase):
 return 'player_unavailable' if phase=='player_preflight' else 'media_failed'
async def main():
 initial=json.loads(await asyncio.to_thread(sys.stdin.readline));root=Path(__file__).resolve().parents[2];config=PlayerConfig(root,initial.get('player_mode','diagnostic'),initial.get('device_id','lx06-primary'))
 restore_decoder=install_opus_repair(asyncio.get_running_loop(),emit)
 pc=RTCPeerConnection();queue=PcmQueue();gate=ActivityGate();uplink=Uplink(queue,gate);pc.addTrack(uplink);dc=pc.createDataChannel('oai-events');player=Player(config);stop=asyncio.Event();tasks=[];connected_client=None;packet_buffers=[]
 def fail(code):emit({'type':'error','code':code});stop.set()
 @dc.on('message')
 def signal(raw):
  try:
   packet=json.loads(raw);typ=packet.get('type')
   if typ in ('turn.done','turn.created'):
    turn=packet.get('turn') or {};emit({'type':'media_signal','event':typ,'role':packet.get('role',turn.get('role')),'keys':list(packet)[:15],'turn_keys':list(turn)[:15]})
  except Exception:pass
 @pc.on('connectionstatechange')
 async def state():
  emit({'type':'transport_state','stage':'peer','state':pc.connectionState})
  if pc.connectionState=='connected':emit({'type':'connected'})
  if pc.connectionState=='failed':fail('media_failed')
 @pc.on('iceconnectionstatechange')
 def ice_state():emit({'type':'transport_state','stage':'ice','state':pc.iceConnectionState})
 @pc.on('signalingstatechange')
 def signaling_state():emit({'type':'transport_state','stage':'signaling','state':pc.signalingState})
 @pc.on('track')
 def track(t):
  async def receive():
   sink=OutputSink(player,gate,queue,emit,gain=initial.get('output_gain',1),buffer_ms=initial.get('output_buffer_ms',600));last_metric=0
   diagnostics=OutputDiagnostics();player.on_stderr=diagnostics.player_stderr;player.on_write=diagnostics.written
   def output_event(event):
    if event['type']=='playing':diagnostics.started()
    if event['type']=='listening':diagnostics.drained()
    emit({'type':'output_metrics',**diagnostics.snapshot()});emit(event)
   sink.emit=output_event
   resampler=av.AudioResampler(format='s16',layout='mono',rate=48000)
   try:
    while not stop.is_set():
     try:frame=await asyncio.wait_for(t.recv(),.8)
     except asyncio.TimeoutError:
      # RTP can stop entirely at the end of a turn, without trailing silence frames.
      diagnostics.timeout();await sink.drain()
      emit({'type':'output_metrics',**diagnostics.snapshot()})
      continue
     if not uplink.output_enabled:continue
     # WebRTC decoded s16 may be planar or packed stereo. Normalize through AV.
     normalized=resampler.resample(frame)
     samples=np.concatenate([f.to_ndarray().reshape(-1) for f in normalized]) if normalized else np.empty(0,dtype=np.int16)
     diagnostics.received(len(samples),time.monotonic())
     peak=await sink.feed(samples)
     if time.monotonic()-last_metric>=1:
      emit({'type':'output_metrics',**diagnostics.snapshot()})
      emit({'type':'media_metrics','peak':peak,'samples':len(samples),'silent_samples':sink.silent});last_metric=time.monotonic()
   except asyncio.CancelledError:raise
   except Exception:
    if not stop.is_set():fail('player_unavailable')
  tasks.append(asyncio.create_task(receive()))
 async def authenticate(conn,request):
  if request.headers.get('Authorization')!='Bearer '+initial['key'] or request.path!='/audio/'+initial['session_id'] or request.headers.get('Origin') not in (None,'null'):
   return Response(401,'Unauthorized',Headers([('Content-Type','text/plain')]),b'Unauthorized')
 async def audio(ws):
  nonlocal connected_client
  if connected_client is not None:await ws.close(1013,'One bridge only');return
  connected_client=ws
  try:
   async for data in ws:
    if not isinstance(data,bytes) or len(data)>64000:raise ValueError('Invalid PCM')
    if uplink.enabled and gate.can_listen(time.monotonic()):queue.feed(data)
  except BufferError:emit({'type':'input_metrics',**queue.stats(),'overflow':True});fail('audio_overflow')
  except Exception:
   if not stop.is_set():fail('bridge_disconnected')
  finally:
   connected_client=None
   if uplink.enabled and not stop.is_set():fail('bridge_disconnected')
 async def flush_audio_tail():
  while not stop.is_set():
   if not packet_buffers:packet_buffers.extend(configure_audio_reorder(pc))
   flush_audio_reorder(packet_buffers,time.monotonic())
   await asyncio.sleep(.02)
 async def network_metrics():
  while not stop.is_set():
   for _,buffer,_ in packet_buffers:emit({'type':'reorder_metrics',**buffer.stats()})
   report=await pc.getStats()
   for item in report.values():
    if item.type=='inbound-rtp' and item.kind=='audio':emit({'type':'rtp_metrics','packets_received':item.packetsReceived,'packets_lost':max(0,item.packetsLost),'jitter_samples':item.jitter})
   await asyncio.sleep(1)
 async def commands():
  while not stop.is_set():
   line=await asyncio.to_thread(sys.stdin.readline)
   if not line:stop.set();return
   packet=json.loads(line)
   if packet['op']=='answer':
    emit({'type':'candidate_summary','side':'remote','counts':candidate_summary(packet['sdp'])})
    await pc.setRemoteDescription(RTCSessionDescription(sdp=packet['sdp'],type='answer'))
    negotiated=SessionDescription.parse(packet['sdp'])
    nack=any(c.mimeType.lower()=='audio/opus' and any(f.type=='nack' and not f.parameter for f in c.rtcpFeedback) for m in negotiated.media if m.kind=='audio' for c in m.rtp.codecs)
    if nack:
     for transceiver in pc.getTransceivers():
      if transceiver.kind=='audio':transceiver.receiver._RTCRtpReceiver__nack_generator=NackGenerator()
    emit({'type':'audio_nack','negotiated':nack})
    packet_buffers.extend(configure_audio_reorder(pc))
    emit({'type':'transport_state','stage':'answer_applied','state':'ok'})
    dtls=pc.sctp.transport
    emit({'type':'transport_state','stage':'dtls','state':dtls.state})
    dtls.on('statechange',lambda:emit({'type':'transport_state','stage':'dtls','state':dtls.state}))
   elif packet['op']=='listen':queue.clear();uplink.enabled=True;uplink.output_enabled=True
   elif packet['op']=='pause_input':queue.clear();uplink.enabled=False
   elif packet['op']=='close':stop.set();return
 phase='player_preflight'
 try:
  await config.preflight()
  phase='media_setup'
  async with serve(audio,'127.0.0.1',4419,process_request=authenticate,max_size=64000,max_queue=8):
   await pc.setLocalDescription(await pc.createOffer())
   emit({'type':'candidate_summary','side':'local','counts':candidate_summary(pc.localDescription.sdp)})
   emit({'type':'offer','sdp':pc.localDescription.sdp})
   tasks.append(asyncio.create_task(network_metrics()))
   tail=asyncio.create_task(flush_audio_tail());watch_task(tail,emit,fail,phase='audio_reorder');tasks.append(tail)
   task=asyncio.create_task(commands());watch_task(task,emit,fail);tasks.append(task);await stop.wait()
 except Exception as error:
  emit({'type':'error','code':failure_code(phase)})
  print('media diagnostic: phase='+phase+' mode='+config.mode+' exception='+type(error).__name__,file=sys.stderr,flush=True)
 finally:
  stop.set();uplink.enabled=False;queue.clear();await pc.close();await player.close()
  for task in tasks:task.cancel()
  await asyncio.gather(*tasks,return_exceptions=True);restore_decoder()
if __name__=='__main__':asyncio.run(main())
