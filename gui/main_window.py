"""
gui/main_window.py

Top-level application window: assembles the top bar (title, search,
refresh, settings), the central search/results panel and the bottom
player/mixer panel. Also owns the global hotkey manager that lets
favorited sounds be triggered from anywhere on the system.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from audio.mixer import AudioMixer
from audio.player import PlaybackError, SoundPlayer
from audio.devices import WindowsDefaultDeviceSwitcher, find_vb_cable_input, find_vb_cable_output
from gui.player_widget import PlayerWidget
from gui.search_widget import SearchWidget
from gui.settings_dialog import SettingsDialog
from gui.tts_widget import TTSWidget
from gui.link_player_widget import LinkPlayerWidget
from myinstants.parser import Sound
from utils.cache import CacheManager
from utils.icons import get_icon
from utils.settings import SettingsManager

logger = logging.getLogger(__name__)


class _AlertManager:
    """Manages transient "alert" messages shown in the top status bar
    with auto-dismiss after a configurable timeout."""

    def __init__(self, label, default_text: str = "", timeout_ms: int = 5000) -> None:
        self._label = label
        self._default_text = default_text
        self._timeout_ms = timeout_ms
        self._timer = None

    def show(self, message: str, timeout_ms: int = 0) -> None:
        """Show a message. If timeout_ms > 0, revert to default after."""
        from PySide6.QtCore import QTimer
        self._label.setText(message)
        if timeout_ms > 0 or (timeout_ms == 0 and self._timeout_ms):
            if self._timer is not None:
                self._timer.stop()
            self._timer = QTimer.singleShot(
                timeout_ms or self._timeout_ms,
                lambda: self._label.setText(self._default_text),
            )




class GlobalHotkeyManager:
    """Wraps the optional `keyboard` package to provide system-wide
    hotkeys for favorite sounds. If `keyboard` is not installed, or the
    process lacks the permissions it needs on Windows, hotkeys are
    silently disabled and the rest of the app continues to work
    normally (in-app playback via the mouse is unaffected)."""

    def __init__(self, on_trigger) -> None:
        self._on_trigger = on_trigger
        self._registered: Dict[str, dict] = {}
        self._available = False
        try:
            import keyboard  # noqa: F401
            self._available = True
        except ImportError:
            logger.warning("The 'keyboard' package is not installed; global hotkeys are disabled.")

    @property
    def available(self) -> bool:
        return self._available

    def _to_keyboard_syntax(self, hotkey: str) -> str:
        return hotkey.lower().replace("ctrl+", "ctrl+")

    def register_all(self, hotkeys: Dict[str, dict]) -> None:
        if not self._available:
            return
        import keyboard

        self.unregister_all()
        for hotkey, sound in hotkeys.items():
            combo = self._to_keyboard_syntax(hotkey)
            try:
                keyboard.add_hotkey(combo, lambda s=sound: self._on_trigger(s))
                self._registered[hotkey] = sound
            except Exception as exc:
                logger.warning("Could not register hotkey '%s': %s", hotkey, exc)

    def unregister_all(self) -> None:
        if not self._available:
            return
        import keyboard

        try:
            keyboard.remove_all_hotkeys()
        except AttributeError:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                # Some versions don't have either; just clear our tracking
                pass
        except Exception as exc:
            logger.warning("Could not unregister hotkeys: %s", exc)
        self._registered.clear()


class MainWindow(QMainWindow):
    """InstantBoard's main application window."""

    def __init__(self, settings: SettingsManager) -> None:
        super().__init__()
        self._settings = settings
        self._cache = CacheManager(settings.get("cache_folder", "cache"))
        self._mixer = AudioMixer()
        self._player = SoundPlayer(self._mixer, on_sound_finished=self._on_sound_finished)
        self._switcher = WindowsDefaultDeviceSwitcher()

        self.setWindowTitle("InstantBoard")
        self.setMinimumSize(1100, 700)
        self.resize(settings.get("window_width", 1200), settings.get("window_height", 800))

        self._build_ui()
        self._hotkeys = GlobalHotkeyManager(self._on_hotkey_triggered)
        self._hotkeys.register_all(self._settings.get_hotkeys())
        if not self._hotkeys.available:
            self._top_status_label.setText("Global hotkeys unavailable (install 'keyboard' package)")
        
        self._last_sound_count = 0
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._check_sound_count)
        self._poll_timer.start()
        self._broadcast_auto_started = False

    # ------------------------------------------------------------------
    def _check_sound_count(self) -> None:
        count = self._mixer.active_sound_count()
        if count != self._last_sound_count:
            self._last_sound_count = count
            self._on_sound_count_changed(count)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_top_bar())

        # ── Tab widget ───────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setObjectName("MainTabs")

        # ── Sounds tab ───────────────────────────────────────────────
        sounds_container = QWidget()
        sounds_layout = QVBoxLayout(sounds_container)
        sounds_layout.setContentsMargins(20, 16, 20, 16)

        self.search_widget = SearchWidget(self._settings, self._cache)
        self.search_widget.sound_ready_to_play.connect(self._on_play_local_path)
        self.search_widget.sound_stop_requested.connect(self._on_stop_sound)
        self.search_widget.status_message.connect(self._on_status_message)
        sounds_layout.addWidget(self.search_widget)

        self._tabs.addTab(sounds_container, get_icon("soundboard", 16), "  Sounds  ")

        # ── TTS tab ──────────────────────────────────────────────────
        tts_container = QWidget()
        tts_layout = QVBoxLayout(tts_container)
        tts_layout.setContentsMargins(20, 16, 20, 16)

        self.tts_widget = TTSWidget(
            mixer=self._mixer,
            prepare_playback_fn=self._prepare_soundboard_playback,
        )
        tts_layout.addWidget(self.tts_widget)

        self._tabs.addTab(tts_container, get_icon("play", 16, "#7c5cff"), "  TTS  ")

        # ── Links tab ────────────────────────────────────────────────
        links_container = QWidget()
        links_layout = QVBoxLayout(links_container)
        links_layout.setContentsMargins(20, 16, 20, 16)

        self.link_widget = LinkPlayerWidget(self._settings, self._cache)
        self.link_widget.sound_ready_to_play.connect(self._on_play_local_path)
        self.link_widget.sound_stop_requested.connect(self._on_stop_sound)
        self.link_widget.status_message.connect(self._on_status_message)
        links_layout.addWidget(self.link_widget)

        self._tabs.addTab(links_container, get_icon("link", 16, "#7c5cff"), "  Links  ")

        root_layout.addWidget(self._tabs, stretch=1)

        self.player_widget = PlayerWidget(self._settings, self._mixer)
        root_layout.addWidget(self.player_widget)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(68)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(14)

        # Brand / Logo
        logo_icon = QLabel()
        logo_icon.setPixmap(get_icon("logo", 26, "#7c5cff").pixmap(26, 26))
        layout.addWidget(logo_icon)

        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(1)
        brand_layout.setContentsMargins(0, 0, 0, 0)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel("InstantBoard")
        title.setObjectName("TitleLabel")
        title_row.addWidget(title)

        pro_badge = QLabel("PRO")
        pro_badge.setStyleSheet("""
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c5cff, stop:1 #9d80ff);
            color: #ffffff;
            font-size: 10px;
            font-weight: 800;
            padding: 2px 6px;
            border-radius: 6px;
        """)
        title_row.addWidget(pro_badge)
        title_row.addStretch()
        brand_layout.addLayout(title_row)

        subtitle = QLabel("Desktop Soundboard & Live Audio Router")
        subtitle.setObjectName("BrandSubtitle")
        brand_layout.addWidget(subtitle)
        layout.addLayout(brand_layout)

        layout.addStretch(1)

        # Dynamic Status Pill
        self._status_container = QFrame()
        self._status_container.setStyleSheet("""
            QFrame {
                background-color: #1e1e2c;
                border: 1px solid #2c2c3e;
                border-radius: 16px;
                padding: 4px 14px;
            }
        """)
        status_layout = QHBoxLayout(self._status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #3ddc97; font-size: 10px;")
        status_layout.addWidget(self._status_dot)

        self._top_status_label = QLabel("Ready")
        self._top_status_label.setStyleSheet("color: #c2c2d4; font-size: 12px; font-weight: 600;")
        status_layout.addWidget(self._top_status_label)

        layout.addWidget(self._status_container)

        # Settings button
        settings_button = QPushButton()
        settings_button.setObjectName("IconButton")
        settings_button.setIcon(get_icon("settings", 20, "#c2c2d4"))
        settings_button.setFixedSize(42, 42)
        settings_button.setToolTip("Settings & Device Configuration")
        settings_button.setStyleSheet("""
            QPushButton {
                background-color: #1e1e2c;
                border: 1px solid #2c2c3e;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: #262638;
                border: 1px solid #7c5cff;
            }
        """)
        settings_button.clicked.connect(self._open_settings)
        layout.addWidget(settings_button)

        return bar

    # ------------------------------------------------------------------
    # Playback plumbing
    # ------------------------------------------------------------------
    def _on_play_local_path(self, local_path: str, card_id: str | None = None) -> None:
        self._prepare_soundboard_playback()
        try:
            self._player.play(local_path, card_id=card_id)
        except PlaybackError as exc:
            logger.error("Playback failed: %s", exc)
            self._on_status_message(f"Playback failed: {exc}")

    def _on_status_message(self, message: str) -> None:
        if message == "STOP_ALL":
            self._player.stop_all()
            self._top_status_label.setText("All sounds stopped")
            self._status_dot.setStyleSheet("color: #ff5c7a; font-size: 10px;")
            return
        if "error" in message.lower() or "failed" in message.lower():
            self._status_dot.setStyleSheet("color: #ff5c7a; font-size: 10px;")
        elif "download" in message.lower() or "loading" in message.lower() or "searching" in message.lower():
            self._status_dot.setStyleSheet("color: #ffb830; font-size: 10px;")
        elif "playing" in message.lower() or "ready" in message.lower():
            self._status_dot.setStyleSheet("color: #3ddc97; font-size: 10px;")
        else:
            self._status_dot.setStyleSheet("color: #7c5cff; font-size: 10px;")
        self._top_status_label.setText(message)

    def _on_stop_sound(self, sound_id: str) -> None:
        """Stop a specific sound by its card identifier."""
        self._player.stop_by_card_id(sound_id)

    def _on_sound_finished(self, card_id: str) -> None:
        """Called by SoundPlayer when a sound finishes naturally."""
        self.search_widget.reset_card_playing(card_id)
        self.link_widget.reset_card_playing(card_id)

    def _prepare_soundboard_playback(self) -> None:
        """Proactively switch to VB-CABLE and start the broadcast stream
        BEFORE the sound renders, so communication apps capture audio
        from the first frame with no cut."""
        cable_in = find_vb_cable_input()
        if not cable_in:
            return

        if getattr(self, "_current_recording_device_name", None) != cable_in.name:
            self._current_recording_device_name = cable_in.name
            if self._switcher.available:
                try:
                    self._switcher.set_default_recording_device(cable_in.name)
                except Exception as exc:
                    logger.warning("Could not switch recording device: %s", exc)

        if not getattr(self, "_broadcast_auto_started", False):
            cable_out = find_vb_cable_output()
            if cable_out:
                try:
                    self._mixer.start_broadcast_sounds_only(cable_out.index)
                    self._broadcast_auto_started = True
                except Exception as exc:
                    logger.warning("Could not start broadcast stream: %s", exc)

    def _on_hotkey_triggered(self, sound_dict: dict) -> None:
        # Hotkeys fire on a background thread owned by the `keyboard`
        # package; downloading/playback is thread-safe by design (the
        # mixer and cache manager both use internal locks), so we can
        # call straight through without marshalling to the GUI thread
        # for the audio path itself. GUI label updates are queued
        # automatically by Qt's signal/slot mechanism across threads
        # since QLabel.setText is invoked via a queued connection here.
        try:
            cached_path = self._cache.get_cached_path(sound_dict.get("download_url", ""))
            if cached_path is None:
                sound = Sound.from_dict(sound_dict)
                from myinstants.api import MyInstantsClient

                client = MyInstantsClient()
                data = client.download_sound(sound)
                cached_path = self._cache.store(sound.download_url, data)
                client.close()
            self._prepare_soundboard_playback()
            self._player.play(cached_path)
        except Exception as exc:
            logger.error("Hotkey playback failed: %s", exc)

    def _on_sound_count_changed(self, count: int) -> None:
        """Automatically switch to VB-CABLE when sounds start playing,
        and switch back to the normal microphone when all sounds stop."""
        cable_in = find_vb_cable_input()
        if not cable_in:
            return

        if count > 0:
            if getattr(self, "_current_recording_device_name", None) == cable_in.name:
                return
            self._current_recording_device_name = cable_in.name
            if self._switcher.available:
                try:
                    self._switcher.set_default_recording_device(cable_in.name)
                except Exception as exc:
                    logger.warning("Could not switch recording device: %s", exc)
            if not getattr(self, "_broadcast_auto_started", False):
                cable_out = find_vb_cable_output()
                if cable_out:
                    try:
                        self._mixer.start_broadcast_sounds_only(cable_out.index)
                        self._broadcast_auto_started = True
                    except Exception as exc:
                        logger.warning("Could not start broadcast stream: %s", exc)
            self._top_status_label.setText(f"Soundboard active - {count} sound(s) playing")
        elif count == 0 and getattr(self, "_current_recording_device_name", None) == cable_in.name:
            mic = self.player_widget._current_input_device()
            if self._switcher.available:
                try:
                    if mic:
                        self._switcher.set_default_recording_device(mic.name)
                        self._top_status_label.setText(f"Normal microphone restored: {mic.name}")
                    else:
                        self._top_status_label.setText("Normal microphone restored")
                except Exception as exc:
                    logger.warning("Could not restore recording device: %s", exc)
            if getattr(self, "_broadcast_auto_started", False):
                self._mixer.stop_broadcast()
                self._broadcast_auto_started = False
            self._current_recording_device_name = None

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self._cache, self)
        dialog.favorite_play_requested.connect(self.search_widget.play_sound_by_dict)
        dialog.hotkeys_changed.connect(lambda: self._hotkeys.register_all(self._settings.get_hotkeys()))
        dialog.exec()
        self.player_widget.refresh_devices()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override naming)
        self._settings.set("window_width", self.width())
        self._settings.set("window_height", self.height())
        self._hotkeys.unregister_all()
        self.search_widget.shutdown()
        self.tts_widget.shutdown()
        self.link_widget.shutdown()
        self.player_widget.shutdown()
        super().closeEvent(event)
