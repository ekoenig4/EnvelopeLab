"""Special shapes on a straight stretch of the envelope (a conical flank): the host is a
cone, R1 = infinity, with the exact membrane stresses of a pressurised cone."""

from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.features.builder import shell_prestress
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    PrimitiveError,
    RowBand,
    design_primitive,
    host_surface_at,
)
from envelopelab.geometry.gore import MeridianProfile
from envelopelab.validation.primitives import cone_envelope as generic_cone_envelope

GORES = 12


def _surface(r: np.ndarray, z: np.ndarray) -> EnvelopeSurface:
    profile = MeridianProfile.from_points(r, z)
    return EnvelopeSurface(profile, GORES, rows=[RowBand("A", 0.0, profile.meridian_length)])


def cone_envelope() -> tuple[EnvelopeSurface, float]:
    """The generic cone envelope and its flank's half angle from the axis, rad."""
    return generic_cone_envelope(GORES), math.atan2(3.0, 6.0)


def test_a_shape_on_a_straight_flank_has_a_conical_host() -> None:
    surface, half_angle = cone_envelope()
    s0 = 0.5 * math.hypot(3.0, 6.0)  # halfway along the flank: r = 2.5 m, z = 3 m
    design = design_primitive(Dome("nose", Placement(1, s0), 0.3, 0.3, gores=12), surface)
    host = host_surface_at(design)
    assert math.isinf(host.meridian_radius)
    # R2 is the normal's length to the axis: r / cos(beta), beta the normal's elevation.
    beta = -half_angle  # the flank widens upward, so its outward normal points down
    assert host.normal_elevation == pytest.approx(beta, abs=1e-3)
    r2 = 2.5 / math.cos(beta)
    assert host.hoop_radius == pytest.approx(r2, rel=1e-3)
    # The exact membrane stresses of a pressurised cone: hoop p R2, meridional p R2 / 2.
    n_u, n_v = shell_prestress(100.0, host)
    assert n_u == pytest.approx(100.0 * r2, rel=1e-3)
    assert n_v == pytest.approx(50.0 * r2, rel=1e-3)


def test_a_shape_where_the_envelope_curves_inward_is_refused() -> None:
    # A waist: the meridian bends towards the axis (concave seen from outside).
    t = np.linspace(0.0, 1.0, 1200)
    r = 3.0 - 1.5 * np.sin(math.pi * t)
    z = 8.0 * t
    phi = np.linspace(0.0, 0.5 * math.pi, 600)[1:]
    surface = _surface(np.r_[r, 3.0 * np.cos(phi)], np.r_[z, 8.0 + 3.0 * np.sin(phi)])
    s_waist = float(surface.profile.s[600])
    design = design_primitive(Dome("nose", Placement(1, s_waist), 0.3, 0.3, gores=12), surface)
    with pytest.raises(PrimitiveError, match="curves inward"):
        host_surface_at(design)
