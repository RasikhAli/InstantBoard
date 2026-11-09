"""
translator/voice_catalog.py

Curated Neural Voice Catalog for InstantBoard.
Includes Microsoft Edge Neural Text-to-Speech voices curated for English,
Urdu, and Arabic with high fidelity, reverent cadence, and natural pacing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class VoiceModel:
    name: str
    short_name: str
    gender: str
    locale: str
    language: str
    best_used_for: str
    is_default: bool = False


# Curated catalog matching OneBukhari Studio 2.0 voice specifications
VOICE_CATALOG: List[VoiceModel] = [
    # ── English Voices ──
    VoiceModel(
        name="Guy (US Male Narrator)",
        short_name="en-US-GuyNeural",
        gender="Male",
        locale="en-US",
        language="English",
        best_used_for="Solemn, reverent English narration",
        is_default=True,
    ),
    VoiceModel(
        name="Jenny (US Female)",
        short_name="en-US-JennyNeural",
        gender="Female",
        locale="en-US",
        language="English",
        best_used_for="Gentle, articulate English narration",
    ),
    VoiceModel(
        name="Ryan (UK Male)",
        short_name="en-GB-RyanNeural",
        gender="Male",
        locale="en-GB",
        language="English",
        best_used_for="Formal, classical English narration",
    ),
    VoiceModel(
        name="Sonia (UK Female)",
        short_name="en-GB-SoniaNeural",
        gender="Female",
        locale="en-GB",
        language="English",
        best_used_for="Smooth UK English presentation",
    ),

    # ── Urdu Voices ──
    VoiceModel(
        name="Asad (Urdu Male Narrator)",
        short_name="ur-PK-AsadNeural",
        gender="Male",
        locale="ur-PK",
        language="Urdu",
        best_used_for="Traditional Pakistani Urdu narration",
        is_default=True,
    ),
    VoiceModel(
        name="Uzma (Urdu Female)",
        short_name="ur-PK-UzmaNeural",
        gender="Female",
        locale="ur-PK",
        language="Urdu",
        best_used_for="Expressive Pakistani Urdu narration",
    ),

    # ── Arabic Voices ──
    VoiceModel(
        name="Hamed (Arabic Male)",
        short_name="ar-SA-HamedNeural",
        gender="Male",
        locale="ar-SA",
        language="Arabic",
        best_used_for="Classical Hijazi Arabic narration",
        is_default=True,
    ),
    VoiceModel(
        name="Zariyah (Arabic Female)",
        short_name="ar-SA-ZariyahNeural",
        gender="Female",
        locale="ar-SA",
        language="Arabic",
        best_used_for="Classical Arabic narration",
    ),
    VoiceModel(
        name="Shakir (Arabic Male)",
        short_name="ar-EG-ShakirNeural",
        gender="Male",
        locale="ar-EG",
        language="Arabic",
        best_used_for="Eloquent Egyptian Arabic narration",
    ),
]


DEFAULT_VOICE_PER_LANG: Dict[str, str] = {
    "en": "en-US-GuyNeural",
    "ur": "ur-PK-AsadNeural",
    "ar": "ar-SA-HamedNeural",
}


def get_voices_for_language(lang_code: str) -> List[VoiceModel]:
    """Return all curated voice models for a given language code ('en', 'ur', 'ar')."""
    lang_code = lang_code.lower().strip()
    lang_map = {
        "en": "English",
        "english": "English",
        "ur": "Urdu",
        "urdu": "Urdu",
        "ar": "Arabic",
        "arabic": "Arabic",
    }
    target_lang = lang_map.get(lang_code, "English")
    return [v for v in VOICE_CATALOG if v.language == target_lang]


def get_default_voice_for_language(lang_code: str) -> str:
    """Return default voice identifier (short_name) for a language code."""
    return DEFAULT_VOICE_PER_LANG.get(lang_code.lower().strip(), "en-US-GuyNeural")


def get_voice_by_short_name(short_name: str) -> Optional[VoiceModel]:
    """Find voice by its short_name identifier."""
    for v in VOICE_CATALOG:
        if v.short_name == short_name:
            return v
    return None
