"""The gore map and 3D sketch of where special shapes sit (envelopelab.project.placement_map)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.project.placement_map import (
    COLUMN_GAP,
    axis_line,
    envelope_sketch,
    footprint_lines,
    gore_map,
    gore_position,
    map_to_placement,
    ring_lines,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import (
    ShapePlacement,
    default_shape,
    envelope_surface,
    shape_design,
)
from envelopelab.project.symmetry import SymmetryAxis

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
SESSION = ProjectSession.open(FIXTURE)
SURFACE = envelope_surface(SESSION.design, SESSION.patterns)
MAP = gore_map(SURFACE)


def test_gores_lie_side_by_side_at_their_flat_width() -> None:
    assert MAP.gores == SURFACE.gore_count == len(MAP.outlines)
    s = np.linspace(0.0, MAP.length, 9)
    w = SURFACE.half_width(s)
    assert MAP.column == pytest.approx(
        2.0 * float(MAP.half_width(np.linspace(0, MAP.length, 97)).max()) * (1 + COLUMN_GAP)
    )
    # A gore's seams on the map are its flat half width either side of its column centre.
    left = MAP.points(np.full(9, 2.0), s)  # the seam between gores 2 and 3, from gore 3
    right = MAP.points(np.full(9, 2.0 - 1e-12), s)  # the same seam, from gore 2
    assert left[:, 0] == pytest.approx(2.5 * MAP.column - w)
    assert right[:, 0] == pytest.approx(1.5 * MAP.column + w, abs=1e-9)
    assert [r[0] for r in MAP.rows] == [r.label for r in SURFACE.rows]


@given(st.integers(1, 8), st.floats(0.05, 9.6), st.floats(-0.5, 0.49))
@settings(max_examples=80, deadline=None)
def test_dragging_on_the_map_gives_the_placement_drawn_there(
    gore: int, tape: float, across: float
) -> None:
    placement = ShapePlacement(gore=gore, tape_position=tape, across=across, lean_deg=12.0)
    ((x, y),) = MAP.points(np.array([gore_position(placement)]), np.array([tape]))
    back = map_to_placement(MAP, float(x), float(y), placement)
    assert back.gore == gore
    assert back.tape_position == pytest.approx(tape, abs=1e-4)
    assert back.across == pytest.approx(across, abs=1e-4)
    assert back.lean_deg == 12.0  # the lean is kept


def test_a_point_beside_a_gore_is_clamped_into_it() -> None:
    p = ShapePlacement(gore=1, tape_position=4.0)
    x = 2.5 * MAP.column - 0.49 * MAP.column  # in the gap left of gore 3's centre
    back = map_to_placement(MAP, x, 4.0, p)
    assert back.gore == 3 and back.across == -0.5
    assert map_to_placement(MAP, 1.0, 99.0, p).tape_position < MAP.length


def test_a_footprint_across_a_seam_is_drawn_in_both_gores() -> None:
    spec = default_shape("dome", SESSION.design, "D").model_copy(
        update={"placement": ShapePlacement(gore=3, tape_position=4.5, across=0.45)}
    )
    placed = shape_design(spec, SURFACE)
    parts = footprint_lines(MAP, placed)
    assert len(parts) == 2
    columns = sorted({int(np.mean(p[:, 0]) // MAP.column) for p in parts})
    assert columns == [2, 3]  # gores 3 and 4
    assert sum(len(p) for p in parts) >= len(placed.footprint_s)


def test_axes_and_holes_on_the_map() -> None:
    line = axis_line(MAP, SymmetryAxis(name="F", line=4.5))  # centre of gore 5
    assert line[:, 0] == pytest.approx(4.5 * MAP.column)
    assert line[0, 1] == 0.0 and line[-1, 1] == pytest.approx(MAP.length)
    (ring,) = ring_lines(MAP, 4.5, 5.0, 0.2)
    span = np.ptp(ring, axis=0)
    assert span == pytest.approx([0.4, 0.4], rel=1e-3)


def test_sketch_is_the_envelope_with_its_seams() -> None:
    sketch = envelope_sketch(SESSION.design)
    n = SESSION.design.gores.count  # type: ignore[union-attr]
    assert sketch.points.shape[1] == 3 and sketch.triangles.max() < len(sketch.points)
    rows = len(SESSION.design.gores.panel_rows)  # type: ignore[union-attr]
    assert len(sketch.seams) == n + rows - 1
    r = np.hypot(sketch.points[:, 0], sketch.points[:, 1])
    assert r.max() > 1.0
