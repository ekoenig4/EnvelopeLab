"""Headless GUI tests of the Special shapes mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from envelopelab.export.qa import check_pack
from envelopelab.io.blender import MeshObject, write_obj_scene
from envelopelab.validation.primitives import ellipsoid_mesh
from envelopelab_app.main_window import MainWindow
from envelopelab_app.panels.shapes import ShapesPanel


def _placed(window: MainWindow) -> ShapesPanel:
    assert window.controller.shapes.wait(120_000)
    return window.shapes


def _messages(window: MainWindow) -> list[str]:
    window.validation.refresh()
    return window.validation.messages()


def test_special_shapes_mode_exists(gore_window: MainWindow) -> None:
    labels = [gore_window.mode_tabs.tabText(i) for i in range(gore_window.mode_tabs.count())]
    assert any(label.startswith("Special shapes") for label in labels)
    gore_window.show_panel("shapes")
    assert gore_window.panel_visible("shapes")


def test_add_dome_is_placed_in_the_background(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    assert panel.add_shape("dome") == "Dome"
    session = gore_window.controller.session
    assert session is not None and [s.name for s in session.state.shapes] == ["Dome"]
    panel = _placed(gore_window)
    assert "placed" in panel.status.text()
    assert panel.pieces.topLevelItemCount() == 16
    assert panel.attachment.topLevelItemCount() >= 1
    assert panel.checks.topLevelItemCount() >= 1
    assert len(panel.preview.pieces) == 16
    assert not any("shape Dome" in m and "[ERROR]" in m for m in _messages(gore_window))
    assert gore_window.controller.artifact_status("shapes") == "current"
    assert "shape:Dome" in gore_window.view3d.labels()


def test_edit_and_undo_shape_parameters(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("tube")
    _placed(gore_window)
    pieces = panel.pieces.topLevelItemCount()
    panel.fields[("panels",)].setValue(6)
    _placed(gore_window)
    assert panel.pieces.topLevelItemCount() == pieces + 2  # 4 -> 6 panels, tip disc kept
    gore_window.undo()
    _placed(gore_window)
    assert panel.pieces.topLevelItemCount() == pieces
    assert panel.fields[("panels",)].value() == 4


def test_shape_that_does_not_fit_is_an_error(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    assert panel.set_value(("base_radius",), 6.0)
    _placed(gore_window)
    assert "CANNOT BE PLACED" in panel.status.text()
    assert any("[ERROR] shape Dome cannot be placed" in m for m in _messages(gore_window))
    assert not panel.simulate_button.isEnabled()
    assert panel.export_pack(Path("unused")) is None  # never leaves a shape out silently


def test_export_build_pack_passes_qa(gore_window: MainWindow, tmp_path: Path) -> None:
    gore_window.show_panel("shapes")
    gore_window.shapes.add_shape("dome")
    panel = _placed(gore_window)
    index = panel.export_pack(tmp_path / "pack")
    assert index is not None
    data = json.loads(index.read_text(encoding="utf-8"))
    assert any(s["piece"].startswith("Dome-G1") for s in data["sheets"])
    assert check_pack(tmp_path / "pack") == []


def test_import_mesh_and_export_to_blender(gore_window: MainWindow, tmp_path: Path) -> None:
    gore_window.show_panel("shapes")
    mesh = ellipsoid_mesh(0.25, 0.2, 0.3, -0.05, rings=10, segments=16)
    path = write_obj_scene(
        tmp_path / "blob.obj", [MeshObject("blob", mesh.vertices, mesh.triangles)]
    )
    panel = gore_window.shapes
    assert panel.import_mesh(path) == "blob"
    _placed(gore_window)
    placed = panel.placed("blob")
    assert placed is not None, panel.status.text()
    # Flattening a near-sphere into 12 panels distorts it; that is shown, never hidden.
    warnings = [c for c in placed.checks if c.severity == "warning"]
    if warnings:
        assert "need attention" in panel.status.text()
        assert any("[WARNING] shape blob" in m for m in _messages(gore_window))
    out = panel.export_blender(tmp_path / "scene.obj")
    assert out is not None
    names = [
        line.split(maxsplit=1)[1] for line in out.read_text().splitlines() if line.startswith("o ")
    ]
    assert any(n.startswith("blob") for n in names) and len(names) >= 2


def test_bad_mesh_file_is_reported(gore_window: MainWindow, tmp_path: Path) -> None:
    rejected: list[str] = []
    gore_window.controller.editRejected.connect(rejected.append)
    bad = tmp_path / "bad.obj"
    bad.write_text("not a mesh\n", encoding="utf-8")
    assert gore_window.shapes.import_mesh(bad) is None
    assert rejected


@pytest.mark.slow
def test_simulate_shape_shows_result_and_goes_stale(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    panel.set_value(("feed_hole_radius",), 0.07)
    _placed(gore_window)
    panel.mesh_spin.setValue(80.0)
    assert panel.simulate_selected()
    assert gore_window.controller.shape_simulator.wait(600_000)
    text = panel.sim_status.text()
    assert text.startswith("Preview (dynamic relaxation)"), text
    assert panel.sim_tree.topLevelItemCount() > 5
    assert gore_window.controller.shapes.simulation_status("Dome") == "current"
    assert "shape-sim:Dome" in gore_window.view3d.labels()
    panel.set_value(("height",), 0.25)
    _placed(gore_window)
    assert gore_window.controller.shapes.simulation_status("Dome") == "stale"
    assert "STALE" in panel.sim_status.text()
    assert any("simulation is STALE" in m for m in _messages(gore_window))


def test_removing_every_shape_leaves_nothing_stale(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    assert gore_window.controller.artifact_status("shapes") == "current"
    panel.remove_selected()
    _placed(gore_window)
    assert gore_window.controller.artifact_status("shapes") == "not built"
    assert not any("special shapes is stale" in m for m in _messages(gore_window))


def test_refused_rename_restores_the_name(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    panel.add_shape("dome")
    assert panel.selected == "Dome 2"
    panel.name_edit.setText("Dome")
    panel.name_edit.editingFinished.emit()
    assert panel.selected == "Dome 2"
    assert panel.name_edit.text() == "Dome 2"
    panel.name_edit.setText("Ear")
    panel.name_edit.editingFinished.emit()
    assert panel.selected == "Ear"
    assert [s.name for s in panel.specs()] == ["Dome", "Ear"]


def _surface_point(window: MainWindow, gore: int, tape: float, across: float = 0.0) -> Any:
    surface = window.controller.envelope_surface()
    assert surface is not None
    theta = surface.theta_at(gore, across)
    return surface.point(np.array([tape]), np.array([theta]))[0]


def test_drag_moves_a_shape_in_one_undo_step(gore_window: MainWindow) -> None:
    gore_window.shapes.add_shape("dome")
    _placed(gore_window)
    view = gore_window.view3d
    session = gore_window.controller.session
    assert session is not None
    before = session.state.shapes[0].placement
    assert view.begin_shape_drag("Dome")
    for tape in (4.5, 5.0, 5.5):  # a drag is many moves, one edit
        placement = view.drag_shape_to(_surface_point(gore_window, 4, tape, 0.25))
        assert placement is not None and view.drag is not None
        assert view.drag.outline is not None and len(view.drag.outline) > 10
    assert "gore 4" in view.info.text()
    history = len(session.stack.history())
    assert view.end_shape_drag()
    after = session.state.shapes[0].placement
    assert (after.gore, after.tape_position, after.across) == (4, 5.5, 0.25)
    assert after.lean_deg == before.lean_deg
    assert len(session.stack.history()) == history + 1
    _placed(gore_window)
    assert gore_window.shapes.placed("Dome") is not None  # re-placed at the new spot
    gore_window.undo()
    assert session.state.shapes[0].placement == before


def test_drag_without_moving_or_of_unknown_shape_changes_nothing(
    gore_window: MainWindow,
) -> None:
    gore_window.shapes.add_shape("tube")
    view = gore_window.view3d
    session = gore_window.controller.session
    assert session is not None
    history = len(session.stack.history())
    assert not view.begin_shape_drag("Nope")
    assert view.begin_shape_drag("Tube")
    assert not view.end_shape_drag()  # released where it started
    assert view.begin_shape_drag("Tube")
    view.drag_shape_to(_surface_point(gore_window, 2, 3.0))
    view.cancel_shape_drag()
    assert view.drag is None and len(session.stack.history()) == history


def test_drag_button_opens_the_3d_view_with_dragging_on(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    gore_window.shapes.add_shape("dome")
    assert gore_window.shapes.drag_button.isEnabled()
    gore_window.shapes.drag_button.click()
    assert gore_window.panel_visible("view3d")
    assert gore_window.view3d.drag_shapes.isChecked()
    assert "drag it over the envelope" in gore_window.view3d.info.text()
    gore_window.view3d.pick.setChecked(True)  # picking and dragging exclude each other
    assert not gore_window.view3d.drag_shapes.isChecked()


def test_3d_view_draws_shapes_as_sewn_pieces(gore_window: MainWindow) -> None:
    """Both shape layers are coloured piece by piece in the skin fabric with their seams;
    a current simulation replaces the designed shape until the user shows it again."""
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    panel.set_value(("feed_hole_radius",), 0.07)
    _placed(gore_window)
    view = gore_window.view3d
    view.refresh()
    designed = view.layers["shape:Dome"]
    assert designed.visible
    assert designed.face_colors is not None and len(designed.face_colors) == len(designed.faces)
    assert len(np.unique(designed.face_colors, axis=0)) == 2  # every second gore darker
    assert len(designed.polylines["skin_seams"]) == 16
    assert len(designed.polylines["skin_rim"]) == 1
    panel.mesh_spin.setValue(80.0)
    assert panel.simulate_selected()
    assert gore_window.controller.shape_simulator.wait(600_000)
    view.refresh()
    sewn = view.layers["shape-sim:Dome"]
    assert "as sewn and inflated" in sewn.label
    assert sewn.visible and not view.layers["shape:Dome"].visible
    assert sewn.face_colors is not None and len(np.unique(sewn.face_colors, axis=0)) == 2
    assert len(sewn.polylines["skin_seams"]) == 16
    # The user's choice is kept when the layers are rebuilt.
    items = [view.layer_list.item(i) for i in range(view.layer_list.count())]
    item = next(i for i in items if i.data(Qt.ItemDataRole.UserRole) == "shape:Dome")
    item.setCheckState(Qt.CheckState.Checked)
    view.refresh()
    assert view.layers["shape:Dome"].visible


def _fed_dome(window: MainWindow) -> ShapesPanel:
    window.show_panel("shapes")
    panel = window.shapes
    panel.add_shape("dome")
    _placed(window)
    panel.set_value(("feed_hole_radius",), 0.07)
    return _placed(window)


@pytest.mark.slow
def test_an_envelope_run_solves_the_special_shapes_too(
    gore_window: MainWindow, qtbot: QtBot, tmp_path: Path
) -> None:
    """Run preview solves the envelope and then every fed shape, with the same solver,
    at the automatic element size; the result is kept with the project and the run."""
    from envelopelab.project.shape_runs import auto_mesh_size
    from envelopelab_app.simulation import PREVIEW

    w = gore_window
    panel = _fed_dome(w)
    panel.add_shape("tube")  # no feed hole: left out, and said so
    _placed(w)
    messages: list[str] = []
    w.controller.message.connect(messages.append)
    session = w.controller.session
    assert session is not None
    assert not session.project.shape_runs
    assert w.simulation.start(PREVIEW)
    assert any("Tube" in m and "no feed hole" in m for m in messages)
    assert w.simulation.wait(900_000)
    qtbot.waitUntil(lambda: session.shape_run("Dome") is not None, timeout=10_000)
    run = session.project.runs[-1]
    record = session.shape_run("Dome")
    placed = panel.placed("Dome")
    assert record is not None and placed is not None
    assert record.envelope_run_id == run.run_id
    assert record.solver == PREVIEW
    assert record.mesh_target_mm == pytest.approx(1000.0 * auto_mesh_size(placed))
    assert session.shape_run("Tube") is None
    assert w.controller.shapes.simulation_status("Dome") == "current"
    w.view3d.refresh()
    assert "shape-sim:Dome" in w.view3d.labels()
    # Kept with the project.
    path = session.save(tmp_path / "with-shapes.elproj")
    assert w.open_project(path) is not None
    _placed(w)
    assert w.controller.shapes.simulation_status("Dome") == "current"


@pytest.mark.slow
def test_a_calculix_run_verifies_the_special_shapes(gore_window: MainWindow, qtbot: QtBot) -> None:
    from envelopelab_app.simulation import CALCULIX

    w = gore_window
    if not w.simulation.calculix_available:
        pytest.skip("CalculiX (ccx) is not installed")
    _fed_dome(w)
    session = w.controller.session
    assert session is not None
    assert w.simulation.start(CALCULIX)
    assert w.simulation.wait(1_800_000)
    qtbot.waitUntil(lambda: session.shape_run("Dome") is not None, timeout=10_000)
    record = session.shape_run("Dome")
    assert record is not None and record.solver == CALCULIX
    assert record.envelope_run_id == session.project.runs[-1].run_id
    if not record.converged:
        assert any(f.severity == "error" for f in record.findings)


def test_pattern_view_shows_where_each_shape_is_sewn(gore_window: MainWindow) -> None:
    """Every panel a shape is sewn on follows the rows as its own piece, with the footprint
    line, the match marks and the feed hole; the rows say which gores are marked."""
    from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsSimpleTextItem

    from envelopelab.export.build_pack import primitive_sheets

    w = gore_window
    panel = _fed_dome(w)
    placed = panel.placed("Dome")
    assert placed is not None
    w.controller.regenerate_patterns()
    w.show_panel("patterns")
    view = w.patterns
    view.refresh()

    def texts() -> list[str]:
        return [
            i.text() for i in view.view.scene().items() if isinstance(i, QGraphicsSimpleTextItem)
        ]

    markings = [s for s in primitive_sheets(placed) if s.kind == "marking"]
    shown = texts()
    for sheet in markings:
        assert f"{sheet.piece.upper()}: Dome" in shown
    numbers = {t.split()[0] for t in shown if "(G" in t}
    assert {str(m.number) for m in placed.marks} <= numbers
    assert any(t.startswith("hole: cut ") for t in shown)
    assert any(t.startswith("Dome: mark gores") for t in shown)
    rings = [i for i in view.view.scene().items() if isinstance(i, QGraphicsEllipseItem)]
    assert len(rings) >= 2  # the feed hole, cut and finished
    view.show_shapes.setChecked(False)
    assert not any(t.startswith("Dome: mark gores") for t in texts())
