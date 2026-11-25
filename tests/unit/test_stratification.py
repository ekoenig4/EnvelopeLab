"""Level-1 stratification: volume by height, profile, mean, floor and pressure."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.atmosphere import PhysicalConstant
from envelopelab.stratification import (
    DEFAULT_MOUTH_EXCESS,
    StratificationModel,
    VolumeDistribution,
)

T_AMB, T_TOP = 288.15, 393.15


def _cone(apex_up: bool) -> VolumeDistribution:
    z = np.linspace(0.0, 10.0, 101)
    r = 5.0 * (1.0 - z / 10.0) if apex_up else 5.0 * z / 10.0 + 1e-9
    return VolumeDistribution.from_profile(r, z)


def _model(dist: VolumeDistribution, phi: float = 0.5, floor: float = 0.0) -> StratificationModel:
    return StratificationModel(
        dist,
        PhysicalConstant(phi, "-", "assumed", ""),
        PhysicalConstant(floor, "K", "assumed", ""),
    )


def test_default_mouth_excess_is_tagged_assumed() -> None:
    assert DEFAULT_MOUTH_EXCESS.value == 0.5 and DEFAULT_MOUTH_EXCESS.source == "assumed"


def test_volume_by_height_of_a_cone() -> None:
    up = _cone(apex_up=True)  # wide at the mouth
    assert up.total == pytest.approx(math.pi * 25.0 * 10.0 / 3.0, rel=1e-6)
    assert up.weights.sum() == pytest.approx(1.0)
    # Two thirds of a cone's height below the middle hold 7/8 of its volume.
    assert up.weights[up.fractions < 0.5].sum() == pytest.approx(7.0 / 8.0, abs=2e-3)


def test_scaling_to_the_lofted_volume_keeps_the_distribution() -> None:
    z = np.linspace(0.0, 10.0, 11)
    plain = VolumeDistribution.from_profile(np.ones_like(z), z)
    scaled = VolumeDistribution.from_profile(np.ones_like(z), z, volume=40.0)
    assert scaled.total == 40.0 and scaled.volumes.sum() == pytest.approx(40.0)
    assert np.allclose(scaled.weights, plain.weights)


def test_shape_decides_the_offset() -> None:
    # Volume high up (cone wide at the crown) sits in hot gas: smaller offset.
    top_heavy = _model(_cone(apex_up=False)).offset(T_TOP, T_AMB)
    bottom_heavy = _model(_cone(apex_up=True)).offset(T_TOP, T_AMB)
    assert top_heavy < bottom_heavy


def test_floor_and_the_profile_it_implies() -> None:
    # Top-heavy cone: 13.4 K offset at phi = 0.5, 27.4 K with the mouth at ambient.
    model = _model(_cone(apex_up=False), floor=20.0)
    assert model.floor_applies(T_TOP, T_AMB)
    assert model.offset(T_TOP, T_AMB) == pytest.approx(20.0)
    phi = model.excess_used(T_TOP, T_AMB)
    assert 0.0 <= phi < 0.5
    t = model.profile(T_TOP, T_AMB, [0.0, model.distribution.crown_height])
    assert t[1] == pytest.approx(T_TOP)  # the crown keeps its temperature
    assert model.effective_mean(T_TOP, T_AMB, phi) == pytest.approx(T_TOP - 20.0)
    # A floor no linear profile reaches: the mean is the floor's, the profile phi = 0.
    deep = _model(_cone(apex_up=False), floor=40.0)
    assert deep.offset(T_TOP, T_AMB) == pytest.approx(40.0)
    assert deep.excess_used(T_TOP, T_AMB) == 0.0


def test_pressure_profile_starts_at_zero_and_grows_faster_near_the_crown() -> None:
    model = _model(_cone(apex_up=True))
    h = np.linspace(0.0, 10.0, 11)
    dp = model.pressure_profile(T_TOP, T_AMB, 101325.0, h)
    assert dp[0] == 0.0
    assert np.all(np.diff(np.diff(dp)) > 0.0)  # hotter gas higher up: convex


def test_bad_parameters_are_refused() -> None:
    dist = _cone(apex_up=True)
    with pytest.raises(ValueError):
        _model(dist, phi=1.5)
    with pytest.raises(ValueError):
        _model(dist, floor=-1.0)
    with pytest.raises(ValueError):
        VolumeDistribution.from_profile([1.0, 1.0], [0.0, 0.0])


@settings(max_examples=150, deadline=None)
@given(
    st.floats(0.0, 1.0),
    st.floats(0.0, 40.0),
    st.floats(243.15, 318.15),
    st.floats(20.0, 150.0),
)
def test_mean_inverts_and_respects_the_floor(
    phi: float, floor: float, ambient: float, rise: float
) -> None:
    model = _model(_cone(apex_up=True), phi, floor)
    top = ambient + rise
    mean = model.mean_from_top(top, ambient)
    assert top - mean >= floor - 1e-9
    assert mean <= top + 1e-9
    assert model.top_from_mean(mean, ambient) == pytest.approx(top, abs=1e-6)
    assert model.mean_from_top(top + 5.0, ambient) > mean  # monotonic


def test_inverse_of_a_very_hot_mean_does_not_fail() -> None:
    # Near the most an envelope lifts, the mean needed is thousands of kelvin; the crown
    # that gives it lies far beyond the first bracket (regression: brentq sign error).
    model = _model(_cone(apex_up=True), 0.5, 12.0)
    top = model.top_from_mean(3000.0, T_AMB)
    assert model.mean_from_top(top, T_AMB) == pytest.approx(3000.0)
