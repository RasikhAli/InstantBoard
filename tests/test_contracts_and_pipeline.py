"""
tests/test_contracts_and_pipeline.py

Unit tests for StreamingTranslatorPipeline contracts, cancellation tokens,
queue bounding, and voice profile enrollment.
"""

import time
import unittest
import numpy as np

from audio.mixer import AudioMixer
from translator.contracts import (
    SynthesizedChunk,
    AudioFrame,
    CancellationGeneration,
    PipelineMetrics,
    SessionStatus,
    TranscriptUnit,
    TranslationUnit,
    VADSegment,
)
from translator.pipeline import StreamingTranslatorPipeline
from translator.profiles import VoiceProfileManager


class TestContractsAndPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.mixer = AudioMixer()
        self.pipeline = StreamingTranslatorPipeline(audio_mixer=self.mixer)

    def tearDown(self) -> None:
        self.pipeline.stop()
        self.pipeline.tts.stop()

    def test_cancellation_token_invalidation(self) -> None:
        gen = CancellationGeneration()
        id1 = gen.current_id
        self.assertTrue(gen.is_valid(id1))

        # New cancellation triggered
        id2 = gen.increment()
        self.assertFalse(gen.is_valid(id1))
        self.assertTrue(gen.is_valid(id2))

    def test_pipeline_start_and_stop_lifecycle(self) -> None:
        self.assertEqual(self.pipeline.status, SessionStatus.IDLE)
        self.assertFalse(self.mixer.translator_active)

        self.pipeline.start()
        self.assertEqual(self.pipeline.status, SessionStatus.LISTENING)
        self.assertTrue(self.mixer.translator_active)

        self.pipeline.stop()
        self.assertEqual(self.pipeline.status, SessionStatus.IDLE)
        self.assertFalse(self.mixer.translator_active)

    def test_emergency_stop_flushes_and_restores(self) -> None:
        self.pipeline.start()
        # Feed mock audio to mixer queue
        self.mixer.feed_translator_audio(np.ones(2400, dtype=np.float32), 24000)
        self.assertGreater(len(self.mixer._translator_broadcast_queue), 0)

        # Trigger emergency stop
        self.pipeline.emergency_stop()

        self.assertEqual(self.pipeline.status, SessionStatus.IDLE)
        self.assertFalse(self.mixer.translator_active)
        self.assertEqual(len(self.mixer._translator_broadcast_queue), 0)

    def test_voice_profile_enrollment_and_listing(self) -> None:
        profile_mgr = VoiceProfileManager()
        # Create a test 3-second audio sample
        sr = 24000
        audio = (0.3 * np.sin(2 * np.pi * 220 * np.linspace(0, 3.0, sr * 3))).astype(np.float32)

        meta = profile_mgr.create_profile_from_audio(
            name="Test User Profile",
            audio_data=audio,
            samplerate=sr,
            notes="Automated test profile",
        )

        self.assertEqual(meta.name, "Test User Profile")
        self.assertGreaterEqual(meta.duration_seconds, 2.9)

        # Verify it lists
        profiles = profile_mgr.list_profiles()
        ids = [p.profile_id for p in profiles]
        self.assertIn(meta.profile_id, ids)

        # Clean up
        profile_mgr.delete_profile(meta.profile_id)


if __name__ == "__main__":
    unittest.main()
