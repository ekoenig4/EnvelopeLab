"""Bulk editing and simplifying of meridian control points (geometry.profile_editing)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.geometry import profile_editing as pe
from envelopelab.geometry.gore import MeridianProfile


def _arc(n: int = 25, radius: float = 8.0) -> tuple[np.ndarray, np.ndarray]:
    """Control points on a half circle from the bottom to the top of a sphere, m."""
    theta = np.linspace(-0.45 * math.pi, 0.45 * math.pi, n)
    return radius * np.cos(theta), radius * np.sin(theta)


def test_falloff_profiles() -> None:
    u = np.array([0.0, 0.5, 1.0, 1.5])
    assert pe.falloff_weight(u, "smooth") == pytest.approx([1.0, 0.5, 0.0, 0.0])
    assert pe.falloff_weight(u, "linear") == pytest.approx([1.0, 0.5, 0.0, 0.0])
    assert pe.falloff_weight(u, "sharp") == pytest.approx([1.0, 0.25, 0.0, 0.0])
    assert pe.falloff_weight(u, "sphere") == pytest.approx([1.0, math.sqrt(0.75), 0.0, 0.0])
    assert pe.falloff_weight(u, "constant") == pytest.approx([1.0, 1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="unknown falloff"):
        pe.falloff_weight(u, "wobbly")  # type: ignore[arg-type]


def test_soft_weights_follow_the_distance_along_the_profile() -> None:
    r, z = _arc()
    hard = pe.soft_weights(r, z, [12])
    assert hard[12] == 1.0 and np.count_nonzero(hard) == 1
    soft = pe.soft_weights(r, z, [12], radius=4.0)
    assert soft[12] == 1.0
    assert np.all(np.diff(soft[:13]) >= 0.0) and np.all(np.diff(soft[12:]) <= 0.0)
    step = pe.polygon_stations(r, z)[1]
    assert np.count_nonzero(soft) == 1 + 2 * int(4.0 / step - 1e-9)
    with pytest.raises(ValueError, match="at least one"):
        pe.soft_weights(r, z, [])
    with pytest.raises(IndexError):
        pe.soft_weights(r, z, [25])


def test_move_scale_and_rotate() -> None:
    r, z = _arc()
    r2, z2 = pe.move_points(r, z, [3, 4], 0.2, -0.1)
    assert r2[3:5] == pytest.approx(r[3:5] + 0.2) and z2[3:5] == pytest.approx(z[3:5] - 0.1)
    assert np.array_equal(np.delete(r2, [3, 4]), np.delete(r, [3, 4]))
    # Scaling about the selection's centroid keeps the centroid.
    sel = [8, 9, 10, 11]
    r3, z3 = pe.scale_points(r, z, sel, 1.5, 0.5)
    assert np.mean(r3[sel]) == pytest.approx(np.mean(r[sel]))
    assert np.ptp(z3[sel]) == pytest.approx(0.5 * np.ptp(z[sel]))
    # A quarter turn about a pivot.
    r4, z4 = pe.rotate_points(r, z, [5], math.pi / 2, pivot=(r[5] - 1.0, z[5]))
    assert (r4[5], z4[5]) == pytest.approx((r[5] - 1.0, z[5] + 1.0))
    # Radii never go negative.
    r5, _ = pe.move_points(r, z, [0], -100.0, 0.0)
    assert r5[0] == 0.0


def test_soft_move_is_a_smooth_bump() -> None:
    r, z = _arc(41)
    r2, _ = pe.move_points(r, z, [20], 0.5, 0.0, radius=3.0, falloff="smooth")
    d = r2 - r
    assert d[20] == pytest.approx(0.5)
    assert d[18] < 0.5 and d[22] < 0.5 and d[0] == 0.0 and d[-1] == 0.0
    assert d[15] == pytest.approx(d[25])  # symmetric about the selected point


def test_straighten_makes_a_straight_section() -> None:
    r, z = _arc()
    r2, z2 = pe.straighten_points(r, z, 4, 10)
    a, b = np.array([r2[4], z2[4]]), np.array([r2[10], z2[10]])
    for k in range(5, 10):
        p = np.array([r2[k], z2[k]])
        cross = (b - a)[0] * (p - a)[1] - (b - a)[1] * (p - a)[0]
        assert abs(cross) < 1e-12
    assert (r2[4], z2[4], r2[10], z2[10]) == (r[4], z[4], r[10], z[10])
    assert np.array_equal(r2[11:], r[11:]) and np.array_equal(r2[:4], r[:4])
    stations = pe.polygon_stations(r2[4:11], z2[4:11])
    assert np.all(np.diff(stations) > 0.0)  # order kept
    with pytest.raises(ValueError, match="at least one between"):
        pe.straighten_points(r, z, 4, 5)


def test_smoothing_removes_a_kink_and_keeps_the_ends() -> None:
    r, z = _arc()
    r[12] += 0.6  # a kink
    r2, z2 = pe.smooth_points(r, z, list(range(25)), strength=0.5, iterations=3)
    assert (r2[0], z2[0], r2[-1], z2[-1]) == (r[0], z[0], r[-1], z[-1])
    rough = np.abs(np.diff(r, 2)).max()
    assert np.abs(np.diff(r2, 2)).max() < 0.5 * rough
    with pytest.raises(ValueError):
        pe.smooth_points(r, z, [3], strength=0.0)


def test_curvature_of_a_circle_is_one_over_its_radius() -> None:
    theta = np.linspace(-0.45 * math.pi, 0.45 * math.pi, 4001)
    profile = MeridianProfile.from_points(8.0 * np.cos(theta), 8.0 * np.sin(theta))
    assert pe.curvature(profile) == pytest.approx(1.0 / 8.0, rel=1e-6)
    line = MeridianProfile.from_points([1.0, 2.0, 3.0], [0.0, 1.0, 2.0])
    assert pe.curvature(line) == pytest.approx(0.0, abs=1e-12)


def test_profile_deviation_is_the_largest_distance() -> None:
    a = MeridianProfile.from_control_points(*_arc(), samples=2001)
    assert pe.profile_deviation(a, a) == pytest.approx(0.0, abs=1e-12)
    r, z = _arc()
    b = MeridianProfile.from_control_points(r, z + 0.01, samples=2001)
    # A 10 mm vertical shift of an arc: at most 10 mm apart, about 10 mm at the sides.
    assert pe.profile_deviation(a, b) == pytest.approx(0.01, rel=0.05)


@pytest.mark.parametrize("tolerance", [0.01, 0.002, 0.0005])
def test_simplify_spline_meets_the_tolerance_with_fewer_points(tolerance: float) -> None:
    r, z = _arc(60)
    r[30:] *= 1.0 + 0.05 * np.sin(np.linspace(0.0, math.pi, 30))  # a shoulder
    result = pe.simplify_profile(r, z, tolerance)
    assert result.within_tolerance and result.count < 60
    assert (result.r[0], result.z[0]) == pytest.approx((r[0], z[0]))
    assert (result.r[-1], result.z[-1]) == pytest.approx((r[-1], z[-1]))
    original = MeridianProfile.from_control_points(r, z)
    fit = MeridianProfile.from_control_points(result.r, result.z)
    assert pe.profile_deviation(original, fit) <= tolerance * 1.01


def test_simplify_straight_segments_keeps_a_subset_of_the_points() -> None:
    # Two straight sections (cone, cylinder) with many points each, and a cap arc.
    r = np.concatenate((np.linspace(2.0, 6.0, 15), np.full(10, 6.0), [5.5, 4.0, 2.0]))
    z = np.concatenate((np.linspace(0.0, 6.0, 15), np.linspace(6.6, 12.0, 10), [13, 14, 14.5]))
    result = pe.simplify_profile(r, z, 0.001, "linear")
    assert result.within_tolerance and result.deviation <= 1e-9
    assert result.count == 6  # the corners only
    pairs = set(zip(r.tolist(), z.tolist(), strict=True))
    assert set(zip(result.r.tolist(), result.z.tolist(), strict=True)) <= pairs


def test_simplify_reports_a_tolerance_it_cannot_meet() -> None:
    r, z = _arc(6)
    result = pe.simplify_profile(r, z, 1e-6, max_points=4)
    assert not result.within_tolerance and result.count <= 4
    with pytest.raises(ValueError, match="positive"):
        pe.simplify_profile(r, z, 0.0)


@settings(max_examples=40, deadline=None)
@given(
    st.lists(st.integers(1, 23), min_size=1, max_size=5),
    st.floats(-0.5, 0.5),
    st.floats(-0.5, 0.5),
    st.floats(0.0, 5.0),
    st.sampled_from(pe.FALLOFFS),
)
def test_a_soft_move_moves_each_point_by_its_weight(
    selected: list[int], dr: float, dz: float, radius: float, falloff: pe.Falloff
) -> None:
    r, z = _arc()
    w = pe.soft_weights(r, z, selected, radius, falloff)
    assert np.all((w >= 0.0) & (w <= 1.0))
    r2, z2 = pe.move_points(r, z, selected, dr, dz, radius, falloff)
    assert r2 - r == pytest.approx(w * dr, abs=1e-12)
    assert z2 - z == pytest.approx(w * dz, abs=1e-12)
