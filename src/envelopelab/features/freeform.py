r"""Free-form shapes from a 3D mesh (Blender) on a standard-gore envelope.

A :class:`~envelopelab.features.primitives.FreeformShape` is a triangle mesh modelled in
its own frame (metres, :math:`z` along the shape's axis, out of the envelope;
:math:`x` up the tape towards the crown; :math:`y = z \times x`; origin on the envelope
at the base point). The part of the mesh below the envelope is cut away, so model the
shape sunk a little into the envelope, as for a boolean union in Blender.

Placement and footprint
-----------------------
The mesh is placed with the axis frame of the primitives
(:math:`\mathbf{x} = \mathbf{P}_0 + x\,\mathbf{b}_1 + y\,\mathbf{b}_2 + z\,\mathbf{a}`)
and clipped at the envelope: every edge whose ends lie on either side of the envelope is
cut at the envelope (signed distance zero, bisection to :data:`ROOT_TOLERANCE`), and the
triangles inside are dropped. The cut edge is the footprint; it must be one closed loop
that turns once round the axis.

Panels
------
The clipped skin is cut along the half-planes through the axis at
:math:`\phi_j = 2\pi j/M - \pi/M`, like the gores of a revolved shape. Every panel must
be a disc bounded by the footprint, its two seams and the *pole*, where the axis leaves
the mesh; shapes whose axis does not pass through their top are rejected (lean the
placement or use more panels).

Flattening
----------
Each panel is flattened by least-squares conformal maps [Levy]_ followed by
as-rigid-as-possible iterations [Liu]_: alternately fit each triangle's best rotation
and solve the cotangent-weighted Laplace system for the flat positions,

.. math:: \min_{\mathbf{u}} \sum_t \sum_{(i,j) \in t} c_{ij}
          \lVert (\mathbf{u}_i - \mathbf{u}_j) - R_t (\mathbf{x}_i - \mathbf{x}_j) \rVert^2,

with the weights of seam and footprint edges raised by :data:`EDGE_WEIGHT`. The panel's
boundary is then rebuilt with every edge at its exact 3D length (edge directions from
that solution, the closure gap removed by the least-norm change of the edge angles) and
the interior relaxed again with the boundary held, so footprint and seams keep their
true lengths and both sides of every seam match; the unavoidable strain of flattening a
doubly curved panel goes into its interior, where the ``area distortion`` and ``edge
strain`` checks report it.

Valid range: the mesh must be a manifold surface, closed except where it enters the
envelope; panels must be discs (no handles); the flattened panels must not fold
(checked). The sub-model rests every triangle in its flat panel as cut; the input mesh
is the designed surface as given (no chord correction, unlike the parametric shapes).

References
----------
.. [Levy] B. Lévy, S. Petitjean, N. Ray and J. Maillot, "Least squares conformal maps
   for automatic texture atlas generation", ACM Trans. Graph. 21(3) (2002) 362-371.
.. [Liu] L. Liu, L. Zhang, Y. Xu, C. Gotsman and S. J. Gortler, "A local/global approach
   to mesh parameterization", Comput. Graph. Forum 27(5) (2008) 1495-1504.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.sparse import coo_matrix, csc_matrix
from scipy.sparse.linalg import splu
from scipy.spatial import cKDTree

from envelopelab.features.builder import DesignedSkin, FeatureBuildError, HostSurface, _mesh_disc
from envelopelab.geometry.polygon import offset_polygon, signed_area
from envelopelab.solvers.membrane import FloatArray, IntArray

if TYPE_CHECKING:
    from envelopelab.features.primitives import (
        EnvelopeSurface,
        FreeformShape,
        PrimitiveDesign,
    )

ROOT_TOLERANCE = 1e-7  # m, footprint bisection (source: assumed)
EDGE_WEIGHT = 200.0  # ARAP weight factor of seam and footprint edges (source: assumed)
ARAP_ITERATIONS = 60
EDGE_STRAIN_LIMIT = 0.02  # largest flat/3D edge length difference flagged (assumed)


def _cut(
    x: FloatArray,
    tri: IntArray,
    value: FloatArray,
    keep: str,
    tol: float,
    point: Any = None,
    accept: Any = None,
    parents: list[int] | None = None,
) -> tuple[FloatArray, IntArray]:
    """Split a triangle mesh along ``value = 0``.

    Vertices with ``|value| <= tol`` lie on the cut and are never split.
    ``point(A, B, S)`` places the crossings on edges ``AB`` (arrays of edge ends, shape
    (k, 3), and linear fractions, shape (k,); default linear), ``accept(P)`` says which
    crossings at ``P`` (shape (k, 3)) are cut at all (a half-plane). ``keep="pos"``
    drops the negative side, ``"both"`` keeps both sides. ``parents``, when given,
    receives the input triangle of every output triangle.

    Only the triangles the cut crosses are split, one by one; the others are copied as
    they are. New vertices are numbered in the order the triangles first use their edges.
    """
    sign = np.where(value > tol, 1, np.where(value < -tol, -1, 0))
    st = sign[tri]
    pos, neg = (st > 0).any(axis=1), (st < 0).any(axis=1)
    crossed = np.flatnonzero(pos & neg)
    side = np.where(pos, 1, np.where(neg, -1, 0))

    # Each crossed triangle: one vertex on the cut (one crossing) or none (two).
    plans: list[tuple[int, int, int, int, int]] = []
    edge_index: dict[tuple[int, int], int] = {}
    ends: list[tuple[int, int]] = []

    def edge(a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in edge_index:
            edge_index[key] = len(ends)
            ends.append((a, b))  # oriented as first used, as the crossing is computed
        return edge_index[key]

    for t in crossed.tolist():
        tt, s3 = tri[t], st[t]
        zero = np.flatnonzero(s3 == 0)
        if len(zero) == 1:
            z = int(zero[0])
            a, b, c = int(tt[z]), int(tt[(z + 1) % 3]), int(tt[(z + 2) % 3])
            edge(b, c)
            plans.append((t, 1, a, b, c))
        else:
            n_pos = int((s3 > 0).sum())
            odd = int(np.flatnonzero(s3 > 0 if n_pos == 1 else s3 < 0)[0])
            a, b, c = int(tt[odd]), int(tt[(odd + 1) % 3]), int(tt[(odd + 2) % 3])
            edge(a, b)
            edge(a, c)
            plans.append((t, 2, a, b, c))

    # Every crossing at once.
    vertex = np.full(len(ends), -1, dtype=np.int64)
    new_points = np.zeros((0, 3))
    if ends:
        ea = np.array([e[0] for e in ends], dtype=np.int64)
        eb = np.array([e[1] for e in ends], dtype=np.int64)
        frac = value[ea] / (value[ea] - value[eb])
        pa, pb = x[ea], x[eb]
        pts = pa + frac[:, None] * (pb - pa) if point is None else point(pa, pb, frac)
        ok = np.ones(len(ends), dtype=bool) if accept is None else np.asarray(accept(pts))
        vertex[ok] = len(x) + np.arange(int(ok.sum()))
        new_points = np.asarray(pts)[ok]

    # The pieces of each crossed triangle (a crossing that is not cut leaves it whole).
    pieces: dict[int, tuple[list[list[int]], list[int]]] = {}
    for t, kind, a, b, c in plans:
        if kind == 1:
            m = int(vertex[edge_index[(min(b, c), max(b, c))]])
            if m < 0:
                pieces[t] = ([[a, b, c]], [2])
            else:
                pieces[t] = ([[a, b, m], [a, m, c]], [int(sign[b]), int(sign[c])])
            continue
        ab = int(vertex[edge_index[(min(a, b), max(a, b))]])
        ac = int(vertex[edge_index[(min(a, c), max(a, c))]])
        if ab < 0 and ac < 0:
            pieces[t] = ([[a, b, c]], [2])
            continue
        if ab < 0 or ac < 0:
            raise FeatureBuildError("a seam cut ends inside a triangle (axis not through the pole)")
        pieces[t] = (
            [[a, ab, ac], [ab, b, c], [ab, c, ac]],
            [int(sign[a]), int(sign[b]), int(sign[b])],
        )

    # Assemble in the input order.
    counts = np.ones(len(tri), dtype=np.int64)
    for t, (tris, _) in pieces.items():
        counts[t] = len(tris)
    first = np.concatenate([[0], np.cumsum(counts)[:-1]])
    out = np.repeat(tri, counts, axis=0)
    out_side = np.repeat(side, counts)
    for t, (tris, sides) in pieces.items():
        out[first[t] : first[t] + len(tris)] = tris
        out_side[first[t] : first[t] + len(tris)] = sides
    src = np.repeat(np.arange(len(tri)), counts)
    keep_mask = out_side > 0 if keep == "pos" else np.ones(len(out), dtype=bool)
    if parents is not None:
        parents[:] = src[keep_mask].tolist()
    return np.vstack([x, new_points]), out[keep_mask]


def _insert_pole(
    x: FloatArray, tri: IntArray, base: FloatArray, axis: FloatArray
) -> tuple[FloatArray, IntArray, int]:
    """Insert the point where the axis leaves the mesh as a vertex (Moller-Trumbore)."""
    p = x[tri]
    e1, e2 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    h = np.cross(axis, e2)
    det = np.einsum("mi,mi->m", e1, h)
    ok = np.abs(det) > 1e-14
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = base - p[:, 0]
    u = np.einsum("mi,mi->m", s, h) * inv
    q = np.cross(s, e1)
    v = np.einsum("j,mj->m", axis, q) * inv
    t = np.einsum("mi,mi->m", e2, q) * inv
    hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 0)
    if not hit.any():
        raise FeatureBuildError("the shape's axis does not leave the mesh; lean the placement")
    k = int(np.flatnonzero(hit)[np.argmax(t[hit])])
    bary = np.array([1.0 - u[k] - v[k], u[k], v[k]])
    pole = base + t[k] * axis
    tk = tri[k]
    if bary.min() < 1e-3:
        # Close to an edge or a vertex: move the nearest vertex onto the axis instead.
        j = int(tk[int(np.argmax(bary))])
        x = x.copy()
        x[j] = pole
        return x, tri, j
    j = len(x)
    x = np.vstack([x, pole])
    new = [[tk[0], tk[1], j], [tk[1], tk[2], j], [tk[2], tk[0], j]]
    tri = np.vstack([np.delete(tri, k, axis=0), new])
    return x, tri, j


def _boundary_loops(tri: IntArray) -> list[list[int]]:
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    key = np.sort(e, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    if np.any(cnt > 2):
        raise FeatureBuildError("the shape mesh is not a manifold surface")
    border = e[cnt[inv.ravel()] == 1]
    nxt = {int(a): int(b) for a, b in border}
    if len(nxt) != len(border):
        raise FeatureBuildError("the shape mesh boundary touches itself")
    loops = []
    left = set(nxt)
    while left:
        start = left.pop()
        loop = [start]
        cur = nxt[start]
        while cur != start:
            loop.append(cur)
            left.discard(cur)
            cur = nxt[cur]
        loops.append(loop)
    return loops


def _local_frames(x: FloatArray, tri: IntArray) -> FloatArray:
    """Isometric 2D coordinates of every triangle's corners, shape (m, 3, 2)."""
    p = x[tri]
    e1 = p[:, 1] - p[:, 0]
    l1 = np.linalg.norm(e1, axis=1)
    e1 /= l1[:, None]
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    n /= np.linalg.norm(n, axis=1)[:, None]
    e2 = np.cross(n, e1)
    d2 = p[:, 2] - p[:, 0]
    out = np.zeros((len(tri), 3, 2))
    out[:, 1, 0] = l1
    out[:, 2, 0] = np.einsum("mi,mi->m", d2, e1)
    out[:, 2, 1] = np.einsum("mi,mi->m", d2, e2)
    return out


def _true_length_boundary(x: FloatArray, flat: FloatArray, loop: list[int]) -> FloatArray:
    """Flat boundary with every edge at its 3D length, closed by small edge rotations.

    Edge directions start from ``flat``; the closure gap is removed by the least-norm
    change of the edge angles (lengths unchanged), iterated to convergence.
    """
    nxt = loop[1:] + loop[:1]
    length = np.linalg.norm(x[nxt] - x[loop], axis=1)
    d = flat[nxt] - flat[loop]
    ang = np.arctan2(d[:, 1], d[:, 0])
    for _ in range(50):
        steps = length[:, None] * np.column_stack([np.cos(ang), np.sin(ang)])
        gap = steps.sum(axis=0)
        if float(np.linalg.norm(gap)) < 1e-12 * float(length.sum()):
            break
        jac = np.vstack([-steps[:, 1], steps[:, 0]])  # d(gap)/d(angle), shape (2, n)
        ang = ang - jac.T @ np.linalg.solve(jac @ jac.T, gap)
    else:
        raise FeatureBuildError("a panel boundary cannot be closed at its true lengths")
    steps = length[:, None] * np.column_stack([np.cos(ang), np.sin(ang)])
    pts = flat[loop[0]] + np.vstack([np.zeros((1, 2)), np.cumsum(steps, axis=0)[:-1]])
    out = flat.copy()
    out[loop] = pts
    return out


def _lscm(x: FloatArray, tri: IntArray, pins: tuple[int, int]) -> FloatArray:
    """Least-squares conformal map with two pinned vertices [Levy]_."""
    n = len(x)
    loc = _local_frames(x, tri)
    area = 0.5 * np.abs(loc[:, 1, 0] * loc[:, 2, 1])
    rows, cols, vals = [], [], []
    for k in range(3):
        a, b = (k + 1) % 3, (k + 2) % 3
        w = (loc[:, b] - loc[:, a]) / np.sqrt(2.0 * np.maximum(area, 1e-300))[:, None]
        rows.append(np.arange(len(tri)))
        cols.append(tri[:, k])
        vals.append(w[:, 0] + 1j * w[:, 1])
    m = coo_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(len(tri), n)
    ).tocsc()
    mr, mi = m.real, m.imag
    big = coo_matrix(np.zeros((0, 0)))
    from scipy.sparse import bmat

    big = bmat([[mr, -mi], [mi, mr]]).tocsc()
    pin_idx = [pins[0], pins[1], pins[0] + n, pins[1] + n]
    pin_val = np.array([0.0, 1.0, 0.0, 0.0])
    free = np.setdiff1d(np.arange(2 * n), pin_idx)
    rhs = -big[:, pin_idx] @ pin_val
    # The least-squares solution from the normal equations, factorised directly (the
    # system is small and sparse; an iterative solver needs thousands of products).
    a = big[:, free]
    sol = splu(csc_matrix(a.T @ a)).solve(a.T @ rhs)
    full = np.zeros(2 * n)
    full[free] = sol
    full[pin_idx] = pin_val
    return np.column_stack([full[:n], full[n:]])


def _best_rotations(cov: FloatArray) -> tuple[FloatArray, FloatArray]:
    r"""Cosine and sine of the rotation :math:`R` maximising :math:`\operatorname{tr}(R^T C)`
    for each 2 x 2 matrix :math:`C` of ``cov`` (shape (m, 2, 2)):
    :math:`\theta = \operatorname{atan2}(C_{10} - C_{01}, C_{00} + C_{11})`, the rotation an
    SVD of :math:`C` gives (with its reflection removed)."""
    theta = np.arctan2(cov[:, 1, 0] - cov[:, 0, 1], cov[:, 0, 0] + cov[:, 1, 1])
    return np.cos(theta), np.sin(theta)


def _arap(
    x: FloatArray,
    tri: IntArray,
    init: FloatArray,
    heavy: set[tuple[int, int]],
    fixed: IntArray | None = None,
) -> FloatArray:
    r"""As-rigid-as-possible flattening [Liu]_ from ``init`` (heavy edges weighted up;
    ``fixed`` vertices keep their ``init`` positions).

    The local step's best rotation of each triangle is closed-form in 2D: for the
    cotangent-weighted covariance :math:`C = \sum c_{ij} \Delta u\,\Delta x^T`, the
    rotation by :math:`\theta = \operatorname{atan2}(C_{10} - C_{01}, C_{00} + C_{11})`
    maximises :math:`\operatorname{tr}(R^T C)` (the polar factor an SVD would give).
    """
    n = len(x)
    loc = _local_frames(x, tri)
    cot = np.zeros((len(tri), 3))
    for k in range(3):
        a, b = loc[:, (k + 1) % 3] - loc[:, k], loc[:, (k + 2) % 3] - loc[:, k]
        cross = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
        cot[:, k] = np.einsum("mi,mi->m", a, b) / np.maximum(np.abs(cross), 1e-300)
    cot = np.clip(cot, 1e-3, None)
    if heavy:
        # Edge (i, j) as one integer i * n + j (i < j), looked up in the heavy set.
        heavy_keys = np.fromiter((i * n + j for i, j in heavy), dtype=np.int64)
        for k in range(3):
            i, j = tri[:, (k + 1) % 3], tri[:, (k + 2) % 3]
            keys = np.minimum(i, j).astype(np.int64) * n + np.maximum(i, j)
            cot[np.isin(keys, heavy_keys), k] *= EDGE_WEIGHT
    rows, cols, vals = [], [], []
    for k in range(3):
        i, j = tri[:, (k + 1) % 3], tri[:, (k + 2) % 3]
        w = cot[:, k]
        rows += [i, j, i, j]
        cols += [i, j, j, i]
        vals += [w, w, -w, -w]
    lap = coo_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)
    ).tocsc()
    pinned = np.array([0]) if fixed is None or not len(fixed) else np.asarray(fixed)
    free = np.setdiff1d(np.arange(n), pinned)
    solver = splu(csc_matrix(lap[free][:, free]))
    lap_fp = lap[free][:, pinned]
    # Gather (edge k of triangle t -> its two vertices) as one sparse matrix, so the right
    # hand side is a product instead of a scatter.
    m = len(tri)
    gather = coo_matrix(
        (
            np.concatenate([np.ones(3 * m), -np.ones(3 * m)]),
            (
                np.concatenate([tri[:, [1, 2, 0]].T.ravel(), tri[:, [2, 0, 1]].T.ravel()]),
                np.concatenate([np.arange(3 * m), np.arange(3 * m)]),
            ),
        ),
        shape=(n, 3 * m),
    ).tocsr()
    dxs = [loc[:, (k + 1) % 3] - loc[:, (k + 2) % 3] for k in range(3)]
    u = init.copy()
    for _ in range(ARAP_ITERATIONS):
        cov = np.zeros((m, 2, 2))
        for k in range(3):
            i, j = tri[:, (k + 1) % 3], tri[:, (k + 2) % 3]
            du = u[i] - u[j]
            cov += cot[:, k][:, None, None] * du[:, :, None] * dxs[k][:, None, :]
        c, sn = _best_rotations(cov)
        r = np.concatenate(
            [
                cot[:, k][:, None]
                * np.column_stack(
                    [c * dxs[k][:, 0] - sn * dxs[k][:, 1], sn * dxs[k][:, 0] + c * dxs[k][:, 1]]
                )
                for k in range(3)
            ]
        )
        rhs = gather @ r
        rhs_f = rhs[free] - lap_fp @ u[pinned]
        u[free] = solver.solve(np.ascontiguousarray(rhs_f))
    return u


@dataclass
class _Panel:
    """One flattened panel: 3D triangles, flat coordinates and its boundary runs.

    ``top`` runs from the top of the right seam to the top of the left one (the pole alone
    without a cap); ``glob`` maps the panel's vertices to the skin's. The cap is a
    ``_Panel`` too, with only a ``top``: its closed loop.
    """

    x: FloatArray
    tri: IntArray
    flat: FloatArray
    rim: list[int]
    right: list[int]
    left: list[int]
    phi_a: float
    phi_b: float
    top: list[int] = field(default_factory=list)
    glob: IntArray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))

    def arc(self, run: list[int], world: bool) -> FloatArray:
        p = self.x[run] if world else self.flat[run]
        return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])

    def run_flat_at(self, run: list[int], frac: FloatArray) -> FloatArray:
        """Flat points at 3D arc-length fractions along a boundary run."""
        s = self.arc(run, True)
        f = np.asarray(frac) * s[-1]
        return np.column_stack([np.interp(f, s, self.flat[run][:, k]) for k in range(2)])

    def run_world_at(self, run: list[int], frac: FloatArray) -> FloatArray:
        s = self.arc(run, True)
        f = np.asarray(frac) * s[-1]
        return np.column_stack([np.interp(f, s, self.x[run][:, k]) for k in range(3)])

    def to_world(self, xy: FloatArray) -> FloatArray:
        """3D points of flat points (barycentric in the flat triangulation)."""
        p = self.flat[self.tri]
        a, b, c = p[:, 0], p[:, 1], p[:, 2]
        out = np.zeros((len(xy), 3))
        det = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
        for k, q in enumerate(xy):
            l1 = (
                (q[0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (q[1] - a[:, 1]) * (c[:, 0] - a[:, 0])
            ) / det
            l2 = (
                (b[:, 0] - a[:, 0]) * (q[1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (q[0] - a[:, 0])
            ) / det
            l0 = 1.0 - l1 - l2
            worst = np.minimum(np.minimum(l0, l1), l2)
            t = int(np.argmax(worst))
            w = np.array([l0[t], l1[t], l2[t]])
            w = np.clip(w, 0.0, None)
            w /= w.sum()
            out[k] = w @ self.x[self.tri[t]]
        return out


@dataclass
class _MeshSkin:
    """Clipped and panelled mesh skin (the free-form counterpart of the revolved skin)."""

    shape: FreeformShape
    surface: EnvelopeSurface
    base: FloatArray
    axis: FloatArray
    b1: FloatArray
    b2: FloatArray
    x: FloatArray
    tri: IntArray
    rim_loop: list[int]
    rim_phi: FloatArray
    panels: list[_Panel] = field(default_factory=list)
    pole: FloatArray = field(default_factory=lambda: np.zeros(3))
    cap: _Panel | None = None
    cap_mask: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    cap_floor: float = 0.0

    def phi_of(self, points: FloatArray) -> FloatArray:
        rel = np.asarray(points).reshape(-1, 3) - self.base
        return np.arctan2(rel @ self.b2, rel @ self.b1)

    def max_height(self) -> float:
        return float(self.surface.signed_distance(self.x).max())

    def rim_points(self, phi: FloatArray) -> FloatArray:
        """Footprint points at angles ``phi`` round the axis (rad), m."""
        pts = self.x[self.rim_loop]
        ang = self.rim_phi
        order = np.argsort(ang)
        ph = np.mod(np.asarray(phi, float) - ang[order][0], 2 * math.pi) + ang[order][0]
        return np.column_stack(
            [np.interp(ph, ang[order], pts[order, k], period=2 * math.pi) for k in range(3)]
        )

    def seam_length(self, j: int) -> float:
        p = self.panels[j % len(self.panels)]
        return float(p.arc(p.left, True)[-1])

    def panel_of(self, phi: float) -> int:
        m = len(self.panels)
        width = 2 * math.pi / m
        start = self.panels[0].phi_a
        return int(((phi - start) % (2 * math.pi)) // width) % m

    def rim_flat(self, k: int, phi: FloatArray) -> FloatArray:
        """Flat rim points of panel ``k`` at angles ``phi`` (rad), m."""
        p = self.panels[k]
        ang = np.unwrap(self.phi_of(p.x[p.rim]))
        q = np.unwrap(np.concatenate([[ang[0]], np.asarray(phi, float)]))[1:]
        q = ang[0] + np.mod(q - ang[0] + math.pi, 2 * math.pi) - math.pi
        order = np.argsort(ang)
        return np.column_stack(
            [np.interp(q, ang[order], p.flat[p.rim][order, c]) for c in range(2)]
        )

    def cap_seam_points(self) -> tuple[tuple[float, float], ...]:
        """Where every seam meets the flattened cap's edge, m, seam 1 first."""
        cap = self.cap
        if cap is None:
            return ()
        local = {int(g): i for i, g in enumerate(cap.glob)}
        out = []
        for p in self.panels:
            xy = cap.flat[local[int(p.glob[p.top[-1]])]]
            out.append((float(xy[0]), float(xy[1])))
        return tuple(out)

    def factory(self, design: PrimitiveDesign, host: HostSurface) -> _MeshFactory:
        return _MeshFactory(design, self)


def build_mesh_skin(
    shape: FreeformShape,
    surface: EnvelopeSurface,
    base: FloatArray,
    axis: FloatArray,
    b1: FloatArray,
    b2: FloatArray,
) -> _MeshSkin:
    """Place, clip, panel and flatten a free-form mesh (module docstring)."""
    name = shape.name
    local = np.asarray(shape.mesh.vertices, dtype=np.float64)
    world = base + local[:, :1] * b1 + local[:, 1:2] * b2 + local[:, 2:3] * axis

    def refine(a: FloatArray, b: FloatArray, _s: FloatArray) -> FloatArray:
        """Crossings of edges ``ab`` with the envelope, by bisection (all at once)."""
        lo, hi = np.zeros(len(a)), np.ones(len(a))
        sa = surface.signed_distance(a) > 0
        length = np.linalg.norm(b - a, axis=1)
        active = np.ones(len(a), dtype=bool)
        for _ in range(60):
            idx = np.flatnonzero(active)
            if not len(idx):
                break
            mid = 0.5 * (lo[idx] + hi[idx])
            sm = surface.signed_distance(a[idx] + mid[:, None] * (b[idx] - a[idx])) > 0
            same = sm == sa[idx]
            lo[idx[same]] = mid[same]
            hi[idx[~same]] = mid[~same]
            active[idx[(hi[idx] - lo[idx]) * length[idx] < ROOT_TOLERANCE]] = False
        out: FloatArray = a + (0.5 * (lo + hi))[:, None] * (b - a)
        return out

    tri = np.asarray(shape.mesh.triangles, dtype=np.int64)
    sd = surface.signed_distance(world)
    if not (sd < 0).any():
        raise FeatureBuildError(
            f"{name}: the mesh does not reach into the envelope; sink its base below z = 0"
        )
    if not (sd > 0).any():
        raise FeatureBuildError(f"{name}: the mesh lies inside the envelope")
    scale = max(float(np.ptp(world, axis=0).max()), 1.0)
    tol = 1e-9 * scale
    x, tri = _cut(world, tri, sd, "pos", tol, refine)
    used = np.unique(tri)
    remap = np.full(len(x), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    x, tri = x[used], remap[tri]
    loops = _boundary_loops(tri)
    if len(loops) != 1:
        raise FeatureBuildError(
            f"{name}: the clipped mesh has {len(loops)} open edges; it must be closed except "
            "for one opening where it enters the envelope"
        )
    if not np.allclose(surface.signed_distance(x[loops[0]]), 0.0, atol=1e-5):
        raise FeatureBuildError(f"{name}: the mesh has holes above the envelope")
    x, tri, pole_index = _insert_pole(x, tri, base, axis)
    rim0 = set(loops[0])

    rc = float(shape.cap_radius)
    cap_tri = np.zeros(len(tri), dtype=bool)
    if rc > 0.0:
        x, tri, cap_tri = _cut_cap(name, x, tri, pole_index, rim0, base, axis, rc, tol)

    # Cut along the seam half-planes (each ends at the pole, which lies on every plane).
    m = shape.panels
    seams = 2.0 * math.pi * np.arange(m) / m - math.pi / m
    for ph in seams:
        d = math.cos(ph) * b1 + math.sin(ph) * b2
        n = -math.sin(ph) * b1 + math.cos(ph) * b2
        f = (x - base) @ n
        f[pole_index] = 0.0
        parents: list[int] = []
        x, tri = _cut(
            x,
            tri,
            f,
            "both",
            tol,
            accept=lambda p, d=d: (p - base) @ d > 0.0,
            parents=parents,
        )
        cap_tri = cap_tri[np.asarray(parents, dtype=np.int64)]

    rim = _boundary_loops(tri)[0]
    rel = x - base
    phi = np.arctan2(rel @ b2, rel @ b1)
    turns = np.sum(np.diff(np.unwrap(np.append(phi[rim], phi[rim][0])))) / (2 * math.pi)
    if abs(abs(turns) - 1.0) > 1e-6:
        raise FeatureBuildError(f"{name}: the footprint must turn once round the shape's axis")
    if turns < 0:
        rim = rim[::-1]
    skin = _MeshSkin(shape, surface, base, axis, b1, b2, x, tri, rim, phi[rim])
    skin.cap_mask = cap_tri
    # The panels end on the cap circle, or at the pole without a cap.
    on_top = np.zeros(len(x), dtype=bool)
    if rc > 0.0:
        cap_loop = _boundary_loops(tri[cap_tri])
        if len(cap_loop) != 1:
            raise FeatureBuildError(
                f"{name}: the cap of diameter {2 * rc:.3f} m is not a disc on the top of the "
                "shape; make it smaller"
            )
        on_top[cap_loop[0]] = True
    else:
        on_top[pole_index] = True
    # Assign the other triangles to panels by centroid angle.
    cen = x[tri].mean(axis=1) - base
    cphi = np.mod(np.arctan2(cen @ b2, cen @ b1) - seams[0], 2 * math.pi)
    which = np.minimum((cphi // (2 * math.pi / m)).astype(int), m - 1)
    which[cap_tri] = -1
    on_rim = np.zeros(len(x), dtype=bool)
    on_rim[rim] = True
    for k in range(m):
        sel = tri[which == k]
        if not len(sel):
            raise FeatureBuildError(f"{name}: panel {k + 1} is empty; use fewer panels")
        used = np.unique(sel)
        remap = np.full(len(x), -1, dtype=np.int64)
        remap[used] = np.arange(len(used))
        pt = remap[sel]
        px = x[used]
        loops = _boundary_loops(pt)
        if len(loops) != 1:
            raise FeatureBuildError(
                f"{name}: panel {k + 1} is not a disc; the shape's axis must pass through its "
                "top (lean the placement) or use more panels"
            )
        loop = loops[0]
        rel = px - base
        fa = rel @ (-math.sin(seams[k]) * b1 + math.cos(seams[k]) * b2)
        fb_phi = seams[(k + 1) % m]
        fb = rel @ (-math.sin(fb_phi) * b1 + math.cos(fb_phi) * b2)
        rimmed = on_rim[used]
        topped = on_top[used]
        seam_tol = 1e-7 * scale
        # Orient the loop with the rim running in increasing angle, then split it. The
        # loop is first rotated to start where the rim does, so the rim is one run.
        if sum(1 for v in loop if rimmed[v]) < 2:
            raise FeatureBuildError(f"{name}: panel {k + 1} does not reach the footprint")
        for _ in range(2):
            start = next(i for i, v in enumerate(loop) if rimmed[v] and not rimmed[loop[i - 1]])
            loop = loop[start:] + loop[:start]
            lr = [v for v in loop if rimmed[v]]
            ang = np.unwrap(np.arctan2(rel[lr] @ b2, rel[lr] @ b1))
            if ang[-1] > ang[0]:
                break
            loop = loop[::-1]
        n_rim = next(i for i, v in enumerate(loop) if not rimmed[v])
        rim_run = loop[:n_rim]
        rest = loop[n_rim:]
        on_b = (np.abs(fb) < seam_tol) & (
            rel @ (math.cos(fb_phi) * b1 + math.sin(fb_phi) * b2) >= -seam_tol
        )
        on_a = (np.abs(fa) < seam_tol) & (
            rel @ (math.cos(seams[k]) * b1 + math.sin(seams[k]) * b2) >= -seam_tol
        )
        # The rest runs up seam b to the top (pole or cap circle), across the top and back
        # down seam a.
        at_top = [i for i, v in enumerate(rest) if topped[v]]
        if not at_top:
            raise FeatureBuildError(f"{name}: the shape's axis does not leave the mesh at its top")
        i0, i1 = at_top[0], at_top[-1]
        if (
            at_top != list(range(i0, i1 + 1))
            or not all(on_b[v] for v in rest[: i0 + 1])
            or not all(on_a[v] for v in rest[i1:])
        ):
            raise FeatureBuildError(
                f"{name}: panel {k + 1} is bounded by more than the footprint, two seams and "
                "the top; the shape's axis must pass through its top"
            )
        right = [rim_run[-1], *rest[: i0 + 1]]
        top = rest[i0 : i1 + 1]
        left = [rim_run[0], *rest[i1:][::-1]]
        flat = _flatten(name, f"panel {k + 1}", px, pt, loop, (rim_run, right, top, left))
        # Rim at the bottom.
        chord = flat[rim_run[-1]] - flat[rim_run[0]]
        c, s = chord / np.linalg.norm(chord)
        rot = np.array([[c, s], [-s, c]])
        flat = flat @ rot.T
        flat -= np.array([flat[rim_run].mean(axis=0)[0], flat[rim_run][:, 1].min()])
        skin.panels.append(
            _Panel(
                px,
                pt,
                flat,
                rim_run,
                right,
                left,
                float(seams[k]),
                float(seams[k]) + 2 * math.pi / m,
                top=top,
                glob=used,
            )
        )
    skin.pole = x[pole_index]
    if rc > 0.0:
        skin.cap = _flatten_cap(name, x, tri[cap_tri], base, b1, b2, axis, skin.panels[0])
        skin.cap_floor = float(((x[on_top] - base) @ axis).min())
    return skin


def _cut_cap(
    name: str,
    x: FloatArray,
    tri: IntArray,
    pole: int,
    rim: set[int],
    base: FloatArray,
    axis: FloatArray,
    radius: float,
    tol: float,
) -> tuple[FloatArray, IntArray, np.ndarray]:
    r"""Cut the cap off the top of a mesh skin: the part round the pole inside the cylinder
    :math:`\rho = r_c` about the axis.

    Only the region joined to the pole is cut (a narrow neck lower down stays whole).
    Crossings are placed on the cylinder by bisection along each edge (:math:`\rho` is
    convex along a straight edge, so it crosses once).

    Returns
    -------
    (ndarray, ndarray, ndarray of bool)
        Vertices, triangles and the cap-triangle mask.
    """

    def rho(p: FloatArray) -> FloatArray:
        rel = np.asarray(p).reshape(-1, 3) - base
        return np.asarray(np.linalg.norm(rel - np.outer(rel @ axis, axis), axis=1))

    r = rho(x)
    inside = r < radius
    nbr: dict[int, set[int]] = {}
    for a, b in np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]):
        nbr.setdefault(int(a), set()).add(int(b))
        nbr.setdefault(int(b), set()).add(int(a))
    comp = {pole}
    stack = [pole]
    while stack:
        v = stack.pop()
        for w in nbr.get(v, ()):
            if w not in comp and inside[w]:
                comp.add(w)
                stack.append(w)
    if comp & rim:
        raise FeatureBuildError(
            f"{name}: the cap of diameter {2 * radius:.3f} m reaches the footprint; make it smaller"
        )
    in_comp = np.zeros(len(x), dtype=bool)
    in_comp[list(comp)] = True
    f = np.where(in_comp, r - radius, np.abs(r - radius))

    def point(a: FloatArray, b: FloatArray, _s: FloatArray) -> FloatArray:
        lo, hi = np.zeros(len(a)), np.ones(len(a))
        a_in = rho(a) < radius
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            same = (rho(a + mid[:, None] * (b - a)) < radius) == a_in
            lo = np.where(same, mid, lo)
            hi = np.where(same, hi, mid)
        out: FloatArray = a + (0.5 * (lo + hi))[:, None] * (b - a)
        return out

    x, tri = _cut(x, tri, f, "both", tol * max(radius, 1.0), point)
    f = np.concatenate([f, np.zeros(len(x) - len(f))])
    cap = np.all(f[tri] <= tol * max(radius, 1.0), axis=1)
    return x, tri, cap


def _flatten(
    name: str,
    what: str,
    px: FloatArray,
    pt: IntArray,
    loop: list[int],
    runs: tuple[list[int], ...],
    pins: tuple[int, int] | None = None,
) -> FloatArray:
    """Flatten a disc-shaped piece: LSCM, ARAP, true-length boundary, ARAP (CCW)."""
    heavy = set()
    for run in runs:
        for a, b in zip(run[:-1], run[1:], strict=True):
            heavy.add((min(a, b), max(a, b)))
    far = pins if pins is not None else (runs[0][0], runs[0][-1])
    flat = _arap(px, pt, _lscm(px, pt, far), heavy)
    # Sewn edges at their true lengths: fix the boundary, relax the interior.
    flat = _true_length_boundary(px, flat, loop)
    flat = _arap(px, pt, flat, heavy, np.asarray(loop))
    # Orientation: flat CCW must match outward normals.
    if signed_area(flat[loop]) < 0:
        flat[:, 0] *= -1.0
    q = flat[pt]
    tri_area = (q[:, 1, 0] - q[:, 0, 0]) * (q[:, 2, 1] - q[:, 0, 1]) - (q[:, 1, 1] - q[:, 0, 1]) * (
        q[:, 2, 0] - q[:, 0, 0]
    )
    if np.any(tri_area <= 0):
        raise FeatureBuildError(f"{name}: {what} folds when flattened; use more panels")
    return flat


def _flatten_cap(
    name: str,
    x: FloatArray,
    cap_tri: IntArray,
    base: FloatArray,
    b1: FloatArray,
    b2: FloatArray,
    axis: FloatArray,
    first: _Panel,
) -> _Panel:
    """Flatten the cap; its loop (``top``) runs round the axis in increasing angle from the
    top of seam 1, centred on the origin with that point on the +x axis."""
    used = np.unique(cap_tri)
    remap = np.full(len(x), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    pt = remap[cap_tri]
    px = x[used]
    loop = _boundary_loops(pt)[0]
    rel = px[loop] - base
    ang = np.unwrap(np.arctan2(rel @ b2, rel @ b1))
    if ang[-1] < ang[0]:
        loop = loop[::-1]
    corner = int(remap[first.glob[first.left[-1]]])
    i = loop.index(corner)
    loop = loop[i:] + loop[:i]
    half = loop[len(loop) // 2]
    flat = _flatten(name, "the cap", px, pt, loop, (loop + loop[:1],), (loop[0], half))
    # Centre the cap; the top of seam 1 on +x.
    flat -= flat[loop].mean(axis=0)
    c, s = flat[corner] / np.linalg.norm(flat[corner])
    flat = flat @ np.array([[c, s], [-s, c]]).T
    return _Panel(px, pt, flat, [], [], [], 0.0, 2 * math.pi, top=loop, glob=used)


@dataclass
class _MeshFactory:
    """Meshes every flattened panel round the conformed footprint loop (see the builder)."""

    design: PrimitiveDesign
    skin: _MeshSkin

    def __call__(self, rim_chart: FloatArray, size: float) -> DesignedSkin:
        from envelopelab.features.primitives import _from_chart, _to_host_frame

        design, skin = self.design, self.skin
        m = len(skin.panels)
        width = 2 * math.pi / m
        start = skin.panels[0].phi_a
        world = _from_chart(design, rim_chart)
        phi_rel = np.mod(skin.phi_of(world) - start, 2 * math.pi)
        notes: list[str] = []
        seam_node = []
        for j in range(m):
            gap = np.abs(np.mod(phi_rel - j * width + math.pi, 2 * math.pi) - math.pi)
            seam_node.append(int(np.argmin(gap)))
        if len(set(seam_node)) != m:
            raise FeatureBuildError(f"{design.primitive.name}: panels too narrow for the mesh size")
        for j, k in enumerate(seam_node):
            phi_rel[k] = j * width
        seam_set = set(seam_node)
        # Shared seam nodes: 3D points along each seam at about the mesh size.
        seam_frac = []
        for j in range(m):
            length = skin.seam_length(j)
            count = max(2, int(math.ceil(length / size)))
            seam_frac.append(np.linspace(0.0, 1.0, count + 1))
        top_frac = []
        for panel in skin.panels:
            length = float(panel.arc(panel.top, True)[-1])
            top_frac.append(np.linspace(0.0, 1.0, max(1, int(math.ceil(length / size))) + 1))
        keys: dict[tuple[Any, ...], int] = {}
        positions: list[FloatArray] = []
        tris, rests, grains = [], [], []
        seam_edges: dict[str, IntArray] = {}

        def node(key: tuple[Any, ...], p: FloatArray) -> int:
            if key not in keys:
                keys[key] = len(positions)
                positions.append(p)
            return keys[key]

        for k, panel in enumerate(skin.panels):
            j_b = (k + 1) % m
            inner = sorted(
                (
                    i
                    for i in range(len(rim_chart))
                    if i not in seam_set and k * width <= phi_rel[i] < (k + 1) * width
                ),
                key=lambda i: float(phi_rel[i]),
            )
            rim_ids = [seam_node[k], *inner, seam_node[j_b]]
            rim_phi = np.array([start + phi_rel[i] for i in rim_ids])
            rim_phi[0], rim_phi[-1] = panel.phi_a, panel.phi_b
            rim_flat = skin.rim_flat(k, rim_phi)
            rim_flat[0], rim_flat[-1] = panel.flat[panel.rim[0]], panel.flat[panel.rim[-1]]
            entries: list[tuple[tuple[Any, ...], FloatArray, FloatArray]] = []
            for i, fxy in zip(rim_ids, rim_flat, strict=True):
                entries.append((("rim", i), fxy, world[i]))
            fr_b = seam_frac[j_b][1:-1]
            pb = panel.run_flat_at(panel.right, fr_b)
            wb = skin.panels[j_b].run_world_at(skin.panels[j_b].left, fr_b)
            entries += [(("seam", j_b, q), pb[q - 1], wb[q - 1]) for q in range(1, len(fr_b) + 1)]
            if skin.cap is None:
                entries.append((("apex",), panel.flat[panel.right[-1]], skin.pole))
            else:
                # Corners at the tops of both seams and the cap circle between them.
                g = top_frac[k][1:-1]
                pt_ = panel.run_flat_at(panel.top, g)
                wt = panel.run_world_at(panel.top, g)
                entries.append((("corner", j_b), panel.flat[panel.top[0]], panel.x[panel.top[0]]))
                entries += [(("top", k, q), pt_[q - 1], wt[q - 1]) for q in range(1, len(g) + 1)]
                entries.append((("corner", k), panel.flat[panel.top[-1]], panel.x[panel.top[-1]]))
            fr_a = seam_frac[k][1:-1]
            pa = panel.run_flat_at(panel.left, fr_a)
            wa = panel.run_world_at(panel.left, fr_a)
            entries += [
                (("seam", k, q), pa[q - 1], wa[q - 1]) for q in reversed(range(1, len(fr_a) + 1))
            ]
            flat_b = np.array([e[1] for e in entries])
            xy, tri = _mesh_disc(flat_b, size)
            dist, hit = cKDTree(xy).query(flat_b)
            if np.any(dist > 1e-6 * max(1.0, float(np.ptp(flat_b)))) or len(
                set(hit.tolist())
            ) != len(hit):
                raise FeatureBuildError(
                    f"{design.primitive.name}: panel {k + 1} boundary was not kept"
                )
            local = np.full(len(xy), -1, dtype=np.int64)
            for (key, _, p), h in zip(entries, hit, strict=True):
                local[h] = node(key, p)
            free = np.flatnonzero(local < 0)
            if len(free):
                local[free] = len(positions) + np.arange(len(free))
                positions.extend(panel.to_world(xy[free]))
            tris.append(local[tri])
            rests.append(xy[tri])
            grains.append(np.tile([0.0, 1.0], (len(tri), 1)))
            chain = [keys[("rim", seam_node[j_b])]]
            chain += [keys[("seam", j_b, q)] for q in range(1, len(fr_b) + 1)]
            chain.append(keys[("apex",) if skin.cap is None else ("corner", j_b)])
            seam_edges[f"{design.primitive.name}:seam {j_b + 1}"] = np.column_stack(
                [chain[:-1], chain[1:]]
            )
        if skin.cap is not None:
            self._cap(keys, positions, tris, rests, grains, seam_edges, top_frac, size)
        rim_index = np.array([keys[("rim", i)] for i in range(len(rim_chart))], dtype=np.int64)
        return DesignedSkin(
            positions=_to_host_frame(design, np.array(positions)),
            triangles=np.concatenate(tris),
            rest_uv=np.concatenate(rests),
            grain=np.concatenate(grains),
            rim_index=rim_index,
            seams=seam_edges,
            notes=notes,
        )

    def _cap(
        self,
        keys: dict[tuple[Any, ...], int],
        positions: list[FloatArray],
        tris: list[IntArray],
        rests: list[FloatArray],
        grains: list[FloatArray],
        seam_edges: dict[str, IntArray],
        top_frac: list[FloatArray],
        size: float,
    ) -> None:
        """Mesh the cap round the panels' top nodes and add its seam (the cap circle)."""
        skin = self.skin
        cap = skin.cap
        assert cap is not None
        m = len(skin.panels)
        # 3D arc length round the cap loop (closed), and where each seam's top is on it.
        loop = [*cap.top, cap.top[0]]
        arc = cap.arc(loop, True)
        where = {int(cap.glob[v]): float(arc[i]) for i, v in enumerate(cap.top)}
        total = float(arc[-1])
        flat_loop = cap.flat[loop]
        ring_keys: list[tuple[Any, ...]] = []
        ring_flat: list[FloatArray] = []
        for k, panel in enumerate(skin.panels):
            s_a = where[int(panel.glob[panel.top[-1]])]  # top of seam k (left)
            s_b = where[int(panel.glob[panel.top[0]])]  # top of seam k + 1 (right)
            span = (s_b - s_a) % total if m > 1 else total
            g = top_frac[k][1:-1]
            ring_keys.append(("corner", k))
            ring_keys += [("top", k, q) for q in reversed(range(1, len(g) + 1))]
            at = np.mod(s_a + (1.0 - np.concatenate([[1.0], g[::-1]])) * span, total)
            ring_flat += list(
                np.column_stack([np.interp(at, arc, flat_loop[:, c]) for c in (0, 1)])
            )
        flat_b = np.array(ring_flat)
        xy, tri = _mesh_disc(flat_b, size)
        dist, hit = cKDTree(xy).query(flat_b)
        if np.any(dist > 1e-6 * max(1.0, float(np.ptp(flat_b)))) or len(set(hit.tolist())) != len(
            hit
        ):
            raise FeatureBuildError(f"{self.design.primitive.name}: cap boundary was not kept")
        local = np.full(len(xy), -1, dtype=np.int64)
        for key, h in zip(ring_keys, hit, strict=True):
            local[h] = keys[key]
        free = np.flatnonzero(local < 0)
        if len(free):
            local[free] = len(positions) + np.arange(len(free))
            positions.extend(cap.to_world(xy[free]))
        tris.append(local[tri])
        rests.append(xy[tri])
        grains.append(np.tile([1.0, 0.0], (len(tri), 1)))
        ids = np.array([keys[key] for key in ring_keys], dtype=np.int64)
        seam_edges[f"{self.design.primitive.name}:tip seam"] = np.column_stack(
            [ids, np.roll(ids, -1)]
        )


def panel_outline(panel: _Panel) -> tuple[FloatArray, dict[str, FloatArray]]:
    """Finished outline (CCW) and edges of a flattened panel, m."""
    rim = panel.flat[panel.rim]
    right = panel.flat[panel.right]
    left = panel.flat[panel.left]
    top = panel.flat[panel.top]
    ring = np.vstack([rim[:-1], right[:-1], top[:-1], left[::-1][:-1]])
    return ring, {"rim": rim, "right": right, "left": left, "top": top}


def cap_outline(cap: _Panel) -> tuple[FloatArray, dict[str, FloatArray]]:
    """Finished outline (CCW) of the flattened cap and its edge (closed), m."""
    ring = cap.flat[cap.top]
    return ring, {"top": np.vstack([ring, ring[:1]])}


def cut_outline(finished: FloatArray, allowance: float) -> FloatArray:
    """Cut outline with the seam allowance, m."""
    return offset_polygon(finished, allowance) if allowance > 0 else finished.copy()
