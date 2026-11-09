"""
tests/test_mixer_routing.py

Unit tests for audio mixer routing, verifying physical mic suppression during
translation sessions, translated audio feeding, and monitor isolation.
"""

import unittest
import numpy as np

from audio.mixer import AudioMixer, PORT_AUDIO_BLOCKSIZE, SAMPLE_RATE


class TestMixerRouting(unittest.TestCase):
    def setUp(self) -> None:
        self.mixer = AudioMixer()

    def tearDown(self) -> None:
        self.mixer.set_translator_active(False)
        self.mixer.clear_translator_audio()

    def test_translator_active_suppresses_mic_on_broadcast(self) -> None:
        # Simulate active mic with non-zero audio
        self.mixer.microphone_enabled = True
        self.mixer.set_translator_active(True)

        frames = PORT_AUDIO_BLOCKSIZE
        outdata = np.zeros((frames, 2), dtype=np.float32)

        # Call broadcast callback with no soundboard sounds and no translated audio queued
        self.mixer._broadcast_callback(outdata, frames, None, None)

        # Output must be completely silent (mic suppressed)
        self.assertEqual(np.max(np.abs(outdata)), 0.0)

    def test_feed_translator_audio_routes_to_broadcast(self) -> None:
        self.mixer.set_translator_active(True)

        # Feed 0.1s of 24 kHz tone
        sr_in = 24000
        n_samples = int(sr_in * 0.1)
        t = np.linspace(0, 0.1, n_samples, endpoint=False)
        audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

        self.mixer.feed_translator_audio(audio, samplerate=sr_in)

        frames = PORT_AUDIO_BLOCKSIZE
        outdata = np.zeros((frames, 2), dtype=np.float32)

        self.mixer._broadcast_callback(outdata, frames, None, None)

        # Output must contain audio from the translator
        peak = np.max(np.abs(outdata))
        self.assertGreater(peak, 0.01)

    def test_clear_translator_audio_flushes_instantly(self) -> None:
        self.mixer.set_translator_active(True)
        audio = np.ones((2400,), dtype=np.float32) * 0.5
        self.mixer.feed_translator_audio(audio, samplerate=24000)

        # Flush
        self.mixer.clear_translator_audio()

        frames = PORT_AUDIO_BLOCKSIZE
        outdata = np.zeros((frames, 2), dtype=np.float32)
        self.mixer._broadcast_callback(outdata, frames, None, None)

        # Should be empty/silent
        self.assertEqual(np.max(np.abs(outdata)), 0.0)

    def test_monitor_isolation(self) -> None:
        # When monitor_translator is False, monitor output does not receive translated speech
        self.mixer.monitor_translator = False
        audio = np.ones((2400,), dtype=np.float32) * 0.5
        self.mixer.feed_translator_audio(audio, samplerate=24000)

        frames = PORT_AUDIO_BLOCKSIZE
        monitor_out = np.zeros((frames, 2), dtype=np.float32)
        self.mixer._monitor_callback(monitor_out, frames, None, None)

        self.assertEqual(np.max(np.abs(monitor_out)), 0.0)


if __name__ == "__main__":
    unittest.main()
