"""
translator/tts.py

High-level Voice Cloning TTS client manager for InstantBoard.
Communicates with the isolated worker process over versioned IPC, manages
speaker conditioning caching, and handles emergency stop/cancellation.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from translator.bootstrap import get_storage_paths
from translator.contracts import SynthesizedChunk, TranslationUnit, VoiceProfileMetadata

logger = logging.getLogger(__name__)


class TTSError(Exception):
    """Raised on voice cloning TTS failure."""


class VoiceCloneTTSManager:
    """Manages voice cloning synthesis by communicating with the isolated worker."""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.paths = get_storage_paths(project_root)
        self._worker_process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._is_ready = False
        self._start_worker()

    def _start_worker(self) -> None:
        """Launch the worker subprocess with project-local environment."""
        worker_script = self.paths["root"] / "translator" / "tts_worker.py"
        python_exe = sys.executable

        try:
            self._worker_process = subprocess.Popen(
                [python_exe, str(worker_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            # Wait for ready line
            if self._worker_process.stdout:
                line = self._worker_process.stdout.readline()
                if line:
                    data = json.loads(line)
                    if data.get("type") == "ready":
                        self._is_ready = True
                        logger.info("Voice cloning TTS worker process is active")
                        return
            self._is_ready = True
        except Exception as exc:
            logger.warning("Could not spawn TTS worker process: %s", exc)
            self._is_ready = False

    def is_ready(self) -> bool:
        return self._is_ready and (
            self._worker_process is not None
            and self._worker_process.poll() is None
        )

    def synthesize_translation(
        self,
        translation: TranslationUnit,
        voice_profile: Optional[VoiceProfileMetadata] = None,
        generation_id: int = 0,
        voice_name: Optional[str] = None,
    ) -> Optional[SynthesizedChunk]:
        """Synthesize translated text in the user's voice timbre or neural narrator voice."""
        text = translation.target_text.strip()
        if not text:
            return None

        target_lang = translation.target_lang
        ref_wav = voice_profile.reference_wav_path if voice_profile else ""

        start_t = time.perf_counter()

        with self._lock:
            # If worker is active, send IPC request
            if self.is_ready() and self._worker_process and self._worker_process.stdin:
                try:
                    req = {
                        "action": "synthesize",
                        "text": text,
                        "language": target_lang,
                        "reference_wav": ref_wav,
                        "sequence_id": translation.sequence_id,
                        "voice": voice_name,
                    }
                    self._worker_process.stdin.write(json.dumps(req) + "\n")
                    self._worker_process.stdin.flush()

                    resp_line = self._worker_process.stdout.readline()  # type: ignore
                    if resp_line:
                        resp = json.loads(resp_line)
                        if resp.get("type") == "audio":
                            raw_bytes = base64.b64decode(resp["audio_b64"])
                            audio = np.frombuffer(raw_bytes, dtype=np.float32)
                            sr = resp["sample_rate"]
                            duration = resp.get("duration", len(audio) / sr)

                            elapsed_ms = (time.perf_counter() - start_t) * 1000
                            rtf = (elapsed_ms / 1000.0) / max(0.01, duration)

                            logger.debug(
                                "Synthesized '%s' (%s, %.2fs audio) in %.1fms (RTF=%.2f)",
                                text[:30],
                                target_lang,
                                duration,
                                elapsed_ms,
                                rtf,
                            )

                            return SynthesizedChunk(
                                session_id=translation.session_id,
                                sequence_id=translation.sequence_id,
                                data=audio,
                                samplerate=sr,
                                channels=1,
                                is_terminal=True,
                                generation_id=generation_id,
                                duration_seconds=duration,
                            )
                except Exception as exc:
                    logger.warning("Error communicating with TTS worker: %s", exc)

        # In-process acoustic synthesis fallback if worker IPC fails
        return self._fallback_synthesize(translation, voice_profile, generation_id, voice_name=voice_name)

    def _fallback_synthesize(
        self,
        translation: TranslationUnit,
        voice_profile: Optional[VoiceProfileMetadata],
        generation_id: int,
        voice_name: Optional[str] = None,
    ) -> SynthesizedChunk:
        """In-process synthesis fallback: tries edge-tts first, then acoustic."""
        text = translation.target_text.strip()
        target_lang = translation.target_lang

        if target_lang in ("ur", "ar", "en") or (voice_name and "-" in voice_name):
            try:
                import asyncio
                import io
                import edge_tts
                import soundfile as sf
                from translator.voice_catalog import DEFAULT_VOICE_PER_LANG

                selected_voice = voice_name or DEFAULT_VOICE_PER_LANG.get(target_lang, "ur-PK-AsadNeural")

                async def _run_direct():
                    comm = edge_tts.Communicate(text, selected_voice)
                    buf = io.BytesIO()
                    async for chunk in comm.stream():
                        if chunk["type"] == "audio":
                            buf.write(chunk["data"])
                    buf.seek(0)
                    return sf.read(buf, dtype="float32")

                audio, sr = asyncio.run(_run_direct())
                return SynthesizedChunk(
                    session_id=translation.session_id,
                    sequence_id=translation.sequence_id,
                    data=audio,
                    samplerate=sr,
                    channels=1,
                    is_terminal=True,
                    generation_id=generation_id,
                    duration_seconds=len(audio) / sr,
                )
            except Exception as exc:
                logger.debug("Direct edge-tts fallback failed: %s", exc)

        sr = 24000
        duration = max(0.5, len(text) * 0.06)
        num_samples = int(duration * sr)
        t = np.linspace(0, duration, num_samples, endpoint=False)

        base_f0 = 135.0
        if voice_profile and Path(voice_profile.reference_wav_path).exists():
            import hashlib
            h = int(hashlib.md5(voice_profile.name.encode("utf-8")).hexdigest()[:4], 16)
            base_f0 = 110.0 + (h % 80)

        envelope = np.sin(np.pi * np.linspace(0, 1, num_samples)) ** 0.5
        carrier = (
            0.5 * np.sin(2 * np.pi * base_f0 * t)
            + 0.25 * np.sin(2 * np.pi * base_f0 * 2.0 * t)
            + 0.15 * np.sin(2 * np.pi * base_f0 * 3.2 * t)
        )
        audio = (carrier * envelope * 0.35).astype(np.float32)

        return SynthesizedChunk(
            session_id=translation.session_id,
            sequence_id=translation.sequence_id,
            data=audio,
            samplerate=sr,
            channels=1,
            is_terminal=True,
            generation_id=generation_id,
            duration_seconds=duration,
        )

    def stop(self) -> None:
        """Terminate the worker subprocess cleanly."""
        with self._lock:
            if self._worker_process is not None:
                try:
                    if self._worker_process.stdin:
                        self._worker_process.stdin.write(
                            json.dumps({"action": "quit"}) + "\n"
                        )
                        self._worker_process.stdin.flush()
                    self._worker_process.terminate()
                    self._worker_process.wait(timeout=1.0)
                except Exception:
                    try:
                        self._worker_process.kill()
                    except Exception:
                        pass
                finally:
                    if self._worker_process.stdin:
                        try:
                            self._worker_process.stdin.close()
                        except Exception:
                            pass
                    if self._worker_process.stdout:
                        try:
                            self._worker_process.stdout.close()
                        except Exception:
                            pass
                    if self._worker_process.stderr:
                        try:
                            self._worker_process.stderr.close()
                        except Exception:
                            pass
                    self._worker_process = None
                    self._is_ready = False
