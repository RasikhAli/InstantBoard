"""
myinstants/api.py

Thin HTTP client around https://www.myinstants.com. Responsible for
building request URLs, handling network errors/timeouts gracefully,
and downloading sound files. Parsing itself lives in parser.py so this
module stays focused purely on transport concerns.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple
from urllib.parse import quote, urljoin

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
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------
    def _get(self, url: str) -> requests.Response:
        try:
            response = self._session.get(url, timeout=self._timeout)
        except requests.exceptions.ConnectionError as exc:
            logger.error("Network error fetching %s: %s", url, exc)
            raise NetworkError(f"Could not connect to MyInstants: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            logger.error("Timeout fetching %s: %s", url, exc)
            raise TimeoutError_(f"Request to MyInstants timed out: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Request error fetching %s: %s", url, exc)
            raise MyInstantsError(f"Request failed: {exc}") from exc

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

        Returns a tuple of (sounds, next_page_url). `next_page_url` is
        None when there is no further page of results.
        """
        url = f"{BASE_URL}{SEARCH_PATH}?name={quote(query)}&page=1"
        logger.info("Searching MyInstants: %s", url)
        response = self._get(url)
        sounds = parse_search_results(response.text)
        next_url = extract_next_page_url(response.text, url)
        return sounds, next_url

    def fetch_page(self, url: str) -> Tuple[List[Sound], Optional[str]]:
        """Fetch an arbitrary MyInstants results page (used for pagination
        and for the homepage / trending list)."""
        response = self._get(url)
        sounds = parse_search_results(response.text)
        next_url = extract_next_page_url(response.text, url)
        return sounds, next_url

    def get_trending(self) -> Tuple[List[Sound], Optional[str]]:
        """Fetch the MyInstants homepage (trending / recently added sounds).
        
        The bare base URL redirects to /en/index/pk/ which shows the
        default trending/recently added sounds page.
        """
        return self.fetch_page(BASE_URL + "/")

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
