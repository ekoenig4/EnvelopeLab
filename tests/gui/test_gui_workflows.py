"""Headless GUI workflow tests (pytest-qt, offscreen Qt platform)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from envelopelab.project.dependencies import invalidated_by
from envelopelab.project.gore_design import editable_outline
from envelopelab.project.model import RunRecord, utc_now
from envelopelab.project.recovery import find_recoverable
from envelopelab.project.session import ProjectSession
from envelopelab.project.simulation import build_solver_model
from envelopelab_app.main_window import MainWindow, dock_titles
from envelopelab_app.settings import load_preferences, recent_projects
from envelopelab_app.simulation import CALCULIX
from envelopelab_app.wizard import NewDesignWizard

from .gui_support import FIXTURES, GORE_PROJECT, make_window

REQUIRED_PANELS = {
    "Design Tree",
    "Properties",
    "Validation / Warnings",
    "Simulation Runs",
    "Materials",
    "3D View",
    "2D Pattern View",
}


def fake_run(session: ProjectSession) -> tuple[RunRecord, dict[str, np.ndarray]]:
    """Bookkeeping-only run record of the current state (no solve)."""
    record = RunRecord(
        run_id="test-preview",
        created=utc_now(),
        solver="envelopelab-preview",
        solver_version="test",
        status="converged",
        converged=True,
        residual=5e-7,
        residual_measure="test",
        iterations=100,
        run_time=1.0,
        n_nodes=3,
        n_elements=1,
        n_tape_elements=0,
        mesh_target_mm=1600.0,
        load_case="test",
        material_sources=["assumed"],
        design_content_hash=session.content_hash(),
        input_fingerprint=session.fingerprints()["simulation"],
        volume=1.0,
        lift=1.0,
        height=1.0,
        max_width=1.0,
    )
    arrays = {
        "positions": np.eye(3),
        "triangles": np.array([[0, 1, 2]]),
    }
    return record, arrays


def table_column(window: MainWindow, column: int) -> list[str]:
    table = window.runs.table
    return [table.item(i, column).text() for i in range(table.rowCount())]  # type: ignore[union-attr]


def test_window_starts_with_every_panel(window: MainWindow) -> None:
    titles = {d.base_title for d in window.docks.values()}
    assert REQUIRED_PANELS <= titles
    menus = [a.text() for a in window.menuBar().actions()]
    assert menus == ["&File", "&Edit", "&Design", "&Simulation", "&View"]
    assert not window.save_action.isEnabled() and not window.undo_action.isEnabled()
    assert not window.preview_action.isEnabled()


def test_create_edit_undo_redo_save_reopen(
    qtbot: QtBot, window: MainWindow, settings: QSettings, tmp_path: Path
) -> None:
    wizard = NewDesignWizard(window.controller.fabrics, window)
    qtbot.addWidget(wizard)
    wizard.name.setText("smoke balloon")
    wizard.volume.setValue(170.0)
    wizard.target_height.setValue(8.2)
    wizard.target_width.setValue(6.4)
    wizard.gores.setValue(8)
    wizard.rows.setValue(4)
    wizard.create_design()
    assert wizard.design is not None, wizard.error.text()
    session = window.new_project(wizard.design)
    window.controller.regenerate_patterns()
    created = session.content_hash()
    volume_before = window.gore_editor.outputs["volume"].text()

    # Exact numeric entry of a profile point in the table (one undoable command).
    item = window.gore_editor.points_table.item(2, 0)
    assert item is not None
    item.setText(f"{float(item.text()) + 0.25:.4f}")
    edited = session.content_hash()
    assert edited != created
    assert session.stack.history() == ["Move control point 3"]
    assert window.gore_editor.outputs["volume"].text() != volume_before  # live outputs
    assert "●" in window.docks["tree"].windowTitle()  # dirty indicator
    # A drag on the profile canvas ends in the same command type.
    window.gore_editor.canvas.pointMoved.emit(1, 2.0, 2.2)
    assert session.stack.history()[-1] == "Move control point 2"
    window.undo_action.trigger()
    assert session.content_hash() == edited
    window.undo_action.trigger()
    assert session.content_hash() == created
    window.redo_action.trigger()
    assert session.content_hash() == edited
    assert window.redo_action.isEnabled()

    path = tmp_path / "smoke.elproj"
    assert window.save_to(path)
    assert not session.is_dirty and "●" not in window.docks["tree"].windowTitle()
    assert recent_projects(settings)[0] == path.resolve()

    other = make_window(qtbot, settings)
    reopened = other.open_project(path)
    assert reopened is not None
    assert reopened.content_hash() == edited == session.content_hash()


def test_seam_allowance_marks_patterns_stale_but_not_the_rest_mesh(
    gore_window: MainWindow, tmp_path: Path
) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    w.patterns.regenerate()
    built = build_solver_model(session.design, session.patterns, tmp_path, 1600.0)
    w.controller.store_model(built, session.fingerprints())
    assert w.controller.artifact_status("rest_mesh") == "current"

    w.patterns.default_allowance.setValue(30.0)  # mm
    w.patterns.default_allowance.editingFinished.emit()
    assert session.design.seam_types[0].allowance == pytest.approx(0.030)

    status = w.controller.artifact_statuses()
    assert status["patterns"] == "stale"
    assert status["rest_mesh"] == "current" and status["assembly"] == "current"
    assert invalidated_by({"seam_allowance"}) == {"patterns", "nesting", "export"}
    assert "STALE" in w.patterns.banner.text()
    titles = dock_titles(w)
    assert "[STALE]" in titles["patterns"] and "[STALE]" not in titles["view3d"]
    messages = " ".join(w.validation.messages())
    assert "patterns is stale" in messages and "rest mesh is stale" not in messages
    assert "STALE" not in w.view3d.labels()["rest"]
    w.undo_action.trigger()
    assert w.controller.artifact_status("patterns") == "current"


def test_internal_temperature_marks_simulation_results_stale(gore_window: MainWindow) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    record, arrays = fake_run(session)
    session.add_run(record, arrays)
    assert table_column(w, 1) == ["CURRENT"]
    assert "[STALE]" not in dock_titles(w)["runs"]

    w.controller.select("operating")
    w.properties.set_field(("operating", "internal_temperature"), "383.15")
    assert session.design.operating.internal_temperature == pytest.approx(383.15)
    assert table_column(w, 1) == ["STALE"]
    assert "[STALE]" in dock_titles(w)["runs"]
    assert "[STALE]" in w.view3d.labels()["envelopelab-preview"]
    assert any("STALE" in m for m in w.validation.messages())
    w.undo_action.trigger()
    assert table_column(w, 1) == ["CURRENT"]


def test_run_calculix_is_disabled_without_ccx(gore_window: MainWindow, tmp_path: Path) -> None:
    w = gore_window
    prefs = load_preferences(w.settings)
    prefs.ccx_path = str(tmp_path / "no-such-ccx")
    w.apply_preferences(prefs)
    assert not w.simulation.calculix_available
    assert not w.calculix_action.isEnabled()
    assert not w.runs.run_calculix.isEnabled()
    assert w.preview_action.isEnabled() and w.runs.run_preview.isEnabled()
    assert "not installed" in w.ccx_label.text()
    assert w.runs.calculix_label.isVisible()
    message = w.runs.calculix_label.text()
    assert "not installed" in message and "calculix-installation.md" in message
    assert "not installed" in w.runs.run_calculix.toolTip()
    assert w.simulation.start(CALCULIX) is False


def test_manual_outline_override_is_flagged(gore_window: MainWindow) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    w.patterns.regenerate()
    w.controller.select("row:B")
    w.patterns.edit_outline.setChecked(True)
    handles = w.patterns.view.handles
    assert len(handles) == 18
    handle = handles[4]
    handle.setPos(handle.pos().x() + 0.06, handle.pos().y())
    w.patterns.view.commit_outline()
    assert session.patterns.row("B").manual_outline is not None
    assert session.project.provenance[-1].action == "manual outline override"
    messages = " ".join(w.validation.messages())
    assert "MANUAL OVERRIDE" in messages
    assert "vertical seam sides differ" in messages
    assert w.controller.artifact_status("patterns") == "stale"
    tree = w.design_tree.tree
    rows = [tree.topLevelItem(0)]
    texts = []
    while rows:
        item = rows.pop()
        if item is None:
            continue
        texts.append(item.text(0))
        rows += [item.child(i) for i in range(item.childCount())]
    assert "Row B (manual override)" in texts
    w.patterns.clear_override.click()
    assert session.patterns.row("B").manual_outline is None


def test_pattern_rows_stack_vertically_as_sewn(
    gore_window: MainWindow, settings: QSettings
) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    w.patterns.regenerate()
    rows = list(w.patterns.rows_by_letter().values())
    assert w.patterns.stack_rows.isChecked()  # default: stacked, mouth at the bottom
    offsets = w.patterns.view.offsets
    for lower, upper in zip(rows, rows[1:], strict=False):
        assert offsets[lower.label][0] == offsets[upper.label][0] == 0.0
        top = offsets[lower.label][1] + lower.cut_outline[:, 1].max()
        bottom = offsets[upper.label][1] + upper.cut_outline[:, 1].min()
        assert bottom - top == pytest.approx(0.4)  # GAP, m: cut outlines never overlap
    # Outline edits map back through the vertical offset: unmoved handles commit the
    # row's own outline, not one shifted by the layout.
    w.controller.select(f"row:{rows[-1].label}")
    w.patterns.edit_outline.setChecked(True)
    w.patterns.view.commit_outline()
    manual = session.patterns.row(rows[-1].label).manual_outline
    assert manual is not None
    expected = w.patterns.rows_by_letter()[rows[-1].label]
    assert np.allclose(manual.points, editable_outline(expected), atol=1e-9)
    w.patterns.edit_outline.setChecked(False)
    w.patterns.stack_rows.setChecked(False)  # side by side, stored in the settings
    offsets = w.patterns.view.offsets
    xs = [offsets[r.label][0] for r in rows]
    assert all(offsets[r.label][1] == 0.0 for r in rows) and xs == sorted(xs)
    assert load_preferences(settings).stack_pattern_rows is False


def test_parachute_is_added_edited_drawn_and_removed(gore_window: MainWindow) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    assert w.add_parachute_action.isEnabled() and not w.remove_parachute_action.isEnabled()
    before = w.controller.outputs
    assert before is not None and before.envelope_mass is not None
    w.add_parachute_action.trigger()
    chute = session.design.gores.parachute  # type: ignore[union-attr]
    assert chute is not None and chute.gore_count == 8
    assert not w.add_parachute_action.isEnabled() and w.remove_parachute_action.isEnabled()
    after = w.controller.outputs
    assert after is not None and after.parachute is not None and after.envelope_mass is not None
    assert after.envelope_mass == pytest.approx(before.envelope_mass + after.parachute.total_mass)
    assert "kg" in w.gore_editor.outputs["parachute"].text()
    tree = w.design_tree.tree
    items = [tree.topLevelItem(0)]
    texts = []
    while items:
        item = items.pop()
        if item is not None:
            texts.append(item.text(0))
            items += [item.child(i) for i in range(item.childCount())]
    assert any(t.startswith("Parachute (8 gores") for t in texts)
    # The parachute is drawn after the crown row, above it when stacked.
    w.patterns.regenerate()
    offsets = w.patterns.view.parachute_offsets
    rows = list(w.patterns.rows_by_letter().values())
    top_row = rows[-1]
    crown_top = w.patterns.view.offsets[top_row.label][1] + top_row.cut_outline[:, 1].max()
    cache = w.controller.patterns_cache
    assert cache is not None and cache.parachute is not None
    gore_bottom = offsets["gore"][1] + cache.parachute.gore_cut[:, 1].min()
    assert gore_bottom == pytest.approx(crown_top + 0.4)
    assert offsets["centre"][1] > offsets["gore"][1]
    # Properties edits the parachute fields; a parachute edit leaves simulations current.
    w.controller.select("parachute")
    w.properties.set_field(("gores", "parachute", "diameter"), str(chute.diameter + 0.1))
    assert session.design.gores.parachute.diameter == pytest.approx(chute.diameter + 0.1)  # type: ignore[union-attr]
    assert w.controller.artifact_status("patterns") == "stale"
    assert w.controller.artifact_status("simulation") != "stale"
    messages = " ".join(w.validation.messages())
    assert "overlaps the hole by" in messages  # no longer the design seal overlap
    w.remove_parachute_action.trigger()
    assert session.design.gores.parachute is None  # type: ignore[union-attr]
    assert "none" in w.gore_editor.outputs["parachute"].text()


def test_pattern_annotations_are_undoable_edits(gore_window: MainWindow) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    w.patterns.regenerate()
    w.controller.select("row:C")
    p = w.patterns
    p.label_text.setText("PANEL C x8 (orange)")
    p.label_text.editingFinished.emit()
    p.grain.setValue(90.0)
    p.grain.editingFinished.emit()
    p.notch_edge.setCurrentText("right")
    p.notch_pos.setValue(0.25)
    p._add_notch()
    p.tape_y.setValue(0.5)
    p._add_tape()
    row = session.patterns.row("C")
    assert row.label_text == "PANEL C x8 (orange)" and row.grain_angle_deg == 90.0
    assert row.notches[0].edge == "right" and row.notches[0].position == 0.25
    assert len(row.tape_paths) == 1
    assert len(session.stack.history()) == 4
    session.stack.go_to(0)
    assert session.patterns.row("C") == type(row)()


def test_autosave_and_crash_recovery(
    qtbot: QtBot, gore_window: MainWindow, settings: QSettings
) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    session.set_design_value(("operating", "payload_mass"), 150.0)
    autosave = w.autosave()
    assert autosave is not None and autosave.is_file()
    edited = session.content_hash()
    # A second window (the next start after a crash) finds and recovers the work.
    other = make_window(qtbot, settings)
    items = find_recoverable(other.prefs.resolved_recovery_dir(), exclude=other.autosave_path())
    assert [i.autosave_path for i in items] == [autosave]
    recovered = other.recover(autosave)
    assert recovered is not None and recovered.content_hash() == edited
    assert recovered.is_dirty and recovered.path == GORE_PROJECT
    assert not autosave.exists()


def test_snapshots_versions_and_history_jumps(gore_window: MainWindow) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    original = session.content_hash()
    session.create_snapshot("baseline")
    session.set_design_value(("operating", "payload_mass"), 200.0)
    session.set_design_value(("operating", "payload_mass"), 250.0)
    assert w.history.snapshots.count() == 1
    assert w.history.history.count() == 3
    first = w.history.history.item(0)
    assert first is not None
    w.history._jump(first)
    assert session.content_hash() == original
    version = session.commit_version("first flight")
    entry = w.history.versions.item(0)
    assert w.history.versions.count() == 1 and entry is not None
    assert version.version_id in entry.text()


def test_special_shape_wizard_and_measurements_stub(qtbot: QtBot, window: MainWindow) -> None:
    wizard = NewDesignWizard(window.controller.fabrics, window)
    qtbot.addWidget(wizard)
    wizard.tabs.setCurrentIndex(2)
    assert not wizard.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    wizard.tabs.setCurrentIndex(1)
    wizard.mesh_path.setText(str(FIXTURES / "alien" / "reference" / "alien-reference.obj"))
    wizard.create_design()
    assert wizard.design is not None and wizard.design.envelope_type == "special"
    window.new_project(wizard.design)
    assert not window.gore_editor.isEnabled()
    assert not window.preview_action.isEnabled()
    assert any("no panels" in m for m in window.validation.messages())
    wizard.mesh_path.setText(str(FIXTURES / "missing.obj"))
    wizard.design = None
    wizard.create_design()
    assert wizard.design is None and wizard.error.text()


def test_refused_edit_is_reported(gore_window: MainWindow) -> None:
    w = gore_window
    w.gore_editor.locks["gore_count"].setChecked(True)
    w.gore_editor.gore_count.setValue(12)
    w.gore_editor.gore_count.editingFinished.emit()
    assert w.controller.design is not None and w.controller.design.gores is not None
    assert w.controller.design.gores.count == 8
    assert "locked" in w.task_label.text()


@pytest.mark.slow
def test_preview_and_calculix_runs_show_distinct_solver_labels(
    qtbot: QtBot, gore_window: MainWindow, ccx: object
) -> None:
    """Run both solvers from the GUI on the generic gore fixture (1600 mm mesh)."""
    w = gore_window
    session = w.controller.session
    assert session is not None
    failures: list[str] = []
    w.simulation.failed.connect(failures.append)

    def run(button: object, count: int, timeout: int) -> None:
        button.click()  # type: ignore[attr-defined]
        # A failed run ends the wait at once (and the test), instead of timing out.
        qtbot.waitUntil(
            lambda: len(session.project.runs) == count or bool(failures), timeout=timeout
        )
        assert not failures, failures
        qtbot.waitUntil(lambda: not w.simulation.running, timeout=60_000)

    run(w.runs.run_preview, 1, 600_000)
    assert w.runs.run_calculix.isEnabled()
    run(w.runs.run_calculix, 2, 1_800_000)

    solvers = table_column(w, 0)
    assert sorted(solvers) == ["CalculiX verification", "Preview (dynamic relaxation)"]
    preview, calculix = sorted(
        session.project.runs, key=lambda r: r.solver != "envelopelab-preview"
    )
    assert preview.solver == "envelopelab-preview" and calculix.solver == "calculix"
    assert preview.converged and preview.residual < 1e-6
    for record in (preview, calculix):
        assert record.run_time > 0 and record.iterations > 0 and np.isfinite(record.residual)
        assert (
            record.n_nodes == preview.n_nodes
            and record.design_content_hash == session.content_hash()
        )
    # Convergence is displayed as reported, never assumed.
    states = dict(zip(solvers, table_column(w, 1), strict=True))
    assert ("NOT CONVERGED" in states["CalculiX verification"]) == (not calculix.converged)
    labels = w.view3d.labels()
    assert labels["envelopelab-preview"].startswith("Preview (dynamic relaxation) result")
    assert labels["calculix"].startswith("CalculiX verification result")
    assert w.view3d.layers["envelopelab-preview"].color != w.view3d.layers["calculix"].color
    assert "rest" in labels and w.controller.artifact_status("rest_mesh") == "current"

    w.controller.select("operating")
    w.properties.set_field(("operating", "internal_temperature"), "383.15")
    assert table_column(w, 1)[0].startswith("STALE") and table_column(w, 1)[1].startswith("STALE")
    assert all(
        "[STALE]" in labels
        for key, labels in w.view3d.labels().items()
        if key in ("envelopelab-preview", "calculix")
    )


def test_layer_list_without_renderer_names_every_source(gore_window: MainWindow) -> None:
    labels = gore_window.view3d.labels()
    assert labels == {"design": "Design surface (profile, current)"}
    item = gore_window.view3d.layer_list.item(0)
    assert item is not None and item.checkState() == Qt.CheckState.Checked
