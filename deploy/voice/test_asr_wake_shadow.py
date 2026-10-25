import unittest
import numpy as np
from asr_wake_shadow import AsrWakeShadow, wake_phrase
class ShadowTests(unittest.TestCase):
 def test_only_complete_wake_phrases_are_allowed(self):
  for t in ['嘿，撸卡！','嘿 卢卡','黑撸卡。','黑卢卡']:self.assertTrue(wake_phrase(t))
  for t in ['卢卡','请解释卢卡这个名字','嘿卢卡是什么','你说嘿撸卡','嘿muse','退下吧','']:self.assertFalse(wake_phrase(t))
 def test_long_wait_does_not_cut_short_actual_utterance(self):
  s=AsrWakeShadow();quiet=np.zeros(320,dtype=np.int16);voice=np.full(320,1000,dtype=np.int16)
  for _ in range(150):self.assertIsNone(s.feed(quiet))
  for _ in range(50):self.assertIsNone(s.feed(voice))
  audio=None
  for _ in range(41):
   a=s.feed(quiet)
   if a is not None:audio=a
  self.assertIsNotNone(audio);self.assertGreater(len(audio),16000);self.assertLess(len(audio),40000)
  self.assertAlmostEqual(float(np.max(audio)),8000/32768)
 def test_continuous_noise_is_bounded_and_waits_for_silence(self):
  s=AsrWakeShadow();voice=np.full(320,1000,dtype=np.int16)
  for _ in range(500):self.assertIsNone(s.feed(voice))
  self.assertEqual(s.stats()['asr_shadow_long_discarded'],1)
  self.assertLessEqual(s.buffered_samples,64000)
 def test_stats_do_not_contain_transcripts(self):
  s=AsrWakeShadow();s.record_result('嘿，撸卡',.123);s.record_result('普通私密问题',.1)
  d=s.stats();self.assertEqual(d['asr_shadow_wakes'],1);self.assertEqual(d['asr_shadow_processed'],2)
  self.assertNotIn('普通私密问题',str(d));self.assertNotIn('撸卡',str(d))
 def test_segment_diagnostics_distinguish_empty_asr_and_short_audio_without_text(self):
  s=AsrWakeShadow()
  audio=np.concatenate([np.full(6400,8000/32768,dtype=np.float32),np.zeros(12800,dtype=np.float32)])
  s.record_result('',.1,audio)
  s.record_result('普通私密问题',.1,audio)
  rows=s.stats()['asr_shadow_outcomes']
  self.assertEqual(rows[0]['normalized_characters'],0)
  self.assertEqual(rows[1]['normalized_characters'],6)
  self.assertEqual(rows[0]['segment_seconds'],1.2)
  self.assertEqual(rows[0]['voiced_seconds'],.4)
  self.assertAlmostEqual(rows[0]['peak_after_gain'],8000/32768,places=3)
  self.assertNotIn('普通私密问题',str(rows))
 def test_subminimum_speech_is_counted_separately_from_asr_mismatch(self):
  s=AsrWakeShadow();voice=np.full(320,1000,dtype=np.int16);quiet=np.zeros(320,dtype=np.int16)
  for frame in [voice]*4+[quiet]*40:self.assertIsNone(s.feed(frame))
  self.assertEqual(s.stats()['asr_shadow_short_discarded'],1)
class PreRollComparisonTests(unittest.TestCase):
 def test_english_candidate_is_exact_shadow_only_and_rejects_ordinary_sentences(self):
  s=AsrWakeShadow()
  for text in ['Hey Luka!','Hey Luca','Hey Looka','Hey Lucas','Hey look','Please say hey Luka','嘿卢卡']:
   s.record_result(text,.1)
  rows=s.stats()['asr_shadow_outcomes']
  self.assertEqual([r['english_candidate_matched'] for r in rows],[True,True,True,False,False,False,False])
  self.assertEqual(s.stats()['asr_shadow_english_candidate_wakes'],3)
  self.assertEqual(s.stats()['asr_shadow_wakes'],1)
 def test_fixed_test_phrase_classes_are_diagnostic_only(self):
  s=AsrWakeShadow()
  for text in ['Hey Luka!','嘿鲁卡','嘿鲁卡嘿鲁卡','请解释卢卡这个名字','Hey look!']:
   s.record_result(text,.1)
  rows=s.stats()['asr_shadow_outcomes']
  self.assertEqual([r['fixed_test_phrase_class'] for r in rows],['english_name','chinese_homophone','repeated_chinese_homophone','other','english_attention'])
  self.assertTrue(all(not r['matched'] for r in rows))
  self.assertEqual(rows[0]['latin_characters'],7)
  self.assertEqual(rows[1]['han_characters'],3)
  for text in ['Hey Luka','嘿鲁卡','请解释卢卡这个名字']:self.assertNotIn(text,str(rows))
 def test_long_pre_roll_preserves_low_energy_onset_without_changing_default(self):
  original=AsrWakeShadow();extended=AsrWakeShadow(pre_frames=25)
  quiet=np.zeros(320,dtype=np.int16);onset=np.full(320,30,dtype=np.int16);voice=np.full(320,1000,dtype=np.int16)
  results=[None,None]
  for frame in [quiet]*30+[onset]*15+[voice]*20+[quiet]*40:
   for i,collector in enumerate([original,extended]):
    clip=collector.feed(frame)
    if clip is not None:results[i]=clip
  self.assertEqual(len(results[1])-len(results[0]),6400)
  self.assertEqual(original.pre.maxlen,5)
 def test_pre_roll_configuration_is_bounded(self):
  for n in [0,26]:
   with self.assertRaises(ValueError):AsrWakeShadow(pre_frames=n)
if __name__=='__main__':unittest.main()
