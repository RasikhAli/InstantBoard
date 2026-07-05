"""
utils/settings.py

Persistent JSON-backed application settings for InstantBoard.

The SettingsManager is the single source of truth for all user
preferences: last-used devices, volumes, window geometry, favorites,
hotkey bindings, cache location and theme. It is intentionally simple
(a thread-safe wrapper around a dict that is flushed to disk) so that
every other module can depend on it without worrying about I/O details.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: Dict[str, Any] = {
    "last_microphone": None,
    "last_speaker": None,
    "last_output_device": None,
    "last_search": "",
    "theme": "dark",
    "window_width": 1200,
    "window_height": 800,
    "favorites": [],
    "cache_folder": "cache",
    "playback_volume": 0.8,
    "microphone_volume": 0.8,
    "soundboard_volume": 0.8,
    "hotkeys": {},
    "auto_cleanup_cache": False,
    "auto_cleanup_days": 30,
}


class SettingsManager:
    """Loads, stores and persists application settings as JSON.

    Parameters
    ----------
    path:
        Path to the settings file on disk. It will be created with
        default values if it does not exist yet.
    """

    def __init__(self, path: str | os.PathLike = "settings.json") -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load settings from disk, merging with defaults for any
        keys that are missing (e.g. after an application update)."""
        with self._lock:
            if self._path.exists():
                try:
                    with open(self._path, "r", encoding="utf-8") as fh:
                        on_disk = json.load(fh)
                    merged = dict(DEFAULT_SETTINGS)
                    merged.update(on_disk)
                    self._data = merged
                    logger.info("Settings loaded from %s", self._path)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.error("Failed to load settings (%s); using defaults", exc)
                    self._data = dict(DEFAULT_SETTINGS)
            else:
                logger.info("No settings file found at %s; creating defaults", self._path)
                self._data = dict(DEFAULT_SETTINGS)
                self.save()

    def save(self) -> None:
        """Persist the current settings dict to disk atomically."""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self._path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, indent=2, ensure_ascii=False)
                tmp_path.replace(self._path)
            except OSError as exc:
                logger.error("Failed to save settings: %s", exc)

    # ------------------------------------------------------------------
    # Generic accessors
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        with self._lock:
            self._data[key] = value
            if persist:
                self.save()

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)

    # ------------------------------------------------------------------
    # Favorites helpers
    # ------------------------------------------------------------------
    def get_favorites(self) -> List[Dict[str, Any]]:
        return list(self.get("favorites", []))

    def add_favorite(self, sound: Dict[str, Any]) -> None:
        with self._lock:
            favorites = self.get_favorites()
            if not any(f.get("id") == sound.get("id") for f in favorites):
                favorites.append(sound)
                self.set("favorites", favorites)

    def remove_favorite(self, sound_id: str) -> None:
        with self._lock:
            favorites = [f for f in self.get_favorites() if f.get("id") != sound_id]
            self.set("favorites", favorites)

    def is_favorite(self, sound_id: str) -> bool:
        return any(f.get("id") == sound_id for f in self.get_favorites())

    # ------------------------------------------------------------------
    # Hotkey helpers
    # ------------------------------------------------------------------
    def get_hotkeys(self) -> Dict[str, Dict[str, Any]]:
        """Return mapping of hotkey string -> sound dict."""
        return dict(self.get("hotkeys", {}))

    def set_hotkey(self, hotkey: str, sound: Dict[str, Any]) -> None:
        with self._lock:
            hotkeys = self.get_hotkeys()
            hotkeys[hotkey] = sound
            self.set("hotkeys", hotkeys)

    def remove_hotkey(self, hotkey: str) -> None:
        with self._lock:
            hotkeys = self.get_hotkeys()
            hotkeys.pop(hotkey, None)
            self.set("hotkeys", hotkeys)
