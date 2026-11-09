"""
translator/profiles.py

Voice profile management, enrollment audio validation, and conditioning caching
for zero-shot voice cloning in InstantBoard.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import soundfile as sf

from translator.bootstrap import get_storage_paths
from translator.contracts import VoiceProfileMetadata

logger = logging.getLogger(__name__)


class VoiceProfileError(Exception):
    """Raised on voice profile creation, validation, or loading error."""


class VoiceProfileManager:
    """Manages voice profiles stored strictly in data/voice_profiles/."""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.paths = get_storage_paths(project_root)
        self.profiles_dir = self.paths["voice_profiles"]
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def list_profiles(self) -> List[VoiceProfileMetadata]:
        """Return metadata for all enrolled voice profiles."""
        profiles = []
        for profile_folder in self.profiles_dir.iterdir():
            if profile_folder.is_dir():
                meta_file = profile_folder / "metadata.json"
                if meta_file.exists():
                    try:
                        data = json.loads(meta_file.read_text(encoding="utf-8"))
                        profiles.append(
                            VoiceProfileMetadata(
                                profile_id=data.get("profile_id", profile_folder.name),
                                name=data.get("name", profile_folder.name),
                                created_at=data.get("created_at", 0.0),
                                reference_wav_path=data.get(
                                    "reference_wav_path",
                                    str(profile_folder / "reference.wav"),
                                ),
                                duration_seconds=data.get("duration_seconds", 0.0),
                                sample_rate=data.get("sample_rate", 24000),
                                conditioning_cache_path=data.get(
                                    "conditioning_cache_path"
                                ),
                                language=data.get("language", "en"),
                                notes=data.get("notes", ""),
                            )
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to parse profile metadata in %s: %s",
                            profile_folder,
                            exc,
                        )
        # Sort by creation date
        profiles.sort(key=lambda p: p.created_at, reverse=True)
        return profiles

    def get_profile(self, name_or_id: str) -> Optional[VoiceProfileMetadata]:
        """Find a profile by ID or human-readable name."""
        for p in self.list_profiles():
            if p.profile_id == name_or_id or p.name.lower() == name_or_id.lower():
                return p
        return None

    def create_profile_from_audio(
        self,
        name: str,
        audio_data: np.ndarray,
        samplerate: int,
        language: str = "en",
        notes: str = "",
    ) -> VoiceProfileMetadata:
        """Create a new voice profile from an in-memory audio array (e.g. recorded from mic)."""
        duration = len(audio_data) / max(1, samplerate)
        if duration < 2.0:
            raise VoiceProfileError(
                f"Reference audio too short ({duration:.1f}s). Please speak clearly for at least 3 to 10 seconds."
            )

        # Normalize to mono float32
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)
        audio_data = audio_data.astype(np.float32)
        peak = np.max(np.abs(audio_data))
        if peak > 0:
            audio_data = audio_data / peak * 0.95  # Normalize

        # Generate clean folder name
        safe_id = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
        if not safe_id:
            safe_id = f"profile_{int(time.time())}"

        profile_dir = self.profiles_dir / safe_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        ref_wav = profile_dir / "reference.wav"
        sf.write(str(ref_wav), audio_data, samplerate, subtype="PCM_16")

        meta = VoiceProfileMetadata(
            profile_id=safe_id,
            name=name,
            created_at=time.time(),
            reference_wav_path=str(ref_wav),
            duration_seconds=round(duration, 2),
            sample_rate=samplerate,
            language=language,
            notes=notes,
        )

        meta_file = profile_dir / "metadata.json"
        meta_file.write_text(
            json.dumps(meta.__dict__, indent=2), encoding="utf-8"
        )
        logger.info("Created voice profile '%s' at %s", name, profile_dir)
        return meta

    def import_profile_from_file(
        self, name: str, file_path: Path, language: str = "en", notes: str = ""
    ) -> VoiceProfileMetadata:
        """Import an existing WAV or MP3 file into a new voice profile."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        data, sr = sf.read(str(file_path), dtype="float32")
        return self.create_profile_from_audio(
            name=name,
            audio_data=data,
            samplerate=sr,
            language=language,
            notes=notes,
        )

    def delete_profile(self, profile_id: str) -> bool:
        """Delete an enrolled voice profile and its cached conditioning files."""
        profile_dir = self.profiles_dir / profile_id
        if profile_dir.exists() and profile_dir.is_dir():
            shutil.rmtree(profile_dir, ignore_errors=True)
            logger.info("Deleted voice profile '%s'", profile_id)
            return True
        return False
