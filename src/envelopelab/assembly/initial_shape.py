r"""Initial 3D geometry for the as-sewn rest model.

The initial geometry is only a *starting guess* for the inflation solver. It is never the
predicted inflated shape; the rest (as-cut) geometry of every triangle is carried
separately in the rest model.

Gore revolution (standard gore rings)
-------------------------------------
Rows are stacked along the gore centreline so that a point with local panel coordinates
:math:`(u, v)` in row :math:`k` sits at arc length :math:`s = S_k + v` from the mouth.
With :math:`x_l(v), x_r(v)` the left and right finished edges of the row piece and
:math:`G` gores, the point maps to

.. math::
    \tau = \frac{u - x_l}{x_r - x_l}, \qquad
    \theta = \frac{2\pi}{G}(g + \tau), \qquad
    \rho(s) = \frac{G\,w(s)}{2\pi}, \qquad
    z(s) = \int_0^s \sqrt{1 - \rho'(\sigma)^2}\,d\sigma

where :math:`g` is the zero-based gore position and :math:`w = x_r - x_l` the finished
panel width. This is the surface of revolution whose parallels have the sewn
circumference (no lobing); :math:`|\rho'|` is clamped to 1. Panel ``+x`` maps to
increasing :math:`\theta` so counter-clockwise panels get outward normals.

Parts that are not in a ring (appendages) are placed by a discrete harmonic extension
from the already placed seam nodes, lifted along the mean outward normal of their
attachment by ``appendage_lift`` times the rest-mesh distance from it.

Reference mesh
--------------
With ``method: reference_mesh`` the revolution guess is projected onto a user-supplied
reference surface (OBJ, m) by closest-point projection. The reference only steers the
initial guess; the rest geometry still comes from the flat patterns.

References
----------
.. [Struik] D. J. Struik, *Lectures on Classical Differential Geometry*, Dover (1988):
   surfaces of revolution parameterised by meridian arc length.
.. [Ericson] C. Ericson, *Real-Time Collision Detection*, Morgan Kaufmann (2005),
   sec. 5.1.5: closest point on a triangle.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree

from envelopelab.assembly.mesh import IntArray, RestMesh
from envelopelab.assembly.seam_graph import Assembly, Instance
from envelopelab.assembly.spec import RingSpec
from envelopelab.geometry.polygon import FloatArray
from envelopelab.io.pattern_import import ImportWarning


class InitialShapeError(ValueError):
    """Raised when no initial guess can be built with the requested method."""


def _edge_x_of_y(points: FloatArray) -> tuple[FloatArray, FloatArray]:
    order = np.argsort(points[:, 1], kind="stable")
    y = points[order, 1]
    x = points[order, 0]
    keep = np.concatenate([[True], np.diff(y) > 1e-12])
    return y[keep], x[keep]


def _ring_profile(
    ring: RingSpec, instances: dict[str, Instance]
) -> tuple[list[float], FloatArray, FloatArray, FloatArray]:
    """Row offsets and the meridian (s, rho, z) of a ring."""
    offsets: list[float] = []
    s_samples: list[FloatArray] = []
    w_samples: list[FloatArray] = []
    total = 0.0
    first_gore = ring.gores[0]
    for row in ring.rows:
        inst = instances[ring.instance_id(row, first_gore)]
        offsets.append(total)
        yl, xl = _edge_x_of_y(inst.edges[ring.edges["left"]].points)
        yr, xr = _edge_x_of_y(inst.edges[ring.edges["right"]].points)
        top = float(inst.outline[:, 1].max())
        v = np.linspace(0.0, top, 41)
        width = np.interp(v, yr, xr) - np.interp(v, yl, xl)
        s_samples.append(total + v)
        w_samples.append(width)
        total += top
    s = np.concatenate(s_samples)
    order = np.argsort(s, kind="stable")
    s = s[order]
    rho = np.concatenate(w_samples)[order] * ring.gore_count / (2 * math.pi)
    keep = np.concatenate([[True], np.diff(s) > 1e-9])
    s, rho = s[keep], rho[keep]
    slope = np.clip(np.gradient(rho, s), -1.0, 1.0)
    dz = np.sqrt(1.0 - slope**2)
    z = np.concatenate([[0.0], np.cumsum(0.5 * (dz[1:] + dz[:-1]) * np.diff(s))])
    return offsets, s, rho, z


def gore_revolution(mesh: RestMesh, assembly: Assembly) -> tuple[FloatArray, np.ndarray]:
    """Place ring nodes on the surface of revolution of their sewn circumference.

    Parameters
    ----------
    mesh : RestMesh
        Sewn mesh.
    assembly : Assembly
        Instances and spec (rings).

    Returns
    -------
    (ndarray, ndarray)
        Positions ``(n, 3)`` in m (NaN for nodes outside every ring) and a boolean mask of
        placed nodes. Nodes sewn from several panels get the mean of their placements.
    """
    positions = np.zeros((mesh.n_nodes, 3))
    counts = np.zeros(mesh.n_nodes)
    index = {iid: k for k, iid in enumerate(mesh.instance_ids)}
    placements: dict[int, tuple[RingSpec, float, int, FloatArray, FloatArray, FloatArray]] = {}
    for ring in assembly.spec.rings:
        offsets, s, rho, z = _ring_profile(ring, assembly.instances)
        for row_i, row in enumerate(ring.rows):
            for gore_i, gore in enumerate(ring.gores):
                iid = ring.instance_id(row, gore)
                if iid in index:
                    placements[index[iid]] = (ring, offsets[row_i], gore_i, s, rho, z)
    for node, refs in enumerate(mesh.node_refs):
        for inst_k, u, v in refs:
            if inst_k not in placements:
                continue
            ring, offset, gore_i, s, rho, z = placements[inst_k]
            inst = assembly.instances[mesh.instance_ids[inst_k]]
            yl, xl = _edge_x_of_y(inst.edges[ring.edges["left"]].points)
            yr, xr = _edge_x_of_y(inst.edges[ring.edges["right"]].points)
            left = float(np.interp(v, yl, xl))
            right = float(np.interp(v, yr, xr))
            tau = (u - left) / max(right - left, 1e-12)
            theta = 2 * math.pi * (gore_i + tau) / ring.gore_count
            sv = offset + v
            r = float(np.interp(sv, s, rho))
            positions[node] += (
                r * math.cos(theta),
                r * math.sin(theta),
                float(np.interp(sv, s, z)),
            )
            counts[node] += 1
    placed = counts > 0
    positions[placed] /= counts[placed, None]
    positions[~placed] = np.nan
    return positions, placed


def _vertex_normals(positions: FloatArray, triangles: IntArray, n: int) -> FloatArray:
    p = np.nan_to_num(positions)
    face = np.cross(
        p[triangles[:, 1]] - p[triangles[:, 0]], p[triangles[:, 2]] - p[triangles[:, 0]]
    )
    normals = np.zeros((n, 3))
    for k in range(3):
        np.add.at(normals, triangles[:, k], face)
    length = np.linalg.norm(normals, axis=1)
    return np.asarray(normals / np.maximum(length, 1e-300)[:, None], dtype=np.float64)


def extend_to_parts(
    mesh: RestMesh,
    positions: FloatArray,
    placed: np.ndarray,
    lift: float,
    warnings: list[ImportWarning],
) -> FloatArray:
    """Place unplaced nodes by harmonic extension plus a lift along the attachment normal.

    Parameters
    ----------
    mesh : RestMesh
        Sewn mesh.
    positions : ndarray, shape (n, 3)
        Positions in m; rows of unplaced nodes are ignored.
    placed : ndarray of bool, shape (n,)
        Nodes with a trusted position.
    lift : float
        Outward offset per m of rest-mesh distance from the placed nodes (dimensionless).
    warnings : list of ImportWarning
        Appended when a part is not connected to any placed node.

    Returns
    -------
    ndarray, shape (n, 3)
        Positions for every node, m.
    """
    out = positions.copy()
    if np.all(placed):
        return out
    tris = mesh.triangles
    edges = np.unique(
        np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1), axis=0
    )
    uv = mesh.rest_uv
    lengths = np.concatenate(
        [np.hypot(*(uv[:, j] - uv[:, i]).T) for i, j in ((0, 1), (1, 2), (2, 0))]
    )
    directed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    n = mesh.n_nodes
    weights = coo_matrix((lengths, (directed[:, 0], directed[:, 1])), shape=(n, n)).tocsr()
    weights = weights.maximum(weights.T)
    free = np.flatnonzero(~placed)
    fixed = np.flatnonzero(placed)
    adjacency = csr_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(n, n))
    adjacency = adjacency + adjacency.T
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    lap = (coo_matrix((degree, (np.arange(n), np.arange(n))), shape=(n, n)) - adjacency).tocsr()
    sub = adjacency[free][:, free]
    n_comp, labels = connected_components(sub, directed=False)
    distance = np.full(n, np.inf)
    if len(fixed):
        distance = dijkstra(weights, indices=fixed, min_only=True)
    normals = _vertex_normals(np.where(placed[:, None], positions, 0.0), tris, n)
    for comp in range(n_comp):
        nodes = free[labels == comp]
        touching = np.unique(adjacency[nodes][:, fixed].nonzero()[1])
        if len(touching) == 0:
            warnings.append(
                ImportWarning(
                    "assumption",
                    f"{len(nodes)} rest-mesh nodes are not connected to any placed panel; "
                    "they keep their flat coordinates as the initial guess",
                    severity="warning",
                )
            )
            for node in nodes:
                k, u, v = mesh.node_refs[node][0]
                out[node] = (u, v, 0.0)
            continue
        boundary = fixed[touching]
        lap_ff = lap[nodes][:, nodes]
        rhs = -lap[nodes][:, boundary] @ positions[boundary]
        solved = np.column_stack([spsolve(lap_ff.tocsc(), rhs[:, k]) for k in range(3)])
        normal = normals[boundary].mean(axis=0)
        norm = float(np.linalg.norm(normal))
        normal = normal / norm if norm > 0 else np.array([0.0, 0.0, 1.0])
        out[nodes] = solved + lift * distance[nodes, None] * normal
    return relax_free_nodes(mesh, out, placed)


def relax_free_nodes(
    mesh: RestMesh,
    positions: FloatArray,
    placed: np.ndarray,
    iterations: int = 300,
    push: float = 0.005,
) -> FloatArray:
    """Relax unplaced nodes towards their rest edge lengths (position-based projection).

    Each iteration moves every free node by the mean of its edge-length corrections
    (Jacobi projection of the constraints :math:`|x_j - x_i| = L_{ij}`) plus an outward
    push of ``push`` times the mean rest edge length along the vertex normal, which
    unfolds collapsed regions. Placed nodes do not move. This only improves the initial
    guess; it is not an equilibrium solve.

    Parameters
    ----------
    mesh : RestMesh
        Sewn mesh (rest edge lengths from ``rest_uv``).
    positions : ndarray, shape (n, 3)
        Start positions, m.
    placed : ndarray of bool, shape (n,)
        Fixed nodes.
    iterations : int
        Number of Jacobi sweeps.
    push : float
        Outward push per sweep as a fraction of the mean rest edge length.

    Returns
    -------
    ndarray, shape (n, 3)
        Relaxed positions, m.
    """
    free = ~placed
    if not np.any(free):
        return positions
    tris = mesh.triangles
    uv = mesh.rest_uv
    pairs = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    rest = np.concatenate([np.hypot(*(uv[:, j] - uv[:, i]).T) for i, j in ((0, 1), (1, 2), (2, 0))])
    involved = free[pairs[:, 0]] | free[pairs[:, 1]]
    pairs, rest = pairs[involved], rest[involved]
    active_tris = tris[np.any(free[tris], axis=1)]
    step = push * float(rest.mean())
    x = positions.copy()
    count = np.bincount(pairs.ravel(), minlength=len(x)).astype(float)
    for _ in range(iterations):
        d = x[pairs[:, 1]] - x[pairs[:, 0]]
        length = np.maximum(np.linalg.norm(d, axis=1), 1e-12)
        corr = 0.5 * ((length - rest) / length)[:, None] * d
        delta = np.zeros_like(x)
        np.add.at(delta, pairs[:, 0], corr)
        np.add.at(delta, pairs[:, 1], -corr)
        normals = _vertex_normals(x, active_tris, len(x))
        move = delta / np.maximum(count, 1.0)[:, None] + step * normals
        x[free] += move[free]
    return x


def load_obj(path: Path) -> tuple[FloatArray, IntArray]:
    """Read vertices and triangular faces from a Wavefront OBJ file (m).

    Parameters
    ----------
    path : Path
        OBJ file; polygons are fan-triangulated.

    Returns
    -------
    (ndarray, ndarray)
        Vertices ``(n, 3)`` in m and triangles ``(m, 3)``.
    """
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            vertices.append([float(x) for x in parts[1:4]])
        elif parts[0] == "f":
            idx = [int(p.split("/")[0]) for p in parts[1:]]
            idx = [i - 1 if i > 0 else len(vertices) + i for i in idx]
            faces.extend([idx[0], idx[k], idx[k + 1]] for k in range(1, len(idx) - 1))
    if not vertices or not faces:
        raise InitialShapeError(f"{path}: no vertices or faces")
    return np.array(vertices), np.array(faces, dtype=np.int64)


def closest_points_on_triangles(
    points: FloatArray, a: FloatArray, b: FloatArray, c: FloatArray
) -> FloatArray:
    """Closest point on triangle ``(a, b, c)`` to each point (row-wise) [Ericson]_.

    Parameters
    ----------
    points, a, b, c : ndarray, shape (k, 3)
        Query points and triangle corners, m.

    Returns
    -------
    ndarray, shape (k, 3)
        Closest points, m.
    """
    ab, ac, ap = b - a, c - a, points - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = points - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = points - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = np.where(np.abs(va + vb + vc) > 1e-300, va + vb + vc, 1e-300)
    v = vb / denom
    w = vc / denom
    result = a + ab * v[:, None] + ac * w[:, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        # Vertex regions.
        m = (d1 <= 0) & (d2 <= 0)
        result[m] = a[m]
        m = (d3 >= 0) & (d4 <= d3)
        result[m] = b[m]
        m = (d6 >= 0) & (d5 <= d6)
        result[m] = c[m]
        # Edge regions.
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = d1 / (d1 - d3)
        result[m] = (a + ab * t[:, None])[m]
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = d2 / (d2 - d6)
        result[m] = (a + ac * t[:, None])[m]
        m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        result[m] = (b + (c - b) * t[:, None])[m]
    return np.asarray(result, dtype=np.float64)


def project_to_reference(
    positions: FloatArray, vertices: FloatArray, faces: IntArray, candidates: int = 12
) -> FloatArray:
    """Project points onto a triangle mesh (closest point among nearby triangles).

    Parameters
    ----------
    positions : ndarray, shape (n, 3)
        Points, m.
    vertices : ndarray, shape (v, 3)
        Reference vertices, m.
    faces : ndarray of int, shape (f, 3)
        Reference triangles.
    candidates : int
        Number of nearest triangle centroids tested per point.

    Returns
    -------
    ndarray, shape (n, 3)
        Projected points, m.
    """
    centroids = vertices[faces].mean(axis=1)
    k = min(candidates, len(faces))
    _, near = cKDTree(centroids).query(positions, k=k)
    near = np.asarray(near).reshape(len(positions), k)
    best = np.full(len(positions), np.inf)
    out = positions.copy()
    for j in range(k):
        f = faces[near[:, j]]
        q = closest_points_on_triangles(
            positions, vertices[f[:, 0]], vertices[f[:, 1]], vertices[f[:, 2]]
        )
        d = np.linalg.norm(q - positions, axis=1)
        better = d < best
        out[better] = q[better]
        best[better] = d[better]
    return out


def initial_positions(
    mesh: RestMesh, assembly: Assembly, warnings: list[ImportWarning]
) -> FloatArray:
    """Initial 3D node positions for the rest model, following ``spec.initial_shape``.

    Parameters
    ----------
    mesh : RestMesh
        Sewn mesh.
    assembly : Assembly
        Assembly (rings, parts, initial-shape settings).
    warnings : list of ImportWarning
        Appended with the assumptions made.

    Returns
    -------
    ndarray, shape (n, 3)
        Positions in m.
    """
    spec = assembly.spec.initial_shape
    if not assembly.spec.rings:
        raise InitialShapeError(
            "the initial guess needs at least one gore ring to anchor the parts; special "
            "shapes without a ring are not supported yet"
        )
    positions, placed = gore_revolution(mesh, assembly)
    positions = extend_to_parts(mesh, positions, placed, spec.appendage_lift, warnings)
    if int((~placed).sum()):
        warnings.append(
            ImportWarning(
                "assumption",
                f"{int((~placed).sum())} appendage nodes placed by harmonic extension with lift "
                f"{spec.appendage_lift:g} (initial guess only)",
                severity="info",
            )
        )
    if spec.method == "reference_mesh":
        if spec.reference_mesh is None:
            raise InitialShapeError("initial_shape.method is reference_mesh but no file given")
        vertices, faces = load_obj(assembly.spec.base_dir / spec.reference_mesh)
        positions = project_to_reference(positions, vertices, faces)
        warnings.append(
            ImportWarning(
                "assumption",
                f"initial guess projected onto reference mesh {spec.reference_mesh} (initial "
                "guess only, not the inflated shape)",
                severity="info",
            )
        )
    return positions
