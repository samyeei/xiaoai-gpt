import unittest
import numpy as np
from lx06_probe_analysis import phrase_flags, active_windows

class AnalysisTests(unittest.TestCase):
 def test_known_phrase_accepts_numeric_and_punctuation_forms(self):
  for text in ('一加一等于几？','1+1=几？','１＋１等于多少','一加一，等于几','一加上数字一，结果是多少？'):
   self.assertTrue(phrase_flags(text)['matched_known_test_phrase'],text)
 def test_unrelated_question_and_answer_are_not_match(self):
  for text in ('一加二等于几','一加一等于二','溢价','你好','二加一等于几'):
   self.assertFalse(phrase_flags(text)['matched_known_test_phrase'],text)
 def test_extracts_utterance_after_long_silence_with_tail_and_pause(self):
  rate=1000;x=np.zeros((40000,8),np.float32)
  x[25000:26000,0]=100;x[26200:27000,0]=100
  windows=active_windows(x,rate)
  self.assertEqual(len(windows),1)
  start,end=windows[0]
  self.assertLessEqual(start,24600);self.assertGreaterEqual(end,27400)
  self.assertLess(end-start,4000)
 def test_preserves_one_second_pause_inside_question(self):
  x=np.zeros((20000,8),np.float32)
  x[5000:6000,0]=100;x[7000:8000,0]=100
  self.assertEqual(len(active_windows(x,1000)),1)
 def test_silence_and_brief_impulse_are_not_speech_windows(self):
  x=np.zeros((40000,8),np.float32)
  self.assertEqual(active_windows(x,1000),[])
  x[20000:20020,1]=1000
  self.assertEqual(active_windows(x,1000),[])

if __name__=='__main__':unittest.main()
