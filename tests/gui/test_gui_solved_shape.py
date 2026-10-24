"""Gore editor: solved tape lines drawn over the profile, compensation and adoption."""

from __future__ import annotations

import math

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from envelopelab.project.gore_design import control_arrays, design_profile
from envelopelab.project.model import RunRecord, utc_now
from envelopelab.project.session import ProjectSession
from envelopelab_app.main_window import MainWindow


def stretched_run(session: ProjectSession, solver: str, converged: bool = True) -> None:
    """Add a run of the current state whose solved shape is the drawn profile revolved
    and stretched 2 % radially and 1 % vertically (structured mesh, seams at 2 pi k / G)."""
    design = session.design
    assert design.gores is not None
    profile = design_profile(design)
    rows, columns = 40, 4 * design.gores.count
    s = np.linspace(0.0, profile.meridian_length, rows)
    r = np.interp(s, profile.s, profile.r)
    z = np.interp(s, profile.s, profile.z)
    theta = 2.0 * math.pi * np.arange(columns) / columns
    x0 = np.column_stack(
        (
            (r[:, None] * np.cos(theta)[None]).ravel(),
            (r[:, None] * np.sin(theta)[None]).ravel(),
            np.repeat(z, columns),
        )
    )
    tris = []
    for i in range(rows - 1):
        for j in range(columns):
            a, b = i * columns + j, i * columns + (j + 1) % columns
            tris += [(a, b, b + columns), (a, b + columns, a + columns)]
    x = x0 * np.array([1.02, 1.02, 1.01])
    record = RunRecord(
        run_id=f"{solver}-{len(session.project.runs)}",
        created=utc_now(),
        solver=solver,  # type: ignore[arg-type]
        solver_version="test",
        status="converged" if converged else "max_iterations",
        converged=converged,
        residual=1e-7,
        residual_measure="test",
        iterations=1,
        run_time=0.0,
        n_nodes=len(x),
        n_elements=len(tris),
        n_tape_elements=0,
        mesh_target_mm=100.0,
        load_case="test",
        material_sources=["assumed"],
        design_content_hash=session.content_hash(),
        input_fingerprint=session.fingerprints()["simulation"],
        volume=1.0,
        lift=1.0,
        height=1.0,
        max_width=1.0,
    )
    arrays = {"positions": x, "initial_positions": x0, "triangles": np.asarray(tris)}
    session.add_run(record, arrays)


def test_ghosts_show_each_solver_and_flag_unconverged_runs(gore_window: MainWindow) -> None:
    editor = gore_window.gore_editor
    panel = editor.solved_shape
    session = gore_window.controller.session
    assert session is not None
    assert editor.canvas.ghosts == {}
    assert "No CalculiX run" in panel.status["calculix"].text()
    assert not panel.compensate.isEnabled()
    stretched_run(session, "envelopelab-preview")
    stretched_run(session, "calculix", converged=False)
    assert set(editor.canvas.ghosts) == {"envelopelab-preview", "calculix"}
    assert "max diameter +" in panel.status["envelopelab-preview"].text()
    assert "NOT CONVERGED" in panel.status["calculix"].text()
    # CalculiX is the default source: its run is not converged, so no update is offered.
    assert not panel.compensate.isEnabled() and not panel.adopt.isEnabled()
    assert "not converged" in panel.update_status.text()
    panel.source.setCurrentIndex(panel.source.findData("envelopelab-preview"))
    panel.refresh()
    assert panel.compensate.isEnabled() and panel.adopt.isEnabled()
    panel.show_ghost["calculix"].setChecked(False)
    assert set(editor.canvas.ghosts) == {"envelopelab-preview"}
    # Magnifying the deviation moves the drawn line further out, never the numbers.
    text = panel.status["envelopelab-preview"].text()
    width = editor.canvas.ghosts["envelopelab-preview"][0].path().boundingRect().width()
    panel.magnify.setValue(10)
    wider = editor.canvas.ghosts["envelopelab-preview"][0].path().boundingRect().width()
    assert wider > width * 1.1
    assert panel.status["envelopelab-preview"].text() == text


def test_compensate_then_restore_from_the_editor(gore_window: MainWindow) -> None:
    editor = gore_window.gore_editor
    panel = editor.solved_shape
    session = gore_window.controller.session
    assert session is not None
    before = np.column_stack(control_arrays(session.design))
    stretched_run(session, "calculix")
    assert panel.compensate.isEnabled()
    panel.compensate.click()
    assert session.project.profile_target is not None
    assert "target" in editor.canvas.ghosts
    assert "Compensated" in panel.update_status.text()
    after = np.column_stack(control_arrays(session.design))
    assert float(after[:, 0].max()) < float(before[:, 0].max())
    # The run is stale now: the ghost stays, flagged, and no further step is offered.
    assert "Stale" in panel.status["calculix"].text()
    assert not panel.compensate.isEnabled()
    assert panel.restore.isEnabled()
    panel.restore.click()
    assert session.project.profile_target is None
    assert np.allclose(np.column_stack(control_arrays(session.design)), before)
    assert "target" not in editor.canvas.ghosts


def test_adopt_from_the_editor_is_one_undo(gore_window: MainWindow) -> None:
    panel = gore_window.gore_editor.solved_shape
    session = gore_window.controller.session
    assert session is not None
    before = np.column_stack(control_arrays(session.design))
    stretched_run(session, "calculix")
    panel.adopt.click()
    after = np.column_stack(control_arrays(session.design))
    assert float(after[:, 0].max()) > float(before[:, 0].max())
    assert session.undo()
    assert np.allclose(np.column_stack(control_arrays(session.design)), before)


def test_the_shape_check_marks_compression_and_the_snap_removes_it(
    gore_window: MainWindow,
) -> None:
    editor = gore_window.gore_editor
    panel = editor.shape_physics
    session = gore_window.controller.session
    assert session is not None
    assert "needs compression" in panel.status.text()
    assert not editor.canvas.compression.path().isEmpty()
    assert panel.snap.isEnabled()
    # The natural shape and the solved runs are drawn side by side.
    stretched_run(session, "calculix")
    panel.natural_on.setChecked(True)
    assert {"natural", "calculix"} <= set(editor.canvas.ghosts)
    panel.check_on.setChecked(False)
    assert editor.canvas.compression.path().isEmpty()
    panel.check_on.setChecked(True)
    before = np.column_stack(control_arrays(session.design))
    panel.snap.click()
    assert "Snapped" in panel.result.text()
    assert "The shape holds" in panel.status.text()
    assert editor.canvas.compression.path().isEmpty()
    assert not panel.snap.isEnabled()
    assert session.undo()
    assert np.allclose(np.column_stack(control_arrays(session.design)), before)
    assert "needs compression" in panel.status.text()


def test_dragging_a_point_rechecks_the_shape_live(gore_window: MainWindow) -> None:
    canvas = gore_window.gore_editor.canvas
    assert canvas.stress_load is not None
    drawn = canvas.compression.path().length()
    handle = canvas.handles[1]
    # Pull the low point outward: more curvature low down, more compression.
    handle.setPos(handle.pos().x() + 0.4, handle.pos().y())
    canvas.preview()  # what a drag calls on every move
    assert canvas.compression.path().length() != drawn


def test_fit_adopts_the_latest_usable_run_in_one_click(gore_window: MainWindow) -> None:
    panel = gore_window.gore_editor.solved_shape
    session = gore_window.controller.session
    assert session is not None
    before = np.column_stack(control_arrays(session.design))
    # CalculiX is the chosen source, but its run is not converged: the preview is used.
    stretched_run(session, "envelopelab-preview")
    stretched_run(session, "calculix", converged=False)
    assert panel.fit.isEnabled()
    panel.flight.setChecked(False)  # adopt the inflated tape line as it is
    panel.fit.click()
    assert "Fitted to the Preview run" in panel.update_status.text()
    after = np.column_stack(control_arrays(session.design))
    assert float(after[:, 0].max()) == pytest.approx(1.02 * float(before[:, 0].max()), rel=5e-3)
    assert not gore_window.simulation.running  # no run was needed
    assert session.undo()
    assert np.allclose(np.column_stack(control_arrays(session.design)), before)


def test_fit_on_a_segment_profile_makes_it_a_spline(gore_window: MainWindow) -> None:
    panel = gore_window.gore_editor.solved_shape
    controller = gore_window.controller
    session = controller.session
    assert session is not None
    controller.edit("set_profile_interpolation", "segments")
    stretched_run(session, "calculix")
    panel.refresh()
    assert not panel.compensate.isEnabled()
    assert panel.adopt.isEnabled() and panel.fit.isEnabled()
    assert "make the profile a spline" in panel.update_status.text()
    panel.fit.click()
    assert session.design.gores is not None
    assert session.design.gores.profile_interpolation == "spline"
    assert "Fitted to the CalculiX run" in panel.update_status.text()


@pytest.mark.slow
def test_fit_without_a_run_solves_the_preview_first(gore_window: MainWindow, qtbot: QtBot) -> None:
    panel = gore_window.gore_editor.solved_shape
    session = gore_window.controller.session
    assert session is not None
    before = np.column_stack(control_arrays(session.design))
    assert panel.fit.isEnabled()
    panel.fit.click()
    assert panel.fit_pending and gore_window.simulation.running
    assert not panel.fit.isEnabled()
    assert "Running the preview" in panel.update_status.text()
    assert gore_window.simulation.wait(600_000)
    qtbot.waitUntil(lambda: not panel.fit_pending, timeout=10_000)
    run = session.project.runs[-1]
    assert run.solver == "envelopelab-preview" and run.converged
    assert "Fitted to the Preview run" in panel.update_status.text()
    after = np.column_stack(control_arrays(session.design))
    assert after.shape != before.shape or not np.allclose(after, before)
    # The run solved the drawn profile, which has changed: it is stale now.
    assert session.run_status(run) == "stale"


def test_an_unconverged_preview_does_not_change_the_profile(gore_window: MainWindow) -> None:
    panel = gore_window.gore_editor.solved_shape
    session = gore_window.controller.session
    assert session is not None
    before = np.column_stack(control_arrays(session.design))
    panel.fit_pending = True  # as after a click that started the preview
    stretched_run(session, "envelopelab-preview", converged=False)
    panel._run_finished(session.project.runs[-1])
    assert not panel.fit_pending
    assert "NOT CONVERGED" in panel.update_status.text()
    assert np.allclose(np.column_stack(control_arrays(session.design)), before)


def test_refreshes_reuse_the_runs_solved_lines(
    gore_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    import envelopelab_app.gore_editor as ge
    from envelopelab.project.profile_match import RunShape, latest_run_shape

    panel = gore_window.gore_editor.solved_shape
    session = gore_window.controller.session
    assert session is not None
    stretched_run(session, "envelopelab-preview")
    calls: list[str] = []

    def counted(s: ProjectSession, solver: str) -> RunShape | None:
        calls.append(solver)
        return latest_run_shape(s, solver)

    monkeypatch.setattr(ge, "latest_run_shape", counted)
    panel.refresh()
    panel.refresh()
    # Runs starting and ending only re-check Fit.
    gore_window.simulation.started.emit("envelopelab-preview")
    gore_window.simulation.idle.emit()
    assert calls == []  # the shapes were read when the run was added
    stretched_run(session, "calculix")
    assert calls == ["calculix"]


def test_fit_cuts_the_flight_shape_by_default(gore_window: MainWindow) -> None:
    panel = gore_window.gore_editor.solved_shape
    session = gore_window.controller.session
    assert session is not None
    before = design_profile(session.design)
    stretched_run(session, "envelopelab-preview")
    assert panel.flight.isChecked()
    panel.fit.click()
    assert "flight shape" in panel.update_status.text()
    assert "stretch taken out" in panel.update_status.text()
    after = design_profile(session.design)
    # The tape length stays (the stretch is taken out); the openings keep their size.
    assert after.meridian_length == pytest.approx(before.meridian_length, abs=5e-3)
    assert after.r[0] == pytest.approx(before.r[0], abs=1e-3)
    assert after.r[-1] == pytest.approx(before.r[-1], abs=5e-3)
