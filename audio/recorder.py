"""
audio/recorder.py

Continuous microphone capture used by the mixer to build the combined
mic + soundboard feed sent to VB-CABLE. Captures audio on a background
PortAudio thread into a small lock-protected ring buffer so the mixer's
output callback can pull the latest microphone frames without ever
blocking (which would cause audible glitches).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class MicrophoneRecorder:
    """Captures audio continuously from a microphone device into a ring
    buffer that can be read from without blocking.

    Parameters
    ----------
    samplerate:
        Sample rate to capture at (and the rate the rest of the audio
        pipeline is normalized to).
    channels:
        Number of input channels to capture (1 = mono).
    buffer_seconds:
        Size of the internal ring buffer, in seconds of audio.
    """

    def __init__(self, samplerate: int = 48000, channels: int = 1, buffer_seconds: float = 0.1) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self._buffer_len = int(samplerate * buffer_seconds)
        self._buffer = np.zeros((self._buffer_len, channels), dtype=np.float32)
        self._write_pos = 0
        self._lock = threading.Lock()
        self._listeners: list[Callable[[np.ndarray, int], None]] = []
        self._stream: Optional[sd.InputStream] = None
        self._device_index: Optional[int] = None
        self._muted = False

    @property
    def is_active(self) -> bool:
        return self._stream is not None and self._stream.active

    @property
    def device_index(self) -> Optional[int]:
        return self._device_index

    def add_listener(self, listener: Callable[[np.ndarray, int], None]) -> None:
        """Register a callback(data: np.ndarray, samplerate: int) to receive live mic audio."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[np.ndarray, int], None]) -> None:
        """Unregister a previously registered mic audio listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("Microphone stream status: %s", status)
        with self._lock:
            data = indata if not self._muted else np.zeros_like(indata)
            end = self._write_pos + frames
            if end <= self._buffer_len:
                self._buffer[self._write_pos:end] = data
            else:
                first_part = self._buffer_len - self._write_pos
                self._buffer[self._write_pos:] = data[:first_part]
                self._buffer[: end - self._buffer_len] = data[first_part:]
            self._write_pos = end % self._buffer_len

        # Dispatch non-blocking copies to external listeners (e.g. streaming VAD/ASR)
        listeners = list(self._listeners)
        if listeners and not self._muted:
            copy_data = indata.copy()
            for listener in listeners:
                try:
                    listener(copy_data, self.samplerate)
                except Exception:
                    pass

    def start(self, device_index: Optional[int]) -> None:
        """Start (or restart, if already running on a different device)
        capturing from the given input device index."""
        self.stop()
        self._device_index = device_index
        try:
            self._stream = sd.InputStream(
                device=device_index,
                channels=self.channels,
                samplerate=self.samplerate,
                dtype="float32",
                callback=self._callback,
                blocksize=0,
            )
            self._stream.start()
            logger.info("Microphone capture started on device %s", device_index)
        except Exception as exc:
            self._stream = None
            logger.error("Failed to start microphone capture: %s", exc)
            raise

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning("Error stopping microphone stream: %s", exc)
            finally:
                self._stream = None

    def read_latest(self, frames: int) -> np.ndarray:
        """Return the most recently captured `frames` samples. If fewer
        than `frames` have ever been captured, the result is zero-padded
        at the start."""
        with self._lock:
            if frames >= self._buffer_len:
                # Reconstruct full buffer in chronological order.
                return np.concatenate(
                    (self._buffer[self._write_pos:], self._buffer[: self._write_pos])
                )[-frames:]
            start = (self._write_pos - frames) % self._buffer_len
            if start < self._write_pos:
                return self._buffer[start:self._write_pos].copy()
            return np.concatenate((self._buffer[start:], self._buffer[: self._write_pos])).copy()
