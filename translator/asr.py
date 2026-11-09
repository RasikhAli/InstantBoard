"""
translator/asr.py

Streaming Automatic Speech Recognition (ASR) and Language Identification (LID)
using faster-whisper (CTranslate2 INT8) with hypothesis stabilization and hysteresis.
"""

from __future__ import annotations

import collections
import logging
import time
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Tuple

import numpy as np

from translator.bootstrap import get_storage_paths
from translator.contracts import TranscriptUnit, VADSegment

logger = logging.getLogger(__name__)


class ASRError(Exception):
    """Raised on ASR initialization or transcription error."""


class FasterWhisperASR:
    """Multilingual Speech Recognition & Language Identification engine.

    Uses CTranslate2 INT8 quantization on CPU for high performance and low memory.
    """

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        source_language: str = "auto",  # 'auto', 'ur', 'en', 'ar'
        beam_size: int = 1,
        compute_type: str = "int8",
        cpu_threads: int = 4,
    ) -> None:
        self.source_language = source_language
        self.beam_size = beam_size
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads

        if model_dir is None:
            paths = get_storage_paths()
            # Prefer large-v3-turbo if installed, else fallback to base
            turbo_dir = paths["models_asr"] / "faster-whisper-large-v3-turbo"
            base_dir = paths["models_asr"] / "faster-whisper-base"
            model_dir = turbo_dir if turbo_dir.exists() else base_dir

        self.model_dir = Path(model_dir)
        self._model = None
        self._is_ready = False

        # Language identification hysteresis state
        self._detected_lang_history: Deque[str] = collections.deque(maxlen=5)
        self._last_committed_text: str = ""

        self._init_model()

    def _init_model(self) -> None:
        """Load the local Whisper model with strict local files."""
        if not self.model_dir.exists():
            logger.warning("ASR model directory does not exist: %s", self.model_dir)
            return

        try:
            from faster_whisper import WhisperModel

            logger.info(
                "Loading faster-whisper from %s (compute_type=%s, threads=%d)",
                self.model_dir,
                self.compute_type,
                self.cpu_threads,
            )
            self._model = WhisperModel(
                str(self.model_dir),
                device="cpu",
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
                local_files_only=True,
            )
            self._is_ready = True
            logger.info("Faster-whisper model loaded and ready on CPU")
        except Exception as exc:
            logger.error("Failed to load faster-whisper model: %s", exc)
            self._model = None
            self._is_ready = False

    def ensure_model_loaded(self) -> bool:
        """Attempt to re-initialize model if files were downloaded after startup."""
        if not self.is_ready:
            paths = get_storage_paths()
            turbo_dir = paths["models_asr"] / "faster-whisper-large-v3-turbo"
            base_dir = paths["models_asr"] / "faster-whisper-base"
            self.model_dir = turbo_dir if turbo_dir.exists() else base_dir
            self._init_model()
        return self.is_ready

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self._model is not None

    def set_source_language(self, lang: str) -> None:
        """Set manual source language ('ur', 'en', 'ar') or 'auto'."""
        self.source_language = lang
        self._detected_lang_history.clear()

    def transcribe_segment(
        self,
        segment: VADSegment,
        generation_id: int = 0,
    ) -> Optional[TranscriptUnit]:
        """Transcribe an isolated voice-active segment from VAD."""
        if not self.is_ready:
            raise ASRError("ASR model is not initialized or model files are missing.")

        audio = segment.audio
        if len(audio) == 0:
            return None

        # Determine language parameter for Whisper
        lang_param = None if self.source_language == "auto" else self.source_language

        start_t = time.perf_counter()

        try:
            segments_gen, info = self._model.transcribe(
                audio,
                language=lang_param,
                beam_size=self.beam_size,
                best_of=1,
                temperature=0.0,
                vad_filter=False,  # Audio is already VAD-filtered by Silero
                condition_on_previous_text=False,
            )

            text_pieces = []
            for seg in segments_gen:
                text_pieces.append(seg.text.strip())

            raw_text = " ".join(text_pieces).strip()
            if not raw_text:
                return None

            # Resolve language with hysteresis
            detected_lang = info.language
            lang_prob = float(info.language_probability)

            effective_lang = self._resolve_language(detected_lang, lang_prob)

            # Deduplicate immediate repeats from segment boundary overlap
            clean_text = self._deduplicate_overlap(raw_text)
            if not clean_text:
                return None

            self._last_committed_text = clean_text
            elapsed_ms = (time.perf_counter() - start_t) * 1000

            logger.debug(
                "ASR transcribed (%s, %.1f%%, %.1fms): '%s'",
                effective_lang,
                lang_prob * 100,
                elapsed_ms,
                clean_text,
            )

            return TranscriptUnit(
                session_id=segment.session_id,
                sequence_id=segment.sequence_id,
                text=clean_text,
                language=effective_lang,
                language_confidence=lang_prob,
                is_committed=True,
                start_time=segment.start_ts,
                end_time=segment.end_ts,
                generation_id=generation_id,
            )

        except Exception as exc:
            logger.exception("ASR transcription error")
            raise ASRError(f"Transcription failed: {exc}") from exc

    def _resolve_language(self, detected: str, prob: float) -> str:
        """Apply hysteresis if in auto-detection mode to prevent flapping."""
        if self.source_language != "auto":
            return self.source_language

        if prob >= 0.6:
            self._detected_lang_history.append(detected)
        elif not self._detected_lang_history:
            self._detected_lang_history.append(detected)

        # Most common recent language in history
        counts: Dict[str, int] = {}
        for l in self._detected_lang_history:
            counts[l] = counts.get(l, 0) + 1
        return max(counts, key=counts.get)  # type: ignore

    def _deduplicate_overlap(self, current: str) -> str:
        """Deduplicate phrases repeated across sliding windows."""
        if not self._last_committed_text:
            return current

        prev_words = self._last_committed_text.split()
        curr_words = current.split()

        # Check for overlap of 2 to 6 trailing words
        for k in range(min(len(prev_words), len(curr_words), 6), 1, -1):
            if prev_words[-k:] == curr_words[:k]:
                return " ".join(curr_words[k:]).strip()

        return current
