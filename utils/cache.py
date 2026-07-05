"""
utils/cache.py

Local disk cache for downloaded MyInstants sounds.

Sounds are cached by a stable identifier derived from their remote
URL so that the same sound is never downloaded twice. The cache also
supports an optional auto-cleanup routine that removes files that
have not been accessed for a configurable number of days.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CacheManager:
    """Manages the on-disk cache of downloaded audio files.

    Parameters
    ----------
    cache_dir:
        Directory in which cached audio files are stored. Created if
        it does not already exist.
    """

    def __init__(self, cache_dir: str | os.PathLike = "cache") -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def set_cache_dir(self, cache_dir: str | os.PathLike) -> None:
        """Change the active cache directory, creating it if needed."""
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]

    def path_for_url(self, url: str, suffix: str = ".mp3") -> Path:
        """Return the deterministic local path a given remote URL would
        be cached at, without checking whether it exists."""
        filename = f"{self._hash_url(url)}{suffix}"
        return self._cache_dir / filename

    def is_cached(self, url: str, suffix: str = ".mp3") -> bool:
        path = self.path_for_url(url, suffix)
        return path.exists() and path.stat().st_size > 0

    def get_cached_path(self, url: str, suffix: str = ".mp3") -> Optional[Path]:
        path = self.path_for_url(url, suffix)
        if path.exists() and path.stat().st_size > 0:
            # Touch the file so cleanup routines treat it as recently used.
            try:
                os.utime(path, None)
            except OSError:
                pass
            return path
        return None

    def store(self, url: str, data: bytes, suffix: str = ".mp3") -> Path:
        """Write downloaded bytes to the cache and return the local path."""
        path = self.path_for_url(url, suffix)
        tmp_path = path.with_suffix(path.suffix + ".part")
        try:
            with open(tmp_path, "wb") as fh:
                fh.write(data)
            tmp_path.replace(path)
            logger.info("Cached sound at %s (%d bytes)", path, len(data))
        except OSError as exc:
            logger.error("Failed to write cache file %s: %s", path, exc)
            raise
        return path

    def total_size_bytes(self) -> int:
        """Total size in bytes of everything currently cached."""
        total = 0
        for entry in self._cache_dir.glob("*"):
            if entry.is_file():
                total += entry.stat().st_size
        return total

    def clear(self) -> int:
        """Delete every cached file. Returns number of files removed."""
        removed = 0
        for entry in self._cache_dir.glob("*"):
            if entry.is_file():
                try:
                    entry.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning("Could not delete %s: %s", entry, exc)
        return removed

    def cleanup_older_than(self, days: int) -> int:
        """Delete cached files that have not been accessed in `days` days.

        Returns the number of files removed.
        """
        cutoff = time.time() - (days * 86400)
        removed = 0
        for entry in self._cache_dir.glob("*"):
            if not entry.is_file():
                continue
            try:
                if entry.stat().st_atime < cutoff:
                    entry.unlink()
                    removed += 1
            except OSError as exc:
                logger.warning("Could not clean up %s: %s", entry, exc)
        if removed:
            logger.info("Cache cleanup removed %d file(s) older than %d days", removed, days)
        return removed
