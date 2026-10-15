"""Solved tape line of a run, its deviation from the drawn profile, and profile updates."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.project import edits
from envelopelab.project.gore_design import LockError, control_arrays, design_profile
from envelopelab.project.model import (
    RunRecord,
    dump_project,
    load_project_text,
    utc_now,
)
from envelopelab.project.profile_match import (
    ProfileMatchError,
    adopted_control_points,
    compensated_control_points,
    latest_run_shape,
    solved_deviation,
    solved_meridian,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.simulation import build_solver_model, run_record, solve_preview

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


def revolution_arrays(
    session: ProjectSession, rows: int = 60, per_gore: int = 4
) -> dict[str, np.ndarray]:
    """Structured mesh of the drawn profile revolved with the design's gore count, laid
    out as the initial shape lays out gores (seams at multiples of 2 pi / G)."""
    design = session.design
    assert design.gores is not None
    profile = design_profile(design)
    g = design.gores.count
    s = np.linspace(0.0, profile.meridian_length, rows)
    r = np.interp(s, profile.s, profile.r)
    z = np.interp(s, profile.s, profile.z)
    columns = g * per_gore
    theta = 2.0 * math.pi * np.arange(columns) / columns
    x = np.column_stack(
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
            c, d = a + columns, b + columns
            tris += [(a, b, d), (a, d, c)]
    return {
        "positions": x.copy(),
        "initial_positions": x,
        "triangles": np.asarray(tris, dtype=np.int64),
    }


def scaled(arrays: dict[str, np.ndarray], radial: float, vertical: float) -> dict[str, np.ndarray]:
    """Solved positions = initial radii times ``radial``, heights times ``vertical``."""
    out = dict(arrays)
    x = arrays["initial_positions"].copy()
    x[:, :2] *= radial
    x[:, 2] *= vertical
    out["positions"] = x
    return out


def add_run(session: ProjectSession, arrays: dict[str, np.ndarray], converged: bool = True) -> None:
    record = RunRecord(
        run_id=f"run-{len(session.project.runs)}",
        created=utc_now(),
        solver="calculix",
        solver_version="test",
        status="converged" if converged else "max_iterations",
        converged=converged,
        residual=1e-7,
        residual_measure="test",
        iterations=1,
        run_time=0.0,
        n_nodes=len(arrays["positions"]),
        n_elements=len(arrays["triangles"]),
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
    session.add_run(record, arrays)


def test_the_initial_shape_reads_back_as_the_drawn_profile() -> None:
    s = ProjectSession.open(FIXTURE)
    arrays = revolution_arrays(s)
    solved = solved_meridian(arrays, 8, 0.0)
    assert solved.seams == 8
    assert solved.spread < 1e-9
    deviation = solved_deviation(design_profile(s.design), solved)
    assert deviation.max_distance < 1e-3  # AGENTS.md geometry tolerance
    assert abs(deviation.height_change) < 1e-3
    assert abs(deviation.max_diameter_change) < 1e-3


def test_a_uniform_stretch_is_measured_as_such() -> None:
    s = ProjectSession.open(FIXTURE)
    profile = design_profile(s.design)
    solved = solved_meridian(scaled(revolution_arrays(s), 1.02, 1.01), 8, 0.0)
    deviation = solved_deviation(profile, solved)
    assert deviation.max_diameter_change == pytest.approx(0.02 * profile.max_width, rel=1e-3)
    assert deviation.height_change == pytest.approx(0.01 * profile.height, rel=1e-3)


def test_the_mouth_is_moved_to_the_drawn_mouth_height() -> None:
    s = ProjectSession.open(FIXTURE)
    arrays = revolution_arrays(s)
    shifted = dict(arrays)
    for key in ("positions", "initial_positions"):
        shifted[key] = arrays[key] + np.array([0.0, 0.0, -5.0])
    solved = solved_meridian(shifted, 8, 0.0)
    assert solved.z[0] == pytest.approx(0.0, abs=1e-12)


def test_the_stored_gore_count_wins_and_a_wrong_one_finds_no_seam() -> None:
    s = ProjectSession.open(FIXTURE)
    arrays = revolution_arrays(s, per_gore=4)
    with pytest.raises(ProfileMatchError, match="only 1 of 7 load-tape seams"):
        solved_meridian(arrays, 7, 0.0)  # 7 gores: no node at 2 pi k / 7 off the x axis
    stored = {**arrays, "gore_count": np.array([8])}
    assert solved_meridian(stored, 7, 0.0).seams == 8
    with pytest.raises(ProfileMatchError, match="no positions"):
        solved_meridian({"triangles": arrays["triangles"]}, 8, 0.0)


def test_an_open_seam_is_skipped() -> None:
    s = ProjectSession.open(FIXTURE)
    arrays = revolution_arrays(s, rows=20, per_gore=4)
    columns = 32
    # Unsew seam 0 over the middle rows: duplicate its nodes for the triangles left of it.
    x = arrays["initial_positions"]
    tris = arrays["triangles"].copy()
    extra: dict[int, int] = {}
    for i in range(8, 12):
        node = i * columns
        extra[node] = len(x) + len(extra)
    for t in tris:
        if any(v % columns == columns - 1 for v in t):
            for k, v in enumerate(t):
                if v in extra:
                    t[k] = extra[v]
    x = np.vstack((x, x[list(extra)]))
    opened = {"positions": x, "initial_positions": x, "triangles": tris}
    solved = solved_meridian(opened, 8, 0.0)
    assert solved.seams == 7


def test_adopting_a_solved_line_reproduces_it_within_the_tolerance() -> None:
    s = ProjectSession.open(FIXTURE)
    solved = solved_meridian(scaled(revolution_arrays(s), 1.03, 1.02), 8, 0.0)
    update = adopted_control_points(s.design, solved, tolerance=2e-3)
    assert update.fit_error <= 2e-3
    pts = np.array(update.points)
    r, z = control_arrays(s.design)
    # The original points are kept (moved onto the solved line) and the ends stay ends.
    assert len(pts) >= len(r)
    assert pts[0] == pytest.approx([1.03 * r[0], 0.0], abs=1e-9)
    assert pts[-1] == pytest.approx([1.03 * r[-1], 1.02 * z[-1]], abs=2e-3)


def test_compensation_inverts_a_uniform_stretch_to_first_order() -> None:
    s = ProjectSession.open(FIXTURE)
    solved = solved_meridian(scaled(revolution_arrays(s), 1.02, 1.0), 8, 0.0)
    update = compensated_control_points(s.design, solved, tolerance=1e-3)
    pts = np.array(update.points)
    r, _ = control_arrays(s.design)
    # The cut is drawn 2 % narrower so that a 2 % radial growth lands on the target.
    assert float(pts[:, 0].max()) == pytest.approx(0.98 * float(r.max()), rel=2e-3)
    with pytest.raises(ValueError, match="relaxation"):
        compensated_control_points(s.design, solved, relaxation=0.0)


def test_compensation_keeps_its_target_across_steps_and_restores_it() -> None:
    s = ProjectSession.open(FIXTURE)
    original = [tuple(p) for p in np.column_stack(control_arrays(s.design)).tolist()]
    add_run(s, scaled(revolution_arrays(s), 1.02, 1.01))
    shape = latest_run_shape(s, "calculix")
    assert shape is not None and shape.usable and shape.solved is not None
    edits.compensate_profile(s, shape.solved)
    target = s.project.profile_target
    assert target is not None
    assert target.control_points == pytest.approx(original)
    # The run is stale now and may not drive another step.
    stale = latest_run_shape(s, "calculix")
    assert stale is not None and not stale.usable and "stale" in stale.refusal
    # A second step corrects towards the stored target, not towards the cut line.
    add_run(s, scaled(revolution_arrays(s), 1.02, 1.01))
    second = latest_run_shape(s, "calculix")
    assert second is not None and second.solved is not None
    edits.compensate_profile(s, second.solved)
    target = s.project.profile_target
    assert target is not None
    assert target.control_points == pytest.approx(original)
    assert len(target.step_deviations) == 2
    # The second run stretches the compensated cut, which lands close to the target.
    assert target.step_deviations[1] < target.step_deviations[0]
    assert edits.restore_profile_target(s)
    assert s.project.profile_target is None
    restored = np.column_stack(control_arrays(s.design))
    assert restored == pytest.approx(np.array(original))


def test_adopting_drops_the_target_and_unconverged_runs_are_refused() -> None:
    s = ProjectSession.open(FIXTURE)
    add_run(s, scaled(revolution_arrays(s), 1.02, 1.01), converged=False)
    shape = latest_run_shape(s, "calculix")
    assert shape is not None and not shape.usable and "not converged" in shape.refusal
    add_run(s, scaled(revolution_arrays(s), 1.02, 1.01))
    shape = latest_run_shape(s, "calculix")
    assert shape is not None and shape.solved is not None
    edits.compensate_profile(s, shape.solved)
    add_run(s, scaled(revolution_arrays(s), 1.0, 1.0))
    again = latest_run_shape(s, "calculix")
    assert again is not None and again.solved is not None
    edits.adopt_solved_profile(s, again.solved)
    assert s.project.profile_target is None
    assert latest_run_shape(s, "envelopelab-preview") is None


def test_shape_locks_refuse_a_profile_update() -> None:
    s = ProjectSession.open(FIXTURE)
    add_run(s, scaled(revolution_arrays(s), 1.02, 1.01))
    shape = latest_run_shape(s, "calculix")
    assert shape is not None and shape.solved is not None
    edits.set_lock(s, "height", True)
    with pytest.raises(LockError, match="unlock height"):
        edits.compensate_profile(s, shape.solved)
    with pytest.raises(LockError, match="unlock height"):
        edits.adopt_solved_profile(s, shape.solved)
    assert s.project.profile_target is None


def test_opening_locks_and_segment_profiles_refuse_a_profile_update() -> None:
    s = ProjectSession.open(FIXTURE)
    add_run(s, scaled(revolution_arrays(s), 1.02, 1.01))
    shape = latest_run_shape(s, "calculix")
    assert shape is not None and shape.solved is not None
    edits.set_lock(s, "top_diameter", True)
    with pytest.raises(LockError, match="unlock top diameter"):
        edits.compensate_profile(s, shape.solved)
    edits.set_lock(s, "top_diameter", False)
    edits.set_profile_interpolation(s, "segments")
    # A segment profile draws the same line, so the run stays readable and current.
    segments = latest_run_shape(s, "calculix")
    assert segments is not None and segments.solved is not None
    assert segments.deviation is not None
    with pytest.raises(ValueError, match="segment profile"):
        edits.compensate_profile(s, segments.solved)
    with pytest.raises(ValueError, match="segment profile"):
        edits.adopt_solved_profile(s, segments.solved)
    assert s.project.profile_target is None


def test_the_target_is_saved_with_the_project_and_absent_without_one() -> None:
    s = ProjectSession.open(FIXTURE)
    assert "profile_target" not in dump_project(s.project)
    add_run(s, scaled(revolution_arrays(s), 1.02, 1.01))
    shape = latest_run_shape(s, "calculix")
    assert shape is not None and shape.solved is not None
    edits.compensate_profile(s, shape.solved)
    assert s.is_dirty
    text = dump_project(s.project)
    loaded = load_project_text(text)
    assert loaded.profile_target == s.project.profile_target


@pytest.mark.slow
def test_a_compensation_step_brings_the_preview_shape_closer(tmp_path: Path) -> None:
    """End to end: preview solve, compensate, solve the compensated cut again."""
    s = ProjectSession.open(FIXTURE)
    deviations = []
    for step in range(2):
        built = build_solver_model(s.design, s.patterns, tmp_path / f"pack{step}", 1600.0)
        result = solve_preview(built)
        assert result.converged
        record, arrays = run_record(result, built, s.fingerprints()["simulation"])
        assert int(arrays["gore_count"][0]) == 8
        s.add_run(record, arrays)
        shape = latest_run_shape(s, "envelopelab-preview")
        assert shape is not None and shape.usable and shape.deviation is not None
        assert shape.solved is not None and shape.solved.seams == 8
        deviations.append(shape.deviation.max_distance)
        if step == 0:
            edits.compensate_profile(s, shape.solved)
    # The intended line is the original drawn profile; the second cut lands closer to it.
    assert deviations[1] < 0.7 * deviations[0]
