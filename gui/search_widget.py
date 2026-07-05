"""
gui/search_widget.py

The central panel of InstantBoard: the search bar plus a scrollable
grid of polished square sound cards with per-card play/stop toggles.
All network activity runs on background QThreads so the GUI never
freezes.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from myinstants.api import MyInstantsClient, MyInstantsError
from myinstants.parser import Sound
from utils.cache import CacheManager
from utils.icons import get_icon
from utils.settings import SettingsManager

logger = logging.getLogger(__name__)

CARD_SIZE = 180
COLUMNS_MIN = 2
COLUMNS_MAX = 8

# Color palette for card accents (cycling through them adds visual variety)
CARD_COLORS = [
    "#7c5cff",  # purple
    "#ff5c7a",  # red
    "#3ddc97",  # green
    "#ffcf4d",  # yellow
    "#5c9cff",  # blue
    "#ff7c5c",  # orange
    "#c45cff",  # magenta
    "#5cffcf",  # teal
]


# ==========================================================================
# Background workers
# ==========================================================================
class SearchWorker(QThread):
    results_ready = Signal(list, object)
    error = Signal(str)

    def __init__(self, client: MyInstantsClient, query: Optional[str] = None, url: Optional[str] = None) -> None:
        super().__init__()
        self._client = client
        self._query = query
        self._url = url

    def run(self) -> None:
        try:
            if self._url:
                sounds, next_url = self._client.fetch_page(self._url)
            elif self._query:
                sounds, next_url = self._client.search(self._query)
            else:
                sounds, next_url = self._client.get_trending()
            self.results_ready.emit(sounds, next_url)
        except MyInstantsError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during search")
            self.error.emit(f"Unexpected error: {exc}")


class DownloadWorker(QThread):
    finished_ok = Signal(str, str)
    error = Signal(str, str)

    def __init__(self, client: MyInstantsClient, cache: CacheManager, sound: Sound) -> None:
        super().__init__()
        self._client = client
        self._cache = cache
        self._sound = sound

    def run(self) -> None:
        try:
            cached_path = self._cache.get_cached_path(self._sound.download_url)
            if cached_path is not None:
                self.finished_ok.emit(str(cached_path), self._sound.id)
                return
            data = self._client.download_sound(self._sound)
            path = self._cache.store(self._sound.download_url, data)
            self.finished_ok.emit(str(path), self._sound.id)
        except MyInstantsError as exc:
            self.error.emit(str(exc), self._sound.id)
        except Exception as exc:
            logger.exception("Unexpected error during download")
            self.error.emit(f"Unexpected error: {exc}", self._sound.id)


# ==========================================================================
# Polished square sound card with play/stop toggle
# ==========================================================================
class SoundCard(QFrame):
    """A single polished square sound card. The main play button toggles
    between 'play' and 'stop' states so the user can stop individual
    sounds without stopping everything."""

    play_requested = Signal(object)  # Sound
    stop_requested = Signal(object)  # Sound
    favorite_toggled = Signal(object, bool)

    def __init__(self, sound: Sound, is_favorite: bool, is_cached: bool,
                 accent_color: str, card_index: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.sound = sound
        self._is_favorite = is_favorite
        self._is_playing = False
        self._accent = accent_color

        self.setObjectName("Card")
        self.setFixedSize(CARD_SIZE, CARD_SIZE)
        self.setCursor(Qt.PointingHandCursor)

        # Card stylesheet with accent color
        self.setStyleSheet(f"""
        QFrame#Card {{
            background-color: #22222e;
            border: 1px solid #33333f;
            border-radius: 16px;
        }}
        QFrame#Card:hover {{
            border: 2px solid {self._accent};
            background-color: #2a2a38;
        }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(0)

        # --- Top row: favorite + cached indicator ---
        top = QHBoxLayout()
        top.setSpacing(0)

        self.fav_btn = QPushButton()
        self.fav_btn.setObjectName("CardIconBtn")
        self.fav_btn.setFixedSize(24, 24)
        self.fav_btn.setCursor(Qt.PointingHandCursor)
        self._update_fav_icon()
        self.fav_btn.clicked.connect(self._on_fav_clicked)
        top.addWidget(self.fav_btn)

        top.addStretch()

        self.cached_label = QLabel()
        self.cached_label.setFixedSize(16, 16)
        if is_cached:
            pix = get_icon("download", 12, "#3ddc97").pixmap(12, 12)
            self.cached_label.setPixmap(pix)
        else:
            self.cached_label.setVisible(False)
        top.addWidget(self.cached_label)
        layout.addLayout(top)

        layout.addSpacing(6)

        # --- Center: large accent-colored play/stop button ---
        center = QHBoxLayout()
        center.addStretch()

        self.action_btn = QPushButton()
        self.action_btn.setObjectName("CardActionBtn")
        self.action_btn.setFixedSize(60, 60)
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setIcon(get_icon("play", 36, "#ffffff"))
        self.action_btn.setStyleSheet(f"""
        QPushButton#CardActionBtn {{
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {self._accent}, stop:1 {self._accent}dd);
            border: none;
            border-radius: 30px;
        }}
        QPushButton#CardActionBtn:hover {{
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {self._accent}ee, stop:1 {self._accent});
            border: 2px solid #ffffff44;
        }}
        QPushButton#CardActionBtn:pressed {{
            background-color: #444;
        }}
        """)
        self.action_btn.clicked.connect(self._on_action_clicked)
        center.addWidget(self.action_btn)
        center.addStretch()
        layout.addLayout(center)

        layout.addSpacing(8)

        # --- Bottom: title ---
        self.title_lbl = QLabel(sound.title)
        self.title_lbl.setAlignment(Qt.AlignCenter)
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setMaximumHeight(42)
        self.title_lbl.setStyleSheet("color: #f2f2f7; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.title_lbl)

        # --- Status text ---
        self.status_lbl = QLabel("")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setFixedHeight(14)
        self.status_lbl.setStyleSheet("color: #9a9aa5; font-size: 10px;")
        layout.addWidget(self.status_lbl)

        # Double-click also triggers play
        self.mouseDoubleClickEvent = lambda e: self._on_action_clicked()

    # ------------------------------------------------------------------
    def _update_fav_icon(self) -> None:
        name = "favorite_filled" if self._is_favorite else "favorite"
        self.fav_btn.setIcon(get_icon(name, 14))

    def _on_fav_clicked(self) -> None:
        self._is_favorite = not self._is_favorite
        self._update_fav_icon()
        self.favorite_toggled.emit(self.sound, self._is_favorite)

    def _on_action_clicked(self) -> None:
        if self._is_playing:
            self.stop_requested.emit(self.sound)
        else:
            self.play_requested.emit(self.sound)

    # ------------------------------------------------------------------
    # Public state setters
    # ------------------------------------------------------------------
    def set_playing(self, playing: bool) -> None:
        """Toggle the button between play and stop icon."""
        self._is_playing = playing
        icon_name = "pause" if playing else "play"
        icon_size = 28 if playing else 36
        self.action_btn.setIcon(get_icon(icon_name, icon_size, "#ffffff"))

    def mark_cached(self) -> None:
        self.cached_label.setPixmap(get_icon("download", 12, "#3ddc97").pixmap(12, 12))
        self.cached_label.setVisible(True)
        self.status_lbl.setText("")

    def mark_downloading(self) -> None:
        self.status_lbl.setText("Downloading...")
        self.action_btn.setEnabled(False)

    def mark_ready(self) -> None:
        self.action_btn.setEnabled(True)

    def mark_error(self, msg: str) -> None:
        self.status_lbl.setText("Failed")
        self.status_lbl.setToolTip(msg)
        self.action_btn.setEnabled(True)


# ==========================================================================
# Main search widget
# ==========================================================================
class SearchWidget(QWidget):
    """Search bar + infinite-scrolling grid of square sound cards."""

    sound_ready_to_play = Signal(str, str)  # local_path, card_id (sound.id)
    sound_stop_requested = Signal(str)  # sound_id (string) to stop
    status_message = Signal(str)

    def __init__(self, settings: SettingsManager, cache: CacheManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cache = cache
        self._client = MyInstantsClient()
        self._columns = COLUMNS_MIN

        self._search_worker: Optional[SearchWorker] = None
        self._download_workers: Dict[str, DownloadWorker] = {}
        self._next_page_url: Optional[str] = None
        self._is_loading = False
        self._current_query = ""
        self._cards: List[SoundCard] = []
        self._playing_sounds: Dict[str, str] = {}  # sound.id -> local_path

        self._build_ui()
        last_query = settings.get("last_search", "")
        if last_query:
            self.search_box.setText(last_query)
            self.run_search(last_query)
        else:
            self.load_trending()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        # Search row
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search sounds on MyInstants...")
        self.search_box.returnPressed.connect(lambda: self.run_search(self.search_box.text()))
        search_row.addWidget(self.search_box, stretch=1)

        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("PrimaryButton")
        self.search_btn.setIcon(get_icon("search", 16, "#ffffff"))
        self.search_btn.clicked.connect(lambda: self.run_search(self.search_box.text()))
        search_row.addWidget(self.search_btn)

        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("IconButton")
        self.refresh_btn.setIcon(get_icon("refresh", 18))
        self.refresh_btn.setFixedSize(38, 38)
        self.refresh_btn.setToolTip("Refresh")
        self.refresh_btn.clicked.connect(self._on_refresh)
        search_row.addWidget(self.refresh_btn)

        self.stop_all_btn = QPushButton()
        self.stop_all_btn.setObjectName("IconButton")
        self.stop_all_btn.setIcon(get_icon("close", 16, "#ff5c7a"))
        self.stop_all_btn.setFixedSize(38, 38)
        self.stop_all_btn.setToolTip("Stop All Sounds")
        self.stop_all_btn.clicked.connect(self._on_stop_all)
        search_row.addWidget(self.stop_all_btn)

        outer.addLayout(search_row)

        # Scrollable grid
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.grid_container = QWidget()
        self.grid_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.grid = QGridLayout(self.grid_container)
        self.grid.setSpacing(12)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.scroll_area.setWidget(self.grid_container)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)
        outer.addWidget(self.scroll_area, stretch=1)

    def _col_count(self) -> int:
        vw = self.scroll_area.viewport().width()
        if vw < 500:
            return 2
        return max(COLUMNS_MIN, min(COLUMNS_MAX, vw // (CARD_SIZE + 12)))

    # ------------------------------------------------------------------
    # Search / load
    # ------------------------------------------------------------------
    def load_trending(self) -> None:
        self._current_query = ""
        self._start_search(None, None)

    def run_search(self, query: str) -> None:
        q = query.strip()
        if not q:
            self.load_trending()
            return
        self._current_query = q
        self._settings.set("last_search", q)
        self._start_search(query=q, url=None)

    def _on_refresh(self) -> None:
        if self._current_query:
            self._start_search(query=self._current_query, url=None)
        else:
            self.load_trending()

    def _on_stop_all(self) -> None:
        # Mark all cards as not playing
        for card in self._cards:
            card.set_playing(False)
        self._playing_sounds.clear()
        self.status_message.emit("STOP_ALL")

    def _start_search(self, query: Optional[str], url: Optional[str]) -> None:
        if self._is_loading:
            return
        self._is_loading = True
        if url is None:
            self._clear_cards()
            self.status_message.emit("Searching...")
        else:
            self.status_message.emit("Loading more...")
        w = SearchWorker(self._client, query=query, url=url)
        w.results_ready.connect(self._on_results)
        w.error.connect(self._on_search_err)
        self._search_worker = w
        w.start()

    def _on_results(self, sounds: List[Sound], next_url: Optional[str]) -> None:
        self._is_loading = False
        self._next_page_url = next_url
        cols = self._col_count()
        self._columns = cols
        for sound in sounds:
            self._add_card(sound)
        self.status_message.emit(f"{len(self._cards)} sound{'s' if len(self._cards) != 1 else ''} loaded")

    def _on_search_err(self, msg: str) -> None:
        self._is_loading = False
        self.status_message.emit(f"Error: {msg}")
        logger.error("Search error: %s", msg)

    def _on_scroll(self, value: int) -> None:
        sb = self.scroll_area.verticalScrollBar()
        if value >= sb.maximum() - 100 and self._next_page_url and not self._is_loading:
            self._start_search(query=None, url=self._next_page_url)

    # ------------------------------------------------------------------
    # Card management
    # ------------------------------------------------------------------
    def _clear_cards(self) -> None:
        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()
        self._playing_sounds.clear()
        self._next_page_url = None
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_card(self, sound: Sound) -> None:
        is_fav = self._settings.is_favorite(sound.id)
        is_cached = self._cache.is_cached(sound.download_url)
        accent = CARD_COLORS[len(self._cards) % len(CARD_COLORS)]
        card = SoundCard(sound, is_fav, is_cached, accent, len(self._cards))
        card.play_requested.connect(self._on_play_card)
        card.stop_requested.connect(self._on_stop_card)
        card.favorite_toggled.connect(self._on_fav_card)

        idx = len(self._cards)
        row, col = idx // self._columns, idx % self._columns
        self.grid.addWidget(card, row, col)
        self._cards.append(card)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def _on_play_card(self, sound: Sound) -> None:
        card = next((c for c in self._cards if c.sound.id == sound.id), None)
        if not card:
            return

        cached = self._cache.get_cached_path(sound.download_url)
        if cached is not None:
            # Already cached: play immediately
            path = str(cached)
            card.set_playing(True)
            self._playing_sounds[sound.id] = path
            self.sound_ready_to_play.emit(path, sound.id)
            return

        # Need to download first
        card.mark_downloading()
        self.status_message.emit(f"Downloading '{sound.title}'...")
        w = DownloadWorker(self._client, self._cache, sound)
        w.finished_ok.connect(self._on_dl_ok)
        w.error.connect(self._on_dl_err)
        self._download_workers[sound.id] = w
        w.start()

    def _on_stop_card(self, sound: Sound) -> None:
        card = next((c for c in self._cards if c.sound.id == sound.id), None)
        if card:
            card.set_playing(False)
        self._playing_sounds.pop(sound.id, None)
        self.sound_stop_requested.emit(sound.id)

    def reset_card_playing(self, sound_id: str) -> None:
        card = next((c for c in self._cards if c.sound.id == sound_id), None)
        if card:
            card.set_playing(False)
        self._playing_sounds.pop(sound_id, None)

    def _on_dl_ok(self, path: str, sound_id: str) -> None:
        self._download_workers.pop(sound_id, None)
        card = next((c for c in self._cards if c.sound.id == sound_id), None)
        if card:
            card.mark_cached()
            card.mark_ready()
            card.set_playing(True)
            self._playing_sounds[sound_id] = path
        self.status_message.emit("Ready")
        self.sound_ready_to_play.emit(path, sound_id)

    def _on_dl_err(self, msg: str, sound_id: str) -> None:
        self._download_workers.pop(sound_id, None)
        card = next((c for c in self._cards if c.sound.id == sound_id), None)
        if card:
            card.mark_error(msg)
        self.status_message.emit(f"Download failed: {msg}")

    def _on_fav_card(self, sound: Sound, fav: bool) -> None:
        if fav:
            self._settings.add_favorite(sound.to_dict())
        else:
            self._settings.remove_favorite(sound.id)

    def play_sound_by_dict(self, d: dict) -> None:
        s = Sound.from_dict(d)
        self._on_play_card(s)

    def shutdown(self) -> None:
        self._client.close()