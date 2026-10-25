import unittest
from fractions import Fraction
import numpy as np
from timeline import PcmTimeline
class TimelineTests(unittest.TestCase):
 def test_missing_rtp_time_is_preserved_as_silence_before_next_audio(self):
  t=PcmTimeline();a=np.full(960,1000,dtype=np.int16)
  np.testing.assert_array_equal(t.align(a,0,Fraction(1,48000)),a)
  b=t.align(a,1920,Fraction(1,48000))
  self.assertEqual(len(b),1920);self.assertTrue(np.all(b[:960]==0));np.testing.assert_array_equal(b[960:],a)
  self.assertEqual(t.stats()['timeline_gap_ms'],20)
 def test_contiguous_frames_and_nonzero_origin_are_unchanged(self):
  t=PcmTimeline();a=np.arange(960,dtype=np.int16)
  for pts in [48000,48960,49920]:np.testing.assert_array_equal(t.align(a,pts,Fraction(1,48000)),a)
  self.assertEqual(t.stats()['timeline_gaps'],0)
 def test_reset_between_turns_does_not_insert_idle_time(self):
  t=PcmTimeline();a=np.ones(960,dtype=np.int16);t.align(a,0,Fraction(1,48000));t.reset()
  self.assertEqual(len(t.align(a,480000,Fraction(1,48000))),960)
 def test_large_discontinuity_is_bounded_and_missing_pts_is_safe(self):
  t=PcmTimeline();a=np.ones(960,dtype=np.int16);t.align(a,0,Fraction(1,48000))
  self.assertEqual(len(t.align(a,480000000,Fraction(1,48000))),960)
  self.assertEqual(t.stats()['timeline_resets'],1)
  self.assertEqual(len(t.align(a,None,None)),960)
 def test_duplicate_or_overlapping_audio_is_not_played_twice(self):
  t=PcmTimeline();a=np.ones(960,dtype=np.int16);t.align(a,0,Fraction(1,48000))
  self.assertEqual(len(t.align(a,0,Fraction(1,48000))),0)
  self.assertEqual(len(t.align(a,480,Fraction(1,48000))),480)
 def test_actual_av_resampler_preserves_timestamp_holes_for_alignment(self):
  import av
  r=av.AudioResampler(format='s16',layout='mono',rate=48000);t=PcmTimeline();out=[]
  for pts in [0,1920,2880]:
   frame=av.AudioFrame(format='s16',layout='mono',samples=960);frame.sample_rate=48000;frame.pts=pts;frame.time_base=Fraction(1,48000);frame.planes[0].update(np.full(960,1000,dtype=np.int16).tobytes())
   for f in r.resample(frame):out.append(t.align(f.to_ndarray().reshape(-1),f.pts,f.time_base))
  self.assertEqual(sum(map(len,out)),3840);self.assertEqual(t.stats()['timeline_gap_ms'],20)
