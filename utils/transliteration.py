"""
utils/transliteration.py

Converts Roman Urdu text (e.g. "yehi baat hai", "kya haal hai", "main theek hoon")
into proper Urdu script (e.g. "یہی بات ہے", "کیا حال ہے", "میں ٹھیک ہوں") for
seamless neural TTS synthesis with Urdu voices like ur-PK-UzmaNeural.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Dict

logger = logging.getLogger(__name__)

# Fast memory cache for transliterated phrases
_TRANSLIT_CACHE: Dict[str, str] = {}

# Common Roman Urdu vocabulary fallback mapping
COMMON_ROMAN_URDU: Dict[str, str] = {
    "yehi": "یہی",
    "yahi": "یہی",
    "ye": "یہ",
    "yeh": "یہ",
    "wo": "وہ",
    "woh": "وہ",
    "baat": "بات",
    "bat": "بات",
    "hai": "ہے",
    "hay": "ہے",
    "hain": "ہیں",
    "ho": "ہو",
    "kya": "کیا",
    "kia": "کیا",
    "kyun": "کیوں",
    "kaise": "کیسے",
    "kese": "کیسے",
    "theek": "ٹھیک",
    "thik": "ٹھیک",
    "main": "میں",
    "mein": "میں",
    "me": "میں",
    "hoon": "ہوں",
    "hun": "ہوں",
    "hum": "ہم",
    "tum": "تم",
    "aap": "آپ",
    "ap": "آپ",
    "kahan": "کہاں",
    "idhar": "ادھر",
    "udhar": "ادھر",
    "shukriya": "شکریہ",
    "acha": "اچھا",
    "accha": "اچھا",
    "bohat": "بہت",
    "bahut": "بہت",
    "bhot": "بہت",
    "bhi": "بھی",
    "suno": "سنو",
    "batao": "بتاؤ",
    "bolo": "بولو",
    "chalo": "چلو",
    "kaam": "کام",
    "ghar": "گھر",
    "waqt": "وقت",
    "subah": "صبح",
    "shaam": "شام",
    "raat": "رات",
    "din": "دن",
    "nahi": "نہیں",
    "nahin": "نہیں",
    "han": "ہاں",
    "haan": "ہاں",
    "ji": "جی",
    "jee": "جی",
    "salaam": "سلام",
    "assalam": "السلام",
    "alaikum": "علیکم",
    "khuda": "خدا",
    "hafiz": "حافظ",
    "dost": "دوست",
    "bhai": "بھائی",
    "yaar": "یار",
}


def is_latin_text(text: str) -> bool:
    """Check if the text contains Latin letters (A-Z, a-z)."""
    return bool(re.search(r"[a-zA-Z]", text))


def fallback_transliterate(text: str) -> str:
    """Offline rule-based fallback for Roman Urdu words."""
    words = text.split()
    out = []
    for w in words:
        clean = re.sub(r"[^\w]", "", w).lower()
        if clean in COMMON_ROMAN_URDU:
            # Preserve punctuation if any
            prefix = re.match(r"^[^\w]*", w).group(0)
            suffix = re.search(r"[^\w]*$", w).group(0)
            out.append(f"{prefix}{COMMON_ROMAN_URDU[clean]}{suffix}")
        else:
            out.append(w)
    return " ".join(out)


def transliterate_roman_urdu(text: str, timeout: float = 1.5) -> str:
    """Convert Roman Urdu string to Urdu script.
    
    Uses Google Input Tools transliteration API for fast and accurate
    conversion, with a dictionary-based fallback if offline or timed out.
    """
    clean_text = text.strip()
    if not clean_text:
        return ""

    # If text is already in Urdu/Arabic script and has no Latin letters, return as-is
    if not is_latin_text(clean_text):
        return clean_text

    # Check cache
    cache_key = clean_text.lower()
    if cache_key in _TRANSLIT_CACHE:
        return _TRANSLIT_CACHE[cache_key]

    try:
        encoded = urllib.parse.quote(clean_text)
        url = f"https://inputtools.google.com/request?text={encoded}&itc=ur-t-i0-und&num=1"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and data[0] == "SUCCESS" and len(data) > 1:
                parts = []
                for item in data[1]:
                    if item and len(item) > 1 and item[1]:
                        parts.append(item[1][0])
                if parts:
                    result = " ".join(parts).strip()
                    _TRANSLIT_CACHE[cache_key] = result
                    logger.debug("Transliterated Roman Urdu '%s' -> '%s'", clean_text, result)
                    return result
    except Exception as exc:
        logger.debug("Online transliteration unavailable (%s), using offline fallback", exc)

    fallback_result = fallback_transliterate(clean_text)
    _TRANSLIT_CACHE[cache_key] = fallback_result
    return fallback_result
