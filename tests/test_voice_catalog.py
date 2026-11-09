"""
tests/test_voice_catalog.py

Tests for the curated Neural Voice Catalog and its integration into
InstantBoard's TTS Widget and StreamingTranslatorPipeline.
"""

import unittest

from gui.tts_widget import VOICES
from translator.voice_catalog import (
    DEFAULT_VOICE_PER_LANG,
    VOICE_CATALOG,
    get_default_voice_for_language,
    get_voice_by_short_name,
    get_voices_for_language,
)


class TestVoiceCatalog(unittest.TestCase):
    def test_curated_voices_present(self) -> None:
        short_names = {v.short_name for v in VOICE_CATALOG}
        expected_urdu = {"ur-PK-AsadNeural", "ur-PK-UzmaNeural"}
        expected_arabic = {
            "ar-SA-HamedNeural",
            "ar-SA-ZariyahNeural",
            "ar-EG-ShakirNeural",
        }
        expected_english = {
            "en-US-GuyNeural",
            "en-US-JennyNeural",
            "en-GB-RyanNeural",
            "en-GB-SoniaNeural",
        }

        self.assertTrue(expected_urdu.issubset(short_names))
        self.assertTrue(expected_arabic.issubset(short_names))
        self.assertTrue(expected_english.issubset(short_names))

    def test_voices_by_language_filtering(self) -> None:
        urdu_voices = get_voices_for_language("ur")
        self.assertEqual(len(urdu_voices), 2)
        self.assertTrue(all(v.language == "Urdu" for v in urdu_voices))

        arabic_voices = get_voices_for_language("ar")
        self.assertEqual(len(arabic_voices), 3)
        self.assertTrue(all(v.language == "Arabic" for v in arabic_voices))

        english_voices = get_voices_for_language("en")
        self.assertEqual(len(english_voices), 4)
        self.assertTrue(all(v.language == "English" for v in english_voices))

    def test_default_voices(self) -> None:
        self.assertEqual(get_default_voice_for_language("ur"), "ur-PK-AsadNeural")
        self.assertEqual(get_default_voice_for_language("ar"), "ar-SA-HamedNeural")
        self.assertEqual(get_default_voice_for_language("en"), "en-US-GuyNeural")

    def test_voice_lookup(self) -> None:
        hamed = get_voice_by_short_name("ar-SA-HamedNeural")
        self.assertIsNotNone(hamed)
        self.assertEqual(hamed.gender, "Male")
        self.assertEqual(hamed.locale, "ar-SA")

        asad = get_voice_by_short_name("ur-PK-AsadNeural")
        self.assertIsNotNone(asad)
        self.assertEqual(asad.gender, "Male")
        self.assertEqual(asad.locale, "ur-PK")

    def test_tts_widget_voices_contains_curated_models(self) -> None:
        tts_voice_ids = {voice_id for _, voice_id in VOICES}
        self.assertIn("ur-PK-AsadNeural", tts_voice_ids)
        self.assertIn("ur-PK-UzmaNeural", tts_voice_ids)
        self.assertIn("ar-SA-HamedNeural", tts_voice_ids)
        self.assertIn("ar-SA-ZariyahNeural", tts_voice_ids)
        self.assertIn("ar-EG-ShakirNeural", tts_voice_ids)
        self.assertIn("en-US-GuyNeural", tts_voice_ids)


if __name__ == "__main__":
    unittest.main()
