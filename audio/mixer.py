"""
audio/mixer.py

The real-time mixing engine at the heart of InstantBoard.

Responsibilities:
  * Keep a list of currently playing sounds ("active sounds"), each of
    which is an independent numpy buffer with its own playback
    position. Sounds are never stopped to make room for new ones -
    they simply play concurrently and are removed once exhausted.
  * Continuously mix those active sounds with the live microphone
    signal (captured by `audio.recorder.MicrophoneRecorder`) and
    stream the result to the chosen *broadcast* output device
    (typically the VB-CABLE "CABLE Input" playback endpoint), so that
    voice-chat / streaming software listening on VB-CABLE hears both
    the user's voice and the soundboard.
  * Separately stream just the sounds (no microphone) to a *monitor*
    output device (e.g. the user's normal speakers/headphones) so the
    user can hear what they're triggering without also hearing their
    own mic looped back.
  * Apply independent volume controls for microphone, playback
    (monitor) and soundboard, and prevent clipping using a soft
    limiter rather than hard truncation.

Design note on dual outputs
----------------------------
Both the broadcast stream and the monitor stream need to play the
*same* sound effects, but each active sound must only advance its
playback position once per block of audio - not once per output
stream. To achieve this, a single background `_RenderThread` is the
only place that ever calls `ActiveSound.next_block()`. It renders one
block at a time and pushes an independent copy onto a small queue for
each output stream to consume. This keeps the two outputs perfectly
in sync while letting them have independent volumes (soundboard vs.
playback) and independent mic mixing (broadcast only).
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

import numpy as np
import sounddevice as sd

from audio.recorder import MicrophoneRecorder

logger = logging.getLogger(__name__)

SAMPLE_RATE = 48000  # Fixed internal rate - all sounds mixed at this rate
BLOCK_SIZE = 480  # 10ms at 48kHz - matches Windows timer resolution for stable timing
_QUEUE_MAX_BLOCKS = 16  # ~320ms of audio buffered
# Use a fixed PortAudio blocksize to match our render thread exactly
PORT_AUDIO_BLOCKSIZE = 480


def _resample_linear(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple, dependency-free linear-interpolation resampler.

    Good enough for short sound-effect clips; avoids requiring scipy
    just to change sample rate.
    """
    if src_rate == dst_rate or data.shape[0] == 0:
        return data
    duration = data.shape[0] / src_rate
    dst_length = max(1, int(round(duration * dst_rate)))
    src_times = np.linspace(0, duration, num=data.shape[0], endpoint=False)
    dst_times = np.linspace(0, duration, num=dst_length, endpoint=False)
    if data.ndim == 1:
        return np.interp(dst_times, src_times, data).astype(np.float32)
    channels = data.shape[1]
    out = np.empty((dst_length, channels), dtype=np.float32)
    for ch in range(channels):
        out[:, ch] = np.interp(dst_times, src_times, data[:, ch])
    return out


def _soft_limit(signal: np.ndarray, threshold: float = 0.98) -> np.ndarray:
    """Apply a soft (tanh-based) limiter so that summed signals which
    briefly exceed +/-1.0 are gently compressed instead of harshly
    clipped, avoiding audible crackle."""
    peak = np.max(np.abs(signal)) if signal.size else 0.0
    if peak <= threshold:
        return signal
    return np.tanh(signal)


@dataclass
class ActiveSound:
    """A single sound effect currently playing, tracked by position."""

    sound_id: int
    data: np.ndarray  # shape (n_samples, 2), float32, at SAMPLE_RATE
    position: int = 0

    @property
    def finished(self) -> bool:
        return self.position >= self.data.shape[0]

    def next_block(self, n_frames: int) -> np.ndarray:
        end = min(self.position + n_frames, self.data.shape[0])
        block = self.data[self.position:end]
        if block.shape[0] < n_frames:
            pad = np.zeros((n_frames - block.shape[0], self.data.shape[1]), dtype=np.float32)
            block = np.concatenate([block, pad], axis=0)
        self.position = end
        return block


class _RenderThread(threading.Thread):
    """Background thread that advances sound playback positions and
    pushes rendered blocks into per-output queues. This ensures each
    sound only advances once per block, even though we have two output
    streams (broadcast + monitor)."""

    def __init__(self, mixer: "AudioMixer") -> None:
        super().__init__(daemon=True, name="InstantBoardRenderThread")
        self._mixer = mixer
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        block_duration = BLOCK_SIZE / SAMPLE_RATE
        next_tick = time.perf_counter()
        while not self._stop_event.is_set():
            mix = self._mixer._pull_sound_mix(BLOCK_SIZE)
            self._mixer._push_block(mix)
            next_tick += block_duration
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                # Sleep for at least 1ms to avoid busy-waiting
                time.sleep(max(0.001, sleep_time))
            else:
                # We're behind schedule; resync instead of spinning.
                next_tick = time.perf_counter()


class AudioMixer:
    """Central real-time audio engine: mixes sounds + microphone and
    streams to a broadcast device, while separately streaming sounds
    alone to a monitor (speaker) device."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_sounds: Dict[int, ActiveSound] = {}
        self._next_sound_id = 1

        self.microphone = MicrophoneRecorder(samplerate=SAMPLE_RATE, channels=1)

        self._broadcast_stream: Optional[sd.OutputStream] = None
        self._monitor_stream: Optional[sd.OutputStream] = None
        self._render_thread: Optional[_RenderThread] = None

        self._broadcast_queue: Deque[np.ndarray] = collections.deque(maxlen=_QUEUE_MAX_BLOCKS)
        self._monitor_queue: Deque[np.ndarray] = collections.deque(maxlen=_QUEUE_MAX_BLOCKS)
        self._queue_lock = threading.Lock()

        # Translator audio source
        self.translator_active = False
        self.translator_volume = 1.0
        self.monitor_translator = False
        self._translator_broadcast_queue: Deque[np.ndarray] = collections.deque(maxlen=200)
        self._translator_monitor_queue: Deque[np.ndarray] = collections.deque(maxlen=200)
        self._translator_lock = threading.Lock()

        self.microphone_volume = 0.8
        self.soundboard_volume = 0.8
        self.playback_volume = 0.8  # monitor-only sound volume

        self.microphone_enabled = False
        self._on_sound_finished = None  # Callback(sound_id) when a sound finishes naturally

    def set_translator_active(self, active: bool) -> None:
        """Enable or disable translator mode. When active, physical mic audio
        is suppressed from the broadcast feed so callers hear only translated speech."""
        self.translator_active = active
        logger.info("Mixer translator mode: active=%s", active)

    def feed_translator_audio(self, data: np.ndarray, samplerate: int) -> None:
        """Ingest synthesized translator audio, normalize to 48kHz stereo, and queue for broadcast."""
        normalized = _resample_linear(data, samplerate, SAMPLE_RATE)
        if normalized.ndim == 1:
            normalized = normalized[:, np.newaxis]
        if normalized.shape[1] == 1:
            normalized = np.repeat(normalized, 2, axis=1)
        elif normalized.shape[1] > 2:
            normalized = normalized[:, :2]

        normalized = normalized.astype(np.float32)

        # Slice into PORT_AUDIO_BLOCKSIZE blocks for smooth streaming
        with self._translator_lock:
            n_samples = normalized.shape[0]
            for start in range(0, n_samples, PORT_AUDIO_BLOCKSIZE):
                end = min(start + PORT_AUDIO_BLOCKSIZE, n_samples)
                block = normalized[start:end]
                if block.shape[0] < PORT_AUDIO_BLOCKSIZE:
                    pad = np.zeros(
                        (PORT_AUDIO_BLOCKSIZE - block.shape[0], 2), dtype=np.float32
                    )
                    block = np.concatenate([block, pad], axis=0)
                self._translator_broadcast_queue.append(block.copy())
                if self.monitor_translator:
                    self._translator_monitor_queue.append(block.copy())

    def clear_translator_audio(self) -> None:
        """Immediately flush all queued translator audio."""
        with self._translator_lock:
            self._translator_broadcast_queue.clear()
            self._translator_monitor_queue.clear()

    def _pop_translator_broadcast_block(self, frames: int) -> np.ndarray:
        with self._translator_lock:
            if self._translator_broadcast_queue:
                block = self._translator_broadcast_queue.popleft()
                if block.shape[0] == frames:
                    return block
        return np.zeros((frames, 2), dtype=np.float32)

    def _pop_translator_monitor_block(self, frames: int) -> np.ndarray:
        with self._translator_lock:
            if self._translator_monitor_queue:
                block = self._translator_monitor_queue.popleft()
                if block.shape[0] == frames:
                    return block
        return np.zeros((frames, 2), dtype=np.float32)

    # ------------------------------------------------------------------
    # Sound registration (called by audio.player.SoundPlayer)
    # ------------------------------------------------------------------
    def add_sound(self, data: np.ndarray, samplerate: int) -> int:
        """Register a decoded sound buffer for playback and return its id."""
        normalized = _resample_linear(data, samplerate, SAMPLE_RATE)
        if normalized.ndim == 1:
            normalized = normalized[:, np.newaxis]
        if normalized.shape[1] == 1:
            normalized = np.repeat(normalized, 2, axis=1)
        elif normalized.shape[1] > 2:
            normalized = normalized[:, :2]
        with self._lock:
            sound_id = self._next_sound_id
            self._next_sound_id += 1
            self._active_sounds[sound_id] = ActiveSound(sound_id=sound_id, data=normalized.astype(np.float32))
        self._ensure_render_thread()
        return sound_id

    def stop_sound(self, sound_id: int) -> None:
        with self._lock:
            self._active_sounds.pop(sound_id, None)

    def stop_all_sounds(self) -> None:
        with self._lock:
            self._active_sounds.clear()

    def active_sound_count(self) -> int:
        with self._lock:
            return len(self._active_sounds)

    # ------------------------------------------------------------------
    # Internal mixing (only ever called from the render thread)
    # ------------------------------------------------------------------
    def _pull_sound_mix(self, n_frames: int) -> np.ndarray:
        mix = np.zeros((n_frames, 2), dtype=np.float32)
        with self._lock:
            finished_ids: List[int] = []
            for sound_id, sound in self._active_sounds.items():
                mix += sound.next_block(n_frames)
                if sound.finished:
                    finished_ids.append(sound_id)
            for sound_id in finished_ids:
                del self._active_sounds[sound_id]
                if self._on_sound_finished:
                    try:
                        self._on_sound_finished(sound_id)
                    except Exception:
                        pass
        return mix

    def _push_block(self, mix: np.ndarray) -> None:
        with self._queue_lock:
            self._broadcast_queue.append(mix)
            self._monitor_queue.append(mix)

    def _pop_block(self, queue: Deque[np.ndarray], n_frames: int) -> np.ndarray:
        with self._queue_lock:
            if queue:
                block = queue.popleft()
                if block.shape[0] == n_frames:
                    return block
        return np.zeros((n_frames, 2), dtype=np.float32)

    def _ensure_render_thread(self) -> None:
        if self._render_thread is None or not self._render_thread.is_alive():
            self._render_thread = _RenderThread(self)
            self._render_thread.start()

    # ------------------------------------------------------------------
    # PortAudio callbacks
    # ------------------------------------------------------------------
    def _broadcast_callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("Broadcast stream status: %s", status)
        # Pop pre-rendered mix from queue
        sound_mix = self._pop_block(self._broadcast_queue, frames) * self.soundboard_volume

        # Pop translated speech audio
        trans_audio = self._pop_translator_broadcast_block(frames) * self.translator_volume

        # When translator is active, suppress original mic so callers hear only translated speech
        if self.translator_active:
            mic = np.zeros((frames, 2), dtype=np.float32)
        elif self.microphone_enabled and self.microphone.is_active:
            mic = self.microphone.read_latest(frames) * self.microphone_volume
            if mic.ndim == 1:
                mic = mic[:, np.newaxis]
            if mic.shape[1] == 1:
                mic = np.repeat(mic, 2, axis=1)
        else:
            mic = np.zeros((frames, 2), dtype=np.float32)

        # Mix with slight ducking to prevent clipping
        mixed = sound_mix + trans_audio + mic * 0.9
        outdata[:] = _soft_limit(mixed)

    def _monitor_callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("Monitor stream status: %s", status)
        sound_mix = self._pop_block(self._monitor_queue, frames) * self.playback_volume
        if self.monitor_translator:
            trans_audio = self._pop_translator_monitor_block(frames) * self.translator_volume
            sound_mix = sound_mix + trans_audio
        outdata[:] = _soft_limit(sound_mix)

    def _broadcast_sounds_only_callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("Broadcast sounds-only stream status: %s", status)
        sound_mix = self._pop_block(self._broadcast_queue, frames) * self.soundboard_volume
        trans_audio = self._pop_translator_broadcast_block(frames) * self.translator_volume
        mixed = sound_mix + trans_audio
        outdata[:] = _soft_limit(mixed)

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------
    def start_broadcast(self, device_index: Optional[int], microphone_device_index: Optional[int]) -> None:
        """Start streaming the mic+soundboard mix to `device_index`
        (typically the VB-CABLE 'CABLE Input' endpoint)."""
        self.stop_broadcast()
        self._ensure_render_thread()
        self.microphone_enabled = True
        self.microphone.start(microphone_device_index)
        try:
            # Always use the fixed internal sample rate. PortAudio will
            # automatically resample to match the device if needed.
            logger.info("Starting broadcast stream at %d Hz", SAMPLE_RATE)

            # Use a fixed blocksize that matches our render thread exactly
            # to avoid timing mismatches that cause robotic audio.
            self._broadcast_stream = sd.OutputStream(
                device=device_index,
                channels=2,
                samplerate=SAMPLE_RATE,
                dtype="float32",
                blocksize=PORT_AUDIO_BLOCKSIZE,
                callback=self._broadcast_callback,
            )
            self._broadcast_stream.start()
            logger.info("Broadcast (mic+soundboard) stream started on device %s", device_index)
        except Exception as exc:
            logger.error("Failed to start broadcast stream: %s", exc)
            self._broadcast_stream = None
            raise

    def start_broadcast_sounds_only(self, device_index: Optional[int]) -> None:
        """Start streaming sounds only (no microphone) to `device_index`.
        This is used for Soundboard mode where we route sounds to VB-CABLE
        but keep the microphone separate to avoid robotic voice issues."""
        self.stop_broadcast()
        self._ensure_render_thread()
        self.microphone_enabled = False
        try:
            logger.info("Starting sounds-only broadcast stream at %d Hz", SAMPLE_RATE)

            self._broadcast_stream = sd.OutputStream(
                device=device_index,
                channels=2,
                samplerate=SAMPLE_RATE,
                dtype="float32",
                blocksize=PORT_AUDIO_BLOCKSIZE,
                callback=self._broadcast_sounds_only_callback,
            )
            self._broadcast_stream.start()
            logger.info("Broadcast (sounds only) stream started on device %s", device_index)
        except Exception as exc:
            logger.error("Failed to start sounds-only broadcast stream: %s", exc)
            self._broadcast_stream = None
            raise

    def stop_broadcast(self) -> None:
        if self._broadcast_stream is not None:
            try:
                self._broadcast_stream.stop()
                self._broadcast_stream.close()
            except Exception as exc:
                logger.warning("Error stopping broadcast stream: %s", exc)
            finally:
                self._broadcast_stream = None
        if not self.translator_active:
            self.microphone.stop()
            self.microphone_enabled = False

    def start_monitor(self, device_index: Optional[int]) -> None:
        """Start streaming sounds-only audio to the user's local
        speakers/headphones (`device_index`), independent of broadcast."""
        self.stop_monitor()
        self._ensure_render_thread()
        try:
            # Always use the fixed internal sample rate. PortAudio will
            # automatically resample to match the device if needed.
            logger.info("Starting monitor stream at %d Hz", SAMPLE_RATE)

            # Use a fixed blocksize that matches our render thread exactly
            # to avoid timing mismatches that cause robotic audio.
            self._monitor_stream = sd.OutputStream(
                device=device_index,
                channels=2,
                samplerate=SAMPLE_RATE,
                dtype="float32",
                blocksize=PORT_AUDIO_BLOCKSIZE,
                callback=self._monitor_callback,
            )
            self._monitor_stream.start()
            logger.info("Monitor stream started on device %s", device_index)
        except Exception as exc:
            logger.error("Failed to start monitor stream: %s", exc)
            self._monitor_stream = None
            raise

    def stop_monitor(self) -> None:
        if self._monitor_stream is not None:
            try:
                self._monitor_stream.stop()
                self._monitor_stream.close()
            except Exception as exc:
                logger.warning("Error stopping monitor stream: %s", exc)
            finally:
                self._monitor_stream = None

    def shutdown(self) -> None:
        self.stop_broadcast()
        self.stop_monitor()
        if self._render_thread is not None:
            self._render_thread.stop()
            self._render_thread.join(timeout=1.0)
            self._render_thread = None
        self.stop_all_sounds()
