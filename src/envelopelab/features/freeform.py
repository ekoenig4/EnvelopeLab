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
from scipy.sparse.linalg import lsqr, splu
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
) -> tuple[FloatArray, IntArray]:
    """Split a triangle mesh along ``value = 0``.

    Vertices with ``|value| <= tol`` lie on the cut and are never split. ``point(a, b, s)``
    places the crossing on edge ``ab`` (default linear), ``accept(p)`` says whether a
    crossing at ``p`` is cut at all (a half-plane). ``keep="pos"`` drops the negative side,
    ``"both"`` keeps both sides.
    """
    sign = np.where(value > tol, 1, np.where(value < -tol, -1, 0))
    verts = list(x)
    cache: dict[tuple[int, int], int | None] = {}

    def cross(a: int, b: int) -> int | None:
        key = (min(a, b), max(a, b))
        if key not in cache:
            s = value[a] / (value[a] - value[b])
            p = x[a] + s * (x[b] - x[a]) if point is None else point(x[a], x[b], s)
            if accept is not None and not accept(p):
                cache[key] = None
            else:
                cache[key] = len(verts)
                verts.append(p)
        return cache[key]

    out: list[list[int]] = []
    side: list[int] = []
    for t in tri:
        st = sign[t]
        if not ((st > 0).any() and (st < 0).any()):
            out.append(list(t))
            side.append(1 if (st > 0).any() else (-1 if (st < 0).any() else 0))
            continue
        zero = np.flatnonzero(st == 0)
        if len(zero) == 1:
            z = int(zero[0])
            a, b, c = t[z], t[(z + 1) % 3], t[(z + 2) % 3]
            m = cross(b, c)
            if m is None:
                out.append(list(t))
                side.append(2)
                continue
            out += [[a, b, m], [a, m, c]]
            side += [int(sign[b]), int(sign[c])]
            continue
        n_pos = int((st > 0).sum())
        odd = int(np.flatnonzero(st > 0 if n_pos == 1 else st < 0)[0])
        a, b, c = t[odd], t[(odd + 1) % 3], t[(odd + 2) % 3]
        ab, ac = cross(a, b), cross(a, c)
        if ab is None and ac is None:
            out.append(list(t))
            side.append(2)
            continue
        if ab is None or ac is None:
            raise FeatureBuildError("a seam cut ends inside a triangle (axis not through the pole)")
        out += [[a, ab, ac], [ab, b, c], [ab, c, ac]]
        side += [int(sign[a]), int(sign[b]), int(sign[b])]
    tri_out = np.asarray(out, dtype=np.int64)
    if keep == "pos":
        keep_mask = np.asarray(side) > 0
        tri_out = tri_out[keep_mask]
    return np.asarray(verts), tri_out


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
    sol = lsqr(big[:, free], rhs, atol=1e-12, btol=1e-12, iter_lim=20000)[0]
    full = np.zeros(2 * n)
    full[free] = sol
    full[pin_idx] = pin_val
    return np.column_stack([full[:n], full[n:]])


def _arap(
    x: FloatArray,
    tri: IntArray,
    init: FloatArray,
    heavy: set[tuple[int, int]],
    fixed: IntArray | None = None,
) -> FloatArray:
    """As-rigid-as-possible flattening [Liu]_ from ``init`` (heavy edges weighted up;
    ``fixed`` vertices keep their ``init`` positions)."""
    n = len(x)
    loc = _local_frames(x, tri)
    cot = np.zeros((len(tri), 3))
    for k in range(3):
        a, b = loc[:, (k + 1) % 3] - loc[:, k], loc[:, (k + 2) % 3] - loc[:, k]
        cross = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
        cot[:, k] = np.einsum("mi,mi->m", a, b) / np.maximum(np.abs(cross), 1e-300)
    cot = np.clip(cot, 1e-3, None)
    for t in range(len(tri)):
        for k in range(3):
            i, j = tri[t, (k + 1) % 3], tri[t, (k + 2) % 3]
            if (min(i, j), max(i, j)) in heavy:
                cot[t, k] *= EDGE_WEIGHT
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
    u = init.copy()
    for _ in range(ARAP_ITERATIONS):
        rot = np.zeros((len(tri), 2, 2))
        cov = np.zeros((len(tri), 2, 2))
        for k in range(3):
            i, j = tri[:, (k + 1) % 3], tri[:, (k + 2) % 3]
            du = u[i] - u[j]
            dx = loc[:, (k + 1) % 3] - loc[:, (k + 2) % 3]
            cov += cot[:, k][:, None, None] * np.einsum("mi,mj->mij", du, dx)
        uu, _, vt = np.linalg.svd(cov)
        rot = uu @ vt
        bad = np.linalg.det(rot) < 0
        uu[bad, :, 1] *= -1.0
        rot[bad] = uu[bad] @ vt[bad]
        rhs = np.zeros((n, 2))
        for k in range(3):
            i, j = tri[:, (k + 1) % 3], tri[:, (k + 2) % 3]
            dx = loc[:, (k + 1) % 3] - loc[:, (k + 2) % 3]
            r = cot[:, k][:, None] * np.einsum("mij,mj->mi", rot, dx)
            np.add.at(rhs, i, r)
            np.add.at(rhs, j, -r)
        rhs_f = rhs[free] - lap[free][:, pinned] @ u[pinned]
        u[free] = np.column_stack([solver.solve(rhs_f[:, 0]), solver.solve(rhs_f[:, 1])])
    return u


@dataclass
class _Panel:
    """One flattened panel: 3D triangles, flat coordinates and its boundary runs."""

    x: FloatArray
    tri: IntArray
    flat: FloatArray
    rim: list[int]
    right: list[int]
    left: list[int]
    phi_a: float
    phi_b: float

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

    def refine(a: FloatArray, b: FloatArray, s: float) -> FloatArray:
        lo, hi = 0.0, 1.0
        sa = surface.signed_distance(a[None])[0]
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            sm = surface.signed_distance((a + mid * (b - a))[None])[0]
            if (sm > 0) == (sa > 0):
                lo = mid
            else:
                hi = mid
            if (hi - lo) * float(np.linalg.norm(b - a)) < ROOT_TOLERANCE:
                break
        return a + 0.5 * (lo + hi) * (b - a)

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

    # Cut along the seam half-planes (each ends at the pole, which lies on every plane).
    m = shape.panels
    seams = 2.0 * math.pi * np.arange(m) / m - math.pi / m
    for ph in seams:
        d = math.cos(ph) * b1 + math.sin(ph) * b2
        n = -math.sin(ph) * b1 + math.cos(ph) * b2
        f = (x - base) @ n
        f[pole_index] = 0.0
        x, tri = _cut(x, tri, f, "both", tol, accept=lambda p, d=d: float((p - base) @ d) > 0.0)

    rim = _boundary_loops(tri)[0]
    rel = x - base
    phi = np.arctan2(rel @ b2, rel @ b1)
    turns = np.sum(np.diff(np.unwrap(np.append(phi[rim], phi[rim][0])))) / (2 * math.pi)
    if abs(abs(turns) - 1.0) > 1e-6:
        raise FeatureBuildError(f"{name}: the footprint must turn once round the shape's axis")
    if turns < 0:
        rim = rim[::-1]
    skin = _MeshSkin(shape, surface, base, axis, b1, b2, x, tri, rim, phi[rim])
    # Assign triangles to panels by centroid angle.
    cen = x[tri].mean(axis=1) - base
    cphi = np.mod(np.arctan2(cen @ b2, cen @ b1) - seams[0], 2 * math.pi)
    which = np.minimum((cphi // (2 * math.pi / m)).astype(int), m - 1)
    on_rim = np.zeros(len(x), dtype=bool)
    on_rim[rim] = True
    pole_cand = []
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
        seam_tol = 1e-7 * scale
        # Orient the loop with the rim running in increasing angle, then split it.
        lr = [i for i in loop if rimmed[i]]
        if len(lr) < 2:
            raise FeatureBuildError(f"{name}: panel {k + 1} does not reach the footprint")
        ang = np.unwrap(np.arctan2(rel[lr] @ b2, rel[lr] @ b1))
        if ang[-1] < ang[0]:
            loop = loop[::-1]
        start = next(i for i, v in enumerate(loop) if rimmed[v] and not rimmed[loop[i - 1]])
        loop = loop[start:] + loop[:start]
        n_rim = next(i for i, v in enumerate(loop) if not rimmed[v])
        rim_run = loop[:n_rim]
        rest = loop[n_rim:]
        on_b = (np.abs(fb) < seam_tol) & (
            rel @ (math.cos(fb_phi) * b1 + math.sin(fb_phi) * b2) >= -seam_tol
        )
        on_a = (np.abs(fa) < seam_tol) & (
            rel @ (math.cos(seams[k]) * b1 + math.sin(seams[k]) * b2) >= -seam_tol
        )
        # The rest runs up seam b to the pole and back down seam a.
        right = [rim_run[-1]] + [v for v in rest if on_b[v] and not on_a[v]]
        left_part = [v for v in rest if on_a[v] and not on_b[v]]
        poles = [v for v in rest if on_a[v] and on_b[v]]
        if len(right) + len(left_part) + len(poles) != len(rest) + 1:
            raise FeatureBuildError(
                f"{name}: panel {k + 1} is bounded by more than the footprint and two seams; "
                "the shape's axis must pass through its top"
            )
        pole = poles[0] if poles else None
        if pole is None:
            raise FeatureBuildError(f"{name}: the shape's axis does not leave the mesh at its top")
        right = right + [pole]
        left = [rim_run[0]] + left_part[::-1] + [pole]
        pole_cand.append(px[pole])
        # Flatten.
        heavy = set()
        for run in (rim_run, right, left):
            for a, b in zip(run[:-1], run[1:], strict=True):
                heavy.add((min(a, b), max(a, b)))
        far = (rim_run[0], rim_run[-1])
        flat = _arap(px, pt, _lscm(px, pt, far), heavy)
        # Sewn edges at their true lengths: fix the boundary, relax the interior.
        flat = _true_length_boundary(px, flat, loop)
        flat = _arap(px, pt, flat, heavy, np.asarray(loop))
        # Orientation: flat CCW must match outward normals; rim at the bottom.
        if signed_area(flat[loop]) < 0:
            flat[:, 0] *= -1.0
        chord = flat[rim_run[-1]] - flat[rim_run[0]]
        c, s = chord / np.linalg.norm(chord)
        rot = np.array([[c, s], [-s, c]])
        flat = flat @ rot.T
        flat -= np.array([flat[rim_run].mean(axis=0)[0], flat[rim_run][:, 1].min()])
        tri_area = (flat[pt][:, 1, 0] - flat[pt][:, 0, 0]) * (
            flat[pt][:, 2, 1] - flat[pt][:, 0, 1]
        ) - (flat[pt][:, 1, 1] - flat[pt][:, 0, 1]) * (flat[pt][:, 2, 0] - flat[pt][:, 0, 0])
        if np.any(tri_area <= 0):
            raise FeatureBuildError(f"{name}: panel {k + 1} folds when flattened; use more panels")
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
            )
        )
    skin.pole = x[pole_index]
    _ = pole_cand
    return skin


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
            entries.append((("apex",), panel.flat[panel.right[-1]], skin.pole))
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
            chain.append(keys[("apex",)])
            seam_edges[f"{design.primitive.name}:seam {j_b + 1}"] = np.column_stack(
                [chain[:-1], chain[1:]]
            )
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


def panel_outline(panel: _Panel) -> tuple[FloatArray, dict[str, FloatArray]]:
    """Finished outline (CCW) and edges of a flattened panel, m."""
    rim = panel.flat[panel.rim]
    right = panel.flat[panel.right]
    left = panel.flat[panel.left]
    ring = np.vstack([rim[:-1], right[:-1], left[::-1][:-1]])
    return ring, {"rim": rim, "right": right, "left": left, "top": right[-1:]}


def cut_outline(finished: FloatArray, allowance: float) -> FloatArray:
    """Cut outline with the seam allowance, m."""
    return offset_polygon(finished, allowance) if allowance > 0 else finished.copy()
