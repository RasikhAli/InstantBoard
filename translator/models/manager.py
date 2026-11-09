"""
translator/models/manager.py

Model download orchestrator, atomic installer, integrity verification,
and offline loading manager for the InstantBoard Local Live Translator.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

from translator.bootstrap import apply_process_environment, get_storage_paths
from translator.models.manifest import MANIFESTS, ModelManifest

logger = logging.getLogger(__name__)


class ModelInstallError(Exception):
    """Raised when model installation, downloading, or verification fails."""


class ModelManager:
    """Manages project-local model downloads, verification, and offline checks."""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.paths = get_storage_paths(project_root)
        self.models_dir = self.paths["models"]
        self.staging_dir = self.paths["runtime_staging"]
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        # Apply strict project-local environment variables
        apply_process_environment(self.paths["root"])

    def get_model_path(self, model_id: str) -> Path:
        """Return the absolute path where the model should reside."""
        if model_id not in MANIFESTS:
            raise KeyError(f"Unknown model_id: '{model_id}'")
        manifest = MANIFESTS[model_id]
        return self.models_dir / manifest.target_dir

    def is_model_installed(self, model_id: str) -> bool:
        """Check if all files declared in the manifest are present and valid."""
        if model_id not in MANIFESTS:
            return False
        manifest = MANIFESTS[model_id]
        model_dir = self.get_model_path(model_id)
        if not model_dir.exists():
            return False

        # If files are explicitly listed, check them
        if manifest.files:
            all_files_exist = True
            for spec in manifest.files:
                target_file = model_dir / spec.relative_path
                if not target_file.exists():
                    all_files_exist = False
                    break
                if spec.expected_size_bytes > 0 and target_file.stat().st_size == 0:
                    all_files_exist = False
                    break
            if all_files_exist:
                return True

        # For Hugging Face repo directories, check if core weight file exists or directory is non-empty
        core_weight_extensions = (".bin", ".pth", ".onnx", ".safetensors")
        has_weights = any(
            f.suffix in core_weight_extensions and f.stat().st_size > 100_000
            for f in model_dir.rglob("*")
            if f.is_file()
        )
        if has_weights:
            return True

        # Verify manifest state marker
        marker_file = model_dir / ".installed_manifest.json"
        return marker_file.exists()

    def get_model_status(self) -> Dict[str, Dict[str, object]]:
        """Return readiness status for all registered models."""
        result = {}
        for mid, manifest in MANIFESTS.items():
            installed = self.is_model_installed(mid)
            path = self.get_model_path(mid)
            size_mb = 0
            if path.exists():
                size_mb = round(
                    sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                    / (1024 * 1024),
                    1,
                )
            result[mid] = {
                "name": manifest.name,
                "category": manifest.category,
                "installed": installed,
                "path": str(path),
                "current_size_mb": size_mb,
                "estimated_size_mb": manifest.estimated_size_mb,
                "license": manifest.license,
            }
        return result

    def verify_free_disk_space(self, required_bytes: int) -> None:
        """Verify that the target drive has enough free space plus safety margin."""
        total, used, free = shutil.disk_usage(self.models_dir)
        safety_margin = 1024 * 1024 * 1024  # 1 GB headroom
        if free < (required_bytes + safety_margin):
            free_gb = free / (1024**3)
            req_gb = (required_bytes + safety_margin) / (1024**3)
            raise ModelInstallError(
                f"Insufficient disk space on {self.models_dir}. Need {req_gb:.2f} GB (with safety margin), but only {free_gb:.2f} GB available."
            )

    def download_direct_file(
        self,
        url: str,
        destination: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Download a single file directly with resume and progress tracking."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_file = destination.with_suffix(destination.suffix + ".part")

        resume_byte = part_file.stat().st_size if part_file.exists() else 0
        req = urllib.request.Request(url)
        if resume_byte > 0:
            req.add_header("Range", f"bytes={resume_byte}-")

        try:
            with urllib.request.urlopen(req) as response:
                content_range = response.headers.get("Content-Range")
                total_bytes = int(response.headers.get("Content-Length", 0))
                if content_range and "bytes" in content_range:
                    total_bytes = int(content_range.split("/")[-1])
                elif resume_byte > 0:
                    total_bytes += resume_byte

                mode = "ab" if resume_byte > 0 else "wb"
                downloaded = resume_byte

                with open(part_file, mode) as out_f:
                    while True:
                        if cancel_check and cancel_check():
                            raise ModelInstallError("Download cancelled by user.")
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_bytes)

            part_file.replace(destination)
        except Exception as exc:
            if isinstance(exc, ModelInstallError):
                raise
            raise ModelInstallError(f"Failed to download {url}: {exc}") from exc

    def download_huggingface_repo(
        self,
        repo_id: str,
        destination: Path,
        revision: str = "main",
        progress_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Download a Hugging Face repository snapshot into an isolated project-local staging dir."""
        if cancel_check and cancel_check():
            raise ModelInstallError("Download cancelled by user.")

        if progress_callback:
            progress_callback(f"Downloading snapshot for {repo_id}…")

        try:
            from huggingface_hub import snapshot_download

            # Enforce local cache dir and local download destination
            local_cache = self.paths["runtime_cache"] / "huggingface" / "hub"
            snapshot_download(
                repo_id=repo_id,
                revision=revision,
                local_dir=destination,
                cache_dir=local_cache,
                local_dir_use_symlinks=False,
            )
        except Exception as exc:
            raise ModelInstallError(f"Hugging Face snapshot download failed for {repo_id}: {exc}") from exc

    def install_model(
        self,
        model_id: str,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """Atomically download and install a model from its manifest."""
        if model_id not in MANIFESTS:
            raise KeyError(f"Unknown model: '{model_id}'")
        manifest = MANIFESTS[model_id]

        target_dir = self.get_model_path(model_id)
        if self.is_model_installed(model_id):
            logger.info("Model '%s' is already installed at %s", model_id, target_dir)
            return target_dir

        required_bytes = manifest.estimated_size_mb * 1024 * 1024
        self.verify_free_disk_space(required_bytes)

        staging_dir = self.staging_dir / manifest.model_id
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Staging installation for '%s' in %s", model_id, staging_dir)

        # 1. If direct URLs are given:
        direct_files = [f for f in manifest.files if f.download_url]
        if direct_files:
            for spec in direct_files:
                dest = staging_dir / spec.relative_path
                self.download_direct_file(
                    url=spec.download_url,  # type: ignore
                    destination=dest,
                    progress_callback=lambda cur, tot: progress_callback(
                        f"Downloading {spec.filename}", cur / max(1, tot)
                    )
                    if progress_callback
                    else None,
                    cancel_check=cancel_check,
                )
        # 2. If Hugging Face repo:
        elif manifest.huggingface_repo_id:
            self.download_huggingface_repo(
                repo_id=manifest.huggingface_repo_id,
                destination=staging_dir,
                revision=manifest.revision,
                progress_callback=lambda msg: progress_callback(msg, 0.5)
                if progress_callback
                else None,
                cancel_check=cancel_check,
            )

        # 3. Write installation marker
        marker_data = {
            "model_id": manifest.model_id,
            "revision": manifest.revision,
            "license": manifest.license,
            "installed_at": os.path.getmtime(staging_dir),
        }
        (staging_dir / ".installed_manifest.json").write_text(
            json.dumps(marker_data, indent=2), encoding="utf-8"
        )

        # 4. Atomic move to target_dir
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir.rename(target_dir)

        logger.info("Successfully installed '%s' to %s", model_id, target_dir)
        if progress_callback:
            progress_callback(f"{manifest.name} ready", 1.0)
        return target_dir
