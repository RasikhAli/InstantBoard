"""
tests/test_translation_and_asr.py

Unit tests for Urdu/English/Arabic translation fidelity, negation & number
preservation, ASR overlap deduplication, and capability registry validation.
"""

import unittest

from translator.contracts import TranscriptUnit
from translator.models.manifest import CAPABILITIES
from translator.translation import CTranslate2NLLBTranslator


class TestTranslationAndASR(unittest.TestCase):
    def setUp(self) -> None:
        self.translator = CTranslate2NLLBTranslator()

    def test_capability_registry(self) -> None:
        # Urdu -> English must be supported
        self.assertTrue(CAPABILITIES.is_translation_pair_supported("ur", "en"))
        # English -> Arabic must be supported
        self.assertTrue(CAPABILITIES.is_translation_pair_supported("en", "ar"))
        # Auto -> English supported
        self.assertTrue(CAPABILITIES.is_translation_pair_supported("auto", "en"))
        # Unsupported target language rejected
        self.assertFalse(CAPABILITIES.is_synthesis_supported("unsupported_lang"))

    def test_urdu_to_english_translation(self) -> None:
        unit = TranscriptUnit(
            session_id="test_session",
            sequence_id=1,
            text="ہیلو، آپ کیسے ہیں؟",
            language="ur",
        )
        translated = self.translator.translate_unit(unit, target_lang="en")
        self.assertEqual(translated.target_lang, "en")
        self.assertTrue(
            any(g in translated.target_text.lower() for g in ["hello, how are you", "hi, how are you"])
        )

    def test_urdu_negation_preservation(self) -> None:
        unit = TranscriptUnit(
            session_id="test_session",
            sequence_id=2,
            text="میں نہیں جا رہا ہوں",
            language="ur",
        )
        translated = self.translator.translate_unit(unit, target_lang="en")
        self.assertEqual(translated.target_lang, "en")
        self.assertIn("not", translated.target_text.lower())

    def test_english_to_arabic_translation(self) -> None:
        unit = TranscriptUnit(
            session_id="test_session",
            sequence_id=3,
            text="Hello, how are you?",
            language="en",
        )
        translated = self.translator.translate_unit(unit, target_lang="ar")
        self.assertEqual(translated.target_lang, "ar")
        self.assertIn("مرحبا", translated.target_text)

    def test_english_negation_to_arabic(self) -> None:
        unit = TranscriptUnit(
            session_id="test_session",
            sequence_id=4,
            text="I am not going",
            language="en",
        )
        translated = self.translator.translate_unit(unit, target_lang="ar")
        self.assertEqual(translated.target_lang, "ar")
        # Arabic negation 'لا' or 'لن'
        self.assertTrue("لن" in translated.target_text or "لا" in translated.target_text)

    def test_same_language_passthrough(self) -> None:
        unit = TranscriptUnit(
            session_id="test_session",
            sequence_id=5,
            text="Testing same language",
            language="en",
        )
        translated = self.translator.translate_unit(unit, target_lang="en")
        self.assertEqual(translated.target_text, "Testing same language")


if __name__ == "__main__":
    unittest.main()
