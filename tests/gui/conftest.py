"""Headless GUI test setup (pytest-qt).

Qt runs on the ``offscreen`` platform, so the tests need no display; the PyVista renderer
is off (the 3D panel still builds its layer list, which is what the tests check). Settings,
autosave files and the fabric library go to the test's temporary directory.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

# The GUI is an optional extra (".[gui]"); CI installs it, so these tests always run there.
pytest.importorskip("PySide6", reason="GUI tests need the 'gui' extra: pip install -e .[gui]")
pytest.importorskip("pytestqt", reason="GUI tests need pytest-qt (dev extra)")

from PySide6.QtCore import QSettings  # noqa: E402
from pytestqt.qtbot import QtBot  # noqa: E402

from envelopelab_app.main_window import MainWindow  # noqa: E402

from .gui_support import GORE_PROJECT, make_window  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    """Isolated settings: autosave off, recovery folder and fabric library in ``tmp_path``."""
    s = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    s.setValue("preferences/autosave_minutes", 0.0)
    s.setValue("preferences/recovery_dir", str(tmp_path / "recovery"))
    s.setValue("preferences/material_library", str(tmp_path / "materials.sqlite"))
    s.setValue("preferences/preview_mesh_mm", 1600.0)
    s.setValue("preferences/calculix_mesh_mm", 1600.0)
    s.sync()
    return s


@pytest.fixture
def window(qtbot: QtBot, settings: QSettings) -> Iterator[MainWindow]:
    """A main window without a project."""
    w = make_window(qtbot, settings)
    yield w
    w.simulation.cancel()
    w.simulation.wait(60_000)
    w.controller.shape_simulator.cancel()
    w.controller.shape_simulator.wait(60_000)
    w.controller.shapes.wait(60_000)


@pytest.fixture
def gore_window(window: MainWindow) -> MainWindow:
    """A main window with the generic standard-gore fixture project open."""
    assert window.open_project(GORE_PROJECT) is not None
    return window
