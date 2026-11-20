"""Where a special shape's panels meet, set as plan fractions (ADR-0052)."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.features.primitives import (
    PrimitiveError,
    meeting_point_plan,
    meeting_point_shift,
)
from envelopelab.project.model import Project, dump_project, load_project_text
from envelopelab.project.session import ProjectSession
from envelopelab.project.shape_groups import mirrored
from envelopelab.project.shapes import (
    DomeShape,
    MeshShape,
    ShapePlacement,
    default_shape,
    envelope_surface,
    meeting_point,
    mesh_shape,
    shape_design,
    to_primitive,
)
from envelopelab.validation.primitives import ellipsoid_mesh

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
SESSION = ProjectSession.open(FIXTURE)
R = 0.5
#: A hemisphere's pointed meridian from the base circle to the tip.
ANGLE = np.linspace(0.0, 0.5 * math.pi, 4001)
RHO, ZETA = R * np.cos(ANGLE), R * np.sin(ANGLE)


@pytest.mark.parametrize("h", [0.1, 0.3, 0.6, 0.9])
def test_on_a_hemisphere_the_distance_from_the_tip_is_r_asin_h(h: float) -> None:
    # Plan radius rho = R h is reached at arc length R asin(h) from the tip.
    shift, direction = meeting_point_shift(RHO, ZETA, 0.0, h)
    assert shift == pytest.approx(R * math.asin(h), abs=1e-6)
    assert direction == 0.0  # straight up the tape
    _, direction = meeting_point_shift(RHO, ZETA, h, 0.0)
    assert direction == pytest.approx(0.5 * math.pi)  # towards the next gore


@settings(max_examples=60, deadline=None)
@given(
    st.floats(min_value=-0.95, max_value=0.95),
    st.floats(min_value=-0.95, max_value=0.95),
)
def test_plan_fractions_round_trip(across: float, up: float) -> None:
    if math.hypot(across, up) > 0.95:
        across, up = 0.6 * across, 0.6 * up
    shift, direction = meeting_point_shift(RHO, ZETA, across, up)
    a, u = meeting_point_plan(RHO, ZETA, shift, direction)
    assert (a, u) == pytest.approx((across, up), abs=1e-6)


def test_the_tip_is_no_move_and_outside_the_outline_is_refused() -> None:
    assert meeting_point_shift(RHO, ZETA, 0.0, 0.0) == (0.0, 0.0)
    with pytest.raises(PrimitiveError):
        meeting_point_shift(RHO, ZETA, 0.8, 0.8)


def _dome(**values: float) -> DomeShape:
    spec = default_shape("dome", SESSION.design, "X")
    assert isinstance(spec, DomeShape)
    return spec.model_copy(update=values)


def test_the_skin_point_seen_from_above_is_at_the_fractions() -> None:
    spec = DomeShape.model_validate({**_dome().model_dump(), "cap_across": 0.15, "cap_up": 0.1})
    surface = envelope_surface(SESSION.design, SESSION.patterns)
    placed = shape_design(spec, surface)
    prim: Any = placed.primitive
    skin = placed._skin
    # The cap's centre on the skin, from the base point, in the shape's plan frame.
    point = skin.at_u(np.array([skin.total_full - prim.cap_shift]), np.array([prim.cap_direction]))[
        0
    ]
    rel = point - placed.base_point
    widest = float(np.max(dataclasses.replace(prim, cap_radius=0.0).meridian()[0]))
    # Across is towards the next gore: -b2 (the frame turns towards the previous one).
    plan = np.array([-(rel @ placed.b2), rel @ placed.b1]) / widest  # across, up
    assert plan == pytest.approx([0.15, 0.1], abs=1e-3)
    assert not [c for c in placed.checks if c.severity == "error"]


def test_the_point_keeps_its_place_when_the_shape_is_resized() -> None:
    small = DomeShape.model_validate({**_dome().model_dump(), "cap_across": 0.2})
    big = small.model_copy(
        update={"base_radius": small.base_radius * 1.5, "height": small.height * 1.5}
    )
    assert meeting_point(small) == meeting_point(big) == (0.2, 0.0)
    # ... so the distance down the skin grows with the shape.
    assert to_primitive(big).cap_shift == pytest.approx(1.5 * to_primitive(small).cap_shift)  # type: ignore[union-attr]


def test_a_cap_shift_reads_as_fractions_and_the_two_ways_are_exclusive() -> None:
    old = _dome(cap_shift=0.04, cap_direction_deg=90.0)
    across, up = meeting_point(old)
    # 90 deg turns towards b2, the previous gore: a negative across.
    assert up == pytest.approx(0.0, abs=1e-9) and across < 0.0
    new = DomeShape.model_validate({**old.model_dump(), "cap_shift": 0.0, "cap_across": across})
    assert to_primitive(new).cap_shift == pytest.approx(0.04, abs=1e-6)  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        DomeShape.model_validate({**old.model_dump(), "cap_across": 0.1})
    with pytest.raises(ValueError):
        DomeShape.model_validate({**_dome().model_dump(), "cap_across": 0.8, "cap_up": 0.8})


def test_a_mirror_twin_meets_across_the_other_way() -> None:
    spec = DomeShape.model_validate({**_dome().model_dump(), "cap_across": 0.2, "cap_up": 0.1})
    data = mirrored(spec, 4.0, SESSION.design.gores.count)  # type: ignore[union-attr]
    assert (data["cap_across"], data["cap_up"]) == (-0.2, 0.1)


def test_relative_meeting_points_survive_a_save_and_load() -> None:
    session = ProjectSession.open(FIXTURE)
    spec = DomeShape.model_validate({**_dome().model_dump(), "cap_across": 0.2, "cap_up": -0.1})
    state = session.state.model_copy(update={"shapes": [spec]})
    project = session.project.model_copy(update={"state": state})
    back = load_project_text(dump_project(project))
    assert isinstance(back, Project) and back.format_version == 7
    (shape,) = back.state.shapes
    assert (shape.cap_across, shape.cap_up) == (0.2, -0.1)


def _blob(**values: float) -> MeshShape:
    mesh = ellipsoid_mesh(0.3, 0.25, 0.35, -0.05, rings=16, segments=24)
    spec = mesh_shape(
        "Blob", mesh.vertices, mesh.triangles, ShapePlacement(gore=3, tape_position=4.0)
    )
    return MeshShape.model_validate({**spec.model_dump(), **values})


@pytest.mark.parametrize(("across", "up"), [(0.2, 0.0), (0.0, -0.25), (-0.15, 0.15)])
def test_a_mesh_shapes_panels_meet_at_the_fractions(across: float, up: float) -> None:
    surface = envelope_surface(SESSION.design, SESSION.patterns)
    placed = shape_design(_blob(cap_across=across, cap_up=up), surface)
    prim: Any = placed.primitive
    rel = placed._skin.pole - placed.base_point
    plan = np.array([-(rel @ placed.b2), rel @ placed.b1]) / prim.widest_radius
    assert plan == pytest.approx([across, up], abs=1e-9)
    # Every panel ends round that point, on the edge of the cap cut about the seam line.
    skin = placed._skin
    assert skin.cap is not None
    cap_nodes = {int(g) for g in skin.cap.glob}
    for panel in skin.panels:
        assert {int(g) for g in panel.glob[panel.top]} <= cap_nodes
    # The cap is centred on the seam line: its nodes all lie within its radius of it.
    rel = skin.x[sorted(cap_nodes)] - skin.base
    off = np.linalg.norm(rel - np.outer(rel @ skin.axis, skin.axis), axis=1)
    assert float(off.max()) <= prim.cap_radius + 1e-9
    assert not [c for c in placed.checks if c.severity == "error" and not c.passed]


def test_a_mesh_shape_on_its_axis_is_unchanged() -> None:
    surface = envelope_surface(SESSION.design, SESSION.patterns)
    a = shape_design(_blob(), surface)
    b = shape_design(_blob(cap_across=0.0, cap_up=0.0), surface)
    for p, q in zip(a.pieces, b.pieces, strict=True):
        np.testing.assert_array_equal(p.finished, q.finished)


def test_a_positive_across_moves_the_point_towards_the_next_gore() -> None:
    # Gore numbers grow with the azimuth theta (EnvelopeSurface.theta_at), so the next
    # gore is at a larger theta than the base point.
    surface = envelope_surface(SESSION.design, SESSION.patterns)
    dome = DomeShape.model_validate({**_dome().model_dump(), "cap_across": 0.2})
    placed = shape_design(dome, surface)
    prim: Any = placed.primitive
    point = placed._skin.at_u(
        np.array([placed._skin.total_full - prim.cap_shift]), np.array([prim.cap_direction])
    )[0]
    _s, theta, _d = surface.locate(point[None])
    assert float(theta[0]) > placed.base_theta
    blob = shape_design(_blob(cap_across=0.2), surface)
    _s, theta, _d = surface.locate(blob._skin.pole[None])
    assert float(theta[0]) > blob.base_theta
