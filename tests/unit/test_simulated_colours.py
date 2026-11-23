"""The inflated shape is coloured piece by piece like the designed one: its tiers and its
cap are the designed skin's (they decide the panel colours drawn on it)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import build_appendage
from envelopelab.features.primitives import Dome, Placement, design_primitive, primitive_appendage
from envelopelab.features.scene import ShapeDisplay, designed_display, simulated_display
from envelopelab.project.shapes import ShapePlacement, mesh_shape, shape_design
from envelopelab.solvers.model import OperatingConditions
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.primitives import SPHERE_RADIUS, ellipsoid_mesh, sphere_envelope

SPHERE = sphere_envelope()
EQUATOR = 0.5 * math.pi * SPHERE_RADIUS - SPHERE.profile.s[0] - 0.15 * math.pi * SPHERE_RADIUS
HOT = OperatingConditions.hot_air(
    celsius_to_kelvin(100.0), mouth_height=float(SPHERE.profile.z[0]), self_weight=False
)


def _areas(shown: ShapeDisplay) -> np.ndarray:
    p = shown.points[shown.triangles]
    return 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)


def _inflated(design: object) -> ShapeDisplay:
    """The display of the sub-model at its starting shape (the designed skin)."""
    spec = primitive_appendage(design, 0.12, load_tape=GENERIC_TAPE, rim_tape=GENERIC_TAPE)  # type: ignore[arg-type]
    am = build_appendage(spec, HOT, {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC})
    return simulated_display(design, am, SimpleNamespace(positions=am.model.positions))  # type: ignore[arg-type]


def _share(shown: ShapeDisplay, mask: np.ndarray) -> float:
    a = _areas(shown)
    return float(a[mask].sum() / a.sum())


def test_an_inflated_split_shape_keeps_its_tiers() -> None:
    dome = Dome("d", Placement(2, EQUATOR), 0.8, 0.9, gores=8, cap_radius=0.15, splits=(0.45,))
    design = design_primitive(dome, SPHERE, feed_hole_radius=0.2)
    designed, inflated = designed_display(design), _inflated(design)
    assert designed.tier is not None
    assert inflated.tier is not None, "the inflated display has no tiers"
    m = inflated.pieces
    upper_designed = _share(designed, (designed.tier == 1) & (designed.piece < m))
    upper_inflated = _share(inflated, (inflated.tier == 1) & (inflated.piece < m))
    assert upper_inflated == pytest.approx(upper_designed, abs=0.02)


def test_an_inflated_mesh_keeps_its_shaped_moved_cap() -> None:
    ball = ellipsoid_mesh(0.9, 0.7, 0.8, -0.1, rings=24, segments=48)
    base = mesh_shape(
        "eye",
        ball.vertices,
        ball.triangles,
        ShapePlacement(gore=2, tape_position=EQUATOR),
        panels=12,
    )
    spec = type(base).model_validate(
        {
            **base.model_dump(),
            "cap_diameter": 0.6,
            "cap_across": -0.1,
            "cap_up": 0.1,
            "crown_shape": {"kind": "footprint"},
            "feed_hole_radius": 0.2,
        }
    )
    design = shape_design(spec, SPHERE)
    designed, inflated = designed_display(design), _inflated(design)
    cap_designed = _share(designed, designed.piece >= designed.pieces)
    cap_inflated = _share(inflated, inflated.piece >= inflated.pieces)
    assert cap_designed > 0.02
    assert cap_inflated == pytest.approx(cap_designed, rel=0.1)


def test_point_triangle_distances() -> None:
    from envelopelab.features.scene import _point_triangle_distance

    a, b, c = np.array([[0.0, 0, 0]]), np.array([[1.0, 0, 0]]), np.array([[0.0, 1, 0]])
    for point, expected in (
        ([0.2, 0.2, 0.5], 0.5),  # above the inside: the height
        ([2.0, 0.0, 0.0], 1.0),  # beyond a corner
        ([0.5, -1.0, 0.0], 1.0),  # beside an edge
        ([0.5, 0.5, 0.0], 0.0),  # on the hypotenuse
    ):
        got = _point_triangle_distance(np.array([point]), a, b, c)
        assert got[0] == pytest.approx(expected, abs=1e-12)


def test_designed_triangles_keep_their_own_labels() -> None:
    from envelopelab.features.scene import designed_labels

    dome = Dome("d", Placement(2, EQUATOR), 0.8, 0.9, gores=8, cap_radius=0.15, splits=(0.45,))
    designed = designed_display(design_primitive(dome, SPHERE))
    centres = designed.points[designed.triangles].mean(axis=1)
    piece, tier = designed_labels(designed, centres)
    assert np.array_equal(piece, designed.piece)
    assert tier is not None and designed.tier is not None
    assert np.array_equal(tier, designed.tier)


def test_result_files_keep_the_tiers_and_older_ones_still_load() -> None:
    from envelopelab.project.shape_runs import display_arrays, display_from_arrays

    dome = Dome("d", Placement(2, EQUATOR), 0.8, 0.9, gores=8, cap_radius=0.15, splits=(0.45,))
    shown = designed_display(design_primitive(dome, SPHERE))
    arrays = display_arrays(shown)
    back = display_from_arrays(arrays)
    assert back.tier is not None and shown.tier is not None
    assert np.array_equal(back.tier, shown.tier)
    older = {k: v for k, v in arrays.items() if k != "tier"}
    assert display_from_arrays(older).tier is None
