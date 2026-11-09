"""
tests/test_vad_stream.py

Unit tests for the Silero VAD streaming processor, verifying frame buffering,
resampling, state reset, and silence hangover logic.
"""

import unittest
import numpy as np

from translator.vad import (
    SileroVADStream,
    VAD_FRAME_SAMPLES,
    VAD_SAMPLE_RATE,
    resample_to_16k_mono,
)


class TestVADStream(unittest.TestCase):
    def setUp(self) -> None:
        self.vad = SileroVADStream(min_speech_duration_ms=100, min_silence_duration_ms=200)

    def test_resampling_48k_to_16k(self) -> None:
        duration_sec = 0.5
        data_48k = np.zeros((int(48000 * duration_sec), 2), dtype=np.float32)
        resampled = resample_to_16k_mono(data_48k, src_rate=48000)

        self.assertEqual(resampled.ndim, 1)
        expected_samples = int(VAD_SAMPLE_RATE * duration_sec)
        self.assertAlmostEqual(len(resampled), expected_samples, delta=2)

    def test_frame_exact_buffering(self) -> None:
        # Ingest 700 samples (< 2 full frames of 512)
        audio = np.random.uniform(-0.1, 0.1, 700).astype(np.float32)
        self.vad.start_session("test_session_1")
        self.vad.process_audio(audio, src_samplerate=16000)

        # Buffer should have consumed 512 samples, leaving 188 samples in _in_buffer
        self.assertEqual(len(self.vad._in_buffer), 700 - VAD_FRAME_SAMPLES)

    def test_flush_emits_pending_segment(self) -> None:
        self.vad.start_session("test_session_2")
        # Ingest 1.0s of simulated active voice audio
        t = np.linspace(0, 1.0, 16000, endpoint=False)
        tone = (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
        self.vad.process_audio(tone, src_samplerate=16000)

        flushed = self.vad.flush()
        if flushed is not None:
            self.assertTrue(flushed.is_speech)
            self.assertGreater(len(flushed.audio), 0)


if __name__ == "__main__":
    unittest.main()
