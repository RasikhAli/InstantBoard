"""
translator/vad.py

Stateful Silero VAD (ONNX) streaming processor with recurrent state handling,
pre-roll, hangover, and bounded speech segment detection.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Deque, List, Optional
import collections

import numpy as np
import onnxruntime as ort

from translator.bootstrap import get_storage_paths
from translator.contracts import VADSegment

logger = logging.getLogger(__name__)

VAD_SAMPLE_RATE = 16000
VAD_FRAME_SAMPLES = 512  # Exactly 32ms at 16 kHz for Silero VAD v5


def resample_to_16k_mono(data: np.ndarray, src_rate: int) -> np.ndarray:
    """Statefully downsample audio to 16 kHz single-channel float32."""
    if data.ndim > 1:
        data = np.mean(data, axis=1)
    data = data.astype(np.float32)

    if src_rate == VAD_SAMPLE_RATE or len(data) == 0:
        return data

    duration = len(data) / src_rate
    dst_len = max(1, int(round(duration * VAD_SAMPLE_RATE)))
    src_indices = np.linspace(0, duration, num=len(data), endpoint=False)
    dst_indices = np.linspace(0, duration, num=dst_len, endpoint=False)
    return np.interp(dst_indices, src_indices, data).astype(np.float32)


class SileroVADStream:
    """Streams microphone audio through Silero VAD v5 (ONNX Runtime on CPU).

    Buffers 512-sample frames, tracks recurrent hidden state, and isolates
    active speech utterances with configurable pre-roll and silence hangover.
    """

    def __init__(
        self,
        onnx_model_path: Optional[Path] = None,
        threshold: float = 0.35,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 400,
        max_speech_duration_sec: float = 8.0,
        pre_roll_chunks: int = 4,  # ~128ms of pre-roll speech audio
    ) -> None:
        if onnx_model_path is None:
            paths = get_storage_paths()
            onnx_model_path = paths["models_vad"] / "silero_vad.onnx"

        self.model_path = Path(onnx_model_path)
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.max_speech_duration_sec = max_speech_duration_sec
        self.pre_roll_chunks = pre_roll_chunks

        self._session: Optional[ort.InferenceSession] = None
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr_tensor = np.array(VAD_SAMPLE_RATE, dtype=np.int64)

        # Incoming audio queue for frame chunking
        self._in_buffer = np.zeros((0,), dtype=np.float32)

        # State tracking for utterance assembly
        self._pre_roll: Deque[np.ndarray] = collections.deque(maxlen=pre_roll_chunks)
        self._current_speech_chunks: List[np.ndarray] = []
        self._is_speaking = False
        self._silence_frames_count = 0
        self._speech_frames_count = 0
        self._session_id = ""
        self._sequence_id = 0

        self._init_session()

    def _init_session(self) -> None:
        """Initialize the ONNX Runtime session if the model is installed."""
        if not self.model_path.exists():
            logger.warning("Silero VAD model not found at %s", self.model_path)
            return

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(
            str(self.model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.reset_state()
        logger.info("Silero VAD ONNX session initialized successfully on CPU")

    def ensure_session(self) -> bool:
        """Attempt to re-initialize ONNX session if model was downloaded after startup."""
        if self._session is None and self.model_path.exists():
            self._init_session()
        return self._session is not None

    def reset_state(self) -> None:
        """Reset the recurrent hidden state and accumulated buffers."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._in_buffer = np.zeros((0,), dtype=np.float32)
        self._pre_roll.clear()
        self._current_speech_chunks.clear()
        self._is_speaking = False
        self._silence_frames_count = 0
        self._speech_frames_count = 0

    def start_session(self, session_id: str) -> None:
        self._session_id = session_id
        self._sequence_id = 0
        self.reset_state()

    def process_audio(
        self,
        data: np.ndarray,
        src_samplerate: int,
        on_segment_ready: Optional[Callable[[VADSegment], None]] = None,
    ) -> List[VADSegment]:
        """Ingest raw audio (any sample rate/channels) and emit complete speech segments."""
        ready_segments: List[VADSegment] = []

        # Convert to 16 kHz mono
        pcm16k = resample_to_16k_mono(data, src_samplerate)
        self._in_buffer = np.concatenate([self._in_buffer, pcm16k])

        # Step in exact 512-sample frames
        while len(self._in_buffer) >= VAD_FRAME_SAMPLES:
            frame = self._in_buffer[:VAD_FRAME_SAMPLES]
            self._in_buffer = self._in_buffer[VAD_FRAME_SAMPLES:]

            prob = self._infer_frame(frame)
            segment = self._update_state_machine(frame, prob)
            if segment:
                ready_segments.append(segment)
                if on_segment_ready:
                    on_segment_ready(segment)

        return ready_segments

    def _infer_frame(self, frame: np.ndarray) -> float:
        """Run single 512-sample frame through the ONNX model."""
        if self._session is None:
            # Fallback simple energy-based VAD if ONNX model is missing
            energy = float(np.sqrt(np.mean(frame**2)))
            return 1.0 if energy > 0.02 else 0.0

        # Input shape: (1, 512)
        input_tensor = frame[np.newaxis, :]
        ort_inputs = {
            "input": input_tensor,
            "state": self._state,
            "sr": self._sr_tensor,
        }
        outputs = self._session.run(None, ort_inputs)
        prob = float(outputs[0][0, 0])
        self._state = outputs[1]
        return prob

    def _update_state_machine(
        self, frame: np.ndarray, prob: float
    ) -> Optional[VADSegment]:
        """State machine for speech onset, hangover, and segment completion."""
        silence_frame_limit = int(
            self.min_silence_duration_ms / (VAD_FRAME_SAMPLES / VAD_SAMPLE_RATE * 1000)
        )
        max_frames = int(
            self.max_speech_duration_sec / (VAD_FRAME_SAMPLES / VAD_SAMPLE_RATE)
        )

        if prob >= self.threshold:
            # Voice active frame
            self._silence_frames_count = 0
            self._speech_frames_count += 1

            if not self._is_speaking:
                self._is_speaking = True
                # Include pre-roll
                self._current_speech_chunks.extend(self._pre_roll)
                self._pre_roll.clear()

            self._current_speech_chunks.append(frame.copy())

            # Check maximum duration to force-flush long continuous speech
            if len(self._current_speech_chunks) >= max_frames:
                return self._emit_current_segment(force=True)

        else:
            # Silence frame
            if self._is_speaking:
                self._current_speech_chunks.append(frame.copy())
                self._silence_frames_count += 1

                if self._silence_frames_count >= silence_frame_limit:
                    return self._emit_current_segment(force=False)
            else:
                self._pre_roll.append(frame.copy())

        return None

    def flush(self) -> Optional[VADSegment]:
        """Flush any pending speech audio (e.g. on push-to-talk release or stop)."""
        if self._current_speech_chunks:
            return self._emit_current_segment(force=True)
        return None

    def _emit_current_segment(self, force: bool = False) -> Optional[VADSegment]:
        """Package accumulated speech frames into a VADSegment."""
        if not self._current_speech_chunks:
            self._is_speaking = False
            return None

        total_audio = np.concatenate(self._current_speech_chunks)
        duration_sec = len(total_audio) / VAD_SAMPLE_RATE

        self._current_speech_chunks.clear()
        self._is_speaking = False
        self._silence_frames_count = 0
        self._speech_frames_count = 0

        # Check minimum speech duration unless forced
        if not force and (duration_sec * 1000) < self.min_speech_duration_ms:
            return None

        self._sequence_id += 1
        return VADSegment(
            audio=total_audio,
            start_ts=0.0,
            end_ts=duration_sec,
            is_speech=True,
            confidence=1.0,
            sequence_id=self._sequence_id,
            session_id=self._session_id,
        )
