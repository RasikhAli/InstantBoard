"""
translator/pipeline.py

Complete asynchronous streaming orchestrator for InstantBoard's Local Live Translator.
Wired between MicrophoneRecorder, Silero VAD, Faster-Whisper ASR, NLLB Translation,
Voice-Cloning TTS, and AudioMixer.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from typing import Callable, Optional

import numpy as np

from translator.asr import FasterWhisperASR
from translator.contracts import (
    AudioFrame,
    CancellationGeneration,
    PipelineMetrics,
    SessionStatus,
    SynthesizedChunk,
    TranscriptUnit,
    TranslationUnit,
    VADSegment,
    VoiceProfileMetadata,
)
from translator.profiles import VoiceProfileManager
from translator.translation import CTranslate2NLLBTranslator
from translator.tts import VoiceCloneTTSManager
from translator.vad import SileroVADStream

logger = logging.getLogger(__name__)


class StreamingTranslatorPipeline:
    """Orchestrates continuous live speech-to-speech translation on background threads."""

    def __init__(
        self,
        audio_mixer,  # audio.mixer.AudioMixer
        on_transcript_update: Optional[Callable[[TranscriptUnit], None]] = None,
        on_translation_update: Optional[Callable[[TranslationUnit], None]] = None,
        on_metrics_update: Optional[Callable[[PipelineMetrics], None]] = None,
        on_status_change: Optional[Callable[[SessionStatus, str], None]] = None,
    ) -> None:
        self.mixer = audio_mixer
        self.on_transcript_update = on_transcript_update
        self.on_translation_update = on_translation_update
        self.on_metrics_update = on_metrics_update
        self.on_status_change = on_status_change

        self.source_language = "auto"
        self.target_language = "en"
        self.target_voice: Optional[str] = None
        self.active_profile: Optional[VoiceProfileMetadata] = None

        # Thread-safe work queues
        self._mic_queue: queue.Queue[AudioFrame] = queue.Queue(maxsize=100)
        self._speech_queue: queue.Queue[VADSegment] = queue.Queue(maxsize=20)
        self._translation_queue: queue.Queue[TranscriptUnit] = queue.Queue(maxsize=20)
        self._tts_queue: queue.Queue[TranslationUnit] = queue.Queue(maxsize=20)

        # Pipeline components
        self.vad = SileroVADStream()
        self.asr = FasterWhisperASR(source_language=self.source_language)
        self.translator = CTranslate2NLLBTranslator()
        self.tts = VoiceCloneTTSManager()
        self.profiles = VoiceProfileManager()

        # State & cancellation
        self._cancellation = CancellationGeneration()
        self._session_id = ""
        self._is_running = False
        self._stop_event = threading.Event()
        self._status = SessionStatus.IDLE

        # Worker threads
        self._threads: list[threading.Thread] = []

    @property
    def status(self) -> SessionStatus:
        return self._status

    def _set_status(self, status: SessionStatus, message: str = "") -> None:
        self._status = status
        if self.on_status_change:
            self.on_status_change(status, message)

    def set_languages(self, source_lang: str, target_lang: str) -> None:
        """Update source and target language configurations."""
        self.source_language = source_lang
        self.target_language = target_lang
        self.asr.set_source_language(source_lang)
        logger.info(
            "Translator languages configured: [%s -> %s]", source_lang, target_lang
        )

    def set_voice_profile(self, profile: Optional[VoiceProfileMetadata]) -> None:
        self.active_profile = profile
        logger.info(
            "Active voice profile set to: %s",
            profile.name if profile else "Default Acoustic",
        )

    def set_target_voice(self, voice_id: Optional[str]) -> None:
        """Configure the active neural narrator voice (e.g. Asad, Hamed, Guy)."""
        self.target_voice = voice_id
        logger.info("Active narrator voice configured: %s", voice_id)

    # ------------------------------------------------------------------
    # Microphone Audio Ingestion Callback
    # ------------------------------------------------------------------
    def on_microphone_frame(self, data: np.ndarray, samplerate: int) -> None:
        """Invoked from MicrophoneRecorder listener without blocking."""
        if not self._is_running:
            return

        frame = AudioFrame(
            data=data.copy(),
            samplerate=samplerate,
            channels=1 if data.ndim == 1 else data.shape[1],
            session_id=self._session_id,
        )
        try:
            self._mic_queue.put_nowait(frame)
        except queue.Full:
            pass  # Drop oldest frame to avoid unbounded buffer buildup

    # ------------------------------------------------------------------
    # Lifecycle: Start / Stop / Emergency Stop
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the live streaming translation session."""
        if self._is_running:
            return

        self._session_id = f"s2st_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        self._is_running = True
        self._stop_event.clear()
        self._cancellation.increment()
        self.vad.start_session(self._session_id)

        # Suppress physical mic on call output (VB-CABLE) so only translation is heard
        self.mixer.set_translator_active(True)

        self._clear_all_queues()

        # Start worker threads
        self._threads = [
            threading.Thread(
                target=self._vad_worker,
                daemon=True,
                name="TranslatorVADWorker",
            ),
            threading.Thread(
                target=self._asr_worker,
                daemon=True,
                name="TranslatorASRWorker",
            ),
            threading.Thread(
                target=self._translation_worker,
                daemon=True,
                name="TranslatorMTWorker",
            ),
            threading.Thread(
                target=self._tts_worker,
                daemon=True,
                name="TranslatorTTSWorker",
            ),
        ]
        for t in self._threads:
            t.start()

        self._set_status(SessionStatus.LISTENING, "Listening for speech…")
        logger.info("StreamingTranslatorPipeline started (session=%s)", self._session_id)

    def stop(self) -> None:
        """Gracefully stop translation and restore audio mixer."""
        if not self._is_running:
            return

        logger.info("Stopping StreamingTranslatorPipeline")
        self._is_running = False

        # Unsuppress physical microphone in mixer
        self.mixer.set_translator_active(False)

        # Flush any trailing speech in VAD
        tail_segment = self.vad.flush()
        if tail_segment:
            try:
                self._speech_queue.put(tail_segment, timeout=0.2)
            except (queue.Full, Exception):
                pass

        self._stop_event.set()
        self._set_status(SessionStatus.IDLE, "Translator stopped")

    def emergency_stop(self) -> None:
        """Instantly silence all translation audio and flush all pipeline queues."""
        logger.warning("EMERGENCY STOP triggered in translator")
        gen_id = self._cancellation.increment()
        self._clear_all_queues()
        self.mixer.clear_translator_audio()
        self.stop()
        self._set_status(SessionStatus.IDLE, "Emergency Stop triggered — silenced")

    def _clear_all_queues(self) -> None:
        for q in [
            self._mic_queue,
            self._speech_queue,
            self._translation_queue,
            self._tts_queue,
        ]:
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    # ------------------------------------------------------------------
    # Worker 1: VAD Segmentation
    # ------------------------------------------------------------------
    def _vad_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                frame = self._mic_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            segments = self.vad.process_audio(frame.data, frame.samplerate)
            for seg in segments:
                try:
                    self._speech_queue.put(seg, timeout=0.5)
                except queue.Full:
                    logger.warning("Speech queue full; dropping segment %d", seg.sequence_id)

    # ------------------------------------------------------------------
    # Worker 2: ASR & Language Identification
    # ------------------------------------------------------------------
    def _asr_worker(self) -> None:
        while not self._stop_event.is_set() or not self._speech_queue.empty():
            try:
                segment = self._speech_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            gen_id = self._cancellation.current_id
            try:
                self._set_status(SessionStatus.TRANSLATING, "Recognizing speech…")
                t0 = time.perf_counter()
                transcript = self.asr.transcribe_segment(segment, generation_id=gen_id)
                asr_ms = (time.perf_counter() - t0) * 1000

                if transcript and self._cancellation.is_valid(gen_id):
                    if self.on_transcript_update:
                        self.on_transcript_update(transcript)
                    self._translation_queue.put(transcript)

            except Exception as exc:
                logger.exception("ASR worker error: %s", exc)

    # ------------------------------------------------------------------
    # Worker 3: Translation Engine
    # ------------------------------------------------------------------
    def _translation_worker(self) -> None:
        while not self._stop_event.is_set() or not self._translation_queue.empty():
            try:
                transcript = self._translation_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            gen_id = transcript.generation_id
            if not self._cancellation.is_valid(gen_id):
                continue

            try:
                self._set_status(SessionStatus.TRANSLATING, "Translating text…")
                t0 = time.perf_counter()
                translation = self.translator.translate_unit(
                    transcript,
                    target_lang=self.target_language,
                    generation_id=gen_id,
                )
                mt_ms = (time.perf_counter() - t0) * 1000

                if translation and self._cancellation.is_valid(gen_id):
                    if self.on_translation_update:
                        self.on_translation_update(translation)
                    self._tts_queue.put(translation)

            except Exception as exc:
                logger.exception("Translation worker error: %s", exc)

    # ------------------------------------------------------------------
    # Worker 4: Voice-Cloning Synthesis & Audio Feed
    # ------------------------------------------------------------------
    def _tts_worker(self) -> None:
        while not self._stop_event.is_set() or not self._tts_queue.empty():
            try:
                translation = self._tts_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            gen_id = translation.generation_id
            if not self._cancellation.is_valid(gen_id):
                continue

            try:
                self._set_status(SessionStatus.SPEAKING, "Synthesizing cloned voice…")
                t0 = time.perf_counter()
                chunk = self.tts.synthesize_translation(
                    translation,
                    voice_profile=self.active_profile,
                    generation_id=gen_id,
                    voice_name=self.target_voice,
                )
                tts_ms = (time.perf_counter() - t0) * 1000

                if chunk and self._cancellation.is_valid(gen_id):
                    # Feed synthesized audio directly into AudioMixer broadcast stream
                    self.mixer.feed_translator_audio(chunk.data, chunk.samplerate)

                    # Update live metrics
                    total_lat = translation.latency_ms + tts_ms
                    metrics = PipelineMetrics(
                        session_id=self._session_id,
                        asr_latency_ms=0.0,
                        translation_latency_ms=translation.latency_ms,
                        tts_total_ms=tts_ms,
                        total_pipeline_latency_ms=total_lat,
                        tts_rtf=round((tts_ms / 1000.0) / max(0.01, chunk.duration_seconds), 2),
                        backlog_seconds=round(self._tts_queue.qsize() * 1.2, 1),
                        active_queue_items=self._tts_queue.qsize(),
                    )
                    if self.on_metrics_update:
                        self.on_metrics_update(metrics)

                    self._set_status(SessionStatus.LISTENING, "Listening for speech…")

            except Exception as exc:
                logger.exception("TTS worker error: %s", exc)
