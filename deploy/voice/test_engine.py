import unittest
import numpy as np
from engine import Utterance

class EndpointTests(unittest.TestCase):
    def test_mac_threshold_accepts_quiet_question_but_not_room_noise(self):
        u=Utterance(threshold=20,silence_seconds=.1)
        for _ in range(20): self.assertIsNone(u.feed(np.full(320,35,dtype=np.int16)))
        for _ in range(4): self.assertIsNone(u.feed(np.full(320,5,dtype=np.int16)))
        self.assertEqual(u.feed(np.full(320,5,dtype=np.int16)),'complete')
        quiet=Utterance(threshold=20,wait_seconds=.1)
        for _ in range(5): result=quiet.feed(np.full(320,5,dtype=np.int16))
        self.assertEqual(result,'timeout')

    def test_endpoint_diagnostics_distinguish_quiet_speech_from_no_audio(self):
        u=Utterance(wait_seconds=.1)
        for _ in range(5): result=u.feed(np.full(320,35,dtype=np.int16))
        self.assertEqual(result,'timeout')
        self.assertEqual(u.diagnostics(),dict(peak_rms=35.0,threshold=60,voiced_seconds=0.0,started=False))

    def test_quiet_room_times_out_without_question(self):
        u=Utterance(wait_seconds=.1)
        result=None
        for _ in range(5): result=u.feed(np.zeros(320,dtype=np.int16))
        self.assertEqual(result,'timeout')

    def test_pre_roll_and_silence_end_one_question(self):
        u=Utterance(silence_seconds=.1)
        for _ in range(3): self.assertIsNone(u.feed(np.zeros(320,dtype=np.int16)))
        for _ in range(20): self.assertIsNone(u.feed(np.full(320,300,dtype=np.int16)))
        for _ in range(4): self.assertIsNone(u.feed(np.zeros(320,dtype=np.int16)))
        self.assertEqual(u.feed(np.zeros(320,dtype=np.int16)),'complete')
        self.assertLessEqual(len(u.audio()),28*320)

    def test_continuous_noise_is_bounded(self):
        u=Utterance(max_seconds=.3)
        result=None
        for _ in range(15): result=u.feed(np.full(320,300,dtype=np.int16))
        self.assertEqual(result,'complete')
        self.assertEqual(len(u.audio()),4800)

if __name__=='__main__': unittest.main()
