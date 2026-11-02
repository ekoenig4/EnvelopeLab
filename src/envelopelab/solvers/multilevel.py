r"""Carry a solved shape from one mesh of a design to another through the flat pattern.

A coarse mesh solves quickly; its equilibrium is a good start for a finer mesh of the same
design. Both meshes are cut from the same flat panels, so every fine node has a position
:math:`(u, v)` in a panel's flat frame, and that point lies in (or next to) one triangle
of the coarse mesh of the same panel. The fine node gets the coarse deformed position
interpolated with the barycentric coordinates :math:`\lambda_k` of :math:`(u, v)` in that
coarse rest triangle:

.. math:: x_{fine} = \sum_{k=1}^{3} \lambda_k(u, v)\, x_{coarse,k}.

Mapping in the flat frame keeps the fine mesh's rest geometry consistent with the coarse
strains. Mapping by nearest points on the two 3D initial shapes does not: their faceting
differs, and fabric is so much stiffer than the pressure load that the resulting misfit
gave the generic fixture a start residual 230 times the load (8 times with this mapping).

Assumptions: both meshes come from the same panels with the same flat frames (one
``panel`` label per triangle, equal labels for the same panel); seam nodes take the
position of their first incident triangle's panel. Points outside every coarse triangle of
their panel (curved outlines discretised differently) take the nearest point of the coarse
panel's boundary.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from envelopelab.solvers.membrane import FloatArray, IntArray


def node_panel_coordinates(
    triangles: IntArray, rest_uv: FloatArray, tri_panel: npt.ArrayLike, n_nodes: int
) -> tuple[IntArray, FloatArray]:
    """Panel label and flat position of every node, from its first incident triangle.

    Parameters
    ----------
    triangles : ndarray of int, shape (m, 3)
        Node indices.
    rest_uv : ndarray, shape (m, 3, 2)
        Flat rest corner coordinates in each panel's frame, m.
    tri_panel : array_like of int, shape (m,)
        Panel label of each triangle.
    n_nodes : int
        Number of nodes.

    Returns
    -------
    panel : ndarray of int, shape (n_nodes,)
        Panel label of each node (-1 for a node no triangle uses).
    uv : ndarray, shape (n_nodes, 2)
        Flat position of each node in that panel's frame, m.
    """
    tri = np.asarray(triangles, dtype=np.int64)
    labels = np.asarray(tri_panel, dtype=np.int64)
    panel = np.full(n_nodes, -1, dtype=np.int64)
    uv = np.zeros((n_nodes, 2))
    flat_nodes = tri.ravel()
    # Reverse order so the first incident triangle is the one written last.
    order = np.arange(flat_nodes.size)[::-1]
    panel[flat_nodes[order]] = np.repeat(labels, 3)[order]
    uv[flat_nodes[order]] = np.asarray(rest_uv, dtype=np.float64).reshape(-1, 2)[order]
    return panel, uv


def barycentric_locate(
    points: FloatArray, rest_uv: FloatArray, candidates: IntArray
) -> tuple[IntArray, FloatArray]:
    """Containing (or nearest) triangle and clamped barycentric coordinates of 2D points.

    Parameters
    ----------
    points : ndarray, shape (k, 2)
        Flat points, m.
    rest_uv : ndarray, shape (m, 3, 2)
        Flat triangle corners, m.
    candidates : ndarray of int, shape (c,)
        Indices of the triangles to search (one panel's triangles).

    Returns
    -------
    triangle : ndarray of int, shape (k,)
        Index (into ``rest_uv``) of the triangle each point lies in, or of the triangle
        holding the nearest boundary point when it lies in none.
    weights : ndarray, shape (k, 3)
        Barycentric coordinates of the point (or of that nearest point): non-negative,
        summing to 1.
    """
    corners = rest_uv[candidates]
    a = corners[:, 0]
    e1 = corners[:, 1] - a
    e2 = corners[:, 2] - a
    det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    triangle = np.empty(len(points), dtype=np.int64)
    weights = np.empty((len(points), 3))
    # Chunked so memory stays bounded for large meshes (k x c doubles per chunk).
    chunk = max(1, 4_000_000 // max(1, len(candidates)))
    for start in range(0, len(points), chunk):
        p = points[start : start + chunk]
        d = p[:, None, :] - a[None, :, :]
        l1 = (d[..., 0] * e2[None, :, 1] - d[..., 1] * e2[None, :, 0]) / det[None, :]
        l2 = (e1[None, :, 0] * d[..., 1] - e1[None, :, 1] * d[..., 0]) / det[None, :]
        l0 = 1.0 - l1 - l2
        excess = (
            np.maximum(-l0, 0.0) + np.maximum(-l1, 0.0) + np.maximum(-l2, 0.0)
        )  # 0 inside the triangle
        best = np.argmin(excess, axis=1)
        rows = np.arange(len(p))
        lam = np.stack([l0[rows, best], l1[rows, best], l2[rows, best]], axis=1)
        outside = np.flatnonzero(excess[rows, best] > 1e-12)
        if len(outside):
            best[outside], lam[outside] = _nearest_on_triangles(p[outside], corners)
        triangle[start : start + len(p)] = candidates[best]
        weights[start : start + len(p)] = lam
    return triangle, weights


def _nearest_on_triangles(points: FloatArray, corners: FloatArray) -> tuple[IntArray, FloatArray]:
    """Nearest boundary point over all triangles: triangle index and its barycentric
    coordinates (for points outside every triangle)."""
    best_d = np.full(len(points), np.inf)
    best_t = np.zeros(len(points), dtype=np.int64)
    best_lam = np.zeros((len(points), 3))
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a = corners[:, i]
        e = corners[:, j] - a
        d = points[:, None, :] - a[None, :, :]
        t = np.clip((d * e[None]).sum(axis=2) / (e * e).sum(axis=1)[None, :], 0.0, 1.0)
        dist = np.linalg.norm(d - t[..., None] * e[None], axis=2)
        k = np.argmin(dist, axis=1)
        rows = np.arange(len(points))
        better = dist[rows, k] < best_d
        best_d[better] = dist[rows, k][better]
        best_t[better] = k[better]
        lam = np.zeros((len(points), 3))
        lam[:, i] = 1.0 - t[rows, k]
        lam[:, j] = t[rows, k]
        best_lam[better] = lam[better]
    return best_t, best_lam


def prolongate(
    coarse_positions: FloatArray,
    coarse_triangles: IntArray,
    coarse_rest_uv: FloatArray,
    coarse_tri_panel: npt.ArrayLike,
    fine_triangles: IntArray,
    fine_rest_uv: FloatArray,
    fine_tri_panel: npt.ArrayLike,
    n_fine: int,
) -> FloatArray:
    """Start positions for a fine mesh from a coarse mesh's solved positions (module
    docstring).

    Parameters
    ----------
    coarse_positions : ndarray, shape (n_c, 3)
        Solved coarse node positions, m.
    coarse_triangles : ndarray of int, shape (m_c, 3)
        Coarse node indices.
    coarse_rest_uv : ndarray, shape (m_c, 3, 2)
        Coarse flat rest corners in the panel frames, m.
    coarse_tri_panel : array_like of int, shape (m_c,)
        Panel label of each coarse triangle.
    fine_triangles : ndarray of int, shape (m_f, 3)
        Fine node indices.
    fine_rest_uv : ndarray, shape (m_f, 3, 2)
        Fine flat rest corners in the same panel frames, m.
    fine_tri_panel : array_like of int, shape (m_f,)
        Panel label of each fine triangle (same labels as the coarse mesh).
    n_fine : int
        Number of fine nodes.

    Returns
    -------
    ndarray, shape (n_fine, 3)
        Interpolated fine positions, m.

    Raises
    ------
    ValueError
        If a fine panel label has no coarse triangle.
    """
    x_c = np.asarray(coarse_positions, dtype=np.float64)
    tri_c = np.asarray(coarse_triangles, dtype=np.int64)
    uv_c = np.asarray(coarse_rest_uv, dtype=np.float64)
    panel_c = np.asarray(coarse_tri_panel, dtype=np.int64)
    panel_f, uv_f = node_panel_coordinates(fine_triangles, fine_rest_uv, fine_tri_panel, n_fine)
    out = np.zeros((n_fine, 3))
    for label in np.unique(panel_f[panel_f >= 0]):
        nodes = np.flatnonzero(panel_f == label)
        candidates = np.flatnonzero(panel_c == label)
        if len(candidates) == 0:
            raise ValueError(f"panel {label} of the fine mesh has no coarse triangles")
        tri, lam = barycentric_locate(uv_f[nodes], uv_c, candidates)
        out[nodes] = np.einsum("ka,kad->kd", lam, x_c[tri_c[tri]])
    return out
