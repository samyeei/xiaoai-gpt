import unittest
from media import failure_code
class FailureTests(unittest.TestCase):
 def test_media_setup_failure_is_not_misreported_as_player_failure(self):
  self.assertEqual(failure_code('player_preflight'),'player_unavailable')
  self.assertEqual(failure_code('media_setup'),'media_failed')
