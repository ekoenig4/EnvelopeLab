"""Segment profiles: lines, arcs and smooth curves with G1 joints (geometry.profile_segments)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.geometry.gore import MeridianProfile
from envelopelab.geometry.profile_segments import (
    Segment,
    arc_points,
    arc_radius,
    merge_segments,
    resolve_segments,
    segment_kinks,
    segment_points,
    split_segment,
)
from envelopelab.project.gore_design import SegmentLayout, profile_from_arrays

LINE = Segment("line", 0.0, False)
R = 3.0
#: Cone (r 1 -> 3 over 2 m), cylinder (4 m), quarter-circle cap tangent to the cylinder.
CAP_R = np.array([1.0, R, R, 0.0])
CAP_Z = np.array([0.0, 2.0, 6.0, 9.0])
CAP_SEGMENTS = [LINE, LINE, Segment("arc", 0.0, True)]


def test_arc_points_lie_on_their_circle() -> None:
    p0, p1 = np.array([3.0, 0.0]), np.array([0.0, 3.0])
    pts = arc_points(p0, p1, math.tan(math.pi / 8), 101)  # a quarter turn, counter-clockwise
    assert np.hypot(*pts.T) == pytest.approx(3.0, abs=1e-12)
    assert pts[50] == pytest.approx([3 / math.sqrt(2), 3 / math.sqrt(2)])
    assert arc_radius(float(np.hypot(*(p1 - p0))), math.tan(math.pi / 8)) == pytest.approx(3.0)
    assert math.isinf(arc_radius(1.0, 0.0))
    # Going up the right-hand side, a positive bulge bows outward (larger r).
    up = arc_points(np.array([2.0, 0.0]), np.array([2.0, 4.0]), 0.3, 21)
    assert up[10, 0] > 2.0


def test_cone_cylinder_and_tangent_cap_match_the_analytic_shape() -> None:
    spans = resolve_segments(CAP_R, CAP_Z, CAP_SEGMENTS)
    assert spans[2].bulge == pytest.approx(math.tan(math.pi / 8))  # tangent quarter circle
    profile = MeridianProfile.from_points(*segment_points(CAP_R, CAP_Z, CAP_SEGMENTS))
    cone = math.pi * 2.0 / 3.0 * (1.0 + R + R * R)
    assert profile.volume == pytest.approx(
        cone + math.pi * R**2 * 4.0 + 2 / 3 * math.pi * R**3, rel=1e-6
    )
    slant = math.hypot(2.0, 2.0)
    assert profile.meridian_length == pytest.approx(slant + 4.0 + math.pi * R / 2, rel=1e-6)
    assert segment_kinks(CAP_R, CAP_Z, CAP_SEGMENTS) == []


def test_all_curves_is_the_spline_and_all_lines_the_straight_segments() -> None:
    r = np.array([2.7, 5.0, 8.0, 8.5, 6.0, 2.0])
    z = np.array([0.0, 3.0, 7.0, 11.0, 15.0, 17.0])
    curves = SegmentLayout(tuple(Segment() for _ in range(5)))
    lines = SegmentLayout(tuple(LINE for _ in range(5)))
    assert np.array_equal(
        profile_from_arrays(r, z, curves).r, profile_from_arrays(r, z, "spline").r
    )
    assert np.array_equal(profile_from_arrays(r, z, lines).z, profile_from_arrays(r, z, "linear").z)
    # The segment sampler draws the same spline (only the sample positions differ).
    own = MeridianProfile.from_points(*segment_points(r, z, curves.segments))
    assert own.volume == pytest.approx(profile_from_arrays(r, z, "spline").volume, rel=1e-6)


def test_smooth_joints_are_tangent_continuous() -> None:
    r = np.array([2.0, 5.0, 8.0, 8.5, 6.0, 2.0])
    z = np.array([0.0, 3.0, 7.0, 11.0, 15.0, 17.0])
    segs = [LINE, Segment(), Segment(), Segment("arc", 0.0, True), Segment("line", 0.0, True)]
    spans = resolve_segments(r, z, segs)
    # Line -> curve run (clamped), curve -> arc (follows), arc -> line: the arc follows the
    # curve, so it cannot also meet the line: that joint is the only kink.
    assert spans[1].start_tangent == pytest.approx(spans[0].end_tangent, abs=1e-12)
    assert spans[3].start_tangent == pytest.approx(spans[2].end_tangent, abs=1e-12)
    kinks = segment_kinks(r, z, segs)
    assert [k for k, _ in kinks] == [4]


def test_an_arc_with_a_corner_start_is_made_tangent_to_the_next_line() -> None:
    r = np.array([2.0, 6.0, 6.0])
    z = np.array([0.0, 3.0, 8.0])
    segs = [Segment("arc", 0.0, False), Segment("line", 0.0, True)]
    spans = resolve_segments(r, z, segs)
    assert spans[0].end_tangent == pytest.approx(math.pi / 2)  # along the vertical line
    assert segment_kinks(r, z, segs) == []
    # Two lines that do not line up cannot be smooth: a kink, reported in radians.
    ((k, turn),) = segment_kinks(r, z, [LINE, Segment("line", 0.0, True)])
    # From (2, 0)-(6, 3) to the vertical (6, 3)-(6, 8).
    assert k == 1 and turn == pytest.approx(math.pi / 2 - math.atan2(3.0, 4.0), abs=1e-12)


def test_splitting_and_merging_keep_the_drawing() -> None:
    r = np.array([2.0, 6.0, 4.0])
    z = np.array([0.0, 4.0, 9.0])
    segs = [Segment("arc", 0.35, False), Segment("arc", -0.2, False)]
    whole = resolve_segments(r, z, segs)[0].points
    mid = whole[len(whole) // 2]
    first, second = split_segment(segs[0])
    halves = resolve_segments(
        np.array([2.0, mid[0], 6.0]), np.array([0.0, mid[1], 4.0]), [first, second]
    )
    radius = arc_radius(float(np.hypot(4.0, 4.0)), 0.35)
    for half in halves:
        chord = float(np.hypot(*(half.points[-1] - half.points[0])))
        assert arc_radius(chord, half.bulge) == pytest.approx(radius, rel=1e-3)
    merged = merge_segments(first, second)
    assert merged.kind == "arc" and merged.bulge == pytest.approx(0.35)
    assert merge_segments(LINE, LINE).kind == "line"
    assert merge_segments(LINE, Segment()).kind == "curve"


def test_invalid_segments_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown segment kind"):
        Segment("spiral")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bulge"):
        Segment("arc", 9.0)
    with pytest.raises(ValueError, match="need 2 segments"):
        resolve_segments([1.0, 2.0, 3.0], [0.0, 1.0, 2.0], [LINE])
