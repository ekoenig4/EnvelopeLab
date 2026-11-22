"""Positions in metres and in balloon coordinates (envelopelab.project.coordinates)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.features.primitives import EnvelopeSurface, Revolved
from envelopelab.project.coordinates import (
    across_from_metres,
    across_metres,
    balloon_position,
    describe_position,
    envelope_position,
    format_row_position,
    parse_row_position,
    row_labels,
    row_position,
    tape_at,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import envelope_surface

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
_SESSION = ProjectSession.open(FIXTURE)
SURFACE: EnvelopeSurface = envelope_surface(_SESSION.design, _SESSION.patterns)
ROWS = SURFACE.rows
LENGTH = float(ROWS[-1].s_top)


def _rows(tape: float) -> tuple[str, float]:
    label, fraction = row_position(SURFACE, tape)
    return label, round(fraction, 9)


def test_the_fixture_has_several_rows() -> None:
    assert len(ROWS) >= 3 and row_labels(SURFACE) == [r.label for r in ROWS]


def test_row_fractions_run_from_the_bottom_seam_to_the_top_seam() -> None:
    row = ROWS[1]
    mid = 0.5 * (row.s_bottom + row.s_top)
    assert _rows(mid) == (row.label, 0.5)
    # A point on a seam belongs to the row above it; the crown end to the top row.
    assert _rows(row.s_bottom) == (row.label, 0.0)
    assert _rows(LENGTH) == (ROWS[-1].label, 1.0)
    assert _rows(0.0) == (ROWS[0].label, 0.0)
    assert tape_at(SURFACE, row.label, 0.25) == pytest.approx(
        row.s_bottom + 0.25 * (row.s_top - row.s_bottom)
    )


def test_gore_fractions_run_from_seam_to_seam() -> None:
    p = balloon_position(SURFACE, 4, -0.5, 1.0)
    assert p.gore == 4 and p.gore_fraction == 0.0
    assert balloon_position(SURFACE, 4, 0.0, 1.0).gore_fraction == 0.5
    assert balloon_position(SURFACE, 4, 0.5, 1.0).gore_fraction == 1.0


@settings(max_examples=200, deadline=None)
@given(
    gore=st.integers(min_value=1, max_value=12),
    across=st.floats(min_value=-0.5, max_value=0.5),
    tape=st.floats(min_value=0.0, max_value=1.0),
)
def test_balloon_coordinates_round_trip(gore: int, across: float, tape: float) -> None:
    """Converting to balloon coordinates and back returns the stored position."""
    s = tape * LENGTH
    p = balloon_position(SURFACE, gore, across, s)
    assert 0.0 <= p.gore_fraction <= 1.0 and 0.0 <= p.row_fraction <= 1.0
    back = envelope_position(SURFACE, p.gore, p.gore_fraction, p.row, p.row_fraction)
    assert back[0] == gore
    assert back[1] == pytest.approx(across, abs=1e-12)
    assert back[2] == pytest.approx(s, abs=1e-9)


@settings(max_examples=100, deadline=None)
@given(
    across=st.floats(min_value=-0.5, max_value=0.5),
    tape=st.floats(min_value=0.02, max_value=0.98),
)
def test_metre_offsets_round_trip(across: float, tape: float) -> None:
    s = tape * LENGTH
    x = across_metres(SURFACE, across, s)
    assert abs(x) <= float(SURFACE.half_width(np.array([s]))[0]) + 1e-12
    assert across_from_metres(SURFACE, x, s) == pytest.approx(across, abs=1e-9)


def test_offsets_outside_the_gore_and_bad_fractions_are_refused() -> None:
    s = 0.5 * LENGTH
    w = float(SURFACE.half_width(np.array([s]))[0])
    with pytest.raises(ValueError, match="outside the gore"):
        across_from_metres(SURFACE, 1.5 * w, s)
    with pytest.raises(ValueError, match="between 0"):
        envelope_position(SURFACE, 1, 1.2, ROWS[0].label, 0.5)
    with pytest.raises(ValueError, match="between 0"):
        tape_at(SURFACE, ROWS[0].label, -0.1)
    with pytest.raises(ValueError, match="no panel row"):
        tape_at(SURFACE, "ZZ", 0.5)


def test_positions_are_described_in_either_way() -> None:
    row = ROWS[2]
    s = row.s_bottom + 0.4 * (row.s_top - row.s_bottom)
    assert describe_position(SURFACE, "balloon", 3, 0.12, s) == (
        f"gore 3 + 0.62, row {row.label} + 0.40"
    )
    metres = describe_position(SURFACE, "metres", 3, 0.12, s)
    assert metres.startswith("gore 3, +") and f"{s:.3f} m up the tape" in metres


def test_row_positions_are_written_and_read_as_text() -> None:
    assert format_row_position("F", 0.4) == "F + 0.400"
    assert parse_row_position("F + 0.4") == ("F", 0.4)
    assert parse_row_position(" NOMEX+.25 ") == ("NOMEX", 0.25)
    assert parse_row_position("i") == ("i", 0.0)
    with pytest.raises(ValueError, match="such as"):
        parse_row_position("F - 0.4")


def test_splits_in_metres_are_lengths_along_the_skin_from_the_rim() -> None:
    from envelopelab.project.coordinates import skin_length, split_fraction, split_metres
    from envelopelab.project.shapes import RevolvedShape, ShapePlacement, default_shape

    revolved = RevolvedShape(
        name="R",
        placement=ShapePlacement(gore=2, tape_position=4.0),
        profile=[(0.3, 0.0), (0.2, 0.4), (0.35, 0.7), (0.0, 1.0)],
        splits=[0.25, 0.6],
    )
    total = skin_length(revolved)
    assert split_metres(revolved) == pytest.approx([0.25 * total, 0.6 * total])
    assert split_fraction(revolved, 0.25 * total) == pytest.approx(0.25)
    with pytest.raises(ValueError, match="between the rim"):
        split_fraction(revolved, 1.5 * total)
    # A pointed dome as high as its base radius is a quarter circle: S = pi r / 2.
    dome = default_shape("dome", _SESSION.design, "D")
    r = dome.base_radius  # type: ignore[union-attr]
    pointed = dome.model_copy(update={"height": r, "cap_diameter": 0.0})
    assert skin_length(pointed) == pytest.approx(0.5 * np.pi * r, rel=1e-4)


def test_a_mesh_shape_has_no_split_length() -> None:
    from envelopelab.project.coordinates import skin_length
    from envelopelab.project.shapes import ShapePlacement, mesh_shape
    from envelopelab.validation.primitives import ellipsoid_mesh

    ball = ellipsoid_mesh(0.3, 0.3, 0.3, 0.0, rings=8, segments=12)
    mesh = mesh_shape("B", ball.vertices, ball.triangles, ShapePlacement(gore=1, tape_position=3))
    with pytest.raises(ValueError, match="cannot be split"):
        skin_length(mesh)


def test_split_lengths_match_where_the_skin_is_cut() -> None:
    """A split shown as metres lies where the shape's own split points are."""
    from envelopelab.project.coordinates import split_metres
    from envelopelab.project.shape_profile import split_points
    from envelopelab.project.shapes import RevolvedShape, ShapePlacement, to_primitive

    spec = RevolvedShape(
        name="R",
        placement=ShapePlacement(gore=2, tape_position=4.0),
        profile=[(0.3, 0.0), (0.25, 0.5), (0.0, 0.9)],
        splits=[0.5],
    )
    prim = to_primitive(spec)
    assert isinstance(prim, Revolved)
    rho, zeta = prim.meridian()
    arc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(rho), np.diff(zeta)))])
    point = split_points(spec)[0]
    i = int(np.argmin(np.hypot(rho - point[0], zeta - point[1])))
    assert arc[i] == pytest.approx(split_metres(spec)[0], abs=1e-3)
