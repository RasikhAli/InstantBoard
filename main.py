"""
main.py

InstantBoard entry point.

Wires up logging, the Qt application, the dark theme stylesheet, the
settings manager and the main window, then starts the Qt event loop.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from resources.theme import DARK_STYLESHEET
from utils.settings import SettingsManager

APP_NAME = "InstantBoard"
SETTINGS_PATH = Path("settings.json")
LOG_PATH = Path("instantboard.log")


def configure_logging() -> None:
    """Configure root logging to write to both stderr and a rotating-free
    (simple, size-unbounded but human-readable) log file next to the
    executable, which is invaluable for diagnosing audio/device issues
    on a user's machine."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    try:
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError:
        # If we can't write a log file (e.g. read-only install dir),
        # console logging alone is still fine.
        root_logger.warning("Could not open log file at %s; logging to console only.", LOG_PATH)


def main() -> int:
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting %s", APP_NAME)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(DARK_STYLESHEET)

    settings = SettingsManager(SETTINGS_PATH)

    window = MainWindow(settings)
    window.show()

    exit_code = app.exec()
    logger.info("%s exited with code %s", APP_NAME, exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
