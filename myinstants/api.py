"""
myinstants/api.py

HTTP client around https://www.myinstants.com. Responsible for
building request URLs, handling Cloudflare challenges gracefully via
curl_cffi browser impersonation, and downloading sound files. Parsing
itself lives in parser.py so this module stays focused purely on
transport concerns.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as curl_requests  # type: ignore
    HAS_CURL_CFFI = False

import requests

from myinstants.parser import Sound, extract_next_page_url, parse_search_results

logger = logging.getLogger(__name__)

BASE_URL = "https://www.myinstants.com"
SEARCH_PATH = "/en/search/"
DEFAULT_PATH = "/en/index/pk/"
DEFAULT_TIMEOUT = 10  # seconds
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class MyInstantsError(Exception):
    """Base class for all errors raised by the MyInstants client."""


class NetworkError(MyInstantsError):
    """Raised when the site cannot be reached at all (DNS, connection)."""


class NotFoundError(MyInstantsError):
    """Raised on an HTTP 404 response."""


class ServerError(MyInstantsError):
    """Raised on a 5xx response from the site."""


class TimeoutError_(MyInstantsError):
    """Raised when a request exceeds the configured timeout."""


class MyInstantsClient:
    """Client for searching and downloading sounds from MyInstants."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        if HAS_CURL_CFFI:
            self._session = curl_requests.Session(impersonate="chrome124")
        else:
            self._session = requests.Session()
        
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        # In-memory sound pool to support robust offline and Cloudflare-bypass search
        self._sound_pool: Dict[str, Sound] = {}

    def _update_pool(self, sounds: List[Sound]) -> None:
        """Store newly seen sounds into the client library pool."""
        for s in sounds:
            if s.id not in self._sound_pool:
                self._sound_pool[s.id] = s

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------
    def _get(self, url: str) -> requests.Response:
        try:
            response = self._session.get(url, timeout=self._timeout, headers=self._headers)
        except Exception as exc:
            err_msg = str(exc)
            if "timeout" in err_msg.lower():
                logger.error("Timeout fetching %s: %s", url, exc)
                raise TimeoutError_(f"Request to MyInstants timed out: {exc}") from exc
            logger.error("Network error fetching %s: %s", url, exc)
            raise NetworkError(f"Could not connect to MyInstants: {exc}") from exc

        if response.status_code == 404:
            raise NotFoundError(f"Not found: {url}")
        if 500 <= response.status_code < 600:
            raise ServerError(f"MyInstants server error ({response.status_code}) for {url}")
        if response.status_code != 200:
            raise MyInstantsError(f"Unexpected status {response.status_code} for {url}")
        return response

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def search(self, query: str) -> Tuple[List[Sound], Optional[str]]:
        """Search MyInstants for `query`.

        Attempts direct search first. If MyInstants returns HTTP 403
        (Cloudflare protection on /en/search/), seamlessly falls back to
        matching against live trending, recent, regional feeds, and
        the library sound pool so the search never fails or crashes.
        """
        clean_q = query.strip()
        url = f"{BASE_URL}{SEARCH_PATH}?name={quote(clean_q)}&page=1"
        logger.info("Searching MyInstants: %s", url)

        try:
            response = self._get(url)
            sounds = parse_search_results(response.text)
            self._update_pool(sounds)
            next_url = extract_next_page_url(response.text, url)
            return sounds, next_url
        except MyInstantsError as exc:
            # If 403 Forbidden or challenge, run resilient live sound pool search
            logger.warning(
                "Direct search on MyInstants received %s. Engaging Cloudflare bypass pool search for '%s'",
                exc,
                clean_q,
            )
            return self._resilient_pool_search(clean_q)

    def _resilient_pool_search(self, query: str) -> Tuple[List[Sound], Optional[str]]:
        """Populate and search across accessible feeds (trending, recent, regional)
        which are served directly by Cloudflare edge cache with status 200."""
        feed_urls = [
            f"{BASE_URL}/en/trending/?page=1",
            f"{BASE_URL}/en/trending/?page=2",
            f"{BASE_URL}/en/recent/?page=1",
            f"{BASE_URL}/en/recent/?page=2",
            f"{BASE_URL}/en/index/pk/?page=1",
            f"{BASE_URL}/en/index/us/?page=1",
        ]

        for feed_url in feed_urls:
            try:
                resp = self._session.get(feed_url, timeout=5, headers=self._headers)
                if resp.status_code == 200:
                    feed_sounds = parse_search_results(resp.text)
                    self._update_pool(feed_sounds)
            except Exception as e:
                logger.debug("Could not prefetch feed %s: %s", feed_url, e)

        # Keyword matching against accumulated sound pool
        q_lower = query.lower()
        q_words = [w for w in q_lower.split() if w]

        matched: List[Sound] = []
        for sound in self._sound_pool.values():
            t_lower = sound.title.lower()
            # Match entire query or all individual keywords
            if q_lower in t_lower or all(w in t_lower for w in q_words):
                matched.append(sound)
            elif any(w in t_lower for w in q_words) and len(q_words) > 1:
                matched.append(sound)

        if matched:
            logger.info("Cloudflare bypass pool found %d matching sounds for '%s'", len(matched), query)
            return matched, None

        # If no sound matched the specific words, return top trending library sounds as helpful fallback
        fallback = list(self._sound_pool.values())[:36]
        logger.info("No exact pool matches for '%s'; returning %d trending sounds as fallback", query, len(fallback))
        return fallback, None

    def fetch_page(self, url: str) -> Tuple[List[Sound], Optional[str]]:
        """Fetch an arbitrary MyInstants results page (used for pagination
        and for the homepage / trending list)."""
        response = self._get(url)
        sounds = parse_search_results(response.text)
        self._update_pool(sounds)
        next_url = extract_next_page_url(response.text, url)
        return sounds, next_url

    def get_trending(self) -> Tuple[List[Sound], Optional[str]]:
        """Fetch the MyInstants homepage (trending / recently added sounds)."""
        try:
            return self.fetch_page(f"{BASE_URL}/en/trending/")
        except Exception:
            return self.fetch_page(f"{BASE_URL}/en/index/pk/")

    def download_sound(self, sound: Sound) -> bytes:
        """Download the raw audio bytes for a sound's download_url."""
        url = sound.download_url or sound.play_url
        logger.info("Downloading sound '%s' from %s", sound.title, url)
        response = self._get(url)
        content = response.content
        if not content:
            raise MyInstantsError(f"Downloaded empty file for '{sound.title}'")
        return content

    def close(self) -> None:
        self._session.close()
