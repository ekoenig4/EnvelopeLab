"""Carrying a solved shape between meshes through the flat pattern."""

from __future__ import annotations

import numpy as np
import pytest

from envelopelab.solvers.multilevel import (
    barycentric_locate,
    node_panel_coordinates,
    prolongate,
)


def grid(n: int, offset: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unit square (shifted by ``offset`` in u) split into 2 n^2 triangles."""
    u, v = np.meshgrid(np.linspace(0.0, 1.0, n + 1), np.linspace(0.0, 1.0, n + 1))
    uv = np.column_stack([u.ravel() + offset, v.ravel()])
    tris = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            tris += [(a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)]
    tri = np.array(tris)
    return uv, tri, uv[tri]


def affine(uv: np.ndarray) -> np.ndarray:
    """A stretched, rotated and lifted image of the flat panel, m."""
    u, v = uv[:, 0], uv[:, 1]
    return np.column_stack([1.1 * u + 0.2 * v, 0.3 * u + 0.9 * v, 0.5 * u - 0.4 * v + 2.0])


def test_an_affine_shape_is_carried_exactly() -> None:
    uv_c, tri_c, rest_c = grid(2)
    uv_f, tri_f, rest_f = grid(7)
    x = prolongate(
        affine(uv_c), tri_c, rest_c, np.zeros(len(tri_c)), tri_f, rest_f,
        np.zeros(len(tri_f)), len(uv_f),
    )  # fmt: skip
    assert x == pytest.approx(affine(uv_f), abs=1e-12)


def test_the_same_mesh_maps_onto_itself() -> None:
    uv, tri, rest = grid(4)
    rng = np.random.default_rng(3)
    x = rng.standard_normal((len(uv), 3))
    out = prolongate(x, tri, rest, np.zeros(len(tri)), tri, rest, np.zeros(len(tri)), len(uv))
    assert out == pytest.approx(x, abs=1e-12)


def test_panels_are_kept_apart() -> None:
    """Two panels with overlapping flat frames: each fine node uses its own panel."""
    uv_c, tri_c, rest_c = grid(1)
    uv_f, tri_f, rest_f = grid(3)
    n_c, n_f = len(uv_c), len(uv_f)
    x_c = np.vstack([affine(uv_c), affine(uv_c) + [0.0, 0.0, 5.0]])
    out = prolongate(
        x_c,
        np.vstack([tri_c, tri_c + n_c]),
        np.vstack([rest_c, rest_c]),
        np.repeat([0, 1], len(tri_c)),
        np.vstack([tri_f, tri_f + n_f]),
        np.vstack([rest_f, rest_f]),
        np.repeat([0, 1], len(tri_f)),
        2 * n_f,
    )
    assert out[:n_f] == pytest.approx(affine(uv_f), abs=1e-12)
    assert out[n_f:] == pytest.approx(affine(uv_f) + [0.0, 0.0, 5.0], abs=1e-12)


def test_points_outside_the_coarse_outline_are_clamped() -> None:
    _, tri, rest = grid(1)
    points = np.array([[0.5, 0.25], [1.2, 0.5], [-0.1, -0.1]])
    which, lam = barycentric_locate(points, rest, np.arange(len(tri)))
    assert (lam >= 0.0).all() and lam.sum(axis=1) == pytest.approx(1.0)
    assert which[0] == 0
    corners = np.einsum("ka,kad->kd", lam, rest[which])
    assert corners[1] == pytest.approx([1.0, 0.5])  # nearest boundary point
    assert corners[2] == pytest.approx([0.0, 0.0])


def test_node_coordinates_come_from_the_first_incident_triangle() -> None:
    uv, tri, rest = grid(2)
    panel, coords = node_panel_coordinates(tri, rest, np.arange(len(tri)), len(uv) + 1)
    assert coords[: len(uv)] == pytest.approx(uv)
    first = [int(np.flatnonzero((tri == i).any(axis=1))[0]) for i in range(len(uv))]
    assert panel[: len(uv)].tolist() == first
    assert panel[-1] == -1  # unused node


def test_a_fine_panel_without_coarse_triangles_is_an_error() -> None:
    uv, tri, rest = grid(1)
    with pytest.raises(ValueError, match="no coarse triangles"):
        prolongate(uv @ np.eye(2, 3), tri, rest, [0, 0], tri, rest, [1, 1], len(uv))
