r"""Deviation of a solved (inflated) shape from its design: inside or outside, by how much.

For every node of the solved membrane mesh, the signed deviation is the distance from the
designed surface to the node, measured along the designed surface's outward normal:

.. math:: d = (\mathbf{x} - \mathbf{q}) \cdot \hat{\mathbf{n}}(\mathbf{q})

with :math:`\mathbf{x}` the solved node position, :math:`\mathbf{q}` the closest point of
the designed surface to it and :math:`\hat{\mathbf{n}}` the designed surface's outward unit
normal there. :math:`d > 0`: the fabric lies **outside** the design (it bulges out);
:math:`d < 0`: **inside** it. Only the normal component counts, so fabric that slid along
the surface (for example a seam that moved up the tape) without leaving it reads as zero.

The deviation is evaluated **at the solved nodes**, where the solver's positions are exact,
against a dense tessellation of the designed surface (its faceting error is far smaller than
the solver mesh's: see :func:`deviation_at_nodes`). For display it is interpolated linearly
(barycentric) onto other points, such as the design's display surface or the flat panels
(:func:`interpolate_on_mesh`); between nodes the shown value is that interpolation, not a
solver result.

Assumptions: both shapes are in the same frame (m, the envelope frame with the mouth at
z = 0); the designed mesh is a consistently wound surface whose normals can be oriented
outward (away from its centroid, or from the z axis for an envelope). Valid where the solved
shape stays within ``max_distance`` of the design; nodes farther away (a part that is not in
the design at all) get NaN.

References: closest point on a triangle, C. Ericson, *Real-Time Collision Detection*,
Morgan Kaufmann, 2005, sect. 5.1.5.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from envelopelab.solvers.membrane import FloatArray, IntArray

#: Candidate triangles searched per point (nearest by centroid).
CANDIDATES = 12


def vertex_normals(
    points: FloatArray, triangles: IntArray, outward: str = "centroid"
) -> FloatArray:
    """Area-weighted unit vertex normals of a triangle mesh, oriented outward.

    Parameters
    ----------
    points : ndarray, shape (n, 3)
        Vertices, m.
    triangles : ndarray of int, shape (m, 3)
        Consistently wound triangles.
    outward : {"centroid", "axis"}
        How "outward" is decided: away from the mesh centroid (any closed-ish shape), or away
        from the z axis (an envelope, whose crown and mouth are open).

    Returns
    -------
    ndarray, shape (n, 3)
        Unit normals (dimensionless); zero for a vertex in no triangle.
    """
    p = np.asarray(points, dtype=np.float64)
    t = np.asarray(triangles, dtype=np.int64)
    face = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])  # 2 x area
    normals = np.zeros_like(p)
    for k in range(3):
        np.add.at(normals, t[:, k], face)
    length = np.linalg.norm(normals, axis=1)
    normals[length > 0] /= length[length > 0, None]
    if outward == "axis":
        away = p.copy()
        away[:, 2] = 0.0
    else:
        away = p - p.mean(axis=0)
    # One orientation for the whole mesh (its winding is consistent), chosen by majority.
    if float(np.sum(np.einsum("ij,ij->i", normals, away))) < 0.0:
        normals = -normals
    return normals


def _closest_on_triangles(
    x: FloatArray, a: FloatArray, b: FloatArray, c: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """Closest point of triangles (a, b, c) to points x (row-wise), and its barycentric
    weights (Ericson 2005, 5.1.5)."""
    ab, ac, ax = b - a, c - a, x - a
    d1 = np.einsum("ij,ij->i", ab, ax)
    d2 = np.einsum("ij,ij->i", ac, ax)
    bx = x - b
    d3 = np.einsum("ij,ij->i", ab, bx)
    d4 = np.einsum("ij,ij->i", ac, bx)
    cx = x - c
    d5 = np.einsum("ij,ij->i", ab, cx)
    d6 = np.einsum("ij,ij->i", ac, cx)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    w = np.zeros((len(x), 3))
    # Interior (default), then the edge and vertex regions override it.
    denom = va + vb + vc
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(denom != 0, vb / denom, 0.0)
        u = np.where(denom != 0, vc / denom, 0.0)
    w[:, 0], w[:, 1], w[:, 2] = 1.0 - v - u, v, u
    with np.errstate(divide="ignore", invalid="ignore"):
        # Edge BC.
        m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        w[m] = np.column_stack((np.zeros(m.sum()), 1 - t[m], t[m]))
        # Edge AC.
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = d2 / (d2 - d6)
        w[m] = np.column_stack((1 - t[m], np.zeros(m.sum()), t[m]))
        # Edge AB.
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = d1 / (d1 - d3)
        w[m] = np.column_stack((1 - t[m], t[m], np.zeros(m.sum())))
    # Vertex regions.
    w[(d1 <= 0) & (d2 <= 0)] = (1.0, 0.0, 0.0)
    w[(d3 >= 0) & (d4 <= d3)] = (0.0, 1.0, 0.0)
    w[(d6 >= 0) & (d5 <= d6)] = (0.0, 0.0, 1.0)
    q = w[:, :1] * a + w[:, 1:2] * b + w[:, 2:] * c
    return q, w


def closest_points(
    points: FloatArray, vertices: FloatArray, triangles: IntArray
) -> tuple[FloatArray, IntArray, FloatArray]:
    """Closest point of a triangle mesh to each point.

    The candidates are the :data:`CANDIDATES` triangles with the nearest centroids; the
    exact closest point on each is computed and the nearest kept.

    Parameters
    ----------
    points : ndarray, shape (k, 3)
        Query points, m.
    vertices : ndarray, shape (n, 3)
        Mesh vertices, m.
    triangles : ndarray of int, shape (m, 3)
        Mesh triangles.

    Returns
    -------
    (ndarray, ndarray, ndarray)
        Closest points (k, 3) in m, the triangle each lies on (k,), and its barycentric
        weights (k, 3).
    """
    x = np.asarray(points, dtype=np.float64)
    v = np.asarray(vertices, dtype=np.float64)
    t = np.asarray(triangles, dtype=np.int64)
    centroids = v[t].mean(axis=1)
    k = min(CANDIDATES, len(t))
    _, cand = cKDTree(centroids).query(x, k=k)
    cand = np.asarray(cand).reshape(len(x), k)
    best_q = np.zeros_like(x)
    best_w = np.zeros((len(x), 3))
    best_t = np.zeros(len(x), dtype=np.int64)
    best_d = np.full(len(x), np.inf)
    for j in range(k):
        tri = t[cand[:, j]]
        q, w = _closest_on_triangles(x, v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]])
        d = np.linalg.norm(x - q, axis=1)
        better = d < best_d
        best_d[better] = d[better]
        best_q[better] = q[better]
        best_w[better] = w[better]
        best_t[better] = cand[better, j]
    return best_q, best_t, best_w


def deviation_at_nodes(
    solved: FloatArray,
    design_points: FloatArray,
    design_triangles: IntArray,
    outward: str = "centroid",
    max_distance: float | None = None,
) -> FloatArray:
    """Signed normal deviation of solved nodes from the designed surface (module docstring).

    Parameters
    ----------
    solved : ndarray, shape (k, 3)
        Solved node positions, m.
    design_points : ndarray, shape (n, 3)
        Designed surface vertices, m. Use a dense tessellation: a flat triangle of edge
        ``h`` on a surface of radius ``R`` lies up to about ``h**2 / (6 R)`` inside it.
    design_triangles : ndarray of int, shape (m, 3)
        Designed surface triangles (consistently wound).
    outward : {"centroid", "axis"}
        How the design's outward side is found (see :func:`vertex_normals`).
    max_distance : float, optional
        Nodes farther than this from the design get NaN, m.

    Returns
    -------
    ndarray, shape (k,)
        Deviation, m: positive outside the design, negative inside.
    """
    x = np.asarray(solved, dtype=np.float64)
    q, tri, w = closest_points(x, design_points, design_triangles)
    normals = vertex_normals(design_points, design_triangles, outward)
    corners = np.asarray(design_triangles, dtype=np.int64)[tri]
    n = np.einsum("ij,ijk->ik", w, normals[corners])
    length = np.linalg.norm(n, axis=1)
    n[length > 0] /= length[length > 0, None]
    d = np.einsum("ij,ij->i", x - q, n)
    if max_distance is not None:
        d[np.linalg.norm(x - q, axis=1) > max_distance] = np.nan
    return np.asarray(d, dtype=np.float64)


def interpolate_on_mesh(
    points: FloatArray, vertices: FloatArray, triangles: IntArray, values: FloatArray
) -> FloatArray:
    """Values given at a mesh's vertices, interpolated linearly at the closest mesh point
    of each query point (for display).

    Parameters
    ----------
    points : ndarray, shape (k, 3)
        Query points, m.
    vertices, triangles
        The mesh (m) the values live on.
    values : ndarray, shape (n,)
        One value per vertex, any unit.

    Returns
    -------
    ndarray, shape (k,)
        Interpolated values, in the unit of ``values`` (NaN where a corner value is NaN).
    """
    _, tri, w = closest_points(points, vertices, triangles)
    corners = np.asarray(triangles, dtype=np.int64)[tri]
    vals = np.asarray(values, dtype=np.float64)[corners]
    return np.asarray(np.einsum("ij,ij->i", w, vals), dtype=np.float64)


#: Tessellation of the designed envelope for the deviation (segments per gore and per row):
#: on a 3 m radius with 8 gores the triangles are about 0.1 m, so the faceting error is
#: about 0.5 mm (see :func:`deviation_at_nodes`).
DENSE_PER_GORE = 24
DENSE_PER_ROW = 24


def envelope_deviation(design: object, positions: FloatArray) -> FloatArray:
    """Signed deviation of a solved envelope's nodes from its designed surface, m.

    Parameters
    ----------
    design : DesignDocument
        The standard-gore design the run was solved from (its profile, rows and loft).
    positions : ndarray, shape (k, 3)
        Solved node positions, m, in the design's frame (mouth at z = 0).

    Returns
    -------
    ndarray, shape (k,)
        Deviation along the design's outward normal (away from the z axis), m: positive
        outside the design, negative inside (see the module docstring).
    """
    from envelopelab.project.gore_design import display_surface

    dense = display_surface(design, DENSE_PER_GORE, DENSE_PER_ROW)  # type: ignore[arg-type]
    return deviation_at_nodes(positions, dense.points, dense.faces, outward="axis")


@dataclass(frozen=True)
class PanelDeviation:
    """Deviation from the design drawn on one flat panel row (for display).

    Attributes
    ----------
    row : str
        Row label.
    points : ndarray, shape (k, 2)
        Grid points in the row's panel coordinates (x across from the centreline, y up from
        the finished bottom seam), m.
    triangles : ndarray of int, shape (t, 3)
        Grid triangles.
    values : ndarray, shape (k,)
        Deviation at each point, m (+ outside, - inside, NaN where unknown): of all the
        gores cut from this row, the one that deviates most there.
    gore : ndarray of int, shape (k,)
        That gore's number (1..N).
    """

    row: str
    points: FloatArray
    triangles: IntArray
    values: FloatArray
    gore: IntArray


def panel_deviation(
    design: object,
    rows: Sequence[Any],
    surface_values: FloatArray,
    per_gore: int = 6,
    per_row: int = 8,
) -> list[PanelDeviation]:
    """Deviation on the display surface's grid, mapped onto the flat panel rows.

    A grid point at tape length :math:`s` in a row and at fraction :math:`u` across its
    gore (0 at the gore's left seam, 1 at its right) is placed on the flat panel at
    :math:`y = s - s_{bottom}`, :math:`x = (2u - 1)\\,w(y)/2` with :math:`w(y)` the panel's
    finished width at that height. This is a display mapping (the panel's y is its
    centreline length up from the bottom seam); the values are those of the surface.

    Parameters
    ----------
    design : DesignDocument
        The standard-gore design of the display surface.
    rows : sequence of PanelRow
        Its panel rows (finished geometry, m), mouth first.
    surface_values : ndarray, shape (n,)
        One value per point of ``display_surface(design, per_gore, per_row)``, m.
    per_gore, per_row : int
        The display surface's tessellation.

    Returns
    -------
    list of PanelDeviation
        One per row that the surface covers.
    """
    from envelopelab.project.gore_design import display_stations

    gores = design.gores  # type: ignore[attr-defined]
    s, _, _ = display_stations(design, per_row)  # type: ignore[arg-type]
    n = int(gores.count)
    m = n * per_gore
    values = np.asarray(surface_values, dtype=np.float64).reshape(len(s), m)
    cols = (np.arange(n)[:, None] * per_gore + np.arange(per_gore + 1)[None, :]) % m  # (n, k)
    out: list[PanelDeviation] = []
    eps = 1e-9
    for row in rows:
        stations = np.flatnonzero((s >= row.s_bottom - eps) & (s <= row.s_top + eps))
        if len(stations) < 2:
            continue
        per = values[stations][:, cols]  # (stations, gores, u)
        magnitude = np.where(np.isnan(per), -1.0, np.abs(per))
        worst = np.argmax(magnitude, axis=1)  # (stations, u)
        picked = np.take_along_axis(per, worst[:, None, :], axis=1)[:, 0, :]
        edge = np.asarray(row.right_edge, dtype=np.float64)
        y = s[stations] - row.s_bottom
        half = np.interp(y, edge[:, 1], edge[:, 0])
        u = np.arange(per_gore + 1) / per_gore
        xs = (2.0 * u[None, :] - 1.0) * half[:, None]
        pts = np.column_stack((xs.ravel(), np.repeat(y, per_gore + 1)))
        k = per_gore + 1
        tris = []
        for i in range(len(stations) - 1):
            for j in range(per_gore):
                a = i * k + j
                tris += [[a, a + 1, a + k + 1], [a, a + k + 1, a + k]]
        out.append(
            PanelDeviation(
                str(row.label),
                pts,
                np.array(tris, dtype=np.int64),
                picked.ravel(),
                (worst.ravel() + 1).astype(np.int64),
            )
        )
    return out
