import unittest
import numpy as np
from wake_diagnostics import WakeDiagnostics
class WakeDiagnosticsTests(unittest.TestCase):
 def test_window_peak_and_clipping_without_retaining_audio(self):
  d=WakeDiagnostics();d.feed(np.array([32767,-32768,0],dtype=np.int16))
  stats=d.snapshot('idle');self.assertEqual(stats['clip_samples'],2);self.assertGreater(stats['rms_window_peak'],26000)
  self.assertEqual(d.snapshot('paused')['worker_state'],'paused');self.assertFalse(hasattr(d,'audio'))
 def test_peak_is_reset_for_next_window(self):
  d=WakeDiagnostics();d.feed(np.full(320,50,dtype=np.int16));self.assertEqual(d.snapshot('idle')['rms_window_peak'],50)
  d.feed(np.ones(320,dtype=np.int16));self.assertEqual(d.snapshot('idle')['rms_window_peak'],1)
 def test_explicit_detection_label_and_time_only(self):
  d=WakeDiagnostics();d.wake('HEY_LUKA',1234);s=d.snapshot('idle');self.assertEqual(s['wake_keyword'],'HEY_LUKA');self.assertEqual(s['wake_detected_at_ms'],1234)
