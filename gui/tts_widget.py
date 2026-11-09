"""
gui/tts_widget.py

TTS panel for InstantBoard — powered by Kyutai Pocket TTS.

Features:
  - Text input with 1.5-second debounce: TTS generates automatically after
    you stop typing, just like the Kyutai web demo.
  - Voice dropdown with all 23 voices from the Kyutai website.
  - Play / Pause / Replay buttons.
  - Audio streamed in chunks through the existing AudioMixer so it also
    routes through VB-CABLE when Soundboard mode is active.
  - Graceful degradation: if pocket-tts is not installed a clear install
    message is shown instead of crashing.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from audio.mixer import AudioMixer
from utils.icons import get_icon

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice catalogue — Curated Urdu & Arabic Neural voices + Kyutai voices
# ---------------------------------------------------------------------------
VOICES = [
    # ── Curated Urdu Neural Voices ──
    ("Asad (Urdu Male Narrator)",              "ur-PK-AsadNeural"),
    ("Uzma (Urdu Female)",                     "ur-PK-UzmaNeural"),
    ("Gul (Urdu Female - India)",              "ur-IN-GulNeural"),
    ("Salman (Urdu Male - India)",             "ur-IN-SalmanNeural"),

    # ── Curated Arabic Neural Voices ──
    ("Hamed (Arabic Male - Hijazi/Saudi)",     "ar-SA-HamedNeural"),
    ("Zariyah (Arabic Female - Classical)",    "ar-SA-ZariyahNeural"),
    ("Shakir (Arabic Male - Egyptian)",        "ar-EG-ShakirNeural"),

    # ── Curated English Neural Voices ──
    ("Guy (US Male Narrator)",                 "en-US-GuyNeural"),
    ("Jenny (US Female)",                      "en-US-JennyNeural"),
    ("Ryan (UK Male)",                         "en-GB-RyanNeural"),
    ("Sonia (UK Female)",                      "en-GB-SoniaNeural"),

    # ── Kyutai Pocket TTS Voices ──
    ("Jane (f, conversation)",          "jane"),
    ("Alba (m, reading)",               "alba"),
    ("Bill Boerst (m, reading)",        "bill_boerst"),
    ("Caro Davy (f, reading)",          "caro_davy"),
    ("Peter Yearsley (m, reading)",     "peter_yearsley"),
    ("Stuart Bell (m, reading)",        "stuart_bell"),
    ("Anna (f, conversation)",          "anna"),
    ("Azelma (f, reading)",             "azelma"),
    ("Charles (m, conversation)",       "charles"),
    ("Eponine (f, reading)",            "eponine"),
    ("Eve (f, conversation)",           "eve"),
    ("Fantine (f, reading)",            "fantine"),
    ("George (m, conversation)",        "george"),
    ("Mary (f, conversation)",          "mary"),
    ("Michael (m, conversation)",       "michael"),
    ("Paul (m, conversation)",          "paul"),
    ("Vera (f, conversation)",          "vera"),
    ("Jean (m, conversation)",          "jean"),
    ("Estelle (French, f)",             "estelle"),
    ("Giovanni (Italian, m)",           "giovanni"),
    ("Juergen (German, m)",             "juergen"),
    ("Lola (Spanish, f)",               "lola"),
    ("Rafael (Brazilian Portuguese, m)","rafael"),
]

SAMPLE_RATE = 24_000          # Pocket TTS & Edge TTS output normalized to 24 kHz
DEBOUNCE_MS = 1000           # ms after last keypress before TTS fires (1 second)
CHUNK_DTYPE = np.float32


# ===========================================================================
# Background worker
# ===========================================================================
class TTSWorker(QObject):
    """
    Runs in a dedicated QThread.  Loads the Pocket TTS model once using local
    cache, and accepts generation requests via the ``generate`` slot for both
    Pocket TTS and high-accuracy Neural Urdu voices.

    Emits:
      model_ready()              — model loaded and ready
      model_error(str)           — load failed
      chunk_ready(np.ndarray)    — one audio chunk (float32 @ 24 kHz)
      generation_started()       — a new utterance is beginning
      generation_done()          — utterance finished (or was cancelled)
      status(str)                — human-readable status update
    """

    model_ready       = Signal()
    model_error       = Signal(str)
    chunk_ready       = Signal(object)      # np.ndarray
    generation_started = Signal()
    generation_done   = Signal()
    status            = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._model = None
        self._voice_states: dict[str, object] = {}
        self._cancel_event = threading.Event()

    # ------------------------------------------------------------------
    @Slot()
    def load_model(self) -> None:
        """Load Pocket TTS model with cache-first lookup to prevent repeated downloads."""
        try:
            self.status.emit("Loading Kyutai Pocket TTS model…")
            import pocket_tts.models.tts_model as tm
            from huggingface_hub import hf_hub_download
            from pathlib import Path

            orig_dl = getattr(tm, "_orig_dl_if_needed", None)
            if orig_dl is None:
                orig_dl = tm.download_if_necessary
                tm._orig_dl_if_needed = orig_dl

            def _cached_dl(file_path: str):
                if file_path.startswith("hf://"):
                    clean = file_path.removeprefix("hf://")
                    parts = clean.split("/")
                    repo_id = "/".join(parts[:2])
                    fname = "/".join(parts[2:])
                    rev = None
                    if "@" in fname:
                        fname, rev = fname.split("@")
                    try:
                        return Path(hf_hub_download(repo_id=repo_id, filename=fname, revision=rev, local_files_only=True))
                    except Exception:
                        pass
                return orig_dl(file_path)

            tm.download_if_necessary = _cached_dl

            from pocket_tts import TTSModel  # type: ignore
            self._model = TTSModel.load_model()
            self.model_ready.emit()
            self.status.emit("Ready (Pocket TTS, Urdu & Arabic Voices active)")
        except ImportError:
            self.model_ready.emit()
            self.status.emit("Urdu & Arabic Neural Voices active (Pocket TTS not installed)")
        except Exception as exc:
            logger.exception("Pocket TTS local model load note: %s", exc)
            self.model_ready.emit()
            self.status.emit("Ready (Urdu & Arabic Neural Voices active)")

    # ------------------------------------------------------------------
    @Slot(str, str)
    def generate(self, text: str, voice_id: str) -> None:
        """Generate audio for *text* using *voice_id*, streaming chunks."""
        text = text.strip()
        if not text:
            return

        if voice_id.startswith("ur-") or voice_id.startswith("en-") or "-" in voice_id:
            self._generate_edge(text, voice_id)
            return

        if self._model is None:
            self.status.emit("Pocket TTS model is still loading…")
            return

        self._cancel_event.clear()
        self.generation_started.emit()
        self.status.emit(f"Generating speech as {voice_id}…")

        try:
            voice_state = self._get_voice_state(voice_id)
            for chunk in self._model.generate_audio_stream(voice_state, text):
                if self._cancel_event.is_set():
                    break
                if chunk is not None:
                    if hasattr(chunk, "cpu"):
                        chunk = chunk.cpu().numpy()
                    if len(chunk) > 0:
                        self.chunk_ready.emit(chunk)
            self.generation_done.emit()
            self.status.emit("Done")
        except Exception as exc:
            logger.exception("TTS generation error")
            self.generation_done.emit()
            self.status.emit(f"Error: {exc}")

    def _generate_edge(self, text: str, voice_id: str) -> None:
        """High-accuracy Neural Edge TTS generation supporting Urdu, Arabic, English, and Roman Urdu."""
        import asyncio
        import io
        import sys
        import edge_tts
        import soundfile as sf
        from audio.mixer import _resample_linear
        from utils.transliteration import transliterate_roman_urdu, is_latin_text

        # Avoid Windows ProactorEventLoop SSL transport shutdown issues
        if sys.platform == "win32":
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except Exception:
                pass

        self._cancel_event.clear()
        self.generation_started.emit()

        # If voice is Urdu and user typed in Latin / Roman Urdu (e.g. "yehi baat hai"),
        # automatically transliterate to proper Urdu script ("یہی بات ہے")
        if voice_id.startswith("ur-") and is_latin_text(text):
            spoken_text = transliterate_roman_urdu(text)
            logger.info("Transliterated Roman Urdu '%s' -> '%s' for %s", text, spoken_text, voice_id)
            self.status.emit(f"Speaking: '{spoken_text}' ({voice_id})…")
        elif voice_id.startswith("ar-"):
            spoken_text = text
            self.status.emit(f"Generating Arabic speech as {voice_id}…")
        elif voice_id.startswith("ur-"):
            spoken_text = text
            self.status.emit(f"Generating Urdu speech as {voice_id}…")
        else:
            spoken_text = text
            self.status.emit(f"Generating speech as {voice_id}…")

        async def _run():
            comm = edge_tts.Communicate(spoken_text, voice_id)
            buf = io.BytesIO()
            async for chunk in comm.stream():
                if self._cancel_event.is_set():
                    break
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf

        try:
            buf = asyncio.run(_run())
            if self._cancel_event.is_set():
                self.generation_done.emit()
                self.status.emit("Cancelled")
                return

            buf.seek(0)
            audio, sr = sf.read(buf, dtype="float32")
            if sr != SAMPLE_RATE and len(audio) > 0:
                audio = _resample_linear(audio, sr, SAMPLE_RATE)

            chunk_size = 2400  # 100ms at 24kHz
            for i in range(0, len(audio), chunk_size):
                if self._cancel_event.is_set():
                    break
                self.chunk_ready.emit(audio[i : i + chunk_size])

            self.generation_done.emit()
            self.status.emit("Done")
        except Exception as exc:
            logger.exception("Edge TTS generation error")
            self.generation_done.emit()
            self.status.emit(f"Error: {exc}")

    # ------------------------------------------------------------------
    @Slot()
    def cancel(self) -> None:
        """Signal the current generation to stop at the next chunk boundary."""
        self._cancel_event.set()

    # ------------------------------------------------------------------
    def _get_voice_state(self, voice_id: str) -> object:
        """Cache voice states so switching voices is fast after first load."""
        if voice_id not in self._voice_states:
            self.status.emit(f"Preparing voice '{voice_id}'…")
            state = self._model.get_state_for_audio_prompt(voice_id)
            self._voice_states[voice_id] = state
        return self._voice_states[voice_id]


# ===========================================================================
# Waveform / pulse animation widget
# ===========================================================================
class PulseBar(QWidget):
    """A simple animated pulse bar that lights up while audio is playing."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self._active = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.15) % (2 * 3.14159)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter, QLinearGradient
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if not self._active:
            painter.fillRect(0, 0, w, h, QColor("#33333f"))
            return
        import math
        alpha = int(180 + 70 * math.sin(self._phase))
        color = QColor(124, 92, 255, alpha)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(61, 220, 151, alpha))
        grad.setColorAt(0.5, QColor(124, 92, 255, alpha))
        grad.setColorAt(1.0, QColor(61, 220, 151, alpha))
        painter.fillRect(0, 0, w, h, grad)


# ===========================================================================
# Main TTS Widget
# ===========================================================================
class TTSWidget(QWidget):
    """
    The TTS panel.  Drop it into any layout — it wires itself to the
    provided AudioMixer for audio output.
    """

    # Signals forwarded to main window for VB-CABLE prep
    tts_started  = Signal()
    tts_finished = Signal()

    def __init__(
        self,
        mixer: AudioMixer,
        prepare_playback_fn: Optional[Callable] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._mixer = mixer
        self._prepare_playback_fn = prepare_playback_fn

        # Audio accumulation buffer for pause/replay
        self._audio_buffer: list[np.ndarray] = []
        self._is_playing = False
        self._is_paused = False
        self._model_ready = True
        self._generation_active = False

        # Debounce timer — fires when user stops typing
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._on_debounce)

        self._build_ui()
        self._start_worker()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # ── Header row ──────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("Text-to-Speech")
        title.setObjectName("TTSTitle")
        header.addWidget(title)
        header.addStretch(1)

        powered = QLabel("Powered by  Kyutai Pocket TTS & Edge Neural")
        powered.setObjectName("MutedLabel")
        header.addWidget(powered)
        root.addLayout(header)

        # ── Voice selector ───────────────────────────────────────────
        voice_row = QHBoxLayout()
        voice_label = QLabel("Voice")
        voice_label.setObjectName("MutedLabel")
        voice_label.setFixedWidth(40)
        voice_row.addWidget(voice_label)

        self.voice_combo = QComboBox()
        self.voice_combo.setObjectName("VoiceCombo")
        for display_name, voice_id in VOICES:
            self.voice_combo.addItem(display_name, voice_id)
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        self.voice_combo.setEnabled(True)  # Urdu neural voices available immediately
        voice_row.addWidget(self.voice_combo, stretch=1)
        root.addLayout(voice_row)

        # ── Text input ───────────────────────────────────────────────
        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("TTSTextEdit")
        self.text_edit.setPlaceholderText(
            "Start typing (Urdu, Arabic, Roman Urdu, or English)… speech will generate automatically after you pause."
        )
        self.text_edit.setMinimumHeight(120)
        self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.text_edit.setEnabled(True)  # enabled immediately
        self.text_edit.installEventFilter(self)
        root.addWidget(self.text_edit, stretch=1)

        # ── Pulse bar ────────────────────────────────────────────────
        self.pulse_bar = PulseBar()
        root.addWidget(self.pulse_bar)

        # ── Controls row ─────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        self.play_btn = QPushButton()
        self.play_btn.setObjectName("TTSPlayBtn")
        self.play_btn.setIcon(get_icon("play", 20, "#ffffff"))
        self.play_btn.setFixedSize(44, 44)
        self.play_btn.setToolTip("Play / Resume")
        self.play_btn.clicked.connect(self._on_play_clicked)
        ctrl.addWidget(self.play_btn)

        self.pause_btn = QPushButton()
        self.pause_btn.setObjectName("IconButton")
        self.pause_btn.setIcon(get_icon("pause", 18))
        self.pause_btn.setFixedSize(40, 40)
        self.pause_btn.setToolTip("Pause")
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.pause_btn.setEnabled(False)
        ctrl.addWidget(self.pause_btn)

        self.replay_btn = QPushButton()
        self.replay_btn.setObjectName("IconButton")
        self.replay_btn.setIcon(get_icon("refresh", 18))
        self.replay_btn.setFixedSize(40, 40)
        self.replay_btn.setToolTip("Replay last speech")
        self.replay_btn.clicked.connect(self._on_replay_clicked)
        self.replay_btn.setEnabled(False)
        ctrl.addWidget(self.replay_btn)

        ctrl.addStretch(1)

        # Debounce label
        self.debounce_label = QLabel("Auto-speak in: —")
        self.debounce_label.setObjectName("MutedLabel")
        ctrl.addWidget(self.debounce_label)

        root.addLayout(ctrl)

        # ── Status bar ───────────────────────────────────────────────
        status_row = QHBoxLayout()
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(16, 16)
        self.status_icon.setPixmap(get_icon("soundboard", 14, "#3ddc97").pixmap(14, 14))
        status_row.addWidget(self.status_icon)

        self.status_label = QLabel("Ready — select voice and start typing")
        self.status_label.setObjectName("TTSStatus")
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

        # ── Debounce countdown timer (UI only) ───────────────────────
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(200)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._debounce_start_ms: float = 0.0

    # ------------------------------------------------------------------
    # Worker thread setup
    # ------------------------------------------------------------------
    def _start_worker(self) -> None:
        self._worker_thread = QThread(self)
        self._worker = TTSWorker()
        self._worker.moveToThread(self._worker_thread)

        self._worker.model_ready.connect(self._on_model_ready)
        self._worker.model_error.connect(self._on_model_error)
        self._worker.chunk_ready.connect(self._on_chunk)
        self._worker.generation_started.connect(self._on_gen_started)
        self._worker.generation_done.connect(self._on_gen_done)
        self._worker.status.connect(self._set_status)

        self._worker_thread.started.connect(self._worker.load_model)
        self._worker_thread.start()

    # ------------------------------------------------------------------
    # Slots — model lifecycle
    # ------------------------------------------------------------------
    @Slot()
    def _on_model_ready(self) -> None:
        self._model_ready = True
        self.text_edit.setEnabled(True)
        self.voice_combo.setEnabled(True)
        self._set_status("Ready (Pocket TTS, Urdu & Arabic Voices active)")
        self.status_icon.setPixmap(
            get_icon("soundboard", 14, "#3ddc97").pixmap(14, 14)
        )

    @Slot(str)
    def _on_model_error(self, msg: str) -> None:
        # Keep enabled for Urdu & Arabic neural voices even if Pocket TTS fails
        self._model_ready = True
        self.text_edit.setEnabled(True)
        self.voice_combo.setEnabled(True)
        self._set_status("Urdu & Arabic Neural Voices active (Pocket TTS offline)")
        self.status_icon.setPixmap(
            get_icon("soundboard", 14, "#3ddc97").pixmap(14, 14)
        )

    # ------------------------------------------------------------------
    # Slots — generation lifecycle
    # ------------------------------------------------------------------
    @Slot()
    def _on_gen_started(self) -> None:
        self._generation_active = True
        self._audio_buffer.clear()
        self._is_playing = True
        self._is_paused = False
        self.pulse_bar.set_active(True)
        self.pause_btn.setEnabled(True)
        self.replay_btn.setEnabled(False)
        self.play_btn.setIcon(get_icon("stop", 20, "#ff5c7a"))
        self.play_btn.setToolTip("Stop")
        self.tts_started.emit()

    @Slot(object)
    def _on_chunk(self, chunk: np.ndarray) -> None:
        """Receive one audio chunk and store it in buffer."""
        self._audio_buffer.append(chunk.copy())

    @Slot()
    def _on_gen_done(self) -> None:
        self._generation_active = False
        if self._audio_buffer:
            try:
                full_audio = np.concatenate(self._audio_buffer, axis=0)
                self._mixer.add_sound(full_audio, SAMPLE_RATE)
            except Exception as exc:
                logger.warning("Error playing TTS audio: %s", exc)
        self._is_playing = False
        self.pulse_bar.set_active(False)
        self.pause_btn.setEnabled(False)
        has_audio = bool(self._audio_buffer)
        self.replay_btn.setEnabled(has_audio)
        self.play_btn.setIcon(get_icon("play", 20, "#ffffff"))
        self.play_btn.setToolTip("Play / Resume")
        self.tts_finished.emit()

    # ------------------------------------------------------------------
    # Text / debounce handling
    # ------------------------------------------------------------------
    def _on_text_changed(self) -> None:
        if not self._model_ready:
            return
        text = self.text_edit.toPlainText().strip()
        if not text:
            self._debounce.stop()
            self._countdown_timer.stop()
            self.debounce_label.setText("Auto-speak in: —")
            return

        # Cancel current generation before restarting debounce
        if self._generation_active:
            self._worker.cancel()

        self._debounce.start()
        self._debounce_start_ms = time.monotonic() * 1000
        self._countdown_timer.start()

    def _update_countdown(self) -> None:
        elapsed = time.monotonic() * 1000 - self._debounce_start_ms
        remaining = max(0.0, DEBOUNCE_MS - elapsed) / 1000
        self.debounce_label.setText(f"Auto-speak in: {remaining:.1f}s")
        if remaining <= 0:
            self._countdown_timer.stop()
            self.debounce_label.setText("Auto-speak in: —")

    def _on_debounce(self) -> None:
        """Called when debounce timer fires — kick off generation."""
        self._countdown_timer.stop()
        self.debounce_label.setText("Auto-speak in: —")
        self._trigger_generation()

    def _trigger_generation(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text or not self._model_ready:
            return
        if self._prepare_playback_fn:
            try:
                self._prepare_playback_fn()
            except Exception:
                pass
        voice_id = self.voice_combo.currentData()
        # Use Qt.QueuedConnection so it crosses to the worker thread
        from PySide6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(
            self._worker,
            "generate",
            Qt.QueuedConnection,
            Q_ARG(str, text),
            Q_ARG(str, voice_id),
        )

    # ------------------------------------------------------------------
    # Control buttons
    # ------------------------------------------------------------------
    def _on_play_clicked(self) -> None:
        if self._generation_active:
            # Acting as Stop
            self._worker.cancel()
        else:
            # (Re-)generate current text
            if self._generation_active:
                self._worker.cancel()
            self._trigger_generation()

    def _on_pause_clicked(self) -> None:
        """Pause: cancel current stream so the model stops."""
        self._is_paused = True
        self._worker.cancel()
        self.pulse_bar.set_active(False)
        self.pause_btn.setEnabled(False)
        self.replay_btn.setEnabled(bool(self._audio_buffer))
        self._set_status("Paused")

    def _on_replay_clicked(self) -> None:
        """Replay the buffered audio from the last generation."""
        if not self._audio_buffer:
            return
        if self._prepare_playback_fn:
            try:
                self._prepare_playback_fn()
            except Exception:
                pass
        self._is_playing = True
        self.pulse_bar.set_active(True)
        self.replay_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.play_btn.setIcon(get_icon("stop", 20, "#ff5c7a"))
        self._set_status("Replaying…")

        full_audio = np.concatenate(self._audio_buffer, axis=0)
        self._mixer.add_sound(full_audio, SAMPLE_RATE)
        self._on_replay_done()

    @Slot()
    def _on_replay_done(self) -> None:
        self._is_playing = False
        self.pulse_bar.set_active(False)
        self.pause_btn.setEnabled(False)
        self.replay_btn.setEnabled(True)
        self.play_btn.setIcon(get_icon("play", 20, "#ffffff"))
        self._set_status("Done")

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        if obj is self.text_edit and event.type() == QEvent.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (key_event.modifiers() & Qt.ShiftModifier):
                self._debounce.stop()
                self._countdown_timer.stop()
                self.debounce_label.setText("Auto-speak in: —")
                self._trigger_generation()
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Voice change
    # ------------------------------------------------------------------
    def _on_voice_changed(self, _index: int) -> None:
        """When voice changes mid-generation, restart."""
        if self._generation_active:
            self._worker.cancel()
            self._trigger_generation()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @Slot(str)
    def _set_status(self, msg: str) -> None:
        self.status_label.setText(msg)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Call from MainWindow.closeEvent to clean up the worker thread."""
        self._debounce.stop()
        self._countdown_timer.stop()
        if self._worker_thread.isRunning():
            self._worker.cancel()
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
