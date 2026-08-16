"""
gui/link_player_widget.py

Dedicated panel to extract and play soundclips from web links (Instagram,
YouTube, Twitter/X, TikTok, direct audio URLs, etc.) and manage a persistent
searchable history of played link clips for instant replay.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from audio.link_downloader import LinkAudioExtractor, LinkDownloadWorker, detect_platform
from audio.player import PlaybackError
from utils.cache import CacheManager
from utils.icons import get_icon
from utils.settings import SettingsManager

logger = logging.getLogger(__name__)


# ==========================================================================
# History Item Card
# ==========================================================================
class HistoryItemCard(QFrame):
    """Card representing one previously played link clip in history."""

    play_requested = Signal(dict)
    stop_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, item: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HistoryCard")
        self.item = item
        self.item_id = item.get("id", "")
        self._is_playing = False

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        # ── Left: Play / Stop Button ─────────────────────────────────
        self.action_btn = QPushButton()
        self.action_btn.setObjectName("IconButton")
        self.action_btn.setIcon(get_icon("play", 20, "#7c5cff"))
        self.action_btn.setFixedSize(44, 44)
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setStyleSheet("""
            QPushButton {
                background-color: #262638;
                border: 1px solid #3b3b52;
                border-radius: 22px;
            }
            QPushButton:hover {
                background-color: #7c5cff;
                border: 1px solid #9d80ff;
            }
        """)
        self.action_btn.clicked.connect(self._on_action_clicked)
        layout.addWidget(self.action_btn)

        # ── Middle: Info ─────────────────────────────────────────────
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)
        info_layout.setContentsMargins(0, 0, 0, 0)

        # Top row: Platform badge + duration + timestamp
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        source = self.item.get("source", "Web Link")
        badge = QLabel(source.upper())
        badge_style_map = {
            "Instagram": "BadgeInstagram",
            "YouTube": "BadgeYouTube",
            "Twitter/X": "BadgeTwitter",
            "TikTok": "BadgeTikTok",
        }
        badge.setObjectName(badge_style_map.get(source, "BadgeDefault"))
        top_row.addWidget(badge)

        duration = self.item.get("duration", "")
        if duration:
            dur_label = QLabel(f"⏱ {duration}")
            dur_label.setStyleSheet("color: #85859e; font-size: 11px; font-weight: 600;")
            top_row.addWidget(dur_label)

        played_at = self.item.get("played_at", "")
        if played_at:
            time_label = QLabel(f"•  {played_at}")
            time_label.setObjectName("MutedLabel")
            top_row.addWidget(time_label)

        top_row.addStretch()
        info_layout.addLayout(top_row)

        # Title
        title_text = self.item.get("title", "Untitled Clip")
        self.title_lbl = QLabel(title_text)
        self.title_lbl.setObjectName("HistoryTitle")
        self.title_lbl.setToolTip(title_text)
        self.title_lbl.setWordWrap(True)
        info_layout.addWidget(self.title_lbl)

        # URL link
        url_text = self.item.get("url", "")
        self.url_lbl = QLabel(url_text)
        self.url_lbl.setObjectName("HistoryMeta")
        self.url_lbl.setToolTip(url_text)
        info_layout.addWidget(self.url_lbl)

        layout.addLayout(info_layout, stretch=1)

        # ── Right: Action Buttons ────────────────────────────────────
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)

        # Copy URL button
        self.copy_btn = QPushButton()
        self.copy_btn.setObjectName("IconButton")
        self.copy_btn.setIcon(get_icon("copy", 16, "#85859e"))
        self.copy_btn.setFixedSize(36, 36)
        self.copy_btn.setToolTip("Copy URL to clipboard")
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        actions_layout.addWidget(self.copy_btn)

        # Delete button
        self.del_btn = QPushButton()
        self.del_btn.setObjectName("IconButton")
        self.del_btn.setIcon(get_icon("trash", 16, "#ff5c7a"))
        self.del_btn.setFixedSize(36, 36)
        self.del_btn.setToolTip("Remove from history")
        self.del_btn.clicked.connect(lambda: self.delete_requested.emit(self.item_id))
        actions_layout.addWidget(self.del_btn)

        layout.addLayout(actions_layout)

        # Double click to play
        self.mouseDoubleClickEvent = lambda e: self._on_action_clicked()

    def _on_action_clicked(self) -> None:
        if self._is_playing:
            self.stop_requested.emit(self.item_id)
        else:
            self.play_requested.emit(self.item)

    def _on_copy_clicked(self) -> None:
        url = self.item.get("url", "")
        if url:
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            self.copy_btn.setToolTip("Copied!")
            self.copy_btn.setIcon(get_icon("check", 16, "#3ddc97"))

    def set_playing(self, playing: bool) -> None:
        self._is_playing = playing
        if playing:
            self.action_btn.setIcon(get_icon("pause", 20, "#ffffff"))
            self.action_btn.setStyleSheet("""
                QPushButton {
                    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #ff5c7a, stop:1 #ff758f);
                    border: 2px solid #ffffff66;
                    border-radius: 22px;
                }
                QPushButton:hover {
                    background-color: #ff758f;
                }
            """)
        else:
            self.action_btn.setIcon(get_icon("play", 20, "#7c5cff"))
            self.action_btn.setStyleSheet("""
                QPushButton {
                    background-color: #262638;
                    border: 1px solid #3b3b52;
                    border-radius: 22px;
                }
                QPushButton:hover {
                    background-color: #7c5cff;
                    border: 1px solid #9d80ff;
                }
            """)


# ==========================================================================
# Main Link Player Widget
# ==========================================================================
class LinkPlayerWidget(QWidget):
    """
    Panel allowing arbitrary link audio extraction and history management.
    """

    sound_ready_to_play = Signal(str, str)  # (local_path, card_id)
    sound_stop_requested = Signal(str)  # card_id
    status_message = Signal(str)

    def __init__(
        self,
        settings: SettingsManager,
        cache: CacheManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cache = cache
        self._extractor = LinkAudioExtractor(cache)
        self._worker: Optional[LinkDownloadWorker] = None
        self._history_cards: List[HistoryItemCard] = []
        self._playing_cards: Dict[str, str] = {}  # card_id -> local_path

        self._build_ui()
        self.reload_history()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)

        # ── Hero URL Input Card ───────────────────────────────────────
        hero_card = QFrame()
        hero_card.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(14)

        # Title & platform chips
        title_row = QHBoxLayout()
        header = QLabel("Play Soundclip via Link")
        header.setObjectName("SectionHeader")
        title_row.addWidget(header)

        title_row.addStretch()

        # Supported platforms chips
        platforms_row = QHBoxLayout()
        platforms_row.setSpacing(6)
        for name, cls in [
            ("Instagram", "BadgeInstagram"),
            ("YouTube", "BadgeYouTube"),
            ("Twitter / X", "BadgeTwitter"),
            ("TikTok", "BadgeTikTok"),
            ("Direct Audio", "BadgeDefault"),
        ]:
            badge = QLabel(name)
            badge.setObjectName(cls)
            platforms_row.addWidget(badge)
        title_row.addLayout(platforms_row)

        hero_layout.addLayout(title_row)

        # URL Input row
        url_row = QHBoxLayout()
        url_row.setSpacing(10)

        self.url_input = QLineEdit()
        self.url_input.setObjectName("UrlInput")
        self.url_input.setPlaceholderText("Paste link here (e.g. https://www.instagram.com/reel/... or https://youtu.be/...)")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._on_play_input_url)
        url_row.addWidget(self.url_input, stretch=1)

        # Paste button
        self.paste_btn = QPushButton(" Paste")
        self.paste_btn.setIcon(get_icon("copy", 15, "#c2c2d4"))
        self.paste_btn.setToolTip("Paste link from clipboard")
        self.paste_btn.clicked.connect(self._on_paste_clicked)
        url_row.addWidget(self.paste_btn)

        # Play button
        self.play_btn = QPushButton(" Play Link")
        self.play_btn.setObjectName("PrimaryButton")
        self.play_btn.setIcon(get_icon("play", 16, "#ffffff"))
        self.play_btn.setMinimumWidth(125)
        self.play_btn.clicked.connect(self._on_play_input_url)
        url_row.addWidget(self.play_btn)

        # Stop all button
        self.stop_all_btn = QPushButton(" Stop All")
        self.stop_all_btn.setObjectName("DangerButton")
        self.stop_all_btn.setIcon(get_icon("close", 14, "#ff5c7a"))
        self.stop_all_btn.setToolTip("Stop all playing sounds")
        self.stop_all_btn.clicked.connect(self._on_stop_all)
        url_row.addWidget(self.stop_all_btn)

        hero_layout.addLayout(url_row)

        # Status text row
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #7c5cff; font-size: 10px;")
        status_row.addWidget(self.status_dot)

        self.status_lbl = QLabel("Enter or paste a media link above to extract and play instantly.")
        self.status_lbl.setObjectName("MutedLabel")
        status_row.addWidget(self.status_lbl, stretch=1)
        hero_layout.addLayout(status_row)

        outer.addWidget(hero_card)

        # ── History Section ──────────────────────────────────────────
        history_header_row = QHBoxLayout()
        history_header_row.setSpacing(10)

        history_title = QLabel("Played Clips History")
        history_title.setObjectName("SectionHeader")
        history_header_row.addWidget(history_title)

        self.count_badge = QLabel("0 Clips")
        self.count_badge.setObjectName("StatusBadge")
        history_header_row.addWidget(self.count_badge)

        history_header_row.addStretch(1)

        # Search filter
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText("Filter history...")
        self.search_filter.setClearButtonEnabled(True)
        self.search_filter.setFixedWidth(220)
        self.search_filter.textChanged.connect(self._on_filter_changed)
        history_header_row.addWidget(self.search_filter)

        # Clear button
        self.clear_btn = QPushButton(" Clear All")
        self.clear_btn.setObjectName("DangerButton")
        self.clear_btn.setIcon(get_icon("trash", 14, "#ff5c7a"))
        self.clear_btn.clicked.connect(self._on_clear_history)
        history_header_row.addWidget(self.clear_btn)

        outer.addLayout(history_header_row)

        # Scrollable list of history items
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setSpacing(10)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setAlignment(Qt.AlignTop)

        # Empty state label
        self.empty_label = QLabel("No links played yet.\nPaste an Instagram, YouTube, Twitter/X or direct link above to get started!")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("MutedLabel")
        self.empty_label.setStyleSheet("padding: 50px; font-size: 13px; font-weight: 500;")
        self.list_layout.addWidget(self.empty_label)

        self.scroll_area.setWidget(self.list_container)
        outer.addWidget(self.scroll_area, stretch=1)

    # ------------------------------------------------------------------
    # URL Actions
    # ------------------------------------------------------------------
    def _on_paste_clicked(self) -> None:
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.url_input.setText(text)
            self.url_input.setFocus()

    def _on_play_input_url(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            self.status_lbl.setText("Please enter or paste a valid URL.")
            self.status_dot.setStyleSheet("color: #ffb830; font-size: 10px;")
            return
        self.play_url(url)

    def play_url(self, url: str) -> None:
        """Download (if not cached) and trigger playback of any link."""
        url = url.strip()
        if not url:
            return

        platform = detect_platform(url)

        # Check if already cached
        cached_path = self._extractor.get_cached_file(url)
        if cached_path is not None:
            self.status_lbl.setText(f"Playing '{platform}' clip from local cache...")
            self.status_dot.setStyleSheet("color: #3ddc97; font-size: 10px;")
            item_id = f"link_{self._extractor.get_url_hash(url)}"

            # Find or create history item
            meta = {
                "id": item_id,
                "url": url,
                "title": f"{platform} Clip",
                "source": platform,
                "cached_path": str(cached_path),
                "duration": "",
                "played_at": "Just now",
            }
            existing = next((h for h in self._settings.get_link_history() if h.get("id") == item_id), None)
            if existing:
                meta.update(existing)

            self._settings.add_link_history_item(meta)
            self.reload_history()
            self._set_card_playing(item_id, True)

            self.sound_ready_to_play.emit(str(cached_path), item_id)
            self.status_message.emit(f"Playing '{meta.get('title')}'")
            return

        # Need to download via background worker
        self.play_btn.setEnabled(False)
        self.status_lbl.setText(f"Connecting and extracting audio from {platform}...")
        self.status_dot.setStyleSheet("color: #ffb830; font-size: 10px;")
        self.status_message.emit(f"Downloading from {platform}...")

        worker = LinkDownloadWorker(self._extractor, url, self)
        worker.progress.connect(self._on_worker_progress)
        worker.finished_ok.connect(self._on_worker_ok)
        worker.error.connect(self._on_worker_err)
        self._worker = worker
        worker.start()

    def _on_worker_progress(self, msg: str) -> None:
        self.status_lbl.setText(msg)

    def _on_worker_ok(self, meta: dict, local_path: str) -> None:
        self.play_btn.setEnabled(True)
        self.status_lbl.setText(f"Playing: {meta.get('title')}")
        self.status_dot.setStyleSheet("color: #3ddc97; font-size: 10px;")

        # Add to history
        self._settings.add_link_history_item(meta)
        self.reload_history()

        item_id = meta.get("id", "")
        self._set_card_playing(item_id, True)

        self.sound_ready_to_play.emit(local_path, item_id)
        self.status_message.emit(f"Playing '{meta.get('title')}'")

    def _on_worker_err(self, err_msg: str) -> None:
        self.play_btn.setEnabled(True)
        self.status_lbl.setText(f"Error: {err_msg}")
        self.status_dot.setStyleSheet("color: #ff5c7a; font-size: 10px;")
        self.status_message.emit(f"Link error: {err_msg}")

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------
    def reload_history(self) -> None:
        history = self._settings.get_link_history()
        self.count_badge.setText(f"{len(history)} Clip{'s' if len(history) != 1 else ''}")

        # Clear existing cards
        for card in self._history_cards:
            card.setParent(None)
            card.deleteLater()
        self._history_cards.clear()

        # Remove items from layout
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not history:
            self.empty_label = QLabel("No links played yet.\nPaste an Instagram, YouTube, Twitter/X or direct link above to get started!")
            self.empty_label.setAlignment(Qt.AlignCenter)
            self.empty_label.setObjectName("MutedLabel")
            self.empty_label.setStyleSheet("padding: 50px; font-size: 13px; font-weight: 500;")
            self.list_layout.addWidget(self.empty_label)
            return

        filter_text = self.search_filter.text().strip().lower()

        for item in history:
            title = item.get("title", "").lower()
            url = item.get("url", "").lower()
            source = item.get("source", "").lower()
            if filter_text and (filter_text not in title and filter_text not in url and filter_text not in source):
                continue

            card = HistoryItemCard(item)
            card.play_requested.connect(self._on_history_play)
            card.stop_requested.connect(self._on_history_stop)
            card.delete_requested.connect(self._on_history_delete)

            if item.get("id") in self._playing_cards:
                card.set_playing(True)

            self.list_layout.addWidget(card)
            self._history_cards.append(card)

    def _on_filter_changed(self, text: str) -> None:
        self.reload_history()

    def _on_history_play(self, item: dict) -> None:
        cached_path = item.get("cached_path")
        url = item.get("url", "")
        item_id = item.get("id", "")

        # If cached file exists, play immediately
        if cached_path:
            from pathlib import Path
            p = Path(cached_path)
            if p.exists() and p.stat().st_size > 0:
                self._set_card_playing(item_id, True)
                self.sound_ready_to_play.emit(str(p), item_id)
                self.status_message.emit(f"Playing '{item.get('title')}'")
                return

        # Otherwise redownload via URL
        if url:
            self.play_url(url)

    def _on_history_stop(self, card_id: str) -> None:
        self._set_card_playing(card_id, False)
        self.sound_stop_requested.emit(card_id)

    def _on_history_delete(self, item_id: str) -> None:
        self._settings.remove_link_history_item(item_id)
        self.reload_history()

    def _on_clear_history(self) -> None:
        self._settings.clear_link_history()
        self.reload_history()

    def _on_stop_all(self) -> None:
        for card in self._history_cards:
            card.set_playing(False)
        self._playing_cards.clear()
        self.status_message.emit("STOP_ALL")

    def _set_card_playing(self, card_id: str, playing: bool) -> None:
        if playing:
            self._playing_cards[card_id] = "playing"
        else:
            self._playing_cards.pop(card_id, None)

        for card in self._history_cards:
            if card.item_id == card_id:
                card.set_playing(playing)

    def reset_card_playing(self, card_id: str) -> None:
        self._set_card_playing(card_id, False)

    def shutdown(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
