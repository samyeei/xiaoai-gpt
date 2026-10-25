import unittest
import numpy as np
from wake_calibration import WakeCalibration
class CalibrationTests(unittest.TestCase):
 def test_same_ram_frame_compared_without_wake_side_effects(self):
  calls=[]
  def baseline(samples):calls.append('baseline');return None
  def candidate(samples):calls.append('candidate');return 'HEY_LUKA'
  c=WakeCalibration(baseline,candidate,max_samples=640);self.assertFalse(c.feed(np.zeros(320,dtype=np.int16)));self.assertTrue(c.feed(np.zeros(320,dtype=np.int16)))
  self.assertEqual(calls,['baseline','candidate']*2);self.assertEqual(c.stats()['candidate_wakes'],2);self.assertEqual(c.stats()['baseline_wakes'],0);self.assertFalse(hasattr(c,'audio'))
 def test_gain_candidates_are_compared_on_same_input_without_storing_audio(self):
  samples=np.array([100,-100],dtype=np.int16);seen=[]
  c=WakeCalibration(lambda x:None,lambda x:None,max_samples=2,variants={'gain2':lambda x:seen.append(x) or 'HEY_LUKA'})
  self.assertTrue(c.feed(samples));self.assertIs(seen[0],samples);self.assertEqual(c.stats()['gain2_wakes'],1);self.assertAlmostEqual(c.stats()['max_rms'],100)
