"""
tests/test_storage_bootstrap.py

Unit tests verifying strict project-local storage, environment variable
isolation, offline mode configuration, and rejection of external junctions.
"""

import os
import unittest
from pathlib import Path

from translator.bootstrap import (
    apply_process_environment,
    ensure_storage_layout,
    get_project_root,
    get_storage_diagnostics,
    get_storage_paths,
    is_path_within_project,
)


class TestStorageBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self.root = get_project_root()

    def test_project_root_is_valid_and_exists(self) -> None:
        self.assertTrue(self.root.exists(), f"Project root '{self.root}' does not exist")
        self.assertTrue(self.root.is_dir(), f"Project root '{self.root}' is not a directory")
        # Ensure we are pointing at the repository root containing main.py
        self.assertTrue((self.root / "main.py").exists(), "main.py not found in project root")

    def test_storage_paths_strictly_within_root(self) -> None:
        paths = get_storage_paths(self.root)
        for name, p in paths.items():
            self.assertTrue(
                is_path_within_project(p, self.root),
                f"Path '{p}' ({name}) escapes project root '{self.root}'",
            )

    def test_rejection_of_external_paths(self) -> None:
        external_path = Path("C:/Windows/System32")
        self.assertFalse(
            is_path_within_project(external_path, self.root),
            "Failed to reject external system path",
        )

    def test_environment_variables_pointed_locally(self) -> None:
        env = apply_process_environment(self.root, offline=True)
        # Check Hugging Face home
        hf_home = Path(env["HF_HOME"])
        self.assertTrue(is_path_within_project(hf_home, self.root))
        self.assertEqual(os.environ.get("HF_HOME"), str(hf_home))

        # Check PyTorch home
        torch_home = Path(env["TORCH_HOME"])
        self.assertTrue(is_path_within_project(torch_home, self.root))

        # Check offline mode flags
        self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")
        self.assertEqual(os.environ.get("TRANSFORMERS_OFFLINE"), "1")

    def test_diagnostics_report(self) -> None:
        diag = get_storage_diagnostics(self.root)
        self.assertIn("project_root", diag)
        self.assertIn("disk_free_gb", diag)
        self.assertGreater(diag["disk_free_gb"], 0.0)


if __name__ == "__main__":
    unittest.main()
