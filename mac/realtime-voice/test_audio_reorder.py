import unittest
from aiortc.rtp import RtpPacket
from audio_reorder import AudioPacketBuffer

def packet(n):
 p=RtpPacket(sequence_number=n%65536,timestamp=n*960,payload_type=96);p._data=str(n).encode();return p
class PacketTests(unittest.TestCase):
 def test_real_loss_does_not_discard_other_received_audio(self):
  clock=[0];b=AudioPacketBuffer(clock=lambda:clock[0]);got=[];received=[]
  for n in range(200):
   clock[0]=n*.02
   got.extend(int(f.data) for f in b.flush_due(clock[0]))
   if n%10==3:continue
   received.append(n);_,frame=b.add(packet(n))
   if frame:got.append(int(frame.data))
  got.extend(int(f.data) for f in b.flush_due(5))
  self.assertEqual(got,received);self.assertEqual(b.stats()['reorder_queued'],0)
 def test_short_reordering_is_preserved_and_tail_is_flushed_after_deadline(self):
  b=AudioPacketBuffer(clock=lambda:0);got=[]
  for n in [0,1,3,2,4]:
   _,f=b.add(packet(n))
   if f:got.append(int(f.data))
  got.extend(int(f.data) for f in b.flush_due(.01));self.assertEqual(got,[0,1,2,3,4])
  self.assertEqual(b.flush_due(.1),[])
 def test_sequence_wrap_duplicate_and_late_packet_are_bounded(self):
  b=AudioPacketBuffer(clock=lambda:0);got=[]
  for n in range(65533,65540):
   _,f=b.add(packet(n))
   if f:got.append(int(f.data))
  got.extend(int(f.data) for f in b.flush_due(.1));self.assertEqual(got,list(range(65533,65540)))
  self.assertIsNone(b.add(packet(65534))[1]);self.assertLessEqual(b.stats()['reorder_queued'],64)
 def test_large_restart_does_not_grow_buffer_or_wait_for_old_packets(self):
  b=AudioPacketBuffer(clock=lambda:0)
  b.add(packet(0));b.add(packet(1000))
  self.assertEqual(b.stats()['reorder_resets'],1)
  self.assertEqual([int(f.data) for f in b.flush_due(.1)],[1000])
 def test_receiver_integration_flushes_tail_through_timestamp_mapper_and_decoder(self):
  from types import SimpleNamespace as NS
  from queue import Queue
  from aiortc.rtcrtpreceiver import TimestampMapper
  from audio_reorder import configure_audio_reorder,flush_audio_reorder
  codec=NS(mimeType='audio/opus');q=Queue();receiver=NS(**{'_RTCRtpReceiver__jitter_buffer':None,'_RTCRtpReceiver__codecs':{96:codec},'_RTCRtpReceiver__decoder_thread':True,'_RTCRtpReceiver__decoder_queue':q,'_RTCRtpReceiver__timestamp_mapper':TimestampMapper()})
  pc=NS(getTransceivers=lambda:[NS(kind='audio',receiver=receiver)])
  configured=configure_audio_reorder(pc);self.assertEqual(len(configured),1);b=configured[0][1]
  b.clock=lambda:0;b.add(packet(10));b.add(packet(11));flush_audio_reorder(configured,.1)
  first=q.get_nowait();second=q.get_nowait();self.assertIs(first[0],codec);self.assertEqual(first[1].timestamp,0);self.assertEqual(second[1].timestamp,960);self.assertTrue(q.empty())
 def test_retransmitted_packet_is_kept_before_deadline(self):
  clock=[0];b=AudioPacketBuffer(clock=lambda:clock[0]);got=[]
  for n in [0,1,2,4,5]:
   _,f=b.add(packet(n))
   if f:got.append(int(f.data))
  got.extend(int(f.data) for f in b.flush_due(.1))
  self.assertEqual(got,[0,1,2])
  clock[0]=.2;_,f=b.add(packet(3))
  if f:got.append(int(f.data))
  got.extend(int(f.data) for f in b.flush_due(.21));self.assertEqual(got,[0,1,2,3,4,5]);self.assertEqual(b.stats()['reorder_skipped'],0)
 def test_unrecoverable_holes_have_independent_bounded_deadlines(self):
  clock=[0];b=AudioPacketBuffer(clock=lambda:clock[0]);got=[]
  for n in [0,2,4,6]:
   _,f=b.add(packet(n))
   if f:got.append(int(f.data))
  got.extend(int(f.data) for f in b.flush_due(.25));self.assertEqual(got,[0,2,4,6]);self.assertEqual(b.stats()['reorder_skipped'],3)
 def test_install_waits_for_codec_and_preserves_existing_buffered_packets(self):
  from types import SimpleNamespace as NS
  from aiortc.jitterbuffer import JitterBuffer
  from audio_reorder import configure_audio_reorder
  old=JitterBuffer(16,prefetch=4);old.add(packet(0));old.add(packet(1))
  receiver=NS(**{'_RTCRtpReceiver__codecs':{},'_RTCRtpReceiver__jitter_buffer':old});pc=NS(getTransceivers=lambda:[NS(kind='audio',receiver=receiver)])
  self.assertEqual(configure_audio_reorder(pc),[])
  receiver._RTCRtpReceiver__codecs={96:NS(mimeType='audio/opus')}
  configured=configure_audio_reorder(pc);self.assertEqual(len(configured),1);b=configured[0][1]
  self.assertEqual([int(f.data) for f in b.flush_due(b.clock()+.1)],[0,1]);self.assertEqual(configure_audio_reorder(pc),[])
 def test_no_loss_tail_is_released_without_waiting_for_another_rtp_packet(self):
  b=AudioPacketBuffer(clock=lambda:0);b.add(packet(0))
  self.assertEqual(b.flush_due(.04),[])
  self.assertEqual([int(f.data) for f in b.flush_due(.08)],[0])
  self.assertEqual(b.stats()['reorder_queued'],0)
