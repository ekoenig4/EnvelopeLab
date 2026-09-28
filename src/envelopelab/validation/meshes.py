"""Analytic triangle meshes for solver benchmarks (spheres, cylinders, sheets, cables).

These are generic geometric shapes, not envelope designs. Every mesh is returned with
flat rest coordinates per triangle so it can be handed to the preview solver:

* doubly curved shapes (spheres) use each 3D facet as its own flat rest triangle, so the
  faceted initial shape is stress-free;
* developable shapes (cylinders, sheets) use the unrolled flat pattern.

All lengths are in m.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from envelopelab.solvers.membrane import FloatArray, IntArray


@dataclass
class AnalyticMesh:
    """Positions, triangles, flat rest coordinates and named node sets.

    Attributes
    ----------
    positions : ndarray, shape (n, 3)
        Node positions, m.
    triangles : ndarray of int, shape (m, 3)
        Counter-clockwise seen from outside (outward normals).
    rest_uv : ndarray, shape (m, 3, 2)
        Flat rest coordinates, m.
    node_sets : dict of str to ndarray of int
        Named node groups (symmetry planes, rings, supports).
    """

    positions: FloatArray
    triangles: IntArray
    rest_uv: FloatArray
    node_sets: dict[str, IntArray] = field(default_factory=dict)


def facet_rest_coordinates(positions: FloatArray, triangles: IntArray) -> FloatArray:
    """Flat coordinates of each 3D triangle in its own plane (stress-free facets).

    Parameters
    ----------
    positions : ndarray, shape (n, 3)
        m.
    triangles : ndarray of int, shape (m, 3)
        Node indices.

    Returns
    -------
    ndarray, shape (m, 3, 2)
        Corner coordinates, m; counter-clockwise for the triangle's own normal.
    """
    x = positions[triangles]
    a = x[:, 1] - x[:, 0]
    b = x[:, 2] - x[:, 0]
    la = np.linalg.norm(a, axis=1)
    e1 = a / la[:, None]
    n = np.cross(a, b)
    e2 = np.cross(n / np.linalg.norm(n, axis=1)[:, None], e1)
    uv = np.zeros((len(triangles), 3, 2))
    uv[:, 1, 0] = la
    uv[:, 2, 0] = np.einsum("mi,mi->m", b, e1)
    uv[:, 2, 1] = np.einsum("mi,mi->m", b, e2)
    return uv


def _dedupe(points: FloatArray, triangles: IntArray, scale: float) -> tuple[FloatArray, IntArray]:
    keys = np.round(points / scale, 9)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    return points[first], inverse.ravel()[triangles]


def _orient_outward(positions: FloatArray, triangles: IntArray, centre: FloatArray) -> IntArray:
    x = positions[triangles]
    normal = np.cross(x[:, 1] - x[:, 0], x[:, 2] - x[:, 0])
    inward = np.einsum("mi,mi->m", normal, x.mean(axis=1) - centre) < 0
    out = triangles.copy()
    out[inward] = out[inward][:, [0, 2, 1]]
    return out


def sphere(radius: float, divisions: int, octant: bool = False) -> AnalyticMesh:
    """Geodesic sphere from a subdivided octahedron.

    Parameters
    ----------
    radius : float
        Sphere radius (all nodes lie on it), m.
    divisions : int
        Subdivisions per octahedron edge (>= 1).
    octant : bool
        Only the x, y, z >= 0 octant, with node sets ``x0``, ``y0``, ``z0`` on the three
        symmetry planes.

    Returns
    -------
    AnalyticMesh
        Stress-free facets (see :func:`facet_rest_coordinates`). Node sets ``bottom``
        (the -z pole) and, for the octant, the symmetry-plane nodes.
    """
    n = divisions
    signs = (
        [(1, 1, 1)]
        if octant
        else [(sx, sy, sz) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)]
    )
    pts: list[FloatArray] = []
    tris: list[IntArray] = []
    offset = 0
    for sx, sy, sz in signs:
        corners = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, sz]], dtype=np.float64)
        index: dict[tuple[int, int], int] = {}
        local: list[FloatArray] = []
        for i in range(n + 1):
            for j in range(n + 1 - i):
                k = n - i - j
                p = (i * corners[0] + j * corners[1] + k * corners[2]) / n
                index[(i, j)] = len(local)
                local.append(p / np.linalg.norm(p))
        faces = []
        for i in range(n):
            for j in range(n - i):
                faces.append((index[(i, j)], index[(i + 1, j)], index[(i, j + 1)]))
                if i + j < n - 1:
                    faces.append((index[(i + 1, j)], index[(i + 1, j + 1)], index[(i, j + 1)]))
        pts.append(np.array(local))
        tris.append(np.array(faces, dtype=np.int64) + offset)
        offset += len(local)
    positions, triangles = _dedupe(np.vstack(pts), np.vstack(tris), 1.0)
    positions = radius * positions / np.linalg.norm(positions, axis=1)[:, None]
    triangles = _orient_outward(positions, triangles, np.zeros(3))
    tol = 1e-9 * radius
    sets = {"bottom": np.flatnonzero(positions[:, 2] < -radius + tol)}
    if octant:
        for axis, name in enumerate(("x0", "y0", "z0")):
            sets[name] = np.flatnonzero(np.abs(positions[:, axis]) < tol)
    return AnalyticMesh(positions, triangles, facet_rest_coordinates(positions, triangles), sets)


def cylinder(radius: float, height: float, n_around: int, n_along: int) -> AnalyticMesh:
    """Closed-loop cylinder surface (no end caps) along z from 0 to ``height``.

    Parameters
    ----------
    radius : float
        Node radius, m.
    height : float
        Length, m.
    n_around : int
        Nodes around the circumference (a multiple of 4 puts nodes on the x and y
        planes).
    n_along : int
        Element rows along the axis.

    Returns
    -------
    AnalyticMesh
        Rest coordinates are the unrolled faceted pattern (chord width per facet), so the
        initial polygonal cylinder is stress-free. Node sets ``bottom``, ``top``,
        ``x0`` (nodes on the plane x = 0) and ``y0``.
    """
    theta = 2.0 * np.pi * np.arange(n_around) / n_around
    z = np.linspace(0.0, height, n_along + 1)
    chord = 2.0 * radius * np.sin(np.pi / n_around)
    tt, zz = np.meshgrid(theta, z)
    positions = np.column_stack(
        [radius * np.cos(tt).ravel(), radius * np.sin(tt).ravel(), zz.ravel()]
    )
    tris = []
    uv = []
    for k in range(n_along):
        for i in range(n_around):
            a = k * n_around + i
            b = k * n_around + (i + 1) % n_around
            c = a + n_around
            d = b + n_around
            u0, u1 = i * chord, (i + 1) * chord
            if (i + k) % 2 == 0:
                tris += [(a, b, d), (a, d, c)]
                uv += [
                    [(u0, z[k]), (u1, z[k]), (u1, z[k + 1])],
                    [(u0, z[k]), (u1, z[k + 1]), (u0, z[k + 1])],
                ]
            else:
                tris += [(a, b, c), (b, d, c)]
                uv += [
                    [(u0, z[k]), (u1, z[k]), (u0, z[k + 1])],
                    [(u1, z[k]), (u1, z[k + 1]), (u0, z[k + 1])],
                ]
    tol = 1e-9 * radius
    sets = {
        "bottom": np.arange(n_around),
        "top": np.arange(n_along * n_around, (n_along + 1) * n_around),
        "x0": np.flatnonzero(np.abs(positions[:, 0]) < tol),
        "y0": np.flatnonzero(np.abs(positions[:, 1]) < tol),
    }
    return AnalyticMesh(positions, np.array(tris, dtype=np.int64), np.array(uv), sets)


def sheet(width: float, height: float, nx: int, ny: int) -> AnalyticMesh:
    """Flat rectangular sheet in the z = 0 plane, rest = initial.

    Parameters
    ----------
    width, height : float
        m.
    nx, ny : int
        Element columns and rows.

    Returns
    -------
    AnalyticMesh
        Node sets ``left``, ``right``, ``bottom``, ``top`` and ``boundary``.
    """
    x = np.linspace(0.0, width, nx + 1)
    y = np.linspace(0.0, height, ny + 1)
    xx, yy = np.meshgrid(x, y)
    positions = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])
    tris = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            b, c, d = a + 1, a + nx + 1, a + nx + 2
            tris += [(a, b, d), (a, d, c)] if (i + j) % 2 == 0 else [(a, b, c), (b, d, c)]
    triangles = np.array(tris, dtype=np.int64)
    rest = positions[:, :2][triangles]
    tol = 1e-9 * max(width, height)
    left = np.flatnonzero(positions[:, 0] < tol)
    right = np.flatnonzero(positions[:, 0] > width - tol)
    bottom = np.flatnonzero(positions[:, 1] < tol)
    top = np.flatnonzero(positions[:, 1] > height - tol)
    boundary = np.unique(np.concatenate([left, right, bottom, top]))
    sets = {"left": left, "right": right, "bottom": bottom, "top": top, "boundary": boundary}
    return AnalyticMesh(positions, triangles, rest, sets)
