"""A design's profile under load: the membrane check and the snap to a shape that holds."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from envelopelab.atmosphere import G0
from envelopelab.project import edits
from envelopelab.project.gore_design import LockError, design_profile, gore_outputs
from envelopelab.project.profile_match import solved_deviation, solved_meridian, station_points
from envelopelab.project.profile_physics import (
    check_design,
    design_load,
    natural_design_shape,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.simulation import build_solver_model, run_record, solve_preview
from envelopelab.solvers.model import SolverSettings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


def test_the_load_comes_from_the_operating_conditions_and_the_mass_estimate() -> None:
    s = ProjectSession.open(FIXTURE)
    out = gore_outputs(s.design, s.patterns)
    loaded = design_load(s.design, s.patterns)
    gamma = (out.ambient_density - out.internal_density) * G0.value
    assert loaded.load.pressure_gradient == pytest.approx(gamma)
    assert out.envelope_mass is not None
    assert loaded.load.areal_weight == pytest.approx(out.envelope_mass * G0.value / out.area)
    assert loaded.sources and not loaded.note


def test_the_fixture_needs_hoop_compression_low_down() -> None:
    """The preview confirms it: there the solved tape line moves inward by up to 62 mm
    while the rest of the envelope holds (docs/theory/profile-physics.md)."""
    s = ProjectSession.open(FIXTURE)
    check = check_design(s.design, s.patterns)
    bad = ~check.holds
    assert 0.15 < check.compressed_fraction < 0.35
    assert float(check.s[bad].max()) < 0.35 * float(check.s[-1])
    assert float(np.nanmax(check.hoop)) > 0.0


def test_snapping_removes_the_compression_and_keeps_the_ends_and_length() -> None:
    s = ProjectSession.open(FIXTURE)
    before = design_profile(s.design)
    result = edits.snap_profile_to_hold(s, tolerance=0.005)
    after = design_profile(s.design)
    assert 0.15 < result.changed < 0.35
    assert result.fit_distance <= 0.005
    assert check_design(s.design, s.patterns).compressed_fraction == 0.0
    assert after.r[0] == pytest.approx(before.r[0], abs=0.005)
    assert after.r[-1] == pytest.approx(before.r[-1], abs=0.005)
    assert after.meridian_length == pytest.approx(before.meridian_length, rel=1e-3)
    assert s.undo()
    np.testing.assert_allclose(design_profile(s.design).r, before.r)


def test_a_shape_that_holds_is_not_changed_and_locks_refuse() -> None:
    s = ProjectSession.open(FIXTURE)
    edits.snap_profile_to_hold(s)
    again = edits.snap_profile_to_hold(s)
    assert again.changed < 0.02
    s2 = ProjectSession.open(FIXTURE)
    edits.set_lock(s2, "height", True)
    with pytest.raises(LockError, match="unlock height"):
        edits.snap_profile_to_hold(s2)


def test_the_natural_shape_of_the_design_keeps_its_ends_and_length() -> None:
    s = ProjectSession.open(FIXTURE)
    profile = design_profile(s.design)
    shape = natural_design_shape(s.design, s.patterns)
    assert shape.converged
    assert shape.profile.r[-1] == pytest.approx(profile.r[-1], abs=1e-6)
    assert shape.profile.meridian_length == pytest.approx(profile.meridian_length, rel=1e-5)
    with pytest.raises(ValueError, match="keep"):
        natural_design_shape(s.design, s.patterns, keep="volume")


def _solved_lower_offset(session: ProjectSession) -> tuple[float, float]:
    """Largest deviation (m) and the most inward normal offset in the lower quarter (m)
    of a converged preview of the session's design."""
    with tempfile.TemporaryDirectory() as tmp:
        built = build_solver_model(session.design, session.patterns, Path(tmp) / "p", 800.0)
        # Viscous damping: on the snapped shape's zero-hoop-stress spans, kinetic damping
        # keeps resetting and its path depends on round-off (from starts perturbed by
        # 1e-15 it converges or wanders past 600k iterations); viscous damping converges
        # in 71k iterations from any of them.
        settings = SolverSettings(max_iterations=600_000, damping="viscous", viscous_damping=0.05)
        result = solve_preview(built, settings)
    assert result.converged
    _, arrays = run_record(result, built, "test")
    profile = design_profile(session.design)
    solved = solved_meridian(arrays, 8, float(profile.z[0]))
    deviation = solved_deviation(profile, solved).max_distance
    offset = np.column_stack((solved.r, solved.z)) - station_points(profile, solved.station)
    theta = np.arctan2(
        np.interp(solved.station * profile.meridian_length, profile.s, np.gradient(profile.z)),
        np.interp(solved.station * profile.meridian_length, profile.s, np.gradient(profile.r)),
    )
    normal = offset[:, 0] * np.sin(theta) - offset[:, 1] * np.cos(theta)
    return deviation, float(normal[solved.station < 0.25].min())


@pytest.mark.slow
def test_the_snapped_fixture_inflates_closer_to_its_profile() -> None:
    """End to end with the preview solver (800 mm mesh): the drawn fixture collapses
    inward low down; snapped, it does not, and its largest deviation halves."""
    s = ProjectSession.open(FIXTURE)
    drawn_dev, drawn_inward = _solved_lower_offset(s)
    edits.snap_profile_to_hold(s)
    snapped_dev, snapped_inward = _solved_lower_offset(s)
    assert drawn_inward < -0.04
    assert snapped_inward > -0.005
    assert snapped_dev < 0.6 * drawn_dev
