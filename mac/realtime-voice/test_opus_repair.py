import unittest
from fractions import Fraction
import numpy as np
import av
from aiortc.codecs.opus import OpusEncoder
from aiortc.jitterbuffer import JitterFrame
from opus_repair import RepairingOpusDecoder
class RepairTests(unittest.TestCase):
 def packets(self):
  e=OpusEncoder();packets=[]
  for n in range(12):
   a=(np.sin((np.arange(960)+n*960)*2*np.pi*220/48000)*8000).astype('<i2');stereo=np.repeat(a,2)
   f=av.AudioFrame(format='s16',layout='stereo',samples=960);f.sample_rate=48000;f.pts=n*960;f.time_base=Fraction(1,48000);f.planes[0].update(stereo.tobytes())
   raw,pts=e.encode(f)
   if raw:packets.append(JitterFrame(data=raw[0],timestamp=pts))
  return packets
 def test_packet_loss_is_concealed_at_decoder_with_correct_timing(self):
  d=RepairingOpusDecoder();p=self.packets();out=[]
  try:
   for x in p[:5]:out.extend(d.decode(x))
   before=len(out);out.extend(d.decode(p[6]))
   self.assertEqual(len(out)-before,2)
   self.assertEqual(out[-2].pts,p[5].timestamp);self.assertEqual(out[-1].pts,p[6].timestamp)
   self.assertTrue(np.any(out[-2].to_ndarray()!=0))
   self.assertEqual(d.stats()['fec_attempts'],1)
  finally:d.close()
 def test_long_idle_does_not_create_unbounded_concealment(self):
  d=RepairingOpusDecoder();p=self.packets()
  try:
   d.decode(p[0]);late=JitterFrame(data=p[1].data,timestamp=48000000)
   out=d.decode(late);self.assertEqual(len(out),1);self.assertEqual(d.stats()['decoder_resets'],1)
  finally:d.close();d.close()
 def test_contiguous_packets_preserve_stereo_and_sample_count(self):
  d=RepairingOpusDecoder();p=self.packets()
  try:
   frames=[f for x in p for f in d.decode(x)]
   self.assertTrue(all(f.samples==960 and f.layout.name=='stereo' for f in frames));self.assertEqual(len(frames),len(p))
  finally:d.close()
 def test_codec_factory_is_scoped_and_other_codecs_are_preserved(self):
  import asyncio
  import aiortc.rtcrtpreceiver as receiver
  from aiortc.codecs import CODECS
  from opus_repair import install_opus_repair
  loop=asyncio.new_event_loop();original=receiver.get_decoder;old=[dict(c.parameters) for c in CODECS['audio']]
  restore=install_opus_repair(loop,lambda e:None)
  try:
   opus=next(c for c in CODECS['audio'] if c.mimeType=='audio/opus');d=receiver.get_decoder(opus)
   self.assertIsInstance(d,RepairingOpusDecoder);d.close();self.assertEqual(opus.parameters['useinbandfec'],1)
   pcmu=next(c for c in CODECS['audio'] if c.mimeType=='audio/PCMU');self.assertEqual(type(receiver.get_decoder(pcmu)),type(original(pcmu)))
  finally:restore();loop.close()
  self.assertIs(receiver.get_decoder,original);self.assertEqual([dict(c.parameters) for c in CODECS['audio']],old)
 def test_corrupt_packet_reports_failure_instead_of_silently_losing_decoder_worker(self):
  errors=[];d=RepairingOpusDecoder(on_error=lambda:errors.append(True))
  try:
   with self.assertRaises(RuntimeError):d.decode(JitterFrame(data=b'\xff',timestamp=0))
   self.assertEqual(errors,[True])
  finally:d.close()
 def test_empty_rtp_payload_does_not_synthesize_120ms_or_advance_decoder(self):
  d=RepairingOpusDecoder()
  try:
   self.assertEqual(d.decode(JitterFrame(data=b'',timestamp=0)),[])
   self.assertIsNone(d.expected)
   self.assertEqual(len(d.decode(self.packets()[0])),1)
  finally:d.close()
