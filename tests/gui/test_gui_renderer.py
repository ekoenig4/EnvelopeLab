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


def test_flat_chord_design_renders_with_its_crest_and_panel_details(
    qtbot: QtBot, settings: QSettings, tmp_path: Path
) -> None:
    from envelopelab.io.shape_file import load_shape_file

    special = load_shape_file(
        Path(__file__).parents[1] / "fixtures/flat_chord_pattern/special.yaml"
    )
    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    session = w.new_project(special.design())
    for shape in special.shapes(session.design):
        w.controller.edit("add_shape", shape)
    w.controller.shapes.wait(60_000)
    w.view3d.refresh()
    assert w.view3d.plotter is not None
    assert {"design", "marks", "shape:blister"} <= set(w.view3d.labels())
    image = tmp_path / "flat.png"
    w.view3d.plotter.screenshot(str(image))
    assert image.stat().st_size > 1000
    w.gore_editor.use_crest.click()
    w.view3d.refresh()
    w.view3d.plotter.screenshot(str(image))
    assert image.stat().st_size > 1000
    w.close()


def test_the_launcher_starts_with_the_3d_view_in_a_wayland_session(tmp_path: Path) -> None:
    """The real start-up path, as under WSLg: Wayland and X both present, no platform set."""
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env.update(
        WAYLAND_DISPLAY="wayland-test",
        ENVELOPELAB_QUIT_AFTER_MS="3000",
        XDG_STATE_HOME=str(tmp_path / "state"),
        HOME=str(tmp_path),
    )
    done = subprocess.run(
        [sys.executable, "-m", "envelopelab_app", str(GORE_PROJECT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    log = tmp_path / "state" / "envelopelab" / "crash.log"
    assert done.returncode == 0, done.stderr + (log.read_text() if log.exists() else "")
    assert "xcb" in done.stderr and log.exists()
    assert "QT_QPA_PLATFORM: xcb" in log.read_text()


def test_a_redraw_renders_once_and_draws_all_tapes_as_one_actor(
    qtbot: QtBot, settings: QSettings, tmp_path: Path
) -> None:
    """Rebuilding the scene renders once (PyVista renders after every added actor
    otherwise: 22 s for the full-size fixture on a software renderer)."""
    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    session = w.open_project(GORE_PROJECT)
    assert session is not None and w.view3d.plotter is not None
    built = build_solver_model(session.design, session.patterns, tmp_path, 1600.0)
    w.controller.store_model(built, session.fingerprints())
    plotter = w.view3d.plotter
    renders: list[bool] = []
    real = plotter.render

    def counted() -> None:
        renders.append(not plotter.suppress_rendering)
        real()

    plotter.render = counted  # PyVista's add_mesh calls it after every actor
    w.view3d.redraw()
    plotter.render = real
    assert sum(renders) == 1
    # 58 tape sets on the rest mesh, one actor for all of them.
    assert len(built.model.cables) > 50
    assert len(plotter.renderer.actors) < 15
    w.close()


def test_the_3d_view_does_not_render_on_a_timer(qtbot: QtBot, settings: QSettings) -> None:
    """pyvistaqt's 5 Hz auto-render is off: an unchanged scene is not redrawn."""
    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    assert w.open_project(GORE_PROJECT) is not None
    plotter = w.view3d.plotter
    assert plotter is not None
    timer = getattr(plotter, "render_timer", None)
    assert timer is None or not timer.isActive()
    w.close()


def test_view_buttons_place_the_camera_and_survive_a_redraw(
    qtbot: QtBot, settings: QSettings
) -> None:
    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    session = w.open_project(GORE_PROJECT)
    assert session is not None and session.design.gores is not None
    view, plotter = w.view3d, w.view3d.plotter
    assert plotter is not None
    view.view_buttons["top"].click()
    position = np.array(plotter.camera.position)
    focal = np.array(plotter.camera.focal_point)
    assert position[:2] == pytest.approx(focal[:2], abs=1e-6) and position[2] > focal[2]
    view.view_buttons["front"].click()
    front = np.array(plotter.camera.position) - np.array(plotter.camera.focal_point)
    assert front[1] < 0.0 and abs(front[0]) < 1e-6 and abs(front[2]) < 1e-6
    # One gore: 360 / 8 = 45 deg about the axis.
    view.view_buttons["gore_next"].click()
    turned = np.array(plotter.camera.position) - np.array(plotter.camera.focal_point)
    angle = np.degrees(np.arctan2(turned[1], turned[0]) - np.arctan2(front[1], front[0]))
    assert angle == pytest.approx(360.0 / session.design.gores.count)
    view.orthographic.setChecked(True)
    assert plotter.camera.parallel_projection
    view.orthographic.setChecked(False)
    assert not plotter.camera.parallel_projection
    # A redraw (any edit, a run arriving) keeps the chosen view.
    before = tuple(plotter.camera.position)
    view.redraw()
    assert tuple(plotter.camera.position) == pytest.approx(before)
    w.close()


def test_view_keys_over_the_3d_view_choose_views(qtbot: QtBot, settings: QSettings) -> None:
    """The number keys reach the view shortcuts, not VTK's own key bindings (VTK's 3
    would turn stereo rendering on)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    assert w.open_project(GORE_PROJECT) is not None
    plotter = w.view3d.plotter
    assert plotter is not None
    plotter.setFocus()
    QTest.keyClick(plotter, Qt.Key.Key_7)
    sight = np.array(plotter.camera.position) - np.array(plotter.camera.focal_point)
    assert abs(sight[0]) < 1e-6 and abs(sight[1]) < 1e-6 and sight[2] > 0.0
    QTest.keyClick(plotter, Qt.Key.Key_3)
    sight = np.array(plotter.camera.position) - np.array(plotter.camera.focal_point)
    assert sight[0] > 0.0 and abs(sight[2]) < 1e-6
    assert not plotter.ren_win.GetStereoRender()
    QTest.keyClick(plotter, Qt.Key.Key_5)
    assert w.view3d.orthographic.isChecked() and plotter.camera.parallel_projection
    # The numeric keypad works as the number row does (Ctrl+keypad 7: into the mouth).
    QTest.keyClick(
        plotter,
        Qt.Key.Key_7,
        Qt.KeyboardModifier.KeypadModifier | Qt.KeyboardModifier.ControlModifier,
    )
    sight = np.array(plotter.camera.position) - np.array(plotter.camera.focal_point)
    assert abs(sight[0]) < 1e-6 and abs(sight[1]) < 1e-6 and sight[2] < 0.0
    w.close()


def test_face_seams_zoom_to_a_layer_and_keep_saved_views_per_project(
    qtbot: QtBot, settings: QSettings
) -> None:
    w = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w)
    w.show()
    assert w.open_project(GORE_PROJECT) is not None
    view, plotter = w.view3d, w.view3d.plotter
    assert plotter is not None

    def azimuth() -> float:
        sight = np.array(plotter.camera.position) - np.array(plotter.camera.focal_point)
        return float(np.degrees(np.arctan2(sight[1], sight[0])) % 360.0)

    view.face_seam(2)  # 8 gores: seam 2 at 90 deg
    assert azimuth() == pytest.approx(90.0)
    view.face_gore(1)
    assert azimuth() == pytest.approx(22.5)
    view.view_buttons["iso"].click()
    far = np.linalg.norm(np.array(plotter.camera.position) - plotter.camera.focal_point)
    view.layer_list.setCurrentRow(0)  # the design surface
    view.view_buttons["zoom_layer"].click()
    near = np.linalg.norm(np.array(plotter.camera.position) - plotter.camera.focal_point)
    assert near <= far
    # Save, move away, come back.
    view.view_buttons["top"].click()
    top = tuple(plotter.camera.position)
    assert view.save_view("crown")
    view.view_buttons["front"].click()
    assert view.restore_view("crown")
    assert tuple(plotter.camera.position) == pytest.approx(top)
    assert view.saved_views.findText("crown") >= 0
    w.close()
    # A new window on the same project finds it again (kept in the settings).
    w2 = MainWindow(settings, enable_3d=True, interactive=False)
    qtbot.addWidget(w2)
    w2.show()
    assert w2.open_project(GORE_PROJECT) is not None
    assert [v["name"] for v in w2.view3d.saved()] == ["crown"]
    assert w2.view3d.delete_view("crown") and w2.view3d.saved() == []
    w2.close()
