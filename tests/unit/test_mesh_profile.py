"""Fitting a revolved profile to a round mesh shape (envelopelab.features.mesh_profile)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from envelopelab.features.mesh_profile import (
    ROUND_TOLERANCE,
    axis_top,
    fit_profile,
    section_radius,
)
from envelopelab.project import edits
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import (
    MeshShape,
    RevolvedShape,
    ShapePlacement,
    default_shape,
    envelope_surface,
    mesh_shape,
    shape_design,
)
from envelopelab.validation.primitives import ellipsoid_mesh
from envelopelab.validation.primitives import revolved_mesh as generic_revolved_mesh

#: A stalk with a ball on top, ending on the axis (generic test geometry), m.
ANTENNA = [
    (0.44, 0.0),
    (0.30, 1.2),
    (0.30, 1.55),
    (0.55, 1.85),
    (0.6, 2.15),
    (0.45, 2.5),
    (0.0, 2.7),
]


def revolved_mesh(
    profile: list[tuple[float, float]], sink: float = 0.05
) -> tuple[np.ndarray, np.ndarray]:
    mesh = generic_revolved_mesh(profile, sink=sink)
    return mesh.vertices, mesh.triangles


def test_axis_top_and_sections_of_a_revolved_mesh() -> None:
    v, t = revolved_mesh(ANTENNA)
    assert axis_top(v, t) == pytest.approx(2.7, abs=1e-9)
    assert section_radius(v, t, 0.6) == pytest.approx(0.37, rel=2e-3)  # on the stalk
    # The ball's widest point falls between two rings of the test mesh, so its section
    # there is a little inside 0.6 m.
    assert section_radius(v, t, 2.15) == pytest.approx(0.6, rel=1e-2)


def test_a_round_antenna_mesh_is_fitted_closely() -> None:
    v, t = revolved_mesh(ANTENNA)
    fit = fit_profile(v, t, points=24)
    assert fit.profile[0][1] == 0.0 and fit.profile[-1] == pytest.approx((0.0, 2.7))
    assert fit.profile[0][0] == pytest.approx(0.44, abs=5e-3)
    assert fit.round
    assert fit.max_deviation < 0.02 * fit.widest_radius + 0.01
    assert fit.widest_radius == pytest.approx(0.6, rel=0.03)


def test_fewer_points_fit_a_sphere_well() -> None:
    ball = ellipsoid_mesh(0.4, 0.4, 0.4, 0.0, rings=24, segments=48)
    fit = fit_profile(ball.vertices, ball.triangles, points=8)
    assert fit.round and fit.relative_deviation < 0.02
    assert fit.profile[-1] == pytest.approx((0.0, 0.4), rel=1e-6)


def test_a_mesh_that_is_not_round_is_reported() -> None:
    ear = ellipsoid_mesh(0.6, 0.2, 0.5, 0.0, rings=24, segments=48)
    fit = fit_profile(ear.vertices, ear.triangles)
    assert not fit.round
    assert fit.relative_deviation > ROUND_TOLERANCE
    assert fit.max_deviation > 0.15  # about the difference of its semi-axes


def test_a_mesh_off_its_axis_is_refused() -> None:
    ball = ellipsoid_mesh(0.3, 0.3, 0.3, 0.0, rings=12, segments=24)
    moved = ball.vertices + np.array([2.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="axis"):
        fit_profile(moved, ball.triangles)


def test_too_few_points_are_refused() -> None:
    v, t = revolved_mesh(ANTENNA)
    with pytest.raises(ValueError, match="at least"):
        fit_profile(v, t, points=2)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


def _session_with_antenna(name: str = "Antenna") -> ProjectSession:
    session = ProjectSession.open(FIXTURE)
    # 40 % of ANTENNA: the fixture's envelope is small.
    v, t = revolved_mesh([(0.4 * r, 0.4 * z) for r, z in ANTENNA], sink=0.02)
    placement = ShapePlacement(gore=3, tape_position=6.0)
    edits.add_shape(session, mesh_shape(name, v, t, placement, "antenna.obj", panels=12))
    return session


def test_converting_a_round_mesh_makes_a_revolved_shape_that_can_be_split() -> None:
    session = _session_with_antenna()
    mesh = session.state.shapes[0]
    assert isinstance(mesh, MeshShape)
    fit = fit_profile(np.asarray(mesh.vertices), np.asarray(mesh.triangles), points=16)
    assert edits.convert_mesh_to_revolved(session, "Antenna", fit.profile, fit.smooth)
    spec = session.state.shapes[0]
    assert isinstance(spec, RevolvedShape)
    assert spec.name == "Antenna" and spec.placement == mesh.placement and spec.gores == 12
    assert np.asarray(spec.profile) == pytest.approx(np.asarray(fit.profile))
    # Revolved, the stalk and the ball can be cut as two tiers.
    assert edits.update_shape(session, "Antenna", {"splits": [0.5]})
    surface = envelope_surface(session.design, session.patterns)
    placed = shape_design(session.state.shapes[0], surface)
    assert any(p.label.endswith("B") for p in placed.pieces)
    session.undo()
    session.undo()
    assert session.state.shapes[0] == mesh


def test_a_mirror_twin_is_converted_with_its_source() -> None:
    session = _session_with_antenna()
    edits.add_symmetry_axis(session, "Face centre", 1.0)
    twin = edits.mirror_shape(session, "Antenna", "Face centre")
    mesh = session.state.shapes[0]
    assert isinstance(mesh, MeshShape)
    fit = fit_profile(np.asarray(mesh.vertices), np.asarray(mesh.triangles))
    assert edits.convert_mesh_to_revolved(session, "Antenna", fit.profile, fit.smooth)
    shapes = {s.name: s for s in session.state.shapes}
    assert isinstance(shapes[twin], RevolvedShape) and shapes[twin].mirror is not None


def test_conversions_that_cannot_be_done_change_nothing() -> None:
    session = _session_with_antenna()
    edits.add_shape(session, default_shape("dome", session.design, "Nose"))
    before = session.state.model_copy(deep=True)
    with pytest.raises(ValueError, match="not a mesh"):
        edits.convert_mesh_to_revolved(session, "Nose", ANTENNA)
    with pytest.raises(KeyError):
        edits.convert_mesh_to_revolved(session, "Tail", ANTENNA)
    with pytest.raises(ValueError):
        edits.convert_mesh_to_revolved(session, "Antenna", [(0.4, 0.5), (0.0, 1.0)])
    assert session.state == before
