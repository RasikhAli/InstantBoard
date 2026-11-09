"""
translator/contracts.py

Typed stage contracts, session tokens, and data models for the
InstantBoard Local Live Translator streaming pipeline.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np


class SessionStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    LISTENING = "listening"
    TRANSLATING = "translating"
    SPEAKING = "speaking"
    ERROR = "error"
    STOPPING = "stopping"


class LanguageCode(str, Enum):
    AUTO = "auto"
    URDU = "ur"
    ENGLISH = "en"
    ARABIC = "ar"


@dataclass
class AudioFrame:
    """Raw microphone frame captured from audio input stream."""

    data: np.ndarray  # float32 audio samples
    samplerate: int
    channels: int
    timestamp: float = field(default_factory=time.time)
    sequence_id: int = 0
    session_id: str = ""


@dataclass
class VADSegment:
    """A bounded segment of detected speech bounded by silence."""

    audio: np.ndarray  # float32, 16 kHz mono
    start_ts: float
    end_ts: float
    is_speech: bool
    confidence: float
    sequence_id: int
    session_id: str


@dataclass
class TranscriptUnit:
    """ASR transcription result (either tentative hypothesis or committed final text)."""

    session_id: str
    sequence_id: int
    text: str
    language: str  # e.g., 'ur', 'en', 'ar'
    language_confidence: float = 1.0
    is_committed: bool = False
    start_time: float = 0.0
    end_time: float = 0.0
    generation_id: int = 0
    tokens: List[int] = field(default_factory=list)


@dataclass
class TranslationUnit:
    """Unit of translated text ready for speech synthesis."""

    session_id: str
    sequence_id: int
    source_text: str
    source_lang: str
    target_text: str
    target_lang: str
    is_final: bool = True
    generation_id: int = 0
    latency_ms: float = 0.0


@dataclass
class SynthesizedChunk:
    """Synthesized PCM audio chunk from the voice cloning TTS engine."""

    session_id: str
    sequence_id: int
    data: np.ndarray  # float32 array
    samplerate: int
    channels: int = 1
    is_terminal: bool = False  # True if this is the last chunk of an utterance
    generation_id: int = 0
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.duration_seconds == 0.0 and self.samplerate > 0:
            self.duration_seconds = len(self.data) / self.samplerate


@dataclass
class PipelineMetrics:
    """Live performance, latency, and backlog indicators for the UI deck."""

    session_id: str = ""
    vad_latency_ms: float = 0.0
    asr_latency_ms: float = 0.0
    translation_latency_ms: float = 0.0
    tts_ttfb_ms: float = 0.0  # Time to first audio block
    tts_total_ms: float = 0.0
    total_pipeline_latency_ms: float = 0.0
    tts_rtf: float = 0.0  # Real Time Factor (compute_time / audio_duration)
    backlog_seconds: float = 0.0
    active_queue_items: int = 0
    cpu_usage_pct: float = 0.0
    ram_usage_mb: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class VoiceProfileMetadata:
    """Metadata for an enrolled user voice profile."""

    profile_id: str
    name: str
    created_at: float
    reference_wav_path: str
    duration_seconds: float
    sample_rate: int
    conditioning_cache_path: Optional[str] = None
    language: str = "en"
    notes: str = ""


@dataclass
class CancellationGeneration:
    """Tracks generation token to invalidate and discard stale inference output."""

    current_id: int = 0

    def increment(self) -> int:
        self.current_id += 1
        return self.current_id

    def is_valid(self, generation_id: int) -> bool:
        return generation_id == self.current_id
