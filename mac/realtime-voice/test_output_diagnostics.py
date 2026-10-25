import unittest
from output_diagnostics import OutputDiagnostics
class DiagnosticsTests(unittest.TestCase):
 def test_receive_gaps_and_write_stalls_are_separate_and_scalar_only(self):
  d=OutputDiagnostics()
  d.received(960,10);d.received(960,10.02);d.received(960,10.22)
  d.written(.15);d.timeout();d.started();d.drained()
  self.assertEqual(d.snapshot(),{'frames':3,'audio_ms':60,'max_receive_gap_ms':200,'receive_gaps_over_80ms':1,'max_write_ms':150,'receive_timeouts':1,'player_starts':1,'player_drains':1,'player_underruns':0})
 def test_player_errors_count_only_known_underrun_without_retaining_text(self):
  d=OutputDiagnostics();d.player_stderr(b'underrun!!! (at least 5 ms long)\nsecret text\n')
  self.assertEqual(d.snapshot()['player_underruns'],1)
  self.assertNotIn('secret',str(vars(d)))
