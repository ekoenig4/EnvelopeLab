"""Gores cut by a slanted footprint (a leaning dome or revolved shape) get as much cloth
as the same gores upright: developed along true parallels and cut along the footprint."""

from __future__ import annotations

import numpy as np
import pytest

from envelopelab.features.primitives import Dome, Placement, Revolved, _pieces, design_primitive
from envelopelab.validation.primitives import sphere_envelope

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


def _shape(kind: str, lean: float) -> object:
    surface = sphere_envelope()
    place = Placement(3, 0.5 * surface.profile.meridian_length, lean_deg=lean, lean_toward_deg=-90)
    prim = (
        Dome("d", place, 0.9, 0.7, 12)
        if kind == "dome"
        else Revolved("s", place, STALK_AND_BALL, gores=12)
    )
    return design_primitive(prim, surface)


def _cloth(design: object) -> tuple[float, float]:
    """Cut over designed area of the gores, minus 1: in total and for the worst gore."""
    gores = [p for p in design.pieces if "TIP" not in p.label]  # type: ignore[attr-defined]
    total = sum(p.flat_area for p in gores) / sum(p.surface_area for p in gores) - 1.0
    worst = min(p.flat_area / p.surface_area - 1.0 for p in gores)
    return total, worst


@pytest.mark.parametrize("kind", ["dome", "stalk"])
@pytest.mark.parametrize("lean", [20.0, 35.0])
def test_a_leaning_shape_gets_as_much_cloth_as_upright(kind: str, lean: float) -> None:
    upright_total, upright_worst = _cloth(_shape(kind, 0.0))
    total, worst = _cloth(_shape(kind, lean))
    assert total == pytest.approx(upright_total, abs=0.01)
    assert worst > upright_worst - 0.015


@pytest.mark.parametrize("lean", [20.0, 35.0])
def test_leaning_gores_keep_true_seam_and_footprint_lengths(lean: float) -> None:
    design = _shape("stalk", lean)
    t = np.linspace(0.0, 1.0, 401)
    for piece in _pieces(design._skin, design.primitive):  # type: ignore[attr-defined]
        if not hasattr(piece, "seam_3d"):
            continue
        for phi, true in zip((piece.phi_a, piece.phi_b), piece.seam_3d, strict=True):
            edge = piece.flat(t, np.full(len(t), phi))
            assert np.sum(np.linalg.norm(np.diff(edge, axis=0), axis=1)) == pytest.approx(
                true, abs=1e-3
            )
        if piece.tier == 0:  # the edge sewn to the envelope keeps its true length
            ph = np.linspace(piece.phi_a, piece.phi_b, 401)
            flat = piece.flat(np.zeros(len(ph)), ph)
            real = piece.skin.at(np.zeros(len(ph)), ph)
            flat_len = np.sum(np.linalg.norm(np.diff(flat, axis=0), axis=1))
            real_len = np.sum(np.linalg.norm(np.diff(real, axis=0), axis=1))
            assert flat_len == pytest.approx(real_len, abs=1e-3)


def test_an_upright_dome_is_cut_as_before() -> None:
    """Footprints that do not slant across a gore keep their pattern bit for bit."""
    design = _shape("dome", 0.0)
    areas = [p.flat_area for p in design.pieces[:2]]  # type: ignore[attr-defined]
    # Sphere envelope gore 3, mid tape (the generic sphere), recorded before the change.
    assert areas == [0.3791983535061876, 0.3791983980815933]


@pytest.mark.parametrize("lean", [20.0, 35.0])
def test_the_top_edge_of_a_slanted_gore_keeps_its_true_length(lean: float) -> None:
    """It is sewn to the tier above or the cap: a slanted footprint must not move it."""
    design = _shape("dome", lean)
    ph_n = 401
    for piece in _pieces(design._skin, design.primitive):  # type: ignore[attr-defined]
        ph = np.linspace(piece.phi_a, piece.phi_b, ph_n)
        flat = piece.flat(np.ones(ph_n), ph)
        real = piece.skin.at(np.ones(ph_n), ph)
        flat_len = np.sum(np.linalg.norm(np.diff(flat, axis=0), axis=1))
        real_len = np.sum(np.linalg.norm(np.diff(real, axis=0), axis=1))
        assert flat_len == pytest.approx(real_len, abs=1e-3)
