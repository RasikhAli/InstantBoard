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
# Voice catalogue — matches the Kyutai web demo <select> exactly
# ---------------------------------------------------------------------------
VOICES = [
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

SAMPLE_RATE = 24_000          # Pocket TTS outputs at 24 kHz
DEBOUNCE_MS = 500            # ms after last keypress before TTS fires
CHUNK_DTYPE = np.float32


# ===========================================================================
# Background worker
# ===========================================================================
class TTSWorker(QObject):
    """
    Runs in a dedicated QThread.  Loads the Pocket TTS model once, then
    accepts generation requests via the ``generate`` slot.

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
        """Load Pocket TTS model. Must be called once before ``generate``."""
        try:
            self.status.emit("Loading Kyutai Pocket TTS model…")
            from pocket_tts import TTSModel  # type: ignore
            self._model = TTSModel.load_model()
            self.model_ready.emit()
            self.status.emit("Model ready")
        except ImportError:
            self.model_error.emit(
                "pocket-tts not installed.\n"
                "Run:  pip install pocket-tts  in your venv then restart."
            )
        except Exception as exc:
            logger.exception("Failed to load Pocket TTS model")
            self.model_error.emit(f"Model load failed: {exc}")

    # ------------------------------------------------------------------
    @Slot(str, str)
    def generate(self, text: str, voice_id: str) -> None:
        """Generate audio for *text* using *voice_id*, streaming chunks."""
        if self._model is None:
            return
        text = text.strip()
        if not text:
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
        self._model_ready = False
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

        powered = QLabel("Powered by  Kyutai Pocket TTS")
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
        self.voice_combo.setEnabled(False)  # enabled once model is ready
        voice_row.addWidget(self.voice_combo, stretch=1)
        root.addLayout(voice_row)

        # ── Text input ───────────────────────────────────────────────
        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("TTSTextEdit")
        self.text_edit.setPlaceholderText(
            "Start typing… speech will generate automatically after you pause."
        )
        self.text_edit.setMinimumHeight(120)
        self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.text_edit.setEnabled(False)  # enabled once model is ready
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
        status_row.addWidget(self.status_icon)

        self.status_label = QLabel("Initialising Pocket TTS…")
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
        self._set_status("Ready — start typing to generate speech")
        self.status_icon.setPixmap(
            get_icon("soundboard", 14, "#3ddc97").pixmap(14, 14)
        )

    @Slot(str)
    def _on_model_error(self, msg: str) -> None:
        self._model_ready = False
        self.text_edit.setEnabled(False)
        self.voice_combo.setEnabled(False)
        self._set_status(msg)
        self.status_icon.setPixmap(
            get_icon("warning", 14, "#ff5c7a").pixmap(14, 14)
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
