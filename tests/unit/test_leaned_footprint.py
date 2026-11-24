"""A tall leaning revolved shape near the crown: the footprint search below its base runs
through the balloon and out of its far side; the footprint is still the crossing next
to the base."""

from __future__ import annotations

import numpy as np
import pytest

from envelopelab.features.primitives import Placement, Revolved, design_primitive
from envelopelab.validation.primitives import sphere_envelope

#: A stalk with a ball on top, 5 m tall (generic test geometry), m.
STALK_AND_BALL = (
    (0.59, 0.0),
    (0.45, 1.0),
    (0.3, 2.0),
    (0.26, 3.0),
    (0.8, 3.4),
    (1.0, 3.9),
    (0.7, 4.6),
    (0.0, 5.0),
)


@pytest.mark.parametrize("lean", [35.0, 45.0])
def test_a_leaning_shape_near_the_crown_is_placed_at_its_base(lean: float) -> None:
    surface = sphere_envelope()
    s0 = 0.8 * surface.profile.meridian_length
    shape = Revolved(
        "stalk",
        Placement(1, s0, lean_deg=lean, lean_toward_deg=-90.0),
        STALK_AND_BALL,
        gores=8,
    )
    design = design_primitive(shape, surface)
    rim = design._skin.rim_points(np.linspace(0.0, 2.0 * np.pi, 64, endpoint=False))
    # On the envelope, and round the base point, not across the balloon.
    assert np.abs(surface.signed_distance(rim)).max() < 1e-3
    s, _, _ = surface.locate(rim)
    assert np.abs(s - s0).max() < 1.5
    # A leaning stalk meets the envelope along an elongated loop: between the base
    # circle and the oblique section 1/cos(lean) longer (taper and curvature allowed).
    circle = 2 * np.pi * 0.59
    assert circle < design.footprint_length < 1.2 * circle / np.cos(np.radians(lean))


def test_the_same_shape_upright_is_unchanged() -> None:
    """Shapes that placed before keep the same footprint (the only crossing): equal to
    the value recorded before the fix up to floating-point rounding, which differs
    between platforms in the last digits (1e-12 relative: far below any change of the
    method, which moves it by percent)."""
    surface = sphere_envelope()
    s0 = 0.8 * surface.profile.meridian_length
    shape = Revolved("stalk", Placement(1, s0, lean_deg=25.0), STALK_AND_BALL, gores=8)
    design = design_primitive(shape, surface)
    assert design.footprint_length == pytest.approx(3.9893326421444746, rel=1e-12)
