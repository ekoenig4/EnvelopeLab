"""Axisymmetric membrane check and natural shape vs closed forms (AGENTS.md 6.4)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import gamma

from envelopelab.geometry.gore import MeridianProfile
from envelopelab.solvers.axisymmetric import (
    AxisymmetricLoad,
    _integrate,
    _rebuild,
    hold_shape,
    membrane_check,
    natural_shape,
)

P = 1000.0  # Pa
R = 2.0  # m


def sphere(radius: float = R, cut: float = 0.15) -> MeridianProfile:
    """Meridian of a sphere from near its bottom pole to near its top pole."""
    phi = np.linspace(-math.pi / 2 + cut, math.pi / 2 - cut, 4001)
    return MeridianProfile.from_points(radius * np.cos(phi), radius * np.sin(phi))


def test_sphere_under_uniform_pressure_has_p_r_over_two_both_ways() -> None:
    check = membrane_check(sphere(), AxisymmetricLoad(0.0, base_pressure=P))
    inner = check.evaluated & (check.s > 0.05 * check.s[-1]) & (check.s < 0.95 * check.s[-1])
    assert check.evaluated.mean() > 0.9
    np.testing.assert_allclose(check.meridional[inner], P * R / 2, rtol=2e-3)
    np.testing.assert_allclose(check.hoop[inner], P * R / 2, rtol=2e-3)
    assert not np.any(check.hoop_compression)


def test_closed_cylinder_has_hoop_p_r_and_axial_p_r_over_two() -> None:
    z = np.linspace(0.0, 5.0, 2001)
    cylinder = MeridianProfile.from_points(np.full_like(z, R), z)
    check = membrane_check(cylinder, AxisymmetricLoad(0.0, base_pressure=P))
    np.testing.assert_allclose(check.meridional, P * R / 2, rtol=1e-9)
    np.testing.assert_allclose(check.hoop, P * R, rtol=1e-9)


def test_hydrostatic_vertical_equilibrium_matches_a_hand_integral() -> None:
    # Cylinder, pressure growing with height, open bottom: N_m = p(z_top) R / 2 at every
    # height (only the top cap pushes up), hoop = p(z) R.
    z = np.linspace(0.0, 4.0, 2001)
    cylinder = MeridianProfile.from_points(np.full_like(z, R), z)
    load = AxisymmetricLoad(pressure_gradient=30.0)
    check = membrane_check(cylinder, load)
    np.testing.assert_allclose(check.meridional, 30.0 * 4.0 * R / 2, rtol=1e-9)
    np.testing.assert_allclose(check.hoop, 30.0 * z * R, rtol=1e-9, atol=1e-9)


def test_mylar_balloon_aspect_ratio() -> None:
    """Uniform pressure, no weight, zero hoop stress from pole to pole: thickness over
    diameter is sqrt(2) pi^(3/2) / Gamma(1/4)^2 = 0.59907 [Paulsen]."""
    exact = math.sqrt(2.0) * math.pi**1.5 / gamma(0.25) ** 2
    load = AxisymmetricLoad(0.0, base_pressure=P)
    # Start a hair off the pole, flat, with the tension that carries the equatorial disk.
    rows = _integrate(load, 1e-6 * R, 0.0, 0.0, math.pi * R**2 * P, 3.0 * R, None, 6000)
    diameter = 2.0 * float(rows[:, 0].max())
    thickness = float(rows[-1, 1])
    assert diameter == pytest.approx(2.0 * R, rel=1e-4)
    assert thickness / diameter == pytest.approx(exact, rel=1e-4)


def hot_air() -> AxisymmetricLoad:
    return AxisymmetricLoad(pressure_gradient=2.7, areal_weight=0.8)


def test_natural_shape_has_no_hoop_stress_and_balances_at_the_mouth() -> None:
    load = hot_air()
    shape = natural_shape(load, (1.0, 0.0), 0.8, length=9.7)
    assert shape.converged
    assert shape.profile.r[-1] == pytest.approx(0.8, abs=1e-6)
    # The 401-point polyline is shorter than the arc by its chord error (2e-6).
    assert shape.profile.meridian_length == pytest.approx(9.7, rel=1e-5)
    check = membrane_check(shape.profile, load)
    assert float(np.nanmax(np.abs(check.hoop))) <= 0.01 * check.scale
    # Global equilibrium: the mouth tension's vertical part carries pressure lift on the
    # envelope and top cap minus the weight (the check's V at the mouth), within 0.5 %.
    lift = 2.0 * math.pi * check.r[0] * check.meridional[0] * math.sin(shape.mouth_angle)
    assert shape.tension[0] * math.sin(shape.mouth_angle) == pytest.approx(lift, rel=5e-3)


def test_natural_shape_can_keep_the_height_instead() -> None:
    shape = natural_shape(hot_air(), (1.0, 0.0), 0.8, height=7.0)
    assert shape.converged
    assert shape.profile.height == pytest.approx(7.0, rel=1e-6)
    with pytest.raises(ValueError, match="exactly one"):
        natural_shape(hot_air(), (1.0, 0.0), 0.8)


def test_the_rebuild_reproduces_a_drawn_profile() -> None:
    profile = sphere()
    seg = np.unwrap(np.arctan2(np.diff(profile.z), np.diff(profile.r)))
    ds = np.diff(profile.s)
    curvature = np.zeros(profile.s.size)
    curvature[1:-1] = np.diff(seg) / (0.5 * (ds[:-1] + ds[1:]))
    curvature[0], curvature[-1] = curvature[1], curvature[-2]
    r, z = _rebuild(
        profile.s,
        curvature,
        np.zeros(profile.s.size),
        float(profile.r[0]),
        float(profile.z[0]),
        float(seg[0]),
    )
    assert float(np.max(np.hypot(r - profile.r, z - profile.z))) < 1e-3


def test_a_shape_that_holds_is_left_alone_and_one_that_does_not_is_fixed() -> None:
    load = hot_air()
    natural = natural_shape(load, (1.0, 0.0), 0.8, length=9.7).profile
    held = hold_shape(natural, load, hoop_margin=0.0)
    assert held.converged and held.changed < 0.02
    # A tall, narrow-shouldered profile needs hoop compression low down.
    s = np.linspace(0.0, 1.0, 4001)
    tall = MeridianProfile.from_points(1.0 + 2.0 * np.sin(math.pi * s) ** 0.6, 8.0 * s)
    before = membrane_check(tall, load)
    assert before.compressed_fraction > 0.05
    fixed = hold_shape(tall, load)
    assert fixed.converged
    assert fixed.check.compressed_fraction == 0.0
    assert fixed.profile.meridian_length == pytest.approx(tall.meridian_length, rel=1e-9)
    assert fixed.profile.r[-1] == pytest.approx(tall.r[-1], abs=1e-6)
