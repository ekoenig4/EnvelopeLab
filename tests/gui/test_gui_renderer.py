"""PyVista 3D renderer (needs OpenGL and a display, e.g. ``xvfb-run``).

The other GUI tests run without a renderer. These run when ENVELOPELAB_TEST_3D=1 is set
(CI does so on Linux: ``QT_QPA_PLATFORM=xcb ENVELOPELAB_TEST_3D=1 xvfb-run -a pytest
tests/gui/test_gui_renderer.py``); without it they are skipped with that reason.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from envelopelab.project.simulation import build_solver_model
from envelopelab_app.main_window import MainWindow

from .gui_support import GORE_PROJECT

pytestmark = pytest.mark.skipif(
    not os.environ.get("ENVELOPELAB_TEST_3D"),
    reason="3D renderer tests need a display; run with ENVELOPELAB_TEST_3D=1 under xvfb-run",
)


def test_renderer_draws_layers_and_edits_the_profile_with_the_spline_widget(
    qtbot: QtBot, settings: QSettings, tmp_path: Path
) -> None:
    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    session = w.open_project(GORE_PROJECT)
    assert session is not None and w.view3d.plotter is not None
    built = build_solver_model(session.design, session.patterns, tmp_path, 1600.0)
    w.controller.store_model(built, session.fingerprints())
    assert set(w.view3d.labels()) == {"design", "rest"}
    w.view3d.section.setChecked(True)
    w.view3d.section.setChecked(False)
    w.view3d.spline.setChecked(True)
    widgets = w.view3d.spline_widgets()
    assert len(widgets) == 1
    x, y, z = widgets[0].GetHandlePosition(2)
    widgets[0].SetHandlePosition(2, x + 0.2, y, z)
    w.view3d._spline_changed(None)
    assert session.stack.history() == ["Edit profile in the 3D view"]
    image = tmp_path / "view.png"
    w.view3d.plotter.screenshot(str(image))
    assert image.stat().st_size > 1000
    for key in ("add_parachute", "add_red_line", "add_flying_wires", "add_vents"):
        w.rigging.buttons[key].click()
    assert "rigging" in w.view3d.labels()
    w.view3d.plotter.screenshot(str(image))
    assert image.stat().st_size > 1000
    w.close()
