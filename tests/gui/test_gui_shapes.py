"""Headless GUI tests of the Special shapes mode."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsPolygonItem, QGraphicsRectItem, QLabel
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
    assert panel.pieces.topLevelItemCount() == 16 + 1  # 16 gores and the automatic cap
    assert panel.attachment.topLevelItemCount() >= 1
    assert panel.checks.topLevelItemCount() >= 1
    assert len(panel.preview.pieces) == 16 + 1
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
    assert len(designed.polylines["skin_seams"]) == 16 + 1  # and the cap's seam
    assert len(designed.polylines["skin_rim"]) == 1
    panel.mesh_spin.setValue(80.0)
    assert panel.simulate_selected()
    assert gore_window.controller.shape_simulator.wait(600_000)
    view.refresh()
    sewn = view.layers["shape-sim:Dome"]
    assert "as sewn and inflated" in sewn.label
    assert sewn.visible and not view.layers["shape:Dome"].visible
    assert sewn.face_colors is not None and len(np.unique(sewn.face_colors, axis=0)) == 2
    assert len(sewn.polylines["skin_seams"]) == 16 + 1
    # The user's choice is kept when the layers are rebuilt.
    item = view.layer_item("shape:Dome")
    assert item is not None
    item.setCheckState(0, Qt.CheckState.Checked)
    view.refresh()
    assert view.layers["shape:Dome"].visible


def test_cap_diameter_is_automatic_or_chosen_in_the_form(gore_window: MainWindow) -> None:
    """Automatic by default (the box shows the diameter used); unticked, the diameter is
    typed (0: the gores meet in a point); each change places the shape again."""
    from envelopelab.project.shapes import cap_diameter

    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    panel = _placed(gore_window)
    spec = panel.spec()
    assert spec is not None and spec.cap_diameter is None
    assert panel.cap_auto.isChecked() and not panel.cap_diameter.isEnabled()
    assert panel.cap_diameter.value() == pytest.approx(cap_diameter(spec))
    panel.cap_auto.setChecked(False)
    spec = panel.spec()
    assert spec is not None and spec.cap_diameter == pytest.approx(cap_diameter(spec))
    assert panel.cap_diameter.isEnabled()
    panel.cap_diameter.setValue(0.0)
    panel = _placed(gore_window)
    spec = panel.spec()
    assert spec is not None and spec.cap_diameter == 0.0
    assert panel.pieces.topLevelItemCount() == 16  # no cap piece
    panel.cap_auto.setChecked(True)
    spec = panel.spec()
    assert spec is not None and spec.cap_diameter is None


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
    panel = _fed_dome(w)
    # CalculiX starts from a converged preview. This small default dome's preview does
    # not converge with its automatic cap (half its base diameter: the flat cap wrinkles
    # round its edge, ADR-0032), so the run would rightly end at the preview; a pointed
    # dome checks that CalculiX solves the shapes of its run.
    panel.set_value(("cap_diameter",), 0.0)
    _placed(w)
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


def test_shape_window_shows_where_each_shape_is_sewn(gore_window: MainWindow) -> None:
    """The Special shapes window shows, with the selected shape, every envelope panel it is
    sewn on (footprint line, match marks, feed hole) and which gores of each row those are;
    the Patterns view shows only the base envelope."""
    from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsSimpleTextItem

    from envelopelab.export.build_pack import primitive_sheets

    w = gore_window
    panel = _fed_dome(w)
    placed = panel.placed("Dome")
    assert placed is not None
    w.controller.regenerate_patterns()
    panel.refresh()
    view = panel.markings
    markings = [s for s in primitive_sheets(placed) if s.kind == "marking"]
    assert markings and len(view.sheets) == len(markings)
    shown = view.labels()
    for sheet in markings:
        assert f"{sheet.piece.upper()}: Dome" in shown
    numbers = {t.split()[0] for t in shown if "(G" in t}
    assert {str(m.number) for m in placed.marks} <= numbers
    assert any(t.startswith("hole: cut ") for t in shown)
    rings = [i for i in view.scene().items() if isinstance(i, QGraphicsEllipseItem)]
    assert len(rings) >= 2  # the feed hole, cut and finished
    assert "Row B: Dome: mark gores" in panel.marking_notes.text()
    assert not view.stale
    # It opens on the marked area; a double click (fit whole) shows the whole panels.
    view.fit()
    assert not view.showing_all
    view.fit(whole=True)
    assert view.showing_all
    # The Patterns view no longer draws any shape's panels or row notes.
    w.show_panel("patterns")
    w.patterns.refresh()
    texts = [
        i.text() for i in w.patterns.view.scene().items() if isinstance(i, QGraphicsSimpleTextItem)
    ]
    assert not any(": Dome" in t or t.startswith("Dome: mark gores") for t in texts)
    assert not hasattr(w.patterns, "show_shapes")


def test_move_feed_holes_clear_of_the_seams(gore_window: MainWindow) -> None:
    w = gore_window
    w.show_panel("shapes")
    panel = w.shapes
    panel.add_shape("dome")
    placed = _placed(w).placed("Dome")
    assert placed is not None
    seam = next(b.s_top for b in placed.surface.rows if b.s_top > placed.base_s)
    spec = panel.spec()
    assert spec is not None
    hole = {
        "gore": spec.placement.gore,
        "tape_position": seam - 0.01,
        "across": 0.0,
        "radius": 0.03,
    }
    panel.set_value(("placement", "tape_position"), seam - 0.05)  # the dome over the seam
    panel.set_value(("feed_holes",), [hole])
    placed = _placed(w).placed("Dome")
    assert placed is not None
    assert any(
        c.name == "feed hole clear of seams" and c.severity == "error" for c in placed.checks
    )
    notes = panel.move_holes_clear()
    assert notes and "moved clear of the seams" in notes[0]
    placed = _placed(w).placed("Dome")
    assert placed is not None
    assert all(c.severity == "info" for c in placed.checks if c.name == "feed hole clear of seams")


def test_editor_and_results_are_in_tabs(gore_window: MainWindow) -> None:
    """Three columns: the shapes, the editor in tabs (Profile only for a revolved shape)
    and the results in tabs."""
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    editor, results = panel.editor_tabs, panel.result_tabs
    assert [editor.tabText(i) for i in range(editor.count())] == [
        "Placement && size",
        "Profile",
        "Feed holes && cap",
        "Panel layout",
        "Simulation",
    ]
    assert [results.tabText(i) for i in range(results.count())] == [
        "On the balloon",
        "Cut pieces",
        "Envelope panels",
        "Checks",
        "Attachment",
    ]
    assert panel.splitter.count() == 3
    panel.add_shape("dome")
    _placed(gore_window)
    assert not editor.isTabVisible(1)
    assert panel.fields[("gores",)].parent() is panel.form_box
    assert panel.cap_diameter.parent() is panel.holes_box
    panel.add_shape("revolved")
    _placed(gore_window)
    assert editor.isTabVisible(1)


def test_cut_piece_drawing_zooms_pans_and_fits(gore_window: MainWindow) -> None:
    from PySide6.QtCore import QPointF

    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    preview = panel.preview
    preview.resize(600, 400)
    # 17 pieces (16 gores and the cap) in rows filling the widget, not one long row.
    offsets, width, height = preview.layout_offsets()
    assert len(offsets) == 17
    rows = len({round(float(o[1]), 9) for o in offsets})
    assert rows > 1
    at = QPointF(150.0, 120.0)
    pan = preview.pan
    preview.zoom_at(2.0, at)
    assert preview.zoom == 2.0
    # The point under the pointer stays put: pan' = at - origin - (at - origin - pan) * 2.
    origin = QPointF(preview._margin, preview.height() - preview._margin)
    expected = at - origin - (at - origin - pan) * 2.0
    assert preview.pan.x() == pytest.approx(expected.x())
    assert preview.pan.y() == pytest.approx(expected.y())
    preview.zoom_at(1e-3, at)
    assert preview.zoom == preview.ZOOM_RANGE[0]
    preview.zoom_at(10.0, at)
    preview.reset_view()
    assert preview.zoom == 1.0 and preview.pan == QPointF(0.0, 0.0)


def test_shapes_are_reported_one_by_one_and_a_stale_batch_stops() -> None:
    """The placing worker announces each shape as soon as it is placed (the first shapes
    show while the rest are placed), and a batch made out of date ends early."""
    from envelopelab.project.session import ProjectSession
    from envelopelab.project.shapes import default_shape
    from envelopelab_app.shapes_service import _DesignWorker

    from .gui_support import GORE_PROJECT

    session = ProjectSession.open(GORE_PROJECT)
    design, patterns = session.state.design, session.state.patterns
    jobs = [(n, f"key-{n}", default_shape("dome", design, n)) for n in ("A", "B", "C")]
    worker = _DesignWorker(design, patterns, jobs)
    batches: list[list[Any]] = []
    worker.done.connect(batches.append)
    worker.run()  # in this thread: every emission is delivered at once
    assert [[name for name, _ in b] for b in batches] == [["A"], ["B"], ["C"]]
    assert all(r.design is not None and r.key == f"key-{n}" for b in batches for n, r in b)

    stopped = _DesignWorker(design, patterns, jobs)
    seen: list[list[Any]] = []

    def stop_after_first(batch: list[Any]) -> None:
        seen.append(batch)
        stopped.stop = True

    stopped.done.connect(stop_after_first)
    stopped.run()
    assert [[name for name, _ in b] for b in seen] == [["A"]]


@pytest.mark.slow
def test_one_run_colours_the_envelope_and_its_shapes_together(
    gore_window: MainWindow, qtbot: QtBot
) -> None:
    """The 3D view's run is the whole balloon: the envelope and the shapes solved with
    it. Its parts share the fields and one colour scale; the run details list each part;
    a shape is not a run of its own (it is reached through its layers and Go to part)."""
    from envelopelab_app.simulation import PREVIEW

    w = gore_window
    _fed_dome(w)
    session = w.controller.session
    assert session is not None
    assert w.simulation.start(PREVIEW)
    assert w.simulation.wait(900_000)
    qtbot.waitUntil(lambda: session.shape_run("Dome") is not None, timeout=10_000)
    view = w.view3d
    view.refresh()
    assert view.run_choice.findData("shape-sim:Dome") < 0  # not a run of its own
    assert view.run_choice.currentData() == PREVIEW
    assert "envelope + 1 shape" in view.run_choice.currentText()
    assert view.parts() == [PREVIEW, "shape-sim:Dome"]
    assert view.part_choice.findData("shape:Dome") >= 0  # Go to part
    record = session.shape_run("Dome")
    assert record is not None
    dome = view.part_fields["shape-sim:Dome"]
    for name in ("fos_warp", "fos_weft", "n1", "n_warp", "wrinkle_state", "displacement"):
        assert name in dome, (name, view.part_missing["shape-sim:Dome"].get(name))
    assert np.isfinite(dome["deviation"].values).all()
    skin = len(view.layers["shape-sim:Dome"].faces)
    assert len(dome["fos_warp"].values) == skin < record.n_elements
    # A current CalculiX run verifies the envelope only: a shape's preview simulation is
    # never shown as verified.
    envelope = session.project.runs[-1]
    session.project.runs.append(envelope.model_copy(update={"solver": "calculix"}))
    try:
        envelope_state, shape_state = view.run_state(), view.run_state("shape-sim:Dome")
        assert envelope_state is not None and envelope_state.verified
        assert shape_state is not None and not shape_state.verified
    finally:
        session.project.runs.pop()
    # The conservative shape summary never exceeds the lowest warp/weft factor shown.
    low = min(float(dome[k].values.min()) for k in ("fos_warp", "fos_weft"))
    assert record.fos["skin"] <= low * (1.0 + 1e-12)
    # One scale: the shared values hold both parts.
    view.field_choice.setCurrentIndex(view.field_choice.findData("n1"))
    shared = view._shared_values("n1")
    assert len(shared) == len(view.fields["n1"].values) + len(dome["n1"].values)
    assert view.part_field("shape-sim:Dome") is dome["n1"]
    # The run details have a row per part.
    details = view.run_details.text()
    assert ">Envelope<" in details and ">Dome<" in details
    assert view.banner.kind in ("info", "fail", "error")
    # The tree groups the layers; the Result group holds the envelope and the dome.
    item = view.layer_item("shape-sim:Dome")
    group = None if item is None else item.parent()
    assert group is not None and group.text(0) == "Result"
    # The Probe names the part it hit.
    on_dome = view.layers["shape-sim:Dome"].points[0]
    assert view.part_at(on_dome) == "shape-sim:Dome"
    assert view.probe_text("shape-sim:Dome", 0).startswith("Dome skin · element 0")
    on_envelope = view.layers[PREVIEW].points[0]
    assert view.part_at(on_envelope) == PREVIEW
    assert view.probe_text(PREVIEW, 0).startswith("Envelope · element 0")


def test_pieces_larger_than_the_print_roll_are_warned(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    assert not panel.preview.oversize
    roll_column = panel.pieces.headerItem().text(5)
    assert roll_column == "Page on print roll"
    assert not any("shape Dome: piece" in m for m in _messages(gore_window))

    # A roll narrower than the pieces: every piece is warned, nothing else changes.
    gore_window.apply_preferences(replace(gore_window.prefs, print_roll_width=0.1))
    items = [panel.pieces.topLevelItem(i) for i in range(panel.pieces.topLevelItemCount())]
    texts = [item.text(5) for item in items if item is not None]
    assert all("LARGER THAN 100 mm ROLL" in t for t in texts)
    assert panel.preview.oversize == {p.label for p in panel.preview.pieces}
    assert "need attention" in panel.status.text()
    found = [m for m in _messages(gore_window) if "[WARNING] shape Dome: piece" in m]
    assert len(found) == panel.pieces.topLevelItemCount()
    # The envelope panels are checked against the same roll (the fixture's 2.5 m rows are
    # larger than a 60 in roll too, so only the roll's width in the message changes).
    assert any(
        m.startswith("[WARNING] row ") and "THE 100 mm print roll" in m
        for m in _messages(gore_window)
    )

    gore_window.apply_preferences(replace(gore_window.prefs, print_roll_width=60 * 0.0254))
    assert not panel.preview.oversize
    assert not any("shape Dome: piece" in m for m in _messages(gore_window))
    assert not any("THE 100 mm print roll" in m for m in _messages(gore_window))


def test_export_dialog_starts_from_the_print_roll_preference(gore_window: MainWindow) -> None:
    from envelopelab_app.dialogs import PreferencesDialog
    from envelopelab_app.export_dialog import ExportPackDialog

    prefs = replace(gore_window.prefs, print_roll_width=72 * 0.0254)
    dialog = PreferencesDialog(prefs, gore_window)
    assert dialog.print_roll.value() == pytest.approx(72.0)
    assert dialog.result_preferences().print_roll_width == pytest.approx(72 * 0.0254)
    export = ExportPackDialog(gore_window, "", prefs.print_roll_width)
    assert export.roll_width() == pytest.approx(72 * 0.0254)


def test_panel_layout_turns_widens_and_splits_the_pieces(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    session = gore_window.controller.session
    assert session is not None
    assert panel.widths_table.rowCount() == 16
    assert "16 gores round the axis (equal), one tier" in panel.layout_note.text()

    panel.seam_turn.setValue(10.0)
    _placed(gore_window)
    assert session.state.shapes[0].seam_offset_deg == pytest.approx(10.0)

    assert panel.set_panel_widths([2.0] + [1.0] * 15)
    _placed(gore_window)
    item = panel.widths_table.item(0, 1)
    assert item is not None and item.text() == f"{360.0 * 2 / 17:.1f}°"

    assert panel.add_split()
    _placed(gore_window)
    assert session.state.shapes[0].splits == [0.5]
    labels = [panel.pieces.topLevelItem(i) for i in range(panel.pieces.topLevelItemCount())]
    names = [i.text(0) for i in labels if i is not None]
    assert names[:2] == ["Dome-G1A", "Dome-G2A"] and "Dome-G16B" in names
    assert names[-1] == "Dome-TIP" and len(names) == 2 * 16 + 1
    assert "in 2 tiers, A at the rim" in panel.layout_note.text()
    assert not any("shape Dome" in m and "[ERROR]" in m for m in _messages(gore_window))

    # Fewer gores keep the widths given for the first ones.
    panel.fields[("gores",)].setValue(8)
    _placed(gore_window)
    assert session.state.shapes[0].panel_widths == [2.0] + [1.0] * 7
    assert panel.widths_table.rowCount() == 8

    assert panel.remove_split()
    _placed(gore_window)
    assert session.state.shapes[0].splits == []
    gore_window.undo()
    _placed(gore_window)
    assert session.state.shapes[0].splits == [0.5]


def test_shapes_grouped_as_one_object_move_mirror_and_export_together(
    gore_window: MainWindow, tmp_path: Path
) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    session = gore_window.controller.session
    assert session is not None
    panel.add_shape("dome")
    panel.add_shape("tube")
    _placed(gore_window)
    assert not panel.move_group_button.isEnabled()
    for name in ("Dome", "Tube"):
        panel.select(name)
        panel.group_combo.setCurrentText("Head")
        panel._group_edited()
    _placed(gore_window)
    assert [s.group for s in session.state.shapes] == ["Head", "Head"]
    assert panel.list.item(0).text().startswith("Head ▸ Dome")
    assert panel.move_group_button.isEnabled() and panel.mirror_group_button.isEnabled()

    before = {s.name: s.placement for s in session.state.shapes}
    assert panel.move_group(1.0, 0.5)
    after = {s.name: s.placement for s in session.state.shapes}
    for name, p in before.items():
        assert after[name].gore == p.gore % 12 + 1
        assert after[name].tape_position == pytest.approx(p.tape_position + 0.5)

    # Dragging one member takes the whole group (one undo step).
    view = gore_window.view3d
    history = len(session.stack.history())
    start = session.state.shapes[0].placement
    assert view.begin_shape_drag("Dome")
    view.drag_shape_to(_surface_point(gore_window, start.gore + 2, start.tape_position))
    assert view.end_shape_drag()
    assert len(session.stack.history()) == history + 1
    tube = next(s for s in session.state.shapes if s.name == "Tube")
    assert tube.placement.gore == after["Tube"].gore + 2

    assert panel.mirror_group(0.0, copy=True)
    names = [s.name for s in session.state.shapes]
    assert names == ["Dome", "Tube", "Dome mirror", "Tube mirror"]
    _placed(gore_window)
    assert not any("[ERROR]" in m and "mirror" in m for m in _messages(gore_window))

    out = panel.export_blender(tmp_path / "head.obj", "Head")
    assert out is not None
    text = (tmp_path / "head.obj").read_text(encoding="utf-8")
    assert "o Tube_mirror_designed" in text and "o envelope" in text


def test_cut_pieces_show_how_they_lie_on_the_print_roll(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("tube")
    _placed(gore_window)
    item = panel.pieces.topLevelItem(0)
    assert item is not None
    assert " mm across, " in item.text(5)
    assert "across the roll" in item.toolTip(5)
    preview = panel.preview
    side_by_side, _w, _h = preview.drawn()
    panel.on_roll_check.setChecked(True)
    assert preview.on_roll
    on_roll, width, length = preview.drawn()
    roll = gore_window.prefs.print_roll_width
    assert width == pytest.approx(roll)
    # One page after the other down the roll (as the PDF pages and the Patterns view),
    # every page within the roll's width.
    tops = [cut[:, 1].max() for _p, (_f, cut, _r) in on_roll]
    assert tops == sorted(tops, reverse=True) and max(tops) <= length
    for _piece, (_f, cut, _r) in on_roll:
        assert cut[:, 0].min() >= 0.0 and cut[:, 0].max() <= roll
    preview.grab()  # paints without error
    panel.on_roll_check.setChecked(False)
    assert len(side_by_side) == len(on_roll)


def test_symmetry_axes_and_linked_mirror_twins(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    session = gore_window.controller.session
    assert session is not None
    panel.add_shape("dome")
    _placed(gore_window)
    assert not panel.edit_axis_button.isEnabled()
    assert panel.add_axis("Face centre", 5.5)
    item = panel.axes_list.item(0)
    assert item is not None and item.text() == "Face centre — centre of gore 6"
    assert "symmetry" in gore_window.view3d.labels()
    assert "Face centre (centre of gore 6)" in gore_window.view3d.labels()["symmetry"]

    assert panel.mirror_selected("Face centre") == "Dome mirror"
    _placed(gore_window)
    assert panel.selected == "Dome mirror"
    assert panel.mirror_label.text().startswith("⇄ Mirror twin of Dome across axis Face centre")
    assert not panel.unlink_button.isHidden() and not panel.mirror_button.isEnabled()
    texts = [panel.list.item(i).text() for i in range(panel.list.count())]
    assert texts[0].endswith("⇄") and texts[1].endswith("⇄ mirror of Dome")
    assert not any("[ERROR]" in m for m in _messages(gore_window))

    # Dragging the twin moves the original as its mirror image (one undo step).
    view = gore_window.view3d
    history = len(session.stack.history())
    assert view.begin_shape_drag("Dome mirror")
    view.drag_shape_to(_surface_point(gore_window, 8, 6.0, 0.25))
    assert view.end_shape_drag()
    assert len(session.stack.history()) == history + 1
    dome, twin = session.state.shapes
    g_dome = dome.placement.gore - 0.5 + dome.placement.across
    g_twin = twin.placement.gore - 0.5 + twin.placement.across
    assert (g_dome + g_twin) % 12 == pytest.approx(11.0 % 12)
    assert dome.placement.tape_position == pytest.approx(6.0)

    panel.select("Dome mirror")
    assert panel.unlink_selected()
    assert session.state.shapes[1].mirror is None
    assert panel.unlink_button.isHidden()


def test_placement_views_show_and_move_the_shapes(gore_window: MainWindow) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    session = gore_window.controller.session
    assert session is not None
    panel.add_shape("dome")
    panel.add_shape("tube")
    _placed(gore_window)
    panel.add_axis("Face centre", 5.5)
    view = panel.placement
    assert panel.result_tabs.indexOf(view) == 0  # the On the balloon tab, the default
    assert panel.result_tabs.currentWidget() is view
    data = view.map.data
    assert [s.name for s in data.shapes] == ["Dome", "Tube"]
    assert [a[0] for a in data.axes] == ["Face centre"]
    assert data.selected == "Tube"
    assert all(len(s.triangles) and s.footprint for s in data.shapes)
    # The 3D sketch faces the selected shape.
    tube = data.shapes[1]
    from envelopelab_app.placement_view import _centre

    rel = tube.base3d - _centre(data.sketch)
    assert view.sketch.azimuth == pytest.approx(np.degrees(np.arctan2(rel[1], rel[0])))
    view.sketch.grab()
    view.map.grab()

    # Click the dome on the map: it is selected.
    mapv = view.map
    mapv.resize(600, 400)
    dome = data.shapes[0]
    at = mapv.to_screen(float(dome.base[0]), float(dome.base[1])).toPoint()
    QTest.mouseClick(mapv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert panel.selected == "Dome"
    # Drag it one gore to the right on the map: it moves there, in one undo step.
    before = session.state.shapes[0].placement
    target = mapv.to_screen(float(dome.base[0]) + mapv.data.gore_map.column, float(dome.base[1]))
    history = len(session.stack.history())
    QTest.mousePress(mapv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    QTest.mouseMove(mapv, QPoint(at.x() + 5, at.y()))
    QTest.mouseMove(mapv, target.toPoint())
    QTest.mouseRelease(
        mapv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target.toPoint()
    )
    after = session.state.shapes[0].placement
    assert after.gore == before.gore % 12 + 1
    assert after.tape_position == pytest.approx(before.tape_position, abs=0.05)
    assert len(session.stack.history()) == history + 1


def test_nudge_and_drag_the_shape_in_either_view(gore_window: MainWindow) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    session = gore_window.controller.session
    assert session is not None
    panel.add_shape("dome")
    _placed(gore_window)
    view = panel.placement
    assert view.step.currentData() == pytest.approx(0.05)

    def where() -> tuple[float, float]:
        p = session.state.shapes[0].placement
        return p.gore - 0.5 + p.across, p.tape_position

    g0, s0 = where()
    view.nudge_buttons["up"].click()
    assert where()[1] == pytest.approx(s0 + 0.05)
    view.nudge_buttons["right"].click()
    assert where()[0] > g0
    # Arrow keys in the gore map or the 3D view; Shift takes five steps; one undo each.
    history = len(session.stack.history())
    _g1, s1 = where()
    QTest.keyClick(view.map, Qt.Key.Key_Down)
    assert where()[1] == pytest.approx(s1 - 0.05)
    QTest.keyClick(view.view3d, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert where()[1] == pytest.approx(s1 - 0.30)
    assert len(session.stack.history()) == history + 2
    gore_window.undo()
    assert where()[1] == pytest.approx(s1 - 0.05)

    # Drag the shape in the 3D sketch: press on its base point, release over the envelope.
    _placed(gore_window)
    sketch = view.sketch
    gore_window.resize(1600, 1000)
    QApplication.processEvents()  # the splitter sizes the view
    data = sketch.data
    shape = data.shapes[0]
    ((x, y),) = sketch._projector()(shape.base3d[None])
    start = QPoint(int(x), int(y))
    before = where()
    QTest.mousePress(sketch, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(sketch, QPoint(start.x() + 40, start.y() - 30))
    QTest.mouseRelease(
        sketch,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(start.x() + 40, start.y() - 30),
    )
    assert where() != pytest.approx(before)  # moved over the envelope ...
    gore_window.undo()
    assert where() == pytest.approx(before)  # ... in one undo step
    # Dragging the background turns the view instead.
    az = sketch.azimuth
    QTest.mousePress(
        sketch, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 5)
    )
    QTest.mouseMove(sketch, QPoint(60, 5))
    QTest.mouseRelease(
        sketch, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 5)
    )
    assert sketch.azimuth != az


def test_hidden_result_tabs_are_filled_when_shown(gore_window: MainWindow) -> None:
    """In the interactive application the result tabs behind On the balloon are filled
    when one is opened, not on every change."""
    gore_window.controller.defer_hidden = True
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    panel.refresh()
    assert panel.result_tabs.currentWidget() is panel.placement
    assert "placed" in panel.status.text()  # the status is always current
    assert panel.pieces.topLevelItemCount() == 0
    panel.result_tabs.setCurrentIndex(1)  # Cut pieces
    assert panel.pieces.topLevelItemCount() == 16 + 1
    assert panel.checks.topLevelItemCount() >= 1


def _map_point(panel: Any, g: float, frac: float = 0.5) -> Any:
    """Widget point of gore position ``g`` at ``frac`` of the tape on the gore map."""
    gm = panel.placement.map.data.gore_map
    ((x, y),) = gm.points(np.array([g]), np.array([frac * gm.length]))
    return panel.placement.map.to_screen(float(x), float(y)).toPoint()


def test_an_axis_is_seen_while_it_is_placed(gore_window: MainWindow) -> None:
    from PySide6.QtTest import QTest

    gore_window.resize(1600, 1000)
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    session = gore_window.controller.session
    assert session is not None
    panel.add_shape("dome")
    _placed(gore_window)
    place, mapv = panel.placement, panel.placement.map
    panel.begin_add_axis()
    assert place.axis_bar.isVisibleTo(place) and mapv.axis_mode
    assert panel.result_tabs.currentWidget() is place
    # The pointer shows where the axis would go (snapped to the centre of gore 3) ...
    QTest.mouseMove(mapv, _map_point(panel, 2.4))
    preview = mapv.preview
    assert preview is not None and preview.hover is not None
    assert preview.hover[:, 0] == pytest.approx(2.5 * mapv.data.gore_map.column)
    assert preview.hover3d and preview.ghosts  # and the dome's mirror image across it
    # ... a click puts it there; the bar says where; Place adds it.
    QTest.mouseClick(
        mapv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _map_point(panel, 2.4)
    )
    assert place.axis_line.value() == pytest.approx(3.0)
    assert place.axis_where.text() == "centre of gore 3"
    place.axis_name.setText("Face centre")
    place.axis_ok.click()
    assert [(a.name, a.line) for a in session.state.symmetry_axes] == [("Face centre", 2.5)]
    assert not place.axis_bar.isVisibleTo(place) and not mapv.axis_mode

    # Typing the gore line moves the preview too; Escape cancels.
    panel.begin_add_axis()
    place.axis_line.setValue(6.5)
    assert panel._axis is not None and panel._axis.line == pytest.approx(6.0)
    QTest.keyClick(mapv, Qt.Key.Key_Escape)
    assert not place.axis_bar.isVisibleTo(place)
    assert len(session.state.symmetry_axes) == 1


def test_mirror_shows_the_mirror_image_before_the_axis_is_placed(
    gore_window: MainWindow,
) -> None:
    from PySide6.QtTest import QTest

    gore_window.resize(1600, 1000)
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    session = gore_window.controller.session
    assert session is not None
    panel.add_shape("dome")
    _placed(gore_window)
    dome = session.state.shapes[0].placement
    g_dome = dome.gore - 0.5 + dome.across
    place, mapv = panel.placement, panel.placement.map
    panel.begin_mirror()
    QTest.mouseMove(mapv, _map_point(panel, 3.0))  # the seam 3|4
    preview = mapv.preview
    assert preview is not None and preview.map_line is None  # not placed yet
    ghost = np.vstack(preview.ghosts)
    gm = mapv.data.gore_map
    centre_g = (ghost[:, 0].min() + ghost[:, 0].max()) / 2 / gm.column
    assert abs(centre_g - (6.0 - g_dome)) < 0.6  # mirrored across gore position 3
    assert len(preview.ghosts3d) == 1
    QTest.mouseClick(
        mapv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _map_point(panel, 3.0)
    )
    place.axis_ok.click()
    _placed(gore_window)
    names = [s.name for s in session.state.shapes]
    assert names == ["Dome", "Dome mirror"]
    twin = session.state.shapes[1]
    assert twin.mirror is not None and twin.mirror.axis == "Axis 1"
    assert (twin.placement.gore - 0.5 + twin.placement.across) == pytest.approx(6.0 - g_dome)
    # Mirroring across an existing axis: choosing it fixes the line; the pointer does not
    # move it.
    panel.add_shape("tube")
    _placed(gore_window)
    panel.begin_mirror()
    place.axis_target.setCurrentIndex(1)  # Across Axis 1
    assert not place.axis_line.isEnabled()
    QTest.mouseClick(
        mapv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _map_point(panel, 5.0)
    )
    assert panel._axis is not None and panel._axis.line == pytest.approx(3.0)
    place.axis_ok.click()
    assert [s.name for s in session.state.shapes][-1] == "Tube mirror"


def test_dragging_an_axis_on_the_map_moves_it_and_its_twins(gore_window: MainWindow) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    gore_window.resize(1600, 1000)
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    session = gore_window.controller.session
    assert session is not None
    panel.add_shape("dome")
    _placed(gore_window)
    panel.add_axis("Face centre", 2.5)
    panel.mirror_selected("Face centre")
    _placed(gore_window)
    panel.select("Dome")
    mapv = panel.placement.map
    start = _map_point(panel, 2.5, 0.8)  # on the axis, away from the shapes
    target = _map_point(panel, 3.5, 0.8)
    history = len(session.stack.history())
    QTest.mousePress(mapv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    assert mapv.preview is not None and mapv.preview.ghosts  # the twin's new place, live
    QTest.mouseMove(mapv, QPoint(start.x() + 3, start.y()))
    QTest.mouseMove(mapv, target)
    QTest.mouseRelease(mapv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
    assert session.state.symmetry_axes[0].line == pytest.approx(3.5)
    assert len(session.stack.history()) == history + 1
    dome, twin = session.state.shapes
    g = dome.placement.gore - 0.5 + dome.placement.across
    gt = twin.placement.gore - 0.5 + twin.placement.across
    assert (g + gt) % 12 == pytest.approx(7.0)
    assert not panel.placement.axis_bar.isVisibleTo(panel.placement)


def test_the_3d_view_places_an_axis_too(gore_window: MainWindow) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    gore_window.resize(1600, 1000)
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    QApplication.processEvents()
    panel.begin_add_axis()
    sketch = panel.placement.sketch
    centre = QPoint(sketch.width() // 2, sketch.height() // 2)
    QTest.mouseClick(sketch, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
    line = panel._axis.line  # type: ignore[union-attr]
    assert line is not None and (line * 2) == pytest.approx(round(line * 2))  # snapped
    assert sketch.preview is not None and sketch.preview.lines3d
    sketch.grab()


def test_patterns_show_the_print_roll_like_the_special_shapes(gore_window: MainWindow) -> None:
    from dataclasses import replace

    gore_window.show_panel("patterns")
    patterns = gore_window.patterns
    patterns.regenerate()
    letter = patterns.selected_letter()
    assert letter is not None
    text = patterns.roll_label.text()
    # The fixture's rows are taller and wider than a 60 in roll.
    assert text.startswith("LARGER THAN THE 1524 mm ROLL")
    gore_window.apply_preferences(replace(gore_window.prefs, print_roll_width=3.7))
    patterns.refresh()
    assert "mm across the 3700 mm roll" in patterns.roll_label.text()
    assert "turned 90°" in patterns.roll_label.text()
    patterns.layout_mode.setCurrentIndex(patterns.layout_mode.findData("roll"))
    patterns._layout_changed(0)
    texts = [i.text() for i in patterns.view.scene().items() if hasattr(i, "text")]
    assert any(t.startswith("Print roll 3700 mm wide") for t in texts)
    assert sum(t.startswith("row ") and "mm across" in t for t in texts) == len(
        patterns.rows_by_letter()
    )
    # Every page lies within the roll's width.
    rect = patterns.view.content_rect
    assert rect.left() >= -1e-6
    # The pieces themselves are drawn on their pages, turned, inside the roll's edges.
    pieces = [
        i
        for i in patterns.view.scene().items()
        # The piece containers (turned); parentItem() is not called: in PySide 6.11 a
        # temporary wrapper it was called on deletes its item when dropped.
        if isinstance(i, QGraphicsRectItem) and i.rotation() != 0.0
    ]
    assert len(pieces) == len(patterns.rows_by_letter())
    for piece in pieces:
        for cut in piece.childItems():
            if isinstance(cut, QGraphicsPolygonItem):
                drawn = cut.sceneBoundingRect()
                assert drawn.left() > -0.01 and drawn.right() < 3.7 + 0.01


def test_resize_a_mesh_shape_in_proportion_or_one_way(
    gore_window: MainWindow, tmp_path: Path
) -> None:
    from envelopelab.project.shapes import MeshShape, mesh_size
    from envelopelab_app.panels.shapes import ResizeMeshDialog

    gore_window.show_panel("shapes")
    mesh = ellipsoid_mesh(0.25, 0.2, 0.3, -0.05, rings=10, segments=16)
    path = write_obj_scene(
        tmp_path / "antenna.obj", [MeshObject("antenna", mesh.vertices, mesh.triangles)]
    )
    panel = gore_window.shapes
    assert panel.import_mesh(path) == "antenna"
    _placed(gore_window)
    spec = panel.spec()
    assert isinstance(spec, MeshShape)
    size = mesh_size(spec)
    label = panel.findChild(QLabel, "shapeMeshSizeLabel")
    assert label is not None and f"{size[2]:.3f} high" in label.text()

    # Keep proportions: a new height scales the other two sizes alike.
    dialog = ResizeMeshDialog(panel, size)
    dialog.boxes[2].setValue(size[2] * 1.5)
    assert dialog.boxes[0].value() == pytest.approx(size[0] * 1.5, abs=1e-3)
    assert dialog.factors() == pytest.approx((1.5, 1.5, 1.5), rel=1e-2)
    # Without: only the height changes.
    dialog = ResizeMeshDialog(panel, size)
    dialog.keep.setChecked(False)
    dialog.boxes[2].setValue(size[2] * 2.0)
    assert dialog.factors() == pytest.approx((1.0, 1.0, 2.0), rel=1e-2)

    assert panel.resize_mesh(*dialog.factors())
    _placed(gore_window)
    resized = panel.spec()
    assert isinstance(resized, MeshShape)
    assert mesh_size(resized)[2] == pytest.approx(2.0 * size[2], rel=1e-2)
    assert f"{mesh_size(resized)[2]:.3f} high" in label.text()
    assert panel.placed("antenna") is not None, panel.status.text()
    gore_window.undo()
    _placed(gore_window)
    back = panel.spec()
    assert isinstance(back, MeshShape) and mesh_size(back) == pytest.approx(size)


def _mouse(view: Any, kind: Any, at: Any, modifiers: Any = None) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    button = Qt.MouseButton.LeftButton
    event = QMouseEvent(
        kind,
        QPointF(at),
        QPointF(at),
        button,
        Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else button,
        modifiers or Qt.KeyboardModifier.NoModifier,
    )
    {
        QMouseEvent.Type.MouseButtonPress: view.mousePressEvent,
        QMouseEvent.Type.MouseMove: view.mouseMoveEvent,
        QMouseEvent.Type.MouseButtonRelease: view.mouseReleaseEvent,
        QMouseEvent.Type.MouseButtonDblClick: view.mouseDoubleClickEvent,
    }[kind](event)


def _at(view: Any, rho: float, zeta: float) -> Any:
    from PySide6.QtCore import QPointF

    return QPointF(view.mapFromScene(QPointF(rho, -zeta)))


def _drag(view: Any, start: Any, end: Any) -> None:
    from PySide6.QtGui import QMouseEvent

    _mouse(view, QMouseEvent.Type.MouseButtonPress, start)
    _mouse(view, QMouseEvent.Type.MouseMove, end)
    _mouse(view, QMouseEvent.Type.MouseButtonRelease, end)


def test_profile_is_edited_by_dragging_points_and_splits(gore_window: MainWindow) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QKeyEvent, QMouseEvent

    from envelopelab.project.shapes import RevolvedShape

    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("revolved")
    _placed(gore_window)
    panel.editor_tabs.setCurrentIndex(1)
    view = panel.profile_view
    view.resize(400, 400)
    view.set_shape(view.profile, view.smooth, view.curve, np.asarray(view.splits))

    def spec() -> RevolvedShape:
        s = panel.spec()
        assert isinstance(s, RevolvedShape)
        return s

    start = spec().profile
    assert view.profile == [tuple(p) for p in start] and len(view.curve) > 10

    # Drag the second point up by about 0.1 m: one edit, the curve follows.
    k = 1
    r, z = start[k]
    _drag(view, _at(view, r, z), _at(view, r, z + 0.1))
    _placed(gore_window)
    moved = spec().profile
    assert moved[k][1] == pytest.approx(z + 0.1, abs=0.02)
    assert moved[0] == start[0] and view.profile[k] == pytest.approx(moved[k])
    gore_window.undo()
    _placed(gore_window)
    assert spec().profile == start

    # Scale the whole shape (no selection) about its base.
    view.select([])
    assert panel.scale_profile(1.5, 1.5)
    _placed(gore_window)
    assert np.asarray(spec().profile) == pytest.approx(1.5 * np.asarray(start))
    assert "placed" in panel.status.text(), panel.status.text()
    gore_window.undo()
    _placed(gore_window)

    # Double-click the outline: a point is added there; Delete removes it again.
    n = len(start)
    mid = view.curve[len(view.curve) // 3]
    _mouse(view, QMouseEvent.Type.MouseButtonDblClick, _at(view, *mid))
    _placed(gore_window)
    assert len(spec().profile) == n + 1 and len(view.selected) == 1
    view.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    )
    _placed(gore_window)
    assert len(spec().profile) == n

    # A split drawn on the outline is dragged along it.
    assert panel.set_value(("splits",), [0.5])
    _placed(gore_window)
    assert len(view.splits) == 1
    sr, sz = view.splits[0]
    target = view.curve[int(0.75 * len(view.curve))]
    _drag(view, _at(view, sr, sz), _at(view, *target))
    _placed(gore_window)
    assert spec().splits[0] > 0.6
    assert view.split_at(QPointF(-1000.0, -1000.0)) is None


def test_convert_a_round_mesh_to_a_revolved_profile(
    gore_window: MainWindow, tmp_path: Path
) -> None:
    from envelopelab.project.shapes import MeshShape, RevolvedShape
    from envelopelab.validation.primitives import revolved_mesh

    antenna = [(0.18, 0.0), (0.12, 0.48), (0.12, 0.62), (0.22, 0.74), (0.24, 0.86), (0.0, 1.08)]
    mesh = revolved_mesh(antenna, sink=0.02)
    path = write_obj_scene(
        tmp_path / "antenna.obj", [MeshObject("antenna", mesh.vertices, mesh.triangles)]
    )
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    assert panel.import_mesh(path) == "antenna"
    _placed(gore_window)
    before = panel.spec()
    assert isinstance(before, MeshShape)

    fit = panel.fit_mesh(16)
    assert fit is not None and fit.round
    summary = panel.fit_summary(fit)
    assert "Largest deviation" in summary and "WARNING" not in summary
    assert panel.convert_mesh(fit)
    _placed(gore_window)
    spec = panel.spec()
    assert isinstance(spec, RevolvedShape) and spec.name == "antenna"
    assert panel.editor_tabs.isTabVisible(1) and panel.editor_tabs.currentIndex() == 1
    assert len(panel.profile_view.profile) == 16
    assert panel.placed("antenna") is not None, panel.status.text()
    # Now the stalk and the ball can be cut as two tiers.
    assert panel.set_value(("splits",), [0.5])
    _placed(gore_window)
    assert len(panel.profile_view.splits) == 1
    gore_window.undo()
    gore_window.undo()
    _placed(gore_window)
    assert panel.spec() == before


def test_a_mesh_that_is_not_round_is_warned_before_converting(
    gore_window: MainWindow, tmp_path: Path
) -> None:
    ear = ellipsoid_mesh(0.3, 0.1, 0.25, -0.05, rings=16, segments=32)
    path = write_obj_scene(tmp_path / "ear.obj", [MeshObject("ear", ear.vertices, ear.triangles)])
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    assert panel.import_mesh(path) == "ear"
    _placed(gore_window)
    fit = panel.fit_mesh()
    assert fit is not None and not fit.round
    assert "WARNING: this mesh is not round" in panel.fit_summary(fit)
