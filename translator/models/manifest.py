"""
translator/models/manifest.py

Model manifest declarations, capability registry, and checksum specifications
for the InstantBoard Local Live Translator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ModelFileSpec:
    """Individual file required by a model."""

    filename: str
    relative_path: str
    expected_size_bytes: int = 0
    sha256: Optional[str] = None
    download_url: Optional[str] = None


@dataclass
class ModelManifest:
    """Complete specification for a managed local model."""

    model_id: str
    name: str
    category: str  # 'vad', 'asr', 'translation', 'tts'
    huggingface_repo_id: Optional[str]
    revision: str
    license: str
    target_dir: str  # relative to models/
    description: str
    estimated_size_mb: int
    files: List[ModelFileSpec] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Capability Registry
# ---------------------------------------------------------------------------
@dataclass
class CapabilityRegistry:
    """Explicitly registers supported recognition, translation, enrollment, and synthesis languages."""

    recognition_languages: Set[str] = field(
        default_factory=lambda: {"auto", "ur", "en", "ar"}
    )
    # Directed translation pairs: (source_lang, target_lang)
    translation_pairs: Set[Tuple[str, str]] = field(
        default_factory=lambda: {
            ("ur", "en"),
            ("en", "ar"),
            ("en", "ur"),
            ("ar", "en"),
            ("ur", "ar"),
            ("ar", "ur"),
        }
    )
    # Languages verified for voice enrollment reference audio
    reference_audio_languages: Set[str] = field(
        default_factory=lambda: {"en", "ur", "ar"}
    )
    # Languages supported by the voice cloning synthesis engine
    synthesis_languages: Set[str] = field(
        default_factory=lambda: {"en", "ar", "ur"}
    )

    def is_translation_pair_supported(self, source: str, target: str) -> bool:
        if source == "auto":
            return target in self.synthesis_languages
        return (source, target) in self.translation_pairs

    def is_synthesis_supported(self, lang: str) -> bool:
        return lang in self.synthesis_languages


CAPABILITIES = CapabilityRegistry()


# ---------------------------------------------------------------------------
# Official Manifest Registry
# ---------------------------------------------------------------------------
MANIFESTS: Dict[str, ModelManifest] = {
    # 1. Silero VAD v5 (ONNX)
    "silero-vad-v5": ModelManifest(
        model_id="silero-vad-v5",
        name="Silero VAD v5 (ONNX)",
        category="vad",
        huggingface_repo_id=None,
        revision="v5.0",
        license="MIT",
        target_dir="vad",
        description="High-precision voice activity detection on CPU via ONNX Runtime.",
        estimated_size_mb=2,
        files=[
            ModelFileSpec(
                filename="silero_vad.onnx",
                relative_path="silero_vad.onnx",
                expected_size_bytes=1_500_000,
                download_url="https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx",
            )
        ],
        tags=["vad", "onnx", "cpu", "silero"],
    ),
    # 2. Faster-Whisper Base (Fast CPU fallback)
    "faster-whisper-base": ModelManifest(
        model_id="faster-whisper-base",
        name="Faster Whisper Base (Multilingual)",
        category="asr",
        huggingface_repo_id="Systran/faster-whisper-base",
        revision="main",
        license="MIT / Apache-2.0",
        target_dir="asr/faster-whisper-base",
        description="Fast multilingual speech recognition & language detection on CPU.",
        estimated_size_mb=150,
        files=[
            ModelFileSpec(filename="model.bin", relative_path="model.bin"),
            ModelFileSpec(filename="config.json", relative_path="config.json"),
            ModelFileSpec(filename="vocabulary.json", relative_path="vocabulary.json"),
            ModelFileSpec(filename="tokenizer.json", relative_path="tokenizer.json"),
        ],
        tags=["asr", "ctranslate2", "multilingual", "whisper"],
    ),
    # 3. Faster-Whisper Large-v3-Turbo (High accuracy)
    "faster-whisper-large-v3-turbo": ModelManifest(
        model_id="faster-whisper-large-v3-turbo",
        name="Faster Whisper Large v3 Turbo",
        category="asr",
        huggingface_repo_id="Systran/faster-whisper-large-v3-turbo",
        revision="main",
        license="MIT / Apache-2.0",
        target_dir="asr/faster-whisper-large-v3-turbo",
        description="State-of-the-art multilingual ASR with high accuracy in Urdu, Arabic, and English.",
        estimated_size_mb=1600,
        files=[
            ModelFileSpec(filename="model.bin", relative_path="model.bin"),
            ModelFileSpec(filename="config.json", relative_path="config.json"),
            ModelFileSpec(filename="vocabulary.json", relative_path="vocabulary.json"),
            ModelFileSpec(filename="tokenizer.json", relative_path="tokenizer.json"),
        ],
        tags=["asr", "ctranslate2", "multilingual", "whisper-turbo"],
    ),
    # 4. NLLB-200 Distilled 600M (CTranslate2 INT8)
    "nllb-200-distilled-600m": ModelManifest(
        model_id="nllb-200-distilled-600m",
        name="NLLB-200 Distilled 600M (CTranslate2 INT8)",
        category="translation",
        huggingface_repo_id="JustFrederik/nllb-200-distilled-600M-ct2-int8",
        revision="main",
        license="CC-BY-NC-4.0",
        target_dir="translation/nllb-200-distilled-600M-int8",
        description="Ultra-fast machine translation supporting Urdu, Arabic, and English with strict adherence.",
        estimated_size_mb=650,
        files=[
            ModelFileSpec(filename="model.bin", relative_path="model.bin"),
            ModelFileSpec(filename="shared_vocabulary.txt", relative_path="shared_vocabulary.txt"),
            ModelFileSpec(filename="config.json", relative_path="config.json"),
        ],
        tags=["translation", "nllb", "ctranslate2", "int8", "urdu", "arabic"],
    ),
    # 5. Coqui XTTS-v2 Voice Cloning Checkpoint
    "coqui-xtts-v2": ModelManifest(
        model_id="coqui-xtts-v2",
        name="Coqui XTTS-v2 (Zero-Shot Voice Cloning)",
        category="tts",
        huggingface_repo_id="coqui/XTTS-v2",
        revision="main",
        license="Coqui Public Model License (CPML)",
        target_dir="tts/xtts_v2",
        description="Zero-shot cross-lingual voice cloning supporting English and Arabic output.",
        estimated_size_mb=2800,
        files=[
            ModelFileSpec(filename="model.pth", relative_path="model.pth"),
            ModelFileSpec(filename="config.json", relative_path="config.json"),
            ModelFileSpec(filename="vocab.json", relative_path="vocab.json"),
            ModelFileSpec(filename="speakers_xtts.pth", relative_path="speakers_xtts.pth"),
        ],
        tags=["tts", "voice-clone", "arabic", "english", "xtts"],
    ),
}
