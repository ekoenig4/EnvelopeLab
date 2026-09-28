from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.geometry.polygon import (
    clean_polyline,
    corner_indices,
    distance_to_polyline,
    graded_fractions,
    interior_point,
    offset_polygon,
    orient_ccw,
    point_at_fractions,
    points_in_polygon,
    polyline_length,
    self_intersections,
    signed_area,
    split_edges,
    validate_outline,
)

SQUARE = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])


def test_signed_area_and_orientation() -> None:
    assert signed_area(SQUARE) == pytest.approx(1.0)
    assert signed_area(SQUARE[::-1]) == pytest.approx(-1.0)
    assert signed_area(orient_ccw(SQUARE[::-1])) == pytest.approx(1.0)


def test_clean_polyline_drops_duplicates_and_closing_vertex() -> None:
    pts = np.array([[0, 0], [0, 0], [1, 0], [1, 1e-6], [1, 1], [0, 1], [0, 0]], dtype=float)
    cleaned = clean_polyline(pts, 1e-4, closed=True)
    assert cleaned.tolist() == [[0, 0], [1, 0], [1, 1], [0, 1]]


def test_validate_outline_valid_square() -> None:
    check = validate_outline(SQUARE, closed=True)
    assert check.valid
    assert check.orientation == "ccw"
    assert check.area == pytest.approx(1.0)


def test_validate_outline_flags_open_bowtie_and_zero_area() -> None:
    bowtie = np.array([[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0]])
    check = validate_outline(bowtie, closed=True)
    assert not check.simple
    assert any("self-intersects" in issue for issue in check.issues)
    assert not validate_outline(SQUARE, closed=False).valid
    flat = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
    assert any("area" in issue for issue in validate_outline(flat, closed=True).issues)


def test_self_intersections_detects_collinear_overlap() -> None:
    # A spike that doubles back on itself along a straight line.
    pts = np.array(
        [
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 1.0],
            [1.0, 1.0],
            [1.0, 0.0],
            [0.5, 0.0],
            [0.5, 2.0],
            [0.0, 2.0],
        ]
    )
    assert self_intersections(pts)


@pytest.mark.parametrize("distance", [0.025, -0.025, 0.1, -0.2])
def test_offset_rectangle_exact(distance: float) -> None:
    rect = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]])
    out = offset_polygon(rect, distance)
    lo, hi = out.min(axis=0), out.max(axis=0)
    assert lo == pytest.approx([-distance, -distance])
    assert hi == pytest.approx([2.0 + distance, 1.0 + distance])
    assert validate_outline(out, True).valid


def test_offset_preserves_input_orientation() -> None:
    assert signed_area(offset_polygon(SQUARE[::-1], -0.1)) < 0


def test_inset_trims_swallowtail_at_clipped_corner() -> None:
    # Cut outline whose corners are clipped by a short edge (as in real pattern packs): a
    # raw bisector inset forms a small loop there, which must be trimmed.
    finished = np.array([[0.0, 0.0], [1.0, 0.0], [0.9, 1.0], [0.1, 1.0]])
    cut = offset_polygon(finished, 0.025)
    clip = cut.copy()
    # Replace the bottom-right corner by a short chamfer inside the mitre point.
    corner = clip[1]
    before = corner + 0.02 * (clip[0] - corner) / np.linalg.norm(clip[0] - corner)
    after = corner + 0.02 * (clip[2] - corner) / np.linalg.norm(clip[2] - corner)
    clipped = np.vstack([clip[:1], before, after, clip[2:]])
    inset = offset_polygon(clipped, -0.025)
    assert validate_outline(inset, True).valid
    assert np.max(distance_to_polyline(finished, inset, True)) < 5e-3


def test_offset_concave_polygon_is_valid() -> None:
    l_shape = np.array([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], dtype=float)
    for d in (-0.1, 0.1):
        out = offset_polygon(l_shape, d)
        assert validate_outline(out, True).valid
        # Mitred offset area: A + d P + d^2 sum(tan(turn/2)); five convex corners and one
        # reflex corner give sum = 5 - 1 = 4.
        perimeter = polyline_length(l_shape, closed=True)
        assert signed_area(out) == pytest.approx(3.0 + d * perimeter + 4.0 * d * d, rel=1e-12)


def test_corner_indices_window_ignores_jagged_edge() -> None:
    # A square whose bottom edge has a small zig-zag (4 mm high, 5 mm pitch).
    x = np.linspace(0.0, 1.0, 201)
    zig = np.where(np.arange(201) % 2 == 0, 0.0, 0.004)
    bottom = np.column_stack([x, zig])[:-1]
    pts = np.vstack([bottom, [[1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]])
    assert len(corner_indices(pts, 30.0, window=0.0)) > 4
    assert len(corner_indices(pts, 30.0, window=0.02)) == 4


def test_split_edges_names_trapezoid_sides() -> None:
    trap = np.array([[0.2, 0.0], [0.8, 0.0], [1.0, 1.0], [0.0, 1.0]])
    edges = {e.name: e for e in split_edges(trap)}
    assert set(edges) == {"bottom", "right", "top", "left"}
    assert edges["bottom"].length == pytest.approx(0.6)
    assert edges["top"].length == pytest.approx(1.0)
    assert edges["right"].points[0].tolist() == [0.8, 0.0]


def test_split_edges_circle_is_one_loop() -> None:
    a = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    circle = np.column_stack([np.cos(a), np.sin(a)])
    (edge,) = split_edges(circle)
    assert edge.name == "loop"
    assert edge.closed_loop
    assert edge.length == pytest.approx(2 * math.pi, rel=2e-3)


def test_point_at_fractions_hits_end_points() -> None:
    line = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    pts = point_at_fractions(line, [0.0, 0.25, 0.5, 1.0])
    assert pts.tolist() == [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0], [1.0, 1.0]]


def test_graded_fractions_refines_ends() -> None:
    f = graded_fractions(1.0, 0.1, 0.02, 1.3)
    assert f[0] == 0.0 and f[-1] == 1.0
    assert np.all(np.diff(f) > 0)
    steps = np.diff(f)
    assert steps[0] < 0.5 * steps[len(steps) // 2]
    uniform = graded_fractions(1.0, 0.1)
    assert len(uniform) == 11


def test_interior_point_of_crescent() -> None:
    a = np.linspace(0.0, math.pi, 50)
    outer = np.column_stack([np.cos(a), np.sin(a)])
    inner = np.column_stack([0.8 * np.cos(a[::-1]), 0.5 * np.sin(a[::-1])])
    crescent = np.vstack([outer, inner])
    point = interior_point(crescent)
    assert points_in_polygon(point, crescent)[0]
