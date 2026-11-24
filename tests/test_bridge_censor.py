import unittest
from cogs.bridge import censor_profanity

class BridgeFeatureTests(unittest.TestCase):
    def test_censor_profanity_words(self):
        cases = [
            ("я пидорас условно", "я п*****с условно"),
            ("ты сука и блять", "ты с**а и б***ь"),
            ("иди нахуй", "иди н***й"),
            ("он долбоеб", "он д*****б"),
            ("заебал уже", "з****л уже"),
            ("хуй знает", "х*й знает"),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(censor_profanity(src), expected)

    def test_censor_profanity_false_positives(self):
        safe_phrases = [
            "страховка на 500 рублей",
            "сабля и гребля",
            "колебание курсов валют",
            "употребление воды",
            "стебель растения",
        ]
        for phrase in safe_phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(censor_profanity(phrase), phrase)

if __name__ == "__main__":
    unittest.main()
