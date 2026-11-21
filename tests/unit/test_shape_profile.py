"""Editing a revolved shape's profile by hand (envelopelab.project.shape_profile)."""

from __future__ import annotations

import numpy as np
import pytest

from envelopelab.features.primitives import Revolved
from envelopelab.project.shape_profile import (
    MIN_RADIUS,
    SPLIT_MARGIN,
    insert_profile_point,
    move_profile_points,
    move_split,
    profile_curve,
    remove_profile_point,
    scale_profile,
    split_fraction_at,
    split_points,
)
from envelopelab.project.shapes import RevolvedShape, ShapePlacement, to_primitive

#: A stalk with a ball on top, ending on the axis (generic test geometry).
ANTENNA = [
    (0.44, 0.0),
    (0.30, 1.2),
    (0.30, 1.55),
    (0.55, 1.85),
    (0.6, 2.15),
    (0.45, 2.5),
    (0.0, 2.7),
]


def _spec(profile: list[tuple[float, float]] = ANTENNA, splits: list[float] = []) -> RevolvedShape:  # noqa: B006
    return RevolvedShape(
        name="Antenna",
        placement=ShapePlacement(gore=3, tape_position=10.0),
        profile=profile,
        gores=12,
        splits=splits,
    )


def test_moving_points_keeps_the_base_on_the_base_circle_and_the_tip_on_the_axis() -> None:
    moved = move_profile_points(ANTENNA, [0, 6], 0.1, 0.2)
    assert moved[0] == pytest.approx((0.54, 0.0))  # slides out, stays at zeta = 0
    assert moved[6] == pytest.approx((0.0, 2.9))  # rises, stays on the axis
    assert np.asarray(moved[1:6]) == pytest.approx(np.asarray(ANTENNA[1:6]))


def test_points_are_kept_off_the_axis() -> None:
    moved = move_profile_points(ANTENNA, [2], -1.0, 0.0)
    assert moved[2][0] == MIN_RADIUS
    _spec(moved)  # still a valid shape


def test_soft_selection_moves_the_neighbours_partly() -> None:
    moved = move_profile_points(ANTENNA, [4], 0.1, 0.0, radius=0.5)
    assert moved[4][0] == pytest.approx(0.7)
    assert 0.55 < moved[3][0] < 0.65 and 0.45 < moved[5][0] < 0.55
    assert moved[0] == ANTENNA[0]


def test_scaling_the_whole_profile_keeps_it_on_its_base_point() -> None:
    bigger = scale_profile(ANTENNA, 1.25, 1.25)
    assert np.asarray(bigger) == pytest.approx(1.25 * np.asarray(ANTENNA))
    taller = scale_profile(ANTENNA, 1.0, 2.0)
    assert [r for r, _ in taller] == pytest.approx([r for r, _ in ANTENNA])
    assert taller[-1][1] == pytest.approx(5.4)


def test_scaling_a_selection_grows_it_about_its_centroid() -> None:
    ball = [3, 4, 5]
    bigger = scale_profile(ANTENNA, 1.5, 1.5, selected=ball)
    centroid = np.mean([ANTENNA[i] for i in ball], axis=0)
    for i in ball:
        assert bigger[i] == pytest.approx(
            tuple(centroid + 1.5 * (np.asarray(ANTENNA[i]) - centroid))
        )
    assert bigger[:3] == ANTENNA[:3] and bigger[6] == ANTENNA[6]


@pytest.mark.parametrize("factor", [0.0, -1.0, float("inf"), float("nan")])
def test_bad_scale_factors_are_refused(factor: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        scale_profile(ANTENNA, factor, 1.0)


def test_inserting_a_point_puts_it_on_the_nearest_side() -> None:
    out, k = insert_profile_point(ANTENNA, 0.31, 1.4)
    assert k == 2 and out[2] == (0.31, 1.4) and len(out) == len(ANTENNA) + 1
    out, k = insert_profile_point(ANTENNA, 0.5, -0.5)  # below the base: after it, never before
    assert k == 1 and out[0] == ANTENNA[0]


def test_removing_points_keeps_the_base_and_two_points() -> None:
    assert remove_profile_point(ANTENNA, 3) == ANTENNA[:3] + ANTENNA[4:]
    with pytest.raises(ValueError, match="base"):
        remove_profile_point(ANTENNA, 0)
    with pytest.raises(ValueError, match="two points"):
        remove_profile_point(ANTENNA[:2], 1)


def test_split_points_lie_on_the_curve_at_their_arc_fraction() -> None:
    spec = _spec(splits=[0.25, 0.6])
    prim = to_primitive(spec)
    assert isinstance(prim, Revolved)
    rho, zeta = prim.meridian()
    arc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(rho), np.diff(zeta)))])
    pts = split_points(spec)
    for (r, z), f in zip(pts, spec.splits, strict=True):
        i = int(np.argmin(np.hypot(rho - r, zeta - z)))
        assert arc[i] / arc[-1] == pytest.approx(f, abs=1e-3)
        assert split_fraction_at(spec, float(r), float(z)) == pytest.approx(f, abs=1e-3)


def test_a_split_picked_at_the_neck_and_its_limits() -> None:
    spec = _spec()
    neck = split_fraction_at(spec, 0.30, 1.55)
    assert 0.3 < neck < 0.7
    assert split_fraction_at(spec, 0.44, -1.0) == SPLIT_MARGIN
    assert split_fraction_at(spec, 0.0, 10.0) == 1.0 - SPLIT_MARGIN


def test_moving_a_split_keeps_the_splits_in_order() -> None:
    assert move_split([0.3, 0.6], 0, 0.45) == [0.45, 0.6]
    assert move_split([0.3, 0.6], 0, 0.9) == pytest.approx([0.6 - SPLIT_MARGIN, 0.6])
    assert move_split([0.3, 0.6], 1, 0.1) == pytest.approx([0.3, 0.3 + SPLIT_MARGIN])
    with pytest.raises(IndexError):
        move_split([0.3], 1, 0.5)


def test_the_drawn_curve_is_the_shapes_meridian() -> None:
    curve = profile_curve(ANTENNA, smooth=True)
    prim = to_primitive(_spec().model_copy(update={"cap_diameter": 0.0}))  # pointed
    assert isinstance(prim, Revolved)
    rho, zeta = prim.meridian(401)
    assert curve == pytest.approx(np.column_stack([rho, zeta]))
    straight = profile_curve(ANTENNA, smooth=False)
    assert straight[0] == pytest.approx(ANTENNA[0]) and straight[-1] == pytest.approx(ANTENNA[-1])
