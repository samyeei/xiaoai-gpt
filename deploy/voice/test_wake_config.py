import copy
import json
import tempfile
import unittest
from pathlib import Path
from wake_config import load_config, match_phrase, keyword_lines


class WakeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.config = {'version': 1, 'routes': [
            {'label': 'CUSTOM', 'backend': 'codex', 'enabled': True,
             'phrases': ['嘿，小明', 'hey ming'], 'kws_tokens': ['HH', 'EY1']},
            {'label': 'OFF', 'backend': 'muse', 'enabled': False,
             'phrases': ['hey muse'], 'kws_tokens': ['M']}]}

    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'wake.json'
            p.write_text(json.dumps(data), encoding='utf-8')
            return load_config(p)

    def test_custom_words_match_exactly_and_disabled_words_never_match(self):
        c = self.load(self.config)
        self.assertEqual(match_phrase('嘿，小明！', c), 'CUSTOM')
        self.assertEqual(match_phrase('ＨＥＹ Ming', c), 'CUSTOM')
        for text in ['请解释嘿小明', 'hey muse', 'hey ming hello', 'hey ming hey ming']:
            self.assertIsNone(match_phrase(text, c))
        self.assertEqual(keyword_lines(c, {'HH', 'EY1', 'M'}), ['HH EY1 @CUSTOM'])

    def test_bad_config_and_duplicate_normalized_words_fail_closed(self):
        cases = []
        c = copy.deepcopy(self.config); c['other'] = 1; cases.append(c)
        c = copy.deepcopy(self.config); c['version'] = 2; cases.append(c)
        c = copy.deepcopy(self.config); c['routes'][0]['backend'] = 'shell'; cases.append(c)
        c = copy.deepcopy(self.config); c['routes'][0]['enabled'] = 'true'; cases.append(c)
        c = copy.deepcopy(self.config); c['routes'][0]['kws_tokens'] = ['HH\n@OFF']; cases.append(c)
        c = copy.deepcopy(self.config); c['routes'][1]['label'] = 'CUSTOM'; cases.append(c)
        c = copy.deepcopy(self.config); c['routes'][1]['phrases'] = ['嘿小明']; cases.append(c)
        for c in cases:
            with self.subTest(c=c), self.assertRaises(ValueError):
                self.load(c)
        with self.assertRaises(ValueError):
            keyword_lines(self.load(self.config), {'HH'})

    def test_default_config_replaces_codex_wake_and_preserves_muse(self):
        c = load_config()
        for text in ['你好机劈替', '你好，GPT', '你好机批替']:
            self.assertEqual(match_phrase(text,c), 'HEY_GPT')
        for text in ['嘿撸卡','hey luka','hey codex','hey gpt','嘿机劈替','请解释你好机劈替']:
            self.assertIsNone(match_phrase(text,c))
        self.assertEqual(match_phrase('hey muse',c),'HEY_MUSE')

if __name__ == '__main__':
    unittest.main()
