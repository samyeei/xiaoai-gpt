import unittest
from pathlib import Path
from keyword_tuning import candidate_lines, validate_lines
class KeywordTuningTests(unittest.TestCase):
 def test_user_pronunciation_keeps_label_and_legacy_compatibility(self):
  source=Path(__file__).with_name('keywords.txt').read_text().splitlines()
  lines=candidate_lines(source);self.assertIn('h èi l ū k ǎ @HEY_LUKA',lines)
  self.assertIn('HH EY1 l ú k ǎ @HEY_LUKA',lines)
  self.assertEqual([x for x in lines if not x.endswith('@HEY_LUKA')],[x for x in source if not x.endswith('@HEY_LUKA')])
 def test_tokens_and_exact_labels_are_validated(self):
  root=Path(__file__).resolve().parents[1]/'models/kws/tokens.txt';tokens={x.split()[0] for x in root.read_text().splitlines()}
  validate_lines(candidate_lines(Path(__file__).with_name('keywords.txt').read_text().splitlines()),tokens)
  for value in ['h invented @HEY_LUKA','h èi @OTHER','h èi :nan @HEY_LUKA','h èi #1.5 @HEY_LUKA']:
   with self.subTest(value=value),self.assertRaises(ValueError):validate_lines([value],tokens)

class GainTests(unittest.TestCase):
 def test_bounded_gain_preserves_sign_and_clamps_instead_of_integer_wrap(self):
  import numpy as np
  from keyword_tuning import bounded_gain
  self.assertEqual(bounded_gain(np.array([20000,-20000,100],dtype=np.int16),2).tolist(),[32767,-32768,200])
  with self.assertRaises(ValueError):bounded_gain(np.zeros(2,dtype=np.int16),16)

 def test_gain_eight_is_supported_for_shadow_comparison(self):
  import numpy as np
  from keyword_tuning import bounded_gain
  self.assertEqual(bounded_gain(np.array([100],dtype=np.int16),8).tolist(),[800])
 def test_parameter_change_applies_only_to_user_luka_candidate(self):
  from keyword_tuning import candidate_lines,USER_PHONES
  original=['HH EY1 M Y UW1 Z @HEY_MUSE']
  result=candidate_lines(original,score=3,threshold=.15)
  self.assertEqual(result[0],original[0]);self.assertEqual(result[-1],'h èi l ū k ǎ :3 #0.15 @HEY_LUKA')
