"""
translator/bootstrap.py

Centralized, early path bootstrap for InstantBoard's Local Live Translator.

Enforces strict project-local storage:
- PROJECT_ROOT is strictly resolved from this file's location (or explicit override),
  NEVER from os.getcwd().
- Sets process-local environment variables for Hugging Face, PyTorch, Numba, and
  temporary files to point strictly underneath PROJECT_ROOT.
- Verifies that directories are not symlinks/junctions pointing outside PROJECT_ROOT.
- Provides offline mode flags and storage health diagnostics.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Determine PROJECT_ROOT: parent directory of 'translator'
_OVERRIDE_PROJECT_ROOT: Optional[Path] = None


def set_override_project_root(root: Path) -> None:
    """Explicitly override PROJECT_ROOT (useful for tests or custom staging)."""
    global _OVERRIDE_PROJECT_ROOT
    _OVERRIDE_PROJECT_ROOT = Path(root).resolve()


def get_project_root() -> Path:
    """Return the validated absolute PROJECT_ROOT."""
    if _OVERRIDE_PROJECT_ROOT is not None:
        return _OVERRIDE_PROJECT_ROOT
    # This file is at <PROJECT_ROOT>/translator/bootstrap.py
    return Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Strict directory layout definition
# ---------------------------------------------------------------------------
def get_storage_paths(project_root: Optional[Path] = None) -> Dict[str, Path]:
    """Return dictionary of all managed project-local directories."""
    root = (project_root or get_project_root()).resolve()
    return {
        "root": root,
        "models": root / "models",
        "models_vad": root / "models" / "vad",
        "models_asr": root / "models" / "asr",
        "models_translation": root / "models" / "translation",
        "models_tts": root / "models" / "tts",
        "models_manifests": root / "models" / "manifests",
        "runtime": root / ".runtime",
        "runtime_cache": root / ".runtime" / "cache",
        "runtime_tmp": root / ".runtime" / "tmp",
        "runtime_staging": root / ".runtime" / "tmp" / "staging",
        "runtime_logs": root / ".runtime" / "logs",
        "runtime_benchmarks": root / ".runtime" / "benchmarks",
        "runtime_venvs": root / ".runtime" / "venvs",
        "voice_profiles": root / "data" / "voice_profiles",
        "translator_data": root / "data" / "translator",
    }


def is_path_within_project(target: Path, project_root: Optional[Path] = None) -> bool:
    """Verify that target resolves strictly inside project_root and is not an external junction."""
    root = (project_root or get_project_root()).resolve()
    try:
        resolved_target = target.resolve()
        resolved_target.relative_to(root)
        return True
    except (ValueError, RuntimeError):
        return False


def ensure_storage_layout(project_root: Optional[Path] = None) -> Dict[str, Path]:
    """Create all managed project-local directories and verify they are safe."""
    paths = get_storage_paths(project_root)
    root = paths["root"]

    # Check if project root is writable
    if root.exists():
        test_file = root / ".runtime_write_test"
        try:
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
        except OSError as exc:
            raise PermissionError(
                f"Project root is not writable: '{root}'. Move the project to a writable location. Error: {exc}"
            ) from exc

    for name, p in paths.items():
        if not is_path_within_project(p, root):
            raise ValueError(
                f"Security violation: Managed directory '{p}' resolves outside project root '{root}'."
            )
        p.mkdir(parents=True, exist_ok=True)

    return paths


def apply_process_environment(
    project_root: Optional[Path] = None, offline: bool = False
) -> Dict[str, str]:
    """Configure process-local environment variables to enforce project-local caching.

    Never modifies global Windows registry or user-level environment settings;
    only applies to the current process and its spawned children.
    """
    paths = ensure_storage_layout(project_root)
    cache_dir = paths["runtime_cache"]
    tmp_dir = paths["runtime_tmp"]

    hf_home = cache_dir / "huggingface"
    hf_hub = hf_home / "hub"
    torch_home = cache_dir / "torch"
    numba_cache = cache_dir / "numba"

    env_vars: Dict[str, str] = {
        # Hugging Face caches
        "HF_HOME": str(hf_home),
        "HF_HUB_CACHE": str(hf_hub),
        "HF_XET_CACHE": str(cache_dir / "xet"),
        "HF_ASSETS_CACHE": str(cache_dir / "assets"),
        # PyTorch & TorchInductor
        "TORCH_HOME": str(torch_home),
        "TORCH_EXTENSIONS_DIR": str(cache_dir / "torch_extensions"),
        # XDG / General caches
        "XDG_CACHE_HOME": str(cache_dir),
        # Numba / Triton
        "NUMBA_CACHE_DIR": str(numba_cache),
        # Temp files
        "TEMP": str(tmp_dir),
        "TMP": str(tmp_dir),
        "TMPDIR": str(tmp_dir),
    }

    if offline:
        env_vars["HF_HUB_OFFLINE"] = "1"
        env_vars["TRANSFORMERS_OFFLINE"] = "1"
        env_vars["HF_DATASETS_OFFLINE"] = "1"

    for k, v in env_vars.items():
        os.environ[k] = v

    logger.info(
        "Applied project-local environment variables beneath %s (offline=%s)",
        paths["root"],
        offline,
    )
    return env_vars


def get_storage_diagnostics(project_root: Optional[Path] = None) -> Dict[str, object]:
    """Return runtime diagnostic information about storage health and locations."""
    paths = get_storage_paths(project_root)
    root = paths["root"]

    import shutil

    total_bytes, used_bytes, free_bytes = shutil.disk_usage(root)

    return {
        "project_root": str(root),
        "paths": {k: str(v) for k, v in paths.items()},
        "disk_free_gb": round(free_bytes / (1024**3), 2),
        "disk_total_gb": round(total_bytes / (1024**3), 2),
        "hf_home_env": os.environ.get("HF_HOME", ""),
        "torch_home_env": os.environ.get("TORCH_HOME", ""),
        "offline_mode": os.environ.get("HF_HUB_OFFLINE") == "1",
    }


# Auto-apply on initial import of this module
_paths = ensure_storage_layout()
apply_process_environment(_paths["root"], offline=False)
