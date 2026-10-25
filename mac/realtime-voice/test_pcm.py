import unittest
import numpy as np
from pcm import PcmQueue, stereo48
class PcmTests(unittest.TestCase):
 def test_residual_samples_and_queue_bound(self):
  q=PcmQueue(max_frames=2);q.feed(bytes(639));self.assertIsNone(q.pop());q.feed(bytes(641));self.assertEqual(len(q.pop()),640);self.assertEqual(len(q.pop()),640)
  with self.assertRaises(BufferError):q.feed(bytes(1920))
 def test_stereo_output_and_clipping(self):
  a=np.array([-1.,0.,1.],dtype=np.float32);data=stereo48(a,48000);v=np.frombuffer(data,dtype='<i2').reshape(-1,2)
  self.assertEqual(v.tolist(),[[-32768,-32768],[0,0],[32767,32767]])
 def test_queue_reports_starvation_without_counting_discarded_audio_as_consumed(self):
  q=PcmQueue();q.feed(bytes(1280));q.pop();q.clear();self.assertIsNone(q.pop())
  self.assertEqual(q.stats(),{'input_frames':2,'consumed_frames':1,'discarded_frames':1,'underruns':1,'queued_frames':0})
 def test_output_gain_boosts_quiet_audio_and_limits_peak_without_overflow(self):
  data=stereo48(np.array([.01,-.02],dtype=np.float32),48000,gain=4)
  self.assertEqual(np.frombuffer(data,dtype='<i2').reshape(-1,2).tolist(),[[1311,1311],[-2621,-2621]])
  data=stereo48(np.array([.75,-.5],dtype=np.float32),48000,gain=4)
  a=np.frombuffer(data,dtype='<i2').reshape(-1,2)[:,0]
  self.assertEqual(a[0],32767);self.assertAlmostEqual(a[1]/a[0],-.5/.75,places=3)
  for gain in [0,9,float('nan')]:
   with self.assertRaises(ValueError):stereo48(np.array([.1]),48000,gain=gain)
