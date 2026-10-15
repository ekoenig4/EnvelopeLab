"""Gore editor: solved tape lines drawn over the profile, compensation and adoption."""

from __future__ import annotations

import math

import numpy as np

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
