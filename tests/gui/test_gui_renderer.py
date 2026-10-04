"""PyVista 3D renderer (needs OpenGL and a display, e.g. ``xvfb-run``).

The other GUI tests run without a renderer. These run when ENVELOPELAB_TEST_3D=1 is set
(CI does so on Linux: ``QT_QPA_PLATFORM=xcb ENVELOPELAB_TEST_3D=1 xvfb-run -a pytest
tests/gui/test_gui_renderer.py``); without it they are skipped with that reason.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
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


def _display_xy(plotter: Any, point: Any) -> tuple[int, int]:
    renderer = plotter.renderer
    renderer.SetWorldPoint(float(point[0]), float(point[1]), float(point[2]), 1.0)
    renderer.WorldToDisplay()
    x, y, _ = renderer.GetDisplayPoint()
    return int(round(x)), int(round(y))


def test_mouse_drag_moves_a_special_shape(qtbot: QtBot, settings: QSettings) -> None:
    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    session = w.open_project(GORE_PROJECT)
    assert session is not None and w.view3d.plotter is not None
    w.shapes.add_shape("dome")
    assert w.controller.shapes.wait(120_000)
    w.show_panel("view3d")
    view, plotter = w.view3d, w.view3d.plotter
    assert "shape:Dome" in plotter.actors
    view.drag_shapes.setChecked(True)
    surface = w.controller.envelope_surface()
    placed = w.shapes.placed("Dome")
    assert surface is not None and placed is not None
    # Look straight at the dome so its apex is the nearest thing under the cursor.
    apex = placed.base_point + 0.8 * placed.designed_height * placed.axis
    plotter.camera.focal_point = tuple(placed.base_point)
    plotter.camera.position = tuple(placed.base_point + 15.0 * placed.axis)
    plotter.render()
    start = session.state.shapes[0].placement
    target = surface.point(np.array([start.tape_position + 1.0]), np.array([surface.theta_at(1)]))
    iren = plotter.iren.interactor
    camera_before = plotter.camera.position
    iren.SetEventInformation(*_display_xy(plotter, apex), 0, 0)
    iren.LeftButtonPressEvent()
    assert view.drag is not None and view.drag.name == "Dome"
    iren.SetEventInformation(*_display_xy(plotter, target[0]), 0, 0)
    iren.MouseMoveEvent()
    assert "shape-drag-outline" in plotter.actors
    iren.LeftButtonReleaseEvent()
    assert view.drag is None and "shape-drag-outline" not in plotter.actors
    assert plotter.camera.position == camera_before  # the drag did not orbit the camera
    moved = session.state.shapes[0].placement
    assert moved.tape_position == pytest.approx(start.tape_position + 1.0, abs=0.05)
    assert moved.gore == 1
    # A press beside the shape still orbits the camera and moves nothing.
    iren.SetEventInformation(5, 5, 0, 0)
    iren.LeftButtonPressEvent()
    assert view.drag is None
    iren.SetEventInformation(60, 40, 0, 0)
    iren.MouseMoveEvent()
    iren.LeftButtonReleaseEvent()
    assert plotter.camera.position != camera_before
    assert session.state.shapes[0].placement == moved
    w.controller.shapes.wait(120_000)
    w.close()


def test_designed_shapes_are_drawn_without_edges(qtbot: QtBot, settings: QSettings) -> None:
    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    assert w.open_project(GORE_PROJECT) is not None and w.view3d.plotter is not None
    w.shapes.add_shape("dome")
    assert w.controller.shapes.wait(120_000)
    actor = w.view3d.plotter.actors["shape:Dome"]
    # The designed skin is a dense display mesh (about 30 000 triangles): with its edges
    # drawn it renders as a black blob instead of in the layer colour.
    assert not actor.GetProperty().GetEdgeVisibility()
    w.close()
