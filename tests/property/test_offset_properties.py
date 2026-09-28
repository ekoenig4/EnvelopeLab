"""Property tests: a valid panel polygon stays valid under a supported allowance offset.

A *supported* offset is one smaller than the local feature size of the outline. The
star-shaped polygons generated here have radii between 1 and 2 m and angular gaps of at
least 12 degrees, so every edge is longer than 0.2 m; seam allowances up to 60 mm are
well below their feature size, and these tests check that the offsets stay valid.
"""

from __future__ import annotations

import math

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.geometry.polygon import (
    distance_to_polyline,
    offset_polygon,
    points_in_polygon,
    polyline_length,
    signed_area,
    validate_outline,
)

MAX_ALLOWANCE = 0.06  # m


@st.composite
def star_polygons(draw: st.DrawFn) -> np.ndarray:
    n = draw(st.integers(min_value=3, max_value=16))
    gaps = draw(st.lists(st.floats(min_value=1.0, max_value=4.0), min_size=n, max_size=n))
    angles = np.cumsum(gaps)
    angles = angles / angles[-1] * 2 * math.pi
    if np.min(np.diff(np.concatenate([[0.0], angles]))) < math.radians(12):
        angles = np.linspace(0.0, 2 * math.pi, n, endpoint=False)
    radii = draw(st.lists(st.floats(min_value=1.0, max_value=2.0), min_size=n, max_size=n))
    pts = np.column_stack([np.cos(angles), np.sin(angles)]) * np.array(radii)[:, None]
    return np.asarray(pts, dtype=np.float64)


allowances = st.floats(min_value=0.001, max_value=MAX_ALLOWANCE)


@settings(max_examples=150, deadline=None)
@given(star_polygons(), allowances)
def test_inset_of_valid_polygon_is_valid(polygon: np.ndarray, allowance: float) -> None:
    assert validate_outline(polygon, True).valid
    inset = offset_polygon(polygon, -allowance)
    check = validate_outline(inset, True)
    assert check.valid, check.issues
    assert signed_area(inset) < signed_area(polygon)
    # Every inset vertex lies inside the cut outline at least one allowance from it.
    assert np.all(points_in_polygon(inset, polygon))
    assert np.min(distance_to_polyline(inset, polygon, True)) >= allowance * (1 - 1e-9)


@settings(max_examples=150, deadline=None)
@given(star_polygons(), allowances)
def test_outset_of_valid_polygon_is_valid(polygon: np.ndarray, allowance: float) -> None:
    grown = offset_polygon(polygon, allowance)
    check = validate_outline(grown, True)
    assert check.valid, check.issues
    # Area grows by at least allowance x perimeter (mitre and bevel corners add more).
    gain = signed_area(grown) - signed_area(polygon)
    assert gain >= allowance * polyline_length(polygon, True) * (1 - 1e-9)


@settings(max_examples=100, deadline=None)
@given(star_polygons(), allowances)
def test_cut_then_finish_round_trip(polygon: np.ndarray, allowance: float) -> None:
    """Growing a finished outline by the allowance and insetting it again restores it."""
    cut = offset_polygon(polygon, allowance, max_miter=1e9)
    back = offset_polygon(cut, -allowance, max_miter=1e9)
    assert validate_outline(back, True).valid
    assert np.max(distance_to_polyline(polygon, back, True)) < 1e-6
    assert abs(signed_area(back) - signed_area(polygon)) < 1e-6 * signed_area(polygon)
