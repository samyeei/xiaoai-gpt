import unittest
from keyword_routes import wake_packet

class KeywordRoutingTests(unittest.TestCase):
    def test_preserves_each_allowed_model_label(self):
        for label in ('HEY_MUSE', 'HEY_CODEX', 'HEY_GPT', 'HEY_LUKA'):
            with self.subTest(label=label):
                self.assertEqual(wake_packet(label), {'type': 'wake', 'keyword': label})

    def test_unknown_and_malformed_results_do_not_wake(self):
        for result in ('OTHER', 'hey codex', 'HEY_CODEX ', '', None, {}, ['HEY_GPT']):
            with self.subTest(result=result):
                self.assertIsNone(wake_packet(result))

if __name__ == '__main__':
    unittest.main()
