from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.geometry.gore import (
    GoreWidthModel,
    MeridianProfile,
    SeamAllowance,
    half_width_chord,
    half_width_small_bulge,
    polygon_area,
    profile_from_gore_widths,
    split_rows,
)


def sphere(
    radius: float, lower: float = -math.pi / 2, upper: float = math.pi / 2
) -> MeridianProfile:
    theta = np.linspace(lower, upper, 2001)
    return MeridianProfile.from_points(radius * np.cos(theta), radius * np.sin(theta))


def test_sphere_volume_area_within_tolerance() -> None:
    profile = sphere(7.5)
    assert profile.volume == pytest.approx(4 / 3 * math.pi * 7.5**3, rel=1e-3)
    assert profile.area == pytest.approx(4 * math.pi * 7.5**2, rel=1e-3)
    assert profile.height == pytest.approx(15.0)
    assert profile.max_width == pytest.approx(15.0, rel=1e-6)
    assert profile.meridian_length == pytest.approx(math.pi * 7.5, rel=1e-3)


def test_cylinder_volume_area() -> None:
    profile = MeridianProfile.from_control_points([2.0, 2.0], [0.0, 5.0])
    assert profile.volume == pytest.approx(math.pi * 4 * 5, rel=1e-3)
    assert profile.area == pytest.approx(2 * math.pi * 2 * 5, rel=1e-3)


def test_control_point_spline_reproduces_sphere() -> None:
    theta = np.linspace(-math.pi / 2, math.pi / 2, 25)
    profile = MeridianProfile.from_control_points(6 * np.cos(theta), 6 * np.sin(theta))
    assert profile.volume == pytest.approx(4 / 3 * math.pi * 216, rel=1e-3)


def test_profile_validation() -> None:
    with pytest.raises(ValueError):
        MeridianProfile.from_points([1.0, 1.0], [0.0, 0.0])
    with pytest.raises(ValueError):
        MeridianProfile.from_points([-1.0, 1.0], [0.0, 1.0])


def test_width_forms_limits() -> None:
    r = np.array([1.0, 4.0])
    n = 16
    np.testing.assert_allclose(half_width_small_bulge(r, n), math.pi * r / n)
    np.testing.assert_allclose(half_width_chord(r, n), r * math.sin(math.pi / n))
    # Bulge radius equal to r reproduces the small-bulge form exactly.
    np.testing.assert_allclose(half_width_chord(r, n, r), math.pi * r / n)
    # A tighter lobe (smaller bulge radius) needs more fabric.
    assert np.all(half_width_chord(r, n, 0.5 * r) > math.pi * r / n)
    with pytest.raises(ValueError):
        half_width_chord(r, n, 0.01)


@pytest.mark.parametrize(
    "model",
    [
        GoreWidthModel(20),
        GoreWidthModel(20, "chord"),
        GoreWidthModel(20, "chord", bulge_radius=3.0),
        GoreWidthModel(20, "chord", bulge_ratio=0.6),
    ],
)
def test_width_model_inverse(model: GoreWidthModel) -> None:
    r = np.linspace(0.5, 9.0, 30)
    np.testing.assert_allclose(model.radius_from_full_width(model.full_width(r)), r, rtol=1e-12)


def test_width_model_validation() -> None:
    with pytest.raises(ValueError):
        GoreWidthModel(2)
    with pytest.raises(ValueError):
        GoreWidthModel(12, "small_bulge", bulge_radius=1.0)
    with pytest.raises(ValueError):
        GoreWidthModel(12, "chord", bulge_radius=1.0, bulge_ratio=1.0)
    with pytest.raises(ValueError):
        GoreWidthModel(12, "chord", bulge_ratio=0.1)


def test_rows_cover_sphere_and_sum_to_surface_area() -> None:
    profile = sphere(5.0)
    model = GoreWidthModel(12)
    heights = [profile.meridian_length / 5] * 5
    rows = split_rows(profile, model, heights)
    assert [row.label for row in rows] == ["A", "B", "C", "D", "E"]
    assert 12 * sum(row.finished_area for row in rows) == pytest.approx(profile.area, rel=1e-6)
    for lower, upper in zip(rows[:-1], rows[1:], strict=True):
        assert lower.top_width == pytest.approx(upper.bottom_width, abs=1e-12)
        assert lower.s_top == pytest.approx(upper.s_bottom)
    equator = rows[2]
    assert equator.loft[2].width == pytest.approx(2 * math.pi * 5.0 / 12, rel=1e-6)
    assert [station.fraction for station in equator.loft] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert equator.loft[0].width == pytest.approx(equator.bottom_width)
    assert equator.loft[-1].width == pytest.approx(equator.top_width)


def test_row_coverage_errors() -> None:
    profile = sphere(5.0)
    model = GoreWidthModel(12)
    with pytest.raises(ValueError, match="meridian"):
        split_rows(profile, model, [1.0, 1.0])
    with pytest.raises(ValueError, match="beyond"):
        split_rows(profile, model, [profile.meridian_length + 0.1])
    rows = split_rows(profile, model, [1.0, 1.0], require_full_coverage=False)
    assert rows[-1].s_top == pytest.approx(2.0)


def rectangle_edge(width: float, height: float) -> np.ndarray:
    y = np.linspace(0.0, height, 11)
    return np.column_stack((np.full_like(y, width / 2), y))


def test_cut_outline_rectangle_miter_and_bevel() -> None:
    profile = MeridianProfile.from_points([2.0, 2.0], [0.0, 3.0])
    model = GoreWidthModel(8)
    allowance = SeamAllowance(side=0.02, bottom=0.01, top=0.03)
    (row,) = split_rows(profile, model, [3.0], allowance=allowance)
    width = 2 * math.pi * 2.0 / 8
    assert row.finished_area == pytest.approx(width * 3.0)
    assert row.cut_area == pytest.approx((width + 0.04) * (3.0 + 0.04), rel=1e-9)
    xs, ys = row.cut_outline[:, 0], row.cut_outline[:, 1]
    assert xs.max() == pytest.approx(width / 2 + 0.02)
    assert ys.min() == pytest.approx(-0.01) and ys.max() == pytest.approx(3.03)
    (bevel,) = split_rows(profile, model, [3.0], allowance=allowance, corner="bevel")
    corner_loss = 2 * (0.02 * 0.01 / 2 + 0.02 * 0.03 / 2)
    assert bevel.cut_area == pytest.approx(row.cut_area - corner_loss, rel=1e-9)


def test_cut_outline_of_tapered_panel_offsets_every_edge() -> None:
    profile = sphere(5.0)
    rows = split_rows(
        profile,
        GoreWidthModel(12),
        [profile.meridian_length / 4] * 4,
        allowance=SeamAllowance(0.015, 0.01, 0.01),
    )
    for row in rows:
        assert row.cut_area > row.finished_area
        # The allowance strip is about perimeter x allowance.
        strip = 2 * row.side_length * 0.015 + (row.bottom_width + row.top_width) * 0.01
        assert row.cut_area - row.finished_area == pytest.approx(strip, rel=0.05)
        assert polygon_area(row.cut_outline) == row.cut_area


def test_round_trip_profile_gores_profile_via_loft_tables() -> None:
    """Measure widths only at the loft stations, as a builder would, then recover r and z."""
    profile = sphere(9.0, -math.radians(50), math.radians(75))
    model = GoreWidthModel(24)
    rows = split_rows(profile, model, [profile.meridian_length / 12] * 12)
    stations = np.unique([row.s_bottom + st.y for row in rows for st in row.loft])
    widths = [
        next(st.width for row in rows for st in row.loft if abs(row.s_bottom + st.y - s) < 1e-12)
        for s in stations
    ]
    result = profile_from_gore_widths(stations, widths, model)
    assert not result.outliers.any()
    assert result.slope_clipped == 0
    check = np.linspace(0.0, profile.meridian_length, 400)
    assert np.max(np.abs(result.profile.radius_at(check) - profile.radius_at(check))) < 1e-3
    z_ref = profile.height_at(check) - profile.z[0]
    assert np.max(np.abs(result.profile.height_at(check) - z_ref)) < 1e-3


def test_inverse_flags_outliers_and_reports_residuals() -> None:
    profile = sphere(9.0, -math.radians(50), math.radians(75))
    model = GoreWidthModel(24)
    s = np.linspace(0.0, profile.meridian_length, 80)
    rng = np.random.default_rng(7)
    widths = model.full_width(profile.radius_at(s)) + rng.normal(0.0, 0.0005, s.size)
    widths[30] += 0.06
    widths[0] -= 0.05
    result = profile_from_gore_widths(s, widths, model)
    assert set(np.flatnonzero(result.outliers)) == {0, 30}
    assert result.residuals[30] > 0.1
    assert result.rms_residual < 0.005
    assert np.max(np.abs(result.fitted_radius[5:-5] - profile.radius_at(s)[5:-5])) < 5e-3


def test_inverse_input_validation() -> None:
    model = GoreWidthModel(12)
    with pytest.raises(ValueError):
        profile_from_gore_widths([0, 1, 2], [1, 1, 1], model)
    with pytest.raises(ValueError):
        profile_from_gore_widths(np.zeros(10), np.ones(10), model)
