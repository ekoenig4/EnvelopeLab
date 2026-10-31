"""Special shapes split into their cut pieces for drawing them as sewn."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import build_appendage
from envelopelab.features.primitives import (
    Dome,
    FreeformShape,
    Placement,
    Tube,
    design_primitive,
    primitive_appendage,
)
from envelopelab.features.scene import ShapeDisplay, designed_display, simulated_display
from envelopelab.solvers.model import OperatingConditions
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.primitives import SPHERE_RADIUS, ellipsoid_mesh, sphere_envelope

SPHERE = sphere_envelope()
EQUATOR = 0.35 * math.pi * SPHERE_RADIUS
HOT = OperatingConditions.hot_air(
    celsius_to_kelvin(100.0), mouth_height=float(SPHERE.profile.z[0]), self_weight=False
)


def _edge_pieces(display: ShapeDisplay) -> dict[tuple[int, int], set[int]]:
    """Pieces of the triangles on either side of every mesh edge."""
    out: dict[tuple[int, int], set[int]] = {}
    for t, tri in enumerate(display.triangles):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            out.setdefault((int(min(a, b)), int(max(a, b))), set()).add(int(display.piece[t]))
    return out


def test_designed_dome_is_split_into_its_gores_along_its_seams() -> None:
    dome = design_primitive(Dome("ear", Placement(3, EQUATOR), 0.8, 0.6, gores=8), SPHERE)
    d = designed_display(dome, per_piece=6)
    assert d.pieces == 8
    counts = np.bincount(d.piece, minlength=8)
    assert len(counts) == 8 and np.all(counts == counts[0])  # one wedge per gore
    assert len(d.seams) == 8
    for seam in d.seams:
        # From the rim (on the envelope) to the apex, on the skin.
        assert abs(SPHERE.signed_distance(seam[:1])[0]) < 1e-6
        assert SPHERE.signed_distance(seam[-1:])[0] == pytest.approx(0.6, abs=2e-3)
    assert np.abs(SPHERE.signed_distance(d.rim)).max() < 1e-6
    assert np.allclose(d.rim[0], d.rim[-1])


def test_designed_tube_tip_disc_is_its_own_piece() -> None:
    tube = design_primitive(Tube("horn", Placement(5, EQUATOR), 0.5, 0.2, 1.0, panels=4), SPHERE)
    d = designed_display(tube, per_piece=8)
    counts = np.bincount(d.piece, minlength=5)
    assert counts[4] == 4 * 8  # the tip fan
    assert np.all(counts[:4] == counts[0])
    assert len(d.seams) == 4 + 1  # four panel seams and the tip seam


def test_designed_freeform_uses_its_panels() -> None:
    blob = ellipsoid_mesh(1.0, 0.7, 1.4, -0.3)
    d0 = design_primitive(FreeformShape("blob", Placement(2, EQUATOR), blob, 6), SPHERE)
    d = designed_display(d0)
    assert d.pieces == 6 and set(d.piece.tolist()) == set(range(6))
    assert len(d.seams) == 6
    # The clipped mesh rim, interpolated round the axis: within 0.1 mm of the envelope.
    assert np.abs(SPHERE.signed_distance(d.rim)).max() < 1e-4


@pytest.mark.parametrize("kind", ["dome", "tube"])
def test_simulated_skin_keeps_its_pieces_and_seams(kind: str) -> None:
    prim = (
        Dome("pod", Placement(2, EQUATOR), 0.8, 0.6, gores=6)
        if kind == "dome"
        else Tube("pod", Placement(2, EQUATOR), 0.6, 0.3, 1.0, panels=4)
    )
    design = design_primitive(prim, SPHERE, feed_hole_radius=0.2)
    am = build_appendage(
        primitive_appendage(design, 0.3, load_tape=GENERIC_TAPE),
        HOT,
        {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC},
    )
    result: Any = SimpleNamespace(positions=am.model.positions, converged=True)
    d = simulated_display(design, am, result)
    m = prim.pieces
    want = set(range(m + 1)) if prim.closed_tip else set(range(m))
    assert set(d.piece.tolist()) == want
    assert len(d.seams) == m + (1 if prim.closed_tip else 0)
    # Every sewn seam edge has a different piece on each side; no other edge does.
    sides = _edge_pieces(d)
    used = np.unique(am.model.triangles[am.skin_triangles])
    index = {int(n): i for i, n in enumerate(used)}
    seam_edges = {
        (min(index[int(a)], index[int(b)]), max(index[int(a)], index[int(b)]))
        for s in am.model.seams
        if s.name.startswith("pod:seam") or s.name == "pod:tip seam"
        for a, b in s.edges
    }
    for edge, pieces in sides.items():
        if len(pieces) == 2:
            assert edge in seam_edges
    for edge in seam_edges:
        assert len(sides[edge]) == 2
    # Unsolved, the skin is where it was designed: the rim is on the envelope.
    assert np.abs(SPHERE.signed_distance(d.rim)).max() < 1e-6
