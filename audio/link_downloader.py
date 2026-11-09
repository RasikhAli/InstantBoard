"""
audio/link_downloader.py

Handles metadata extraction and audio downloading from arbitrary web links
(Instagram Reels/Posts, YouTube Videos/Shorts, Twitter/X, TikTok, SoundCloud,
Reddit, Twitch, direct audio URLs, etc.) using yt-dlp with caching and
background QThread execution.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal

from utils.cache import CacheManager

logger = logging.getLogger(__name__)


def detect_platform(url: str) -> str:
    """Return a clean platform name from the URL."""
    low = url.lower()
    if "instagram.com" in low or "instagr.am" in low:
        return "Instagram"
    elif "youtube.com" in low or "youtu.be" in low:
        return "YouTube"
    elif "twitter.com" in low or "x.com" in low:
        return "Twitter/X"
    elif "tiktok.com" in low:
        return "TikTok"
    elif "soundcloud.com" in low:
        return "SoundCloud"
    elif "reddit.com" in low or "redd.it" in low:
        return "Reddit"
    elif "twitch.tv" in low:
        return "Twitch"
    elif "facebook.com" in low or "fb.watch" in low:
        return "Facebook"
    elif any(low.endswith(ext) or ext + "?" in low for ext in (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac")):
        return "Direct Audio"
    else:
        try:
            domain = urllib.parse.urlparse(url).netloc
            return domain.replace("www.", "").capitalize() if domain else "Web Link"
        except Exception:
            return "Web Link"


def format_duration(seconds: Optional[float | int]) -> str:
    """Format duration in seconds as M:SS or H:MM:SS."""
    if seconds is None or seconds <= 0:
        return ""
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class LinkAudioExtractor:
    """Extracts audio and metadata from web links into a local cache."""

    def __init__(self, cache: CacheManager) -> None:
        self._cache = cache

    @staticmethod
    def get_url_hash(url: str) -> str:
        # Normalize URL by removing trailing slash & standardizing
        clean_url = url.strip().rstrip("/")
        return hashlib.sha256(clean_url.encode("utf-8")).hexdigest()[:20]

    def get_cached_file(self, url: str) -> Optional[Path]:
        """Check if any audio format is already cached for this URL."""
        url_hash = self.get_url_hash(url)
        cache_dir = self._cache.cache_dir
        for ext in (".m4a", ".mp3", ".webm", ".opus", ".wav", ".aac", ".ogg", ".mp4"):
            candidate = cache_dir / f"link_{url_hash}{ext}"
            if candidate.exists() and candidate.stat().st_size > 1024:
                return candidate
        return None

    def download(self, url: str, on_status: Optional[callable] = None) -> Tuple[Dict[str, Any], str]:
        """
        Download and extract audio for a URL.
        Returns:
            (metadata_dict, local_audio_path_str)
        """
        url = url.strip()
        if not url:
            raise ValueError("URL cannot be empty")

        url_hash = self.get_url_hash(url)
        platform = detect_platform(url)

        # Check if already cached
        cached_file = self.get_cached_file(url)
        if cached_file is not None:
            if on_status:
                on_status("Loaded from cache")
            logger.info("Found cached audio for %s at %s", url, cached_file)
            # Create metadata
            meta = {
                "id": f"link_{url_hash}",
                "url": url,
                "title": f"{platform} clip ({cached_file.stem})",
                "source": platform,
                "cached_path": str(cached_file),
                "duration": "",
                "played_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            return meta, str(cached_file)

        # Direct audio download fallback if URL directly ends with audio format
        lower_url = url.lower()
        for ext in (".mp3", ".wav", ".ogg", ".m4a", ".aac"):
            if lower_url.endswith(ext) or (ext + "?" in lower_url):
                if on_status:
                    on_status("Downloading direct audio...")
                dest_file = self._cache.cache_dir / f"link_{url_hash}{ext}"
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                })
                with urllib.request.urlopen(req, timeout=20) as resp, open(dest_file, "wb") as out_f:
                    out_f.write(resp.read())

                filename_title = Path(urllib.parse.urlparse(url).path).name or f"{platform} Audio"
                meta = {
                    "id": f"link_{url_hash}",
                    "url": url,
                    "title": filename_title,
                    "source": "Direct Audio",
                    "cached_path": str(dest_file),
                    "duration": "",
                    "played_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                return meta, str(dest_file)

        # Use yt-dlp
        if on_status:
            on_status(f"Connecting to {platform}...")

        import yt_dlp
        import imageio_ffmpeg

        ffmpeg_exe = None
        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass

        out_template = str(self._cache.cache_dir / f"link_{url_hash}.%(ext)s")

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "fixup": "never",
            "overwrites": True,
            "socket_timeout": 20,
            "noplaylist": True,
            "ignoreerrors": False,
        }

        if ffmpeg_exe:
            ydl_opts["ffmpeg_location"] = ffmpeg_exe
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if on_status:
                    on_status(f"Extracting {platform} audio...")
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise RuntimeError("No media stream found at this URL.")

                # If it's a playlist or multiple entries, pick the first
                if "entries" in info and info["entries"]:
                    info = info["entries"][0]

                raw_title = info.get("title") or info.get("description") or f"{platform} Clip"
                # Clean up multiline or long titles
                raw_title = raw_title.strip().split("\n")[0].strip()
                if len(raw_title) > 90:
                    raw_title = raw_title[:87] + "..."
                if not raw_title:
                    raw_title = f"{platform} Audio"

                duration_sec = info.get("duration")
                duration_str = format_duration(duration_sec)

                # Look for downloaded file matching link_{url_hash}.*
                # Prefer .mp3 if postprocessed
                mp3_candidate = self._cache.cache_dir / f"link_{url_hash}.mp3"
                if mp3_candidate.exists():
                    downloaded_path = mp3_candidate
                else:
                    filename = ydl.prepare_filename(info)
                    downloaded_path = Path(filename)
                    if not downloaded_path.exists():
                        found = list(self._cache.cache_dir.glob(f"link_{url_hash}.*"))
                        if found:
                            downloaded_path = found[0]
                        else:
                            raise FileNotFoundError(f"Audio file was not saved to {filename}")

                # Verify that the downloaded file contains an actual audio stream
                try:
                    import av
                    with av.open(str(downloaded_path)) as c:
                        if not any(s.type == "audio" for s in c.streams):
                            try:
                                downloaded_path.unlink(missing_ok=True)
                            except Exception:
                                pass
                            raise RuntimeError(
                                f"This {platform} video does not have an audio track (it is silent or muted)."
                            )
                except RuntimeError:
                    raise
                except Exception:
                    pass

                meta = {
                    "id": f"link_{url_hash}",
                    "url": url,
                    "title": raw_title,
                    "source": platform,
                    "cached_path": str(downloaded_path),
                    "duration": duration_str,
                    "played_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                }

                if on_status:
                    on_status("Ready")

                return meta, str(downloaded_path)

        except Exception as exc:
            logger.exception("Error extracting audio from link: %s", url)
            err_msg = str(exc)
            if "unable to obtain file audio codec" in err_msg.lower() or "does not have an audio track" in err_msg.lower():
                err_msg = f"This {platform} video does not have an audio track (it is silent or muted)."
            elif "Unsupported URL" in err_msg:
                err_msg = "Unsupported website or invalid link format."
            elif "Private video" in err_msg or "login" in err_msg.lower():
                err_msg = "Content is private or requires login."
            elif "Video unavailable" in err_msg:
                err_msg = "Media is unavailable or was deleted."
            raise RuntimeError(err_msg) from exc


# ==========================================================================
# Background Worker
# ==========================================================================
class LinkDownloadWorker(QThread):
    """
    Downloads and caches audio from a link in a background QThread.
    Emits:
      progress(str) -> status message
      finished_ok(dict, str) -> (metadata, local_path)
      error(str) -> error message
    """

    progress = Signal(str)
    finished_ok = Signal(dict, str)
    error = Signal(str)

    def __init__(self, extractor: LinkAudioExtractor, url: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._extractor = extractor
        self._url = url

    def run(self) -> None:
        try:
            meta, local_path = self._extractor.download(
                self._url,
                on_status=lambda msg: self.progress.emit(msg),
            )
            self.finished_ok.emit(meta, local_path)
        except Exception as exc:
            self.error.emit(str(exc))
