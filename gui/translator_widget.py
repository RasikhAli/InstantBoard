"""
gui/translator_widget.py

Complete PySide6 GUI panel for InstantBoard's Local Live Translator.
Provides audio controls, language selection (Urdu, English, Arabic), voice profile
enrollment, dual real-time RTL/LTR transcripts, live audio level meter,
VB-CABLE routing preparation, and Emergency Stop control.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from audio.devices import list_input_devices
from audio.mixer import AudioMixer
from audio.recorder import MicrophoneRecorder
from translator.contracts import (
    PipelineMetrics,
    SessionStatus,
    TranscriptUnit,
    TranslationUnit,
    VoiceProfileMetadata,
)
from translator.models.manager import ModelManager
from translator.models.manifest import CAPABILITIES, MANIFESTS
from translator.pipeline import StreamingTranslatorPipeline
from translator.profiles import VoiceProfileManager
from utils.icons import get_icon

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background enrollment recorder thread
# ---------------------------------------------------------------------------
class ProfileRecordWorker(QObject):
    """Records a 5-second clean voice sample from the microphone for enrollment."""

    finished = Signal(object, int)  # np.ndarray, samplerate
    progress = Signal(float)  # 0.0 to 1.0
    error = Signal(str)

    def __init__(self, device_index: Optional[int], duration_sec: float = 5.0) -> None:
        super().__init__()
        self.device_index = device_index
        self.duration_sec = duration_sec

    @Slot()
    def record(self) -> None:
        import sounddevice as sd

        sr = 24000
        total_frames = int(sr * self.duration_sec)
        chunks: list[np.ndarray] = []

        try:
            with sd.InputStream(
                device=self.device_index,
                channels=1,
                samplerate=sr,
                dtype="float32",
            ) as stream:
                frames_recorded = 0
                step_frames = int(sr * 0.1)  # 100ms steps
                while frames_recorded < total_frames:
                    to_read = min(step_frames, total_frames - frames_recorded)
                    data, _ = stream.read(to_read)
                    chunks.append(data.copy())
                    frames_recorded += len(data)
                    self.progress.emit(frames_recorded / total_frames)

            full_audio = np.concatenate(chunks, axis=0).flatten()
            self.finished.emit(full_audio, sr)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Background model downloader thread
# ---------------------------------------------------------------------------
class ModelDownloadWorker(QObject):
    """Downloads an AI model in a background thread with progress reporting."""

    progress = Signal(str, float)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, model_manager: ModelManager, model_id: str) -> None:
        super().__init__()
        self.mgr = model_manager
        self.model_id = model_id

    @Slot()
    def run(self) -> None:
        try:
            path = self.mgr.install_model(
                self.model_id,
                progress_callback=lambda msg, pct: self.progress.emit(msg, pct),
            )
            self.finished.emit(str(path))
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Main Translator Widget
# ---------------------------------------------------------------------------
class TranslatorWidget(QWidget):
    """The Live Translator tab for InstantBoard."""

    mic_level_signal = Signal(float)
    transcript_signal = Signal(object)
    translation_signal = Signal(object)
    metrics_signal = Signal(object)
    status_signal = Signal(object, str)

    def __init__(
        self,
        mixer: AudioMixer,
        prepare_playback_fn: Optional[Callable] = None,
        get_input_device_fn: Optional[Callable] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.mixer = mixer
        self._prepare_playback_fn = prepare_playback_fn
        self._get_input_device_fn = get_input_device_fn
        self.profile_mgr = VoiceProfileManager()
        self.model_mgr = ModelManager()

        self._physical_mic_idx: Optional[int] = None
        self._physical_mic_name: str = "Default Microphone"

        # Wire pipeline via Qt signals for thread-safe GUI updates
        self.transcript_signal.connect(self._on_transcript_received)
        self.translation_signal.connect(self._on_translation_received)
        self.metrics_signal.connect(self._on_metrics_received)
        self.status_signal.connect(self._on_status_changed)

        self.pipeline = StreamingTranslatorPipeline(
            audio_mixer=mixer,
            on_transcript_update=self.transcript_signal.emit,
            on_translation_update=self.translation_signal.emit,
            on_metrics_update=self.metrics_signal.emit,
            on_status_change=self.status_signal.emit,
        )

        # Connect mixer microphone listener to the translator pipeline & visual level meter
        def mic_listener(data: np.ndarray, samplerate: int) -> None:
            if self._is_active:
                self.pipeline.on_microphone_frame(data, samplerate)
            if data.size > 0:
                peak = float(np.max(np.abs(data)))
                self.mic_level_signal.emit(peak)

        self.mixer.microphone.add_listener(mic_listener)
        self.mic_level_signal.connect(self._update_mic_level)

        self._is_active = False
        self._is_push_to_talk = False

        self._build_ui()
        self._refresh_profiles()
        self._refresh_models_status()
        self._refresh_narrator_voices("en")

    def _resolve_physical_mic(self) -> tuple[Optional[int], str]:
        """Find the real physical microphone device, never VB-CABLE or virtual endpoints."""
        dev = self._get_input_device_fn() if self._get_input_device_fn else None
        if dev is not None:
            nl = dev.name.lower()
            if not any(v in nl for v in ["cable", "vb-audio", "virtual audio"]):
                return dev.index, dev.name

        # If not explicitly selected or was System Default, locate physical mic
        from audio.devices import list_input_devices
        for d in list_input_devices():
            nl = d.name.lower()
            if "microsoft sound mapper" in nl or "primary sound" in nl:
                continue
            if any(v in nl for v in ["cable", "vb-audio", "virtual audio", "point", "voicemod", "steam"]):
                continue
            return d.index, d.name

        for d in list_input_devices():
            if "cable" not in d.name.lower() and "virtual" not in d.name.lower():
                return d.index, d.name
        return None, "Default Microphone"

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(14)

        # ── Header Deck (Controls, Language Pair, Profile) ───────────
        header_card = QFrame()
        header_card.setObjectName("DeckCard")
        header_card.setStyleSheet("""
            QFrame#DeckCard {
                background-color: #1e1e28;
                border: 1px solid #2d2d3d;
                border-radius: 12px;
                padding: 12px;
            }
        """)
        h_layout = QVBoxLayout(header_card)
        h_layout.setSpacing(10)

        # Row 1: Languages and Profile Selection
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        # Source Language
        row1.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems([
            "Auto (Detect)",
            "Urdu (اردو)",
            "English",
            "Arabic (العربية)",
        ])
        self.source_combo.currentIndexChanged.connect(self._on_language_changed)
        row1.addWidget(self.source_combo)

        # Arrow indicator
        arrow_lbl = QLabel("➔")
        arrow_lbl.setStyleSheet("color: #7c5cff; font-weight: bold; font-size: 16px;")
        row1.addWidget(arrow_lbl)

        # Target Language
        row1.addWidget(QLabel("Target:"))
        self.target_combo = QComboBox()
        self.target_combo.addItems([
            "English",
            "Urdu (اردو)",
            "Arabic (العربية)",
        ])
        self.target_combo.currentIndexChanged.connect(self._on_language_changed)
        row1.addWidget(self.target_combo)

        # Narrator Voice Selector
        row1.addWidget(QLabel("Voice:"))
        self.narrator_combo = QComboBox()
        self.narrator_combo.setMinimumWidth(160)
        self.narrator_combo.currentIndexChanged.connect(self._on_narrator_changed)
        row1.addWidget(self.narrator_combo)

        row1.addSpacing(12)

        # Voice Profile Selector
        row1.addWidget(QLabel("Clone Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(150)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        row1.addWidget(self.profile_combo)

        self.btn_new_profile = QPushButton("Record Voice (5s)")
        self.btn_new_profile.setIcon(get_icon("soundboard", 14, "#ffffff"))
        self.btn_new_profile.clicked.connect(self._record_voice_profile)
        row1.addWidget(self.btn_new_profile)

        self.btn_import_profile = QPushButton("Import WAV")
        self.btn_import_profile.clicked.connect(self._import_voice_profile)
        row1.addWidget(self.btn_import_profile)

        row1.addStretch(1)
        h_layout.addLayout(row1)

        # Row 2: Action Buttons & Emergency Stop
        row2 = QHBoxLayout()
        row2.setSpacing(12)

        self.btn_start = QPushButton("  Start Live Translation  ")
        self.btn_start.setIcon(get_icon("play", 16, "#ffffff"))
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c5cff, stop:1 #9d80ff);
                color: #ffffff;
                font-weight: 700;
                font-size: 13px;
                padding: 8px 18px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background: #8b6dff;
            }
        """)
        self.btn_start.clicked.connect(self._toggle_translation)
        row2.addWidget(self.btn_start)

        self.btn_ptt = QPushButton("Push-to-Talk (Hold)")
        self.btn_ptt.setStyleSheet("""
            QPushButton {
                background-color: #2a2a3b;
                color: #e0e0e0;
                font-weight: 600;
                padding: 8px 14px;
                border-radius: 8px;
                border: 1px solid #3d3d52;
            }
            QPushButton:pressed {
                background-color: #3ddc97;
                color: #121217;
            }
        """)
        self.btn_ptt.pressed.connect(self._ptt_pressed)
        self.btn_ptt.released.connect(self._ptt_released)
        row2.addWidget(self.btn_ptt)

        self.btn_emergency = QPushButton("  EMERGENCY STOP  ")
        self.btn_emergency.setStyleSheet("""
            QPushButton {
                background-color: #ff3355;
                color: #ffffff;
                font-weight: 800;
                padding: 8px 16px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #ff4d6d;
            }
        """)
        self.btn_emergency.clicked.connect(self._emergency_stop)
        row2.addWidget(self.btn_emergency)

        row2.addSpacing(16)

        # Routing status pill
        self.routing_badge = QLabel("VB-CABLE: Standby")
        self.routing_badge.setStyleSheet("""
            background-color: #262636;
            color: #a0a0b2;
            font-size: 11px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 6px;
            border: 1px solid #333347;
        """)
        row2.addWidget(self.routing_badge)

        # Live Mic Audio Level Meter
        row2.addWidget(QLabel("Mic:"))
        self.mic_meter = QProgressBar()
        self.mic_meter.setRange(0, 100)
        self.mic_meter.setValue(0)
        self.mic_meter.setFixedWidth(80)
        self.mic_meter.setFixedHeight(12)
        self.mic_meter.setTextVisible(False)
        self.mic_meter.setStyleSheet("""
            QProgressBar {
                background-color: #15151e;
                border: 1px solid #2d2d3d;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #3ddc97;
                border-radius: 3px;
            }
        """)
        row2.addWidget(self.mic_meter)

        # Monitor checkbox
        self.chk_monitor = QCheckBox("Monitor in Headphones")
        self.chk_monitor.setChecked(True)
        self.chk_monitor.toggled.connect(self._on_monitor_toggled)
        self.mixer.monitor_translator = True
        row2.addWidget(self.chk_monitor)

        row2.addStretch(1)
        h_layout.addLayout(row2)

        root.addWidget(header_card)

        # ── Dual Live Transcript Deck ────────────────────────────────
        transcript_container = QHBoxLayout()
        transcript_container.setSpacing(14)

        # Left: Original Speech (Urdu / English)
        left_box = QVBoxLayout()
        left_box.setSpacing(6)
        lbl_left = QLabel("Original Speech (Detected):")
        lbl_left.setStyleSheet("color: #a0a0b2; font-weight: 600; font-size: 12px;")
        left_box.addWidget(lbl_left)

        self.txt_source = QTextEdit()
        self.txt_source.setReadOnly(True)
        self.txt_source.setPlaceholderText("Speak into your microphone… (Urdu / English / Arabic)")
        self.txt_source.setStyleSheet("""
            QTextEdit {
                background-color: #171720;
                color: #ffffff;
                border: 1px solid #282838;
                border-radius: 10px;
                padding: 12px;
                font-size: 14px;
                line-height: 1.4;
            }
        """)
        left_box.addWidget(self.txt_source)
        transcript_container.addLayout(left_box, 1)

        # Right: Translated Cloned Speech
        right_box = QVBoxLayout()
        right_box.setSpacing(6)
        lbl_right = QLabel("Call Output (Cloned Voice into VB-CABLE):")
        lbl_right.setStyleSheet("color: #7c5cff; font-weight: 600; font-size: 12px;")
        right_box.addWidget(lbl_right)

        self.txt_target = QTextEdit()
        self.txt_target.setReadOnly(True)
        self.txt_target.setPlaceholderText("Translated speech will play to callers in your voice…")
        self.txt_target.setStyleSheet("""
            QTextEdit {
                background-color: #171720;
                color: #3ddc97;
                border: 1px solid #282838;
                border-radius: 10px;
                padding: 12px;
                font-size: 14px;
                line-height: 1.4;
            }
        """)
        right_box.addWidget(self.txt_target)
        transcript_container.addLayout(right_box, 1)

        root.addLayout(transcript_container, 1)

        # ── Diagnostics & Live Metrics Bar ───────────────────────────
        metrics_bar = QHBoxLayout()
        metrics_bar.setSpacing(16)

        self.lbl_status = QLabel("Status: Ready")
        self.lbl_status.setStyleSheet("color: #a0a0b2; font-size: 12px;")
        metrics_bar.addWidget(self.lbl_status)

        self.lbl_latency = QLabel("Latency: —")
        self.lbl_latency.setStyleSheet("color: #a0a0b2; font-size: 12px;")
        metrics_bar.addWidget(self.lbl_latency)

        self.lbl_backlog = QLabel("Backlog: 0.0s")
        self.lbl_backlog.setStyleSheet("color: #a0a0b2; font-size: 12px;")
        metrics_bar.addWidget(self.lbl_backlog)

        metrics_bar.addStretch(1)

        self.btn_download_models = QPushButton("Download AI Models")
        self.btn_download_models.setStyleSheet("""
            QPushButton {
                background-color: #2a2a3d;
                color: #3ddc97;
                font-size: 11px;
                font-weight: bold;
                padding: 3px 8px;
                border: 1px solid #3ddc97;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #3ddc97;
                color: #121217;
            }
        """)
        self.btn_download_models.clicked.connect(self._download_models_dialog)
        metrics_bar.addWidget(self.btn_download_models)

        self.btn_models_setup = QPushButton("Model Diagnostics")
        self.btn_models_setup.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #7c5cff;
                font-size: 11px;
                text-decoration: underline;
                border: none;
            }
        """)
        self.btn_models_setup.clicked.connect(self._show_model_diagnostics)
        metrics_bar.addWidget(self.btn_models_setup)

        root.addLayout(metrics_bar)

    # ------------------------------------------------------------------
    # Profiles Management
    # ------------------------------------------------------------------
    def _refresh_profiles(self) -> None:
        self.profile_combo.clear()
        profiles = self.profile_mgr.list_profiles()
        if not profiles:
            self.profile_combo.addItem("Default Acoustic Profile", None)
        else:
            for p in profiles:
                self.profile_combo.addItem(f"{p.name} ({p.duration_seconds}s)", p)

        self._on_profile_changed()

    def _on_profile_changed(self) -> None:
        idx = self.profile_combo.currentIndex()
        profile = self.profile_combo.itemData(idx)
        self.pipeline.set_voice_profile(profile)

    def _record_voice_profile(self) -> None:
        """Prompt name and record a 5s clean sample from active mic."""
        name, ok = QInputDialog.getText(
            self, "New Voice Profile", "Enter a name for this voice profile (e.g. 'My Voice'):"
        )
        if not ok or not name.strip():
            return

        self.btn_new_profile.setEnabled(False)
        self.btn_new_profile.setText("Recording (5s)…")

        mic_dev = self._get_input_device_fn() if self._get_input_device_fn else None
        dev_idx = mic_dev.index if mic_dev else self.mixer.microphone.device_index

        self._rec_thread = QThread(self)
        self._rec_worker = ProfileRecordWorker(
            device_index=dev_idx,
            duration_sec=5.0,
        )
        self._rec_worker.moveToThread(self._rec_thread)

        def on_rec_done(audio_data: np.ndarray, sr: int) -> None:
            try:
                self.profile_mgr.create_profile_from_audio(
                    name=name.strip(),
                    audio_data=audio_data,
                    samplerate=sr,
                    notes="Recorded via InstantBoard Live Translator",
                )
                self._refresh_profiles()
                self.lbl_status.setText(f"Voice profile '{name}' enrolled successfully!")
            except Exception as exc:
                self.lbl_status.setText(f"Profile error: {exc}")
            finally:
                self.btn_new_profile.setEnabled(True)
                self.btn_new_profile.setText("Record Voice (5s)")
                self._rec_thread.quit()

        def on_rec_error(err: str) -> None:
            self.lbl_status.setText(f"Recording failed: {err}")
            self.btn_new_profile.setEnabled(True)
            self.btn_new_profile.setText("Record Voice (5s)")
            self._rec_thread.quit()

        self._rec_worker.finished.connect(on_rec_done)
        self._rec_worker.error.connect(on_rec_error)
        self._rec_thread.started.connect(self._rec_worker.record)
        self._rec_thread.start()

    def _import_voice_profile(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Voice Sample", "", "Audio Files (*.wav *.mp3 *.flac)"
        )
        if not file_path:
            return

        p = Path(file_path)
        name = p.stem.replace("_", " ").title()
        try:
            self.profile_mgr.import_profile_from_file(name=name, file_path=p)
            self._refresh_profiles()
            self.lbl_status.setText(f"Imported profile '{name}'")
        except Exception as exc:
            self.lbl_status.setText(f"Import error: {exc}")

    # ------------------------------------------------------------------
    # Language Handlers
    # ------------------------------------------------------------------
    def _on_language_changed(self) -> None:
        src_map = {
            "Auto (Detect)": "auto",
            "Urdu (اردو)": "ur",
            "English": "en",
            "Arabic (العربية)": "ar",
        }
        tgt_map = {
            "English": "en",
            "Urdu (اردو)": "ur",
            "Arabic (العربية)": "ar",
        }
        s = src_map.get(self.source_combo.currentText(), "auto")
        t = tgt_map.get(self.target_combo.currentText(), "en")
        self.pipeline.set_languages(s, t)
        self._refresh_narrator_voices(t)

    def _refresh_narrator_voices(self, target_lang_code: str) -> None:
        """Populate the narrator combo with curated neural voices matching the target language."""
        from translator.voice_catalog import get_voices_for_language
        self.narrator_combo.blockSignals(True)
        self.narrator_combo.clear()
        voices = get_voices_for_language(target_lang_code)
        for v in voices:
            self.narrator_combo.addItem(f"{v.name}", v.short_name)
        self.narrator_combo.blockSignals(False)
        self._on_narrator_changed()

    def _on_narrator_changed(self) -> None:
        """Forward chosen narrator voice identifier to the streaming pipeline."""
        voice_id = self.narrator_combo.currentData()
        self.pipeline.set_target_voice(voice_id)

    def _on_monitor_toggled(self, checked: bool) -> None:
        self.mixer.monitor_translator = checked

    # ------------------------------------------------------------------
    # Start / Stop / Emergency Stop
    # ------------------------------------------------------------------
    def _toggle_translation(self) -> None:
        if self._is_active:
            self._stop_translation()
        else:
            self._start_translation()

    def _start_translation(self) -> None:
        # 1. Resolve real physical mic BEFORE switching Windows default recording device to VB-CABLE
        mic_idx, mic_name = self._resolve_physical_mic()
        self._physical_mic_idx = mic_idx
        self._physical_mic_name = mic_name

        # 2. Ensure models are initialized
        self.pipeline.vad.ensure_session()
        self.pipeline.asr.ensure_model_loaded()
        self.pipeline.translator.ensure_model_loaded()

        # 3. Start physical microphone capture on the resolved physical device
        try:
            self.mixer.microphone.start(mic_idx)
            logger.info("Translator started physical mic on %s (index=%s)", mic_name, mic_idx)
        except Exception as exc:
            logger.error("Failed to start microphone: %s", exc)
            self.lbl_status.setText(f"Mic error: {exc}")
            QMessageBox.warning(
                self,
                "Microphone Error",
                f"Could not open microphone '{mic_name}': {exc}\nPlease check your audio device settings in the bottom panel.",
            )
            return

        # 4. Proactively switch Windows default recording device to VB-CABLE and start broadcast stream
        if self._prepare_playback_fn:
            try:
                self._prepare_playback_fn()
            except Exception as exc:
                logger.warning("Could not switch to VB-CABLE: %s", exc)

        # 5. Start pipeline
        self._is_active = True
        self.btn_start.setText("  Stop Translation  ")
        self.btn_start.setIcon(get_icon("stop", 16, "#ff5c7a"))
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: #333347;
                color: #ff5c7a;
                font-weight: 700;
                padding: 8px 18px;
                border-radius: 8px;
                border: 1px solid #ff5c7a;
            }
        """)
        self.routing_badge.setText("VB-CABLE: Injected (Mic Suppressed)")
        self.routing_badge.setStyleSheet("""
            background-color: #1b382b;
            color: #3ddc97;
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 6px;
            border: 1px solid #3ddc97;
        """)
        self.pipeline.start()

        self.lbl_status.setText(f"🎙️ Listening to {mic_name}… Speak now!")

    def _stop_translation(self) -> None:
        self._is_active = False
        self.btn_start.setText("  Start Live Translation  ")
        self.btn_start.setIcon(get_icon("play", 16, "#ffffff"))
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c5cff, stop:1 #9d80ff);
                color: #ffffff;
                font-weight: 700;
                padding: 8px 18px;
                border-radius: 8px;
                border: none;
            }
        """)
        self.routing_badge.setText("VB-CABLE: Standby")
        self.routing_badge.setStyleSheet("""
            background-color: #262636;
            color: #a0a0b2;
            font-size: 11px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 6px;
            border: 1px solid #333347;
        """)
        self.pipeline.stop()
        self.mixer.microphone.stop()

        # Restore Windows default recording device to physical mic
        from audio.devices import WindowsDefaultDeviceSwitcher
        switcher = WindowsDefaultDeviceSwitcher()
        if switcher.available and getattr(self, "_physical_mic_name", None):
            try:
                switcher.set_default_recording_device(self._physical_mic_name)
            except Exception:
                pass

        self.lbl_status.setText("Status: Ready")
        self.mic_meter.setValue(0)

    def _emergency_stop(self) -> None:
        self._is_active = False
        self.pipeline.emergency_stop()
        self._stop_translation()
        self.txt_source.append("\n[EMERGENCY STOP — QUEUES FLUSHED]\n")
        self.txt_target.append("\n[EMERGENCY STOP — QUEUES FLUSHED]\n")

    def _ptt_pressed(self) -> None:
        if not self._is_active:
            self._start_translation()

    def _ptt_released(self) -> None:
        if self._is_active:
            self._stop_translation()

    # ------------------------------------------------------------------
    # Pipeline Callbacks
    # ------------------------------------------------------------------
    def _on_transcript_received(self, unit: TranscriptUnit) -> None:
        """Render transcript with proper RTL direction for Urdu/Arabic."""
        is_rtl = unit.language in ("ur", "ar")
        tag = f"[{unit.language.upper()} {int(unit.language_confidence * 100)}%]"

        self.txt_source.setLayoutDirection(
            Qt.RightToLeft if is_rtl else Qt.LeftToRight
        )
        self.txt_source.append(f"{tag}: {unit.text}")

        # Auto-scroll to bottom
        sb = self.txt_source.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_translation_received(self, unit: TranslationUnit) -> None:
        """Render translation with proper RTL direction for Arabic."""
        is_rtl = unit.target_lang in ("ar", "ur")
        tag = f"[{unit.target_lang.upper()}]"

        self.txt_target.setLayoutDirection(
            Qt.RightToLeft if is_rtl else Qt.LeftToRight
        )
        self.txt_target.append(f"{tag}: {unit.target_text}")

        sb = self.txt_target.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_metrics_received(self, m: PipelineMetrics) -> None:
        self.lbl_latency.setText(
            f"Latency: {int(m.total_pipeline_latency_ms)}ms (TTS RTF: {m.tts_rtf:.2f})"
        )
        self.lbl_backlog.setText(f"Backlog: {m.backlog_seconds:.1f}s ({m.active_queue_items} items)")

    def _on_status_changed(self, status: SessionStatus, msg: str) -> None:
        self.lbl_status.setText(f"Status: {msg}")

    @Slot(float)
    def _update_mic_level(self, peak: float) -> None:
        """Update live audio level meter (0-100) when microphone is active."""
        if self._is_active:
            lvl = int(min(1.0, peak * 3.5) * 100)
            self.mic_meter.setValue(lvl)
        else:
            self.mic_meter.setValue(0)

    # ------------------------------------------------------------------
    # Diagnostics & Model Download Dialog
    # ------------------------------------------------------------------
    def _refresh_models_status(self) -> None:
        pass

    def _download_models_dialog(self) -> None:
        """Allow 1-click downloading of optional higher-accuracy models."""
        items = [
            "silero-vad-v5 (Silero VAD v5 ONNX, ~1.5 MB)",
            "faster-whisper-base (Whisper Base ASR, ~150 MB)",
            "nllb-200-distilled-600m (NLLB-200 INT8 Translation, ~650 MB)",
            "faster-whisper-large-v3-turbo (Whisper Large v3 Turbo, ~1.6 GB)",
        ]
        item, ok = QInputDialog.getItem(
            self,
            "Download AI Model",
            "Select an AI model to download locally:",
            items,
            0,
            False,
        )
        if not ok or not item:
            return

        model_id = item.split()[0]
        self.lbl_status.setText(f"Downloading {model_id}… please wait…")
        self.btn_download_models.setEnabled(False)

        self._dl_thread = QThread(self)
        self._dl_worker = ModelDownloadWorker(self.model_mgr, model_id)
        self._dl_worker.moveToThread(self._dl_thread)

        def on_dl_progress(msg: str, pct: float) -> None:
            self.lbl_status.setText(f"{msg} ({int(pct * 100)}%)")

        def on_dl_done(path: str) -> None:
            self.lbl_status.setText(f"Model '{model_id}' installed successfully!")
            self.btn_download_models.setEnabled(True)
            self._dl_thread.quit()
            self.pipeline.vad.ensure_session()
            self.pipeline.asr.ensure_model_loaded()
            self.pipeline.translator.ensure_model_loaded()
            QMessageBox.information(self, "Download Complete", f"Successfully installed {model_id} to:\n{path}")

        def on_dl_err(err: str) -> None:
            self.lbl_status.setText(f"Download failed: {err}")
            self.btn_download_models.setEnabled(True)
            self._dl_thread.quit()
            QMessageBox.warning(self, "Download Error", f"Failed to download {model_id}:\n{err}")

        self._dl_worker.progress.connect(on_dl_progress)
        self._dl_worker.finished.connect(on_dl_done)
        self._dl_worker.error.connect(on_dl_err)
        self._dl_thread.started.connect(self._dl_worker.run)
        self._dl_thread.start()

    def shutdown(self) -> None:
        """Clean shutdown invoked on application close."""
        self.pipeline.emergency_stop()
        self.pipeline.tts.stop()

    def _show_model_diagnostics(self) -> None:
        status_info = self.model_mgr.get_model_status()
        diag_lines = ["Local Model Readiness Status:"]
        for mid, st in status_info.items():
            inst = "READY (Installed)" if st["installed"] else "NOT DOWNLOADED"
            diag_lines.append(f"• {st['name']}: {inst}")
            diag_lines.append(f"  Path: {st['path']}")
            diag_lines.append(f"  Size: {st['current_size_mb']} MB / {st['estimated_size_mb']} MB")

        QMessageBox.information(
            self,
            "Translator Diagnostics",
            "\n".join(diag_lines),
        )
