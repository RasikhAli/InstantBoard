"""
audio/player.py

High-level playback API used by the GUI: given a path to a cached
audio file (almost always an MP3 downloaded from MyInstants), decode
it to PCM and register it with the `AudioMixer` so it plays
immediately, overlapping with anything already playing, and is also
mixed into the VB-CABLE broadcast feed if enabled.

Decoding strategy
------------------
`soundfile` (libsndfile) can read MP3 directly on recent libsndfile
versions, so we try that first since it requires no subprocess. If
that fails (older libsndfile, exotic encoding, corrupt header) we fall
back to invoking `ffmpeg` to transcode the file to a temporary WAV,
which `soundfile` can always read. This keeps playback working even
in edge cases without requiring ffmpeg for the common path.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
import soundfile as sf

from audio.mixer import AudioMixer

logger = logging.getLogger(__name__)


class PlaybackError(Exception):
    """Raised when a sound file cannot be decoded or played."""


class AudioDecoder:
    """Decodes audio files to (float32 PCM data, samplerate) tuples."""

    @staticmethod
    def _ffmpeg_available() -> bool:
        return shutil.which("ffmpeg") is not None

    @staticmethod
    def _decode_with_soundfile(path: Path) -> Tuple[np.ndarray, int]:
        data, samplerate = sf.read(str(path), dtype="float32", always_2d=True)
        return data, samplerate

    @staticmethod
    def _decode_with_ffmpeg(path: Path) -> Tuple[np.ndarray, int]:
        if not AudioDecoder._ffmpeg_available():
            raise PlaybackError(
                f"Could not decode '{path.name}': unsupported format and ffmpeg is not installed."
            )
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "decoded.wav"
            command = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-ar",
                "48000",
                "-ac",
                "2",
                str(wav_path),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=30)
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
                raise PlaybackError(f"ffmpeg failed to decode '{path.name}': {stderr}") from exc
            except subprocess.TimeoutExpired as exc:
                raise PlaybackError(f"ffmpeg timed out decoding '{path.name}'") from exc
            return AudioDecoder._decode_with_soundfile(wav_path)

    @staticmethod
    def decode(path: str | os.PathLike) -> Tuple[np.ndarray, int]:
        """Decode an audio file, returning (data, samplerate).

        `data` has shape (n_samples, n_channels) and dtype float32.
        Raises `PlaybackError` if the file cannot be decoded by any
        available method.
        """
        file_path = Path(path)
        if not file_path.exists() or file_path.stat().st_size == 0:
            raise PlaybackError(f"Audio file is missing or empty: {file_path}")

        try:
            return AudioDecoder._decode_with_soundfile(file_path)
        except Exception as exc:
            logger.warning(
                "soundfile could not decode '%s' directly (%s); falling back to ffmpeg",
                file_path.name,
                exc,
            )

        try:
            return AudioDecoder._decode_with_ffmpeg(file_path)
        except PlaybackError:
            raise
        except Exception as exc:
            raise PlaybackError(f"Could not decode '{file_path.name}': {exc}") from exc


class SoundPlayer:
    """Front-end for playing cached sound files through the shared
    `AudioMixer`. Every call to `play()` starts a brand-new, fully
    independent playback instance - existing sounds are never
    interrupted, matching InstantBoard's "overlap, don't replace"
    soundboard behavior.

    Card-level tracking: each sound that is played through this player
    gets a *card_id* (the MyInstants sound.id string) mapped to the
    mixer's internal numeric sound_id(s). Since a card can be played
    multiple times simultaneously, card_id maps to a *list* of mixer
    ids. Stop by card_id terminates every instance of that sound."""

    def __init__(self, mixer: AudioMixer, on_sound_finished: Optional[Callable[[str], None]] = None) -> None:
        self._mixer = mixer
        self._card_map: dict[str, list[int]] = {}  # card_id -> [mixer_id, ...]
        self._on_sound_finished = on_sound_finished
        mixer._on_sound_finished = self._on_mixer_sound_finished

    def _on_mixer_sound_finished(self, sound_id: int) -> None:
        for card_id, ids in list(self._card_map.items()):
            if sound_id in ids:
                ids.remove(sound_id)
                if not ids:
                    del self._card_map[card_id]
                if self._on_sound_finished:
                    self._on_sound_finished(card_id)
                break

    def play(self, path: str | os.PathLike, card_id: str | None = None) -> int:
        """Decode and play a sound file. Returns the mixer's internal
        sound id. If `card_id` is given, the mixer id is tracked so
        `stop_by_card_id` can later stop this sound instance."""
        data, samplerate = AudioDecoder.decode(path)
        sound_id = self._mixer.add_sound(data, samplerate)
        logger.info("Playing '%s' (sound id %d)", Path(path).name, sound_id)

        if card_id is not None:
            if card_id not in self._card_map:
                self._card_map[card_id] = []
            self._card_map[card_id].append(sound_id)

        return sound_id

    def stop(self, sound_id: int) -> None:
        self._mixer.stop_sound(sound_id)
        # Clean up card map
        for card_id, ids in list(self._card_map.items()):
            if sound_id in ids:
                ids.remove(sound_id)
                if not ids:
                    del self._card_map[card_id]
                break

    def stop_by_card_id(self, card_id: str) -> None:
        """Stop all mixer sounds associated with a card identifier."""
        ids = self._card_map.pop(card_id, [])
        for sid in ids:
            self._mixer.stop_sound(sid)
        logger.info("Stopped %d instance(s) for card '%s'", len(ids), card_id)

    def stop_all(self) -> None:
        self._mixer.stop_all_sounds()
        self._card_map.clear()

    @property
    def active_count(self) -> int:
        return self._mixer.active_sound_count()
