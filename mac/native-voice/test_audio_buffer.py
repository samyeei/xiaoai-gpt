import unittest
from unittest.mock import patch
import numpy as np
from audio_buffer import AudioBuffer

class AudioTests(unittest.TestCase):
    def test_s32_conversion_resampling_stereo_and_silence(self):
        b=AudioBuffer(gain=1)
        b.feed(np.array([16384<<16,-16384<<16],dtype='<i4').tobytes())
        result=b.drain(8)
        np.testing.assert_array_equal(result[:6,0],[.5,.5,.5,-.5,-.5,-.5])
        np.testing.assert_array_equal(result[:,0],result[:,1])
        self.assertFalse(result[6:].any())

    def test_overflow_keeps_newest_and_rejects_bad_frames(self):
        b=AudioBuffer(capacity=6,gain=1)
        b.feed(np.array([100<<16,200<<16,300<<16],dtype='<i4').tobytes())
        self.assertEqual(b.pending,6)
        self.assertEqual(b.dropped,3)
        self.assertAlmostEqual(b.drain(1)[0,0],200/32768)
        with self.assertRaises(ValueError): b.feed(b'123')

    def test_gain_is_clipped(self):
        b=AudioBuffer(gain=8)
        b.feed(np.array([32767<<16],dtype='<i4').tobytes())
        self.assertEqual(b.drain(1)[0,0],1)

    def test_callback_never_waits_on_producer(self):
        b = AudioBuffer()
        output = np.ones((4, 2), dtype=np.float32)
        b._lock.acquire()
        try:
            b.drain_into(output)
        finally:
            b._lock.release()
        self.assertFalse(output.any())
        self.assertEqual(b.contention_frames, 4)

    def test_wraparound_keeps_order(self):
        b = AudioBuffer(capacity=9, gain=1)
        b.feed(np.array([100 << 16, 200 << 16], dtype='<i4').tobytes())
        b.drain(4)
        b.feed(np.array([300 << 16, 400 << 16], dtype='<i4').tobytes())
        np.testing.assert_array_equal(b.drain(8)[:, 0],
                                      np.array([200, 200, 300, 300, 300, 400, 400, 400]) / 32768)

    def test_empty_text_and_oversized_are_rejected(self):
        for payload in [b'', 'text', b'\x00' * 256004]:
            with self.assertRaises(ValueError): AudioBuffer().feed(payload)

    def test_pause_persists_clears_queue_and_requires_explicit_resume(self):
        now = [10.0]
        clock_patch = patch('time.monotonic', side_effect=lambda: now[0])
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        b = AudioBuffer()
        pcm = np.array([100 << 16], dtype='<i4').tobytes()
        b.feed(pcm)
        b.pause()
        self.assertEqual(b.pending, 0)
        self.assertFalse(b._ring.any())
        b.feed(pcm)
        self.assertFalse(b.drain(3).any())
        self.assertEqual(b.muted_s32_frames, 1)
        now[0] = 10.8
        b.pause()
        now[0] = 11.1
        b.feed(pcm)
        self.assertFalse(b.drain(3).any())
        now[0] = 11.81
        self.assertFalse(b.drain(3).any())
        b.feed(pcm)
        self.assertFalse(b.drain(3).any())
        now[0] = 100000.0
        b.feed(pcm)
        self.assertFalse(b.drain(3).any())
        b.resume()
        self.assertFalse(b.drain(3).any())
        b.feed(pcm)
        self.assertTrue(b.drain(3).any())

    def test_pause_during_conversion_discards_pre_pause_pcm_after_resume(self):
        b = AudioBuffer()
        original = np.repeat
        def convert_and_pause(*args, **kwargs):
            converted = original(*args, **kwargs)
            b.pause()
            b.resume()
            return converted
        with patch('audio_buffer.np.repeat', side_effect=convert_and_pause):
            b.feed(np.array([100 << 16], dtype='<i4').tobytes())
        self.assertFalse(b.drain(3).any())

if __name__=='__main__': unittest.main()
