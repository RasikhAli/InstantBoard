"""
gui/settings_dialog.py

Settings dialog: cache management, favorites list, and hotkey
assignment (F1-F12 and Ctrl+<letter> combinations bound to favorite
sounds).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from myinstants.parser import Sound
from utils.cache import CacheManager
from utils.icons import get_icon
from utils.settings import SettingsManager

logger = logging.getLogger(__name__)

AVAILABLE_HOTKEYS = [f"F{i}" for i in range(1, 13)] + [f"Ctrl+{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]


class SettingsDialog(QDialog):
    """Modal dialog exposing cache, favorites and hotkey management."""

    favorite_play_requested = Signal(dict)
    hotkeys_changed = Signal()

    def __init__(
        self,
        settings: SettingsManager,
        cache: CacheManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — InstantBoard")
        self.setMinimumSize(600, 520)
        self._settings = settings
        self._cache = cache

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # Dialog Title Header
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        settings_icon = QLabel()
        settings_icon.setPixmap(get_icon("settings", 22, "#7c5cff").pixmap(22, 22))
        header_row.addWidget(settings_icon)

        title = QLabel("InstantBoard Settings")
        title.setObjectName("TitleLabel")
        header_row.addWidget(title)
        header_row.addStretch()
        layout.addLayout(header_row)

        tabs = QTabWidget()
        layout.addWidget(tabs, stretch=1)

        tabs.addTab(self._build_general_tab(), "  General & Cache  ")
        tabs.addTab(self._build_favorites_tab(), "  Favorites  ")
        tabs.addTab(self._build_hotkeys_tab(), "  Global Hotkeys  ")

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton(" Done")
        close_button.setObjectName("PrimaryButton")
        close_button.setIcon(get_icon("check", 14, "#ffffff"))
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

    # ------------------------------------------------------------------
    # General tab
    # ------------------------------------------------------------------
    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(14)
        layout.setContentsMargins(12, 14, 12, 14)

        # Cache Card
        cache_card = QFrame()
        cache_card.setObjectName("Card")
        cache_card.setStyleSheet("""
            QFrame#Card {
                background-color: #1a1a26;
                border: 1px solid #28283a;
                border-radius: 14px;
                padding: 16px;
            }
        """)
        cc_layout = QVBoxLayout(cache_card)
        cc_layout.setSpacing(12)

        header_lbl = QLabel("Audio Disk Cache")
        header_lbl.setObjectName("SectionHeader")
        cc_layout.addWidget(header_lbl)

        cache_row = QHBoxLayout()
        cache_label = QLabel(f"Location: {self._cache.cache_dir}")
        cache_label.setObjectName("MutedLabel")
        self._cache_label = cache_label
        cache_row.addWidget(cache_label, stretch=1)
        change_button = QPushButton("Change Folder...")
        change_button.clicked.connect(self._on_change_cache_folder)
        cache_row.addWidget(change_button)
        cc_layout.addLayout(cache_row)

        size_label = QLabel(f"Total Cached Size: {self._format_size(self._cache.total_size_bytes())}")
        size_label.setStyleSheet("color: #3ddc97; font-size: 12px; font-weight: 700;")
        self._size_label = size_label
        cc_layout.addWidget(size_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        clear_button = QPushButton(" Clear Entire Cache")
        clear_button.setObjectName("DangerButton")
        clear_button.setIcon(get_icon("trash", 14, "#ff5c7a"))
        clear_button.clicked.connect(self._on_clear_cache)
        btn_row.addWidget(clear_button)

        cleanup_button = QPushButton(" Clean Up Old Files (30+ days)")
        cleanup_button.setIcon(get_icon("time", 14, "#c2c2d4"))
        cleanup_button.clicked.connect(self._on_cleanup_cache)
        btn_row.addWidget(cleanup_button)
        btn_row.addStretch()
        cc_layout.addLayout(btn_row)

        layout.addWidget(cache_card)
        layout.addStretch(1)
        return widget

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        size = float(num_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _on_change_cache_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Cache Folder", str(self._cache.cache_dir))
        if folder:
            self._cache.set_cache_dir(folder)
            self._settings.set("cache_folder", folder)
            self._cache_label.setText(f"Cache folder: {self._cache.cache_dir}")
            self._size_label.setText(f"Cache size: {self._format_size(self._cache.total_size_bytes())}")

    def _on_clear_cache(self) -> None:
        confirm = QMessageBox.question(
            self, "Clear Cache", "Delete every downloaded sound file? This cannot be undone."
        )
        if confirm == QMessageBox.Yes:
            removed = self._cache.clear()
            self._size_label.setText(f"Cache size: {self._format_size(self._cache.total_size_bytes())}")
            QMessageBox.information(self, "Cache Cleared", f"Removed {removed} file(s).")

    def _on_cleanup_cache(self) -> None:
        removed = self._cache.cleanup_older_than(30)
        self._size_label.setText(f"Cache size: {self._format_size(self._cache.total_size_bytes())}")
        QMessageBox.information(self, "Cleanup Complete", f"Removed {removed} old file(s).")

    # ------------------------------------------------------------------
    # Favorites tab
    # ------------------------------------------------------------------
    def _build_favorites_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.favorites_list = QListWidget()
        self._reload_favorites_list()
        layout.addWidget(self.favorites_list, stretch=1)

        button_row = QHBoxLayout()
        play_button = QPushButton("Play Selected")
        play_button.setIcon(get_icon("play", 16))
        play_button.clicked.connect(self._on_play_favorite)
        button_row.addWidget(play_button)

        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self._on_remove_favorite)
        button_row.addWidget(remove_button)
        layout.addLayout(button_row)

        return widget

    def _reload_favorites_list(self) -> None:
        self.favorites_list.clear()
        for fav in self._settings.get_favorites():
            item = QListWidgetItem(fav.get("title", "Untitled"))
            item.setData(Qt.UserRole, fav)
            self.favorites_list.addItem(item)

    def _on_play_favorite(self) -> None:
        item = self.favorites_list.currentItem()
        if item:
            self.favorite_play_requested.emit(item.data(Qt.UserRole))

    def _on_remove_favorite(self) -> None:
        item = self.favorites_list.currentItem()
        if item:
            sound = item.data(Qt.UserRole)
            self._settings.remove_favorite(sound.get("id"))
            self._reload_favorites_list()

    # ------------------------------------------------------------------
    # Hotkeys tab
    # ------------------------------------------------------------------
    def _build_hotkeys_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel(
            "Assign a hotkey to any favorited sound. Hotkeys work globally "
            "while InstantBoard is running (F1-F12 and Ctrl+letter combinations)."
        )
        info.setWordWrap(True)
        info.setObjectName("MutedLabel")
        layout.addWidget(info)

        assign_row = QHBoxLayout()
        self.hotkey_combo = QComboBox()
        self.hotkey_combo.addItems(AVAILABLE_HOTKEYS)
        assign_row.addWidget(self.hotkey_combo)

        self.favorite_combo = QComboBox()
        for fav in self._settings.get_favorites():
            self.favorite_combo.addItem(fav.get("title", "Untitled"), fav)
        assign_row.addWidget(self.favorite_combo, stretch=1)

        assign_button = QPushButton("Assign")
        assign_button.setObjectName("PrimaryButton")
        assign_button.clicked.connect(self._on_assign_hotkey)
        assign_row.addWidget(assign_button)
        layout.addLayout(assign_row)

        self.hotkeys_list = QListWidget()
        self._reload_hotkeys_list()
        layout.addWidget(self.hotkeys_list, stretch=1)

        remove_button = QPushButton("Remove Selected Hotkey")
        remove_button.clicked.connect(self._on_remove_hotkey)
        layout.addWidget(remove_button)

        return widget

    def _reload_hotkeys_list(self) -> None:
        self.hotkeys_list.clear()
        for hotkey, sound in self._settings.get_hotkeys().items():
            item = QListWidgetItem(f"{hotkey}  ->  {sound.get('title', 'Untitled')}")
            item.setData(Qt.UserRole, hotkey)
            self.hotkeys_list.addItem(item)

    def _on_assign_hotkey(self) -> None:
        hotkey = self.hotkey_combo.currentText()
        sound = self.favorite_combo.currentData()
        if not sound:
            QMessageBox.warning(self, "No Favorites", "Favorite a sound first, then assign a hotkey to it.")
            return
        self._settings.set_hotkey(hotkey, sound)
        self._reload_hotkeys_list()
        self.hotkeys_changed.emit()

    def _on_remove_hotkey(self) -> None:
        item = self.hotkeys_list.currentItem()
        if item:
            hotkey = item.data(Qt.UserRole)
            self._settings.remove_hotkey(hotkey)
            self._reload_hotkeys_list()
            self.hotkeys_changed.emit()
