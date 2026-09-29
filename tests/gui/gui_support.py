"""Shared helpers of the GUI tests (imported by conftest.py and the test modules)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from envelopelab_app.main_window import MainWindow

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GORE_PROJECT = FIXTURES / "standard_gore" / "design.elproj"


def make_window(qtbot: QtBot, settings: QSettings) -> MainWindow:
    """A headless main window (no 3D renderer, no dialogs) managed by ``qtbot``."""
    window = MainWindow(settings, enable_3d=False, interactive=False)
    qtbot.addWidget(window)
    window.show()
    return window
