"""
myinstants/parser.py

BeautifulSoup-based parsing of MyInstants HTML pages into structured
Sound records. Kept separate from api.py so that the scraping logic
can evolve independently of the HTTP/session handling, and so it can
be unit tested against saved HTML fixtures without a network call.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.myinstants.com"


@dataclass
class Sound:
    """A single sound result scraped from MyInstants."""

    id: str
    title: str
    play_url: str
    download_url: str
    detail_url: Optional[str] = None
    duration: Optional[float] = None
    thumbnail_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "play_url": self.play_url,
            "download_url": self.download_url,
            "detail_url": self.detail_url,
            "duration": self.duration,
            "thumbnail_url": self.thumbnail_url,
        }

    @staticmethod
    def from_dict(data: dict) -> "Sound":
        return Sound(
            id=data["id"],
            title=data["title"],
            play_url=data["play_url"],
            download_url=data["download_url"],
            detail_url=data.get("detail_url"),
            duration=data.get("duration"),
            thumbnail_url=data.get("thumbnail_url"),
        )


def _make_sound_id(onclick_value: str, href_fallback: str = "") -> str:
    """MyInstants buttons look like:

        <div class="instant" onclick="play('/media/sounds/foo.mp3')">

    We derive a stable ID from the mp3 path, since it never changes.
    """
    match = re.search(r"play\('([^']+)'", onclick_value)
    path = match.group(1) if match else href_fallback
    return re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()


def parse_search_results(html: str) -> List[Sound]:
    """Parse a MyInstants search (or homepage / category) results page.

    The site renders each sound as a `div.instant` element containing:
      - a `<button class="small-button">` with an
        `onclick="play('/media/....mp3', 'loader-xxx', 'slug')"`
        attribute holding the *playable* (streamed) URL
      - an anchor `a.instant-link` with the human-readable title and a
        link to the sound's detail page
      - a download button (not always present; when absent we fall back
        to the play URL)
    """
    soup = BeautifulSoup(html, "html.parser")
    sounds: List[Sound] = []

    for node in soup.select("div.instant"):
        # The onclick is on a child button, not on the div itself
        play_button = node.select_one("button.small-button")
        if not play_button:
            continue
        onclick = play_button.get("onclick", "") or ""
        media_match = re.search(r"play\('([^']+)'", onclick)
        if not media_match:
            continue
        media_path = media_match.group(1)
        play_url = urljoin(BASE_URL, media_path)

        title_anchor = node.select_one("a.instant-link")
        title = title_anchor.get_text(strip=True) if title_anchor else "Untitled"
        detail_href = title_anchor.get("href") if title_anchor else None
        detail_url = urljoin(BASE_URL, detail_href) if detail_href else None

        # MyInstants no longer provides separate download links on the
        # search page; the play URL is the MP3 itself, so we use it
        # directly as the download URL.
        download_url = play_url

        sound_id = _make_sound_id(onclick, media_path)

        sounds.append(
            Sound(
                id=sound_id,
                title=title,
                play_url=play_url,
                download_url=download_url,
                detail_url=detail_url,
            )
        )

    logger.debug("Parsed %d sound(s) from search results page", len(sounds))
    return sounds


def _extract_page_number(url: str) -> int:
    """Extract the page number from a MyInstants URL, defaulting to 1."""
    match = re.search(r"[?&]page=(\d+)", url)
    return int(match.group(1)) if match else 1


def _has_results(html: str) -> bool:
    """Return True if the page contains at least one sound result."""
    soup = BeautifulSoup(html, "html.parser")
    return len(soup.select("div.instant")) > 0


def extract_next_page_url(html: str, current_url: str) -> Optional[str]:
    """Extract the URL of the next results page, if any.

    MyInstants does not provide traditional HTML pagination links;
    instead it uses JavaScript-based infinite scroll with a `?page=N`
    query parameter. Since we fetch pages server-side, we generate the
    next page URL by incrementing the page number. We stop when the
    page contains no results.
    """
    # Check if this page actually has results
    if not _has_results(html):
        return None

    # Get current page number
    current_page = _extract_page_number(current_url)
    next_page = current_page + 1

    # Build next page URL by adding/replacing page parameter
    if "?" in current_url:
        if re.search(r"[?&]page=", current_url):
            next_url = re.sub(r"([?&])page=\d+", f"\\1page={next_page}", current_url)
        else:
            next_url = f"{current_url}&page={next_page}"
    else:
        next_url = f"{current_url}?page={next_page}"

    return next_url
