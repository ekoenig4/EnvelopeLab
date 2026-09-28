r"""Planar polygon and polyline utilities for flat patterns.

All coordinates are in m in a pattern plane whose :math:`+y` axis points "up" the envelope
(towards the crown). Closed outlines are stored without repeating the first vertex.

These are the geometric primitives behind pattern import (containment of labels and sew
lines in cut outlines) and virtual sewing (outline validation, seam-allowance offsets,
edge splitting at corners and arc-length resampling of seam edges).

References
----------
.. [ORourke] J. O'Rourke, *Computational Geometry in C*, 2nd ed., Cambridge University
   Press (1998): signed area (sec. 1.3), segment intersection (sec. 1.5) and point in
   polygon (sec. 7.4).
.. [Held] M. Held, *On the Computational Geometry of Pocket Machining*, Springer LNCS 500
   (1991): offset curves of polygons and the validity limit of vertex-bisector offsets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

#: Default turning angle above which an outline vertex is treated as a panel corner, deg.
DEFAULT_CORNER_ANGLE_DEG = 30.0
#: Default arc-length window for corner detection, m.
DEFAULT_CORNER_WINDOW = 0.02


def as_points(values: npt.ArrayLike) -> FloatArray:
    """Return ``values`` as a float ``(n, 2)`` array.

    Parameters
    ----------
    values : array_like, shape (n, 2)
        Point coordinates, m.

    Returns
    -------
    ndarray, shape (n, 2)
        Copy of the coordinates as float64, m.
    """
    points = np.array(values, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError(f"expected an (n, 2) array of points, got shape {points.shape}")
    return points


def clean_polyline(points: npt.ArrayLike, tolerance: float, closed: bool) -> FloatArray:
    """Remove consecutive duplicate vertices (and a repeated closing vertex).

    Parameters
    ----------
    points : array_like, shape (n, 2)
        Vertices, m.
    tolerance : float
        Vertices closer than this to the previously kept vertex are dropped, m.
    closed : bool
        If true, a last vertex that coincides with the first is dropped as well.

    Returns
    -------
    ndarray, shape (k, 2)
        Cleaned vertices, m.
    """
    pts = as_points(points)
    if len(pts) == 0:
        return pts
    kept = [pts[0]]
    for point in pts[1:]:
        if math.hypot(*(point - kept[-1])) > tolerance:
            kept.append(point)
    if closed:
        while len(kept) > 1 and math.hypot(*(kept[-1] - kept[0])) <= tolerance:
            kept.pop()
    return np.array(kept, dtype=np.float64)


def signed_area(points: FloatArray) -> float:
    r"""Signed area of a closed polygon (shoelace formula).

    .. math:: A = \tfrac12 \sum_i (x_i y_{i+1} - x_{i+1} y_i)

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Vertices, m, first vertex not repeated.

    Returns
    -------
    float
        Area, m^2; positive for counter-clockwise order.
    """
    if len(points) < 3:
        return 0.0
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def orient_ccw(points: FloatArray) -> FloatArray:
    """Return a closed outline in counter-clockwise order.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Closed outline, m.

    Returns
    -------
    ndarray, shape (n, 2)
        The same vertices, reversed if the input was clockwise, m.
    """
    return points[::-1].copy() if signed_area(points) < 0 else points.copy()


def polyline_length(points: FloatArray, closed: bool = False) -> float:
    """Length of a polyline or closed outline.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Vertices, m.
    closed : bool
        Include the closing segment from the last vertex back to the first.

    Returns
    -------
    float
        Length, m.
    """
    if len(points) < 2:
        return 0.0
    pts = np.vstack([points, points[:1]]) if closed else points
    return float(np.sum(np.hypot(*np.diff(pts, axis=0).T)))


def cumulative_length(points: FloatArray) -> FloatArray:
    """Cumulative arc length at each vertex of an open polyline.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Vertices, m.

    Returns
    -------
    ndarray, shape (n,)
        Arc length from the first vertex, m.
    """
    seg = np.hypot(*np.diff(points, axis=0).T)
    return np.concatenate([[0.0], np.cumsum(seg)])


def point_at_fractions(points: FloatArray, fractions: npt.ArrayLike) -> FloatArray:
    """Points at given arc-length fractions along an open polyline.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Polyline vertices, m.
    fractions : array_like, shape (k,)
        Arc-length fractions in [0, 1] (dimensionless).

    Returns
    -------
    ndarray, shape (k, 2)
        Interpolated points, m. Fractions 0 and 1 return the end vertices exactly.
    """
    t = np.clip(np.asarray(fractions, dtype=np.float64), 0.0, 1.0)
    s = cumulative_length(points)
    total = s[-1]
    if total <= 0.0:
        return np.repeat(points[:1], len(t), axis=0)
    target = t * total
    x = np.interp(target, s, points[:, 0])
    y = np.interp(target, s, points[:, 1])
    out = np.column_stack([x, y])
    out[t <= 0.0] = points[0]
    out[t >= 1.0] = points[-1]
    return out


def points_in_polygon(points: npt.ArrayLike, polygon: FloatArray) -> npt.NDArray[np.bool_]:
    """Even-odd point-in-polygon test (ray casting), vectorised over points.

    Parameters
    ----------
    points : array_like, shape (k, 2)
        Query points, m.
    polygon : ndarray, shape (n, 2)
        Closed outline, m.

    Returns
    -------
    ndarray of bool, shape (k,)
        True for points strictly inside (points on the boundary may go either way).
    """
    q = as_points(np.atleast_2d(points))
    x0, y0 = polygon[:, 0], polygon[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    qx = q[:, 0][:, None]
    qy = q[:, 1][:, None]
    crosses = (y0 > qy) != (y1 > qy)
    with np.errstate(divide="ignore", invalid="ignore"):
        x_at = x0 + (qy - y0) * (x1 - x0) / (y1 - y0)
    hits = crosses & (qx < x_at)
    return np.asarray(np.count_nonzero(hits, axis=1) % 2 == 1)


def interior_point(polygon: FloatArray) -> FloatArray:
    """A point strictly inside a simple closed polygon (also for non-convex shapes).

    The polygon is cut by the horizontal line through the middle of its bounding box (or a
    nearby line that avoids vertices); the midpoint of the widest inside interval is
    returned.

    Parameters
    ----------
    polygon : ndarray, shape (n, 2)
        Closed outline, m.

    Returns
    -------
    ndarray, shape (2,)
        Interior point, m.
    """
    lo = polygon[:, 1].min()
    hi = polygon[:, 1].max()
    best: tuple[float, FloatArray] | None = None
    for frac in (0.5, 0.37, 0.63, 0.25, 0.75, 0.11, 0.89):
        y = lo + frac * (hi - lo)
        y0, y1 = polygon[:, 1], np.roll(polygon[:, 1], -1)
        x0, x1 = polygon[:, 0], np.roll(polygon[:, 0], -1)
        crosses = (y0 > y) != (y1 > y)
        if not np.any(crosses):
            continue
        xs = np.sort(x0[crosses] + (y - y0[crosses]) * (x1 - x0)[crosses] / (y1 - y0)[crosses])
        for a, b in zip(xs[0::2], xs[1::2], strict=False):
            if best is None or b - a > best[0]:
                best = (float(b - a), np.array([(a + b) / 2.0, y]))
        if best is not None:
            return best[1]
    return np.asarray(polygon.mean(axis=0), dtype=np.float64)


def polygon_contains(outer: FloatArray, inner: FloatArray, min_fraction: float = 1.0) -> bool:
    """Whether ``outer`` contains the vertices of ``inner``.

    Parameters
    ----------
    outer, inner : ndarray, shape (n, 2)
        Closed outlines, m.
    min_fraction : float
        Fraction of ``inner`` vertices that must lie inside ``outer`` (dimensionless).
        Use a value below 1 when the two outlines may touch (e.g. a sew line that meets
        its cut line at an exact edge).

    Returns
    -------
    bool
        True when at least ``min_fraction`` of the inner vertices are inside.
    """
    inside = points_in_polygon(inner, outer)
    return bool(np.mean(inside) >= min_fraction - 1e-12)


def distance_to_polyline(points: npt.ArrayLike, polyline: FloatArray, closed: bool) -> FloatArray:
    """Shortest distance from each point to a polyline.

    Parameters
    ----------
    points : array_like, shape (k, 2)
        Query points, m.
    polyline : ndarray, shape (n, 2)
        Polyline vertices, m.
    closed : bool
        Include the closing segment.

    Returns
    -------
    ndarray, shape (k,)
        Distances, m.
    """
    q = as_points(np.atleast_2d(points))
    a = polyline
    b = np.roll(polyline, -1, axis=0)
    if not closed:
        a, b = a[:-1], b[:-1]
    ab = b - a
    ab2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-300)
    result = np.empty(len(q))
    chunk = max(1, 2_000_000 // max(len(a), 1))
    for start in range(0, len(q), chunk):
        qq = q[start : start + chunk, None, :]
        t = np.clip(np.einsum("kij,ij->ki", qq - a[None], ab) / ab2, 0.0, 1.0)
        proj = a[None] + t[..., None] * ab[None]
        d = np.hypot(*(qq - proj).transpose(2, 0, 1))
        result[start : start + chunk] = d.min(axis=1)
    return result


def self_intersections(points: FloatArray, closed: bool = True) -> list[tuple[int, int]]:
    """Pairs of non-adjacent segments of an outline that intersect or touch.

    Segment ``i`` runs from vertex ``i`` to vertex ``i + 1`` (wrapping for closed outlines).

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Vertices, m.
    closed : bool
        Treat the outline as closed.

    Returns
    -------
    list of (int, int)
        Intersecting segment index pairs ``(i, j)`` with ``i < j``; empty for a simple
        outline.
    """
    n = len(points)
    if n < 4 and closed or n < 3:
        return []
    a = points
    b = np.roll(points, -1, axis=0)
    m = n if closed else n - 1
    a, b = a[:m], b[:m]
    lo = np.minimum(a, b)
    hi = np.maximum(a, b)
    scale = float(np.max(hi - lo)) if m else 1.0
    eps = 1e-12 * max(scale, 1.0)
    pairs: list[tuple[int, int]] = []
    for i in range(m - 1):
        j = np.arange(i + 1, m)
        # Adjacent segments share a vertex and are not reported.
        adjacent = j == i + 1
        if closed and i == 0:
            adjacent |= j == m - 1
        box = (
            (lo[j, 0] <= hi[i, 0] + eps)
            & (hi[j, 0] >= lo[i, 0] - eps)
            & (lo[j, 1] <= hi[i, 1] + eps)
            & (hi[j, 1] >= lo[i, 1] - eps)
            & ~adjacent
        )
        cand = j[box]
        if len(cand) == 0:
            continue
        p, r = a[i], b[i] - a[i]
        q, s = a[cand], b[cand] - a[cand]
        rxs = r[0] * s[:, 1] - r[1] * s[:, 0]
        qp = q - p
        qpxr = qp[:, 0] * r[1] - qp[:, 1] * r[0]
        qpxs = qp[:, 0] * s[:, 1] - qp[:, 1] * s[:, 0]
        parallel = np.abs(rxs) <= eps * max(float(np.hypot(*r)), 1e-300)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = qpxs / rxs
            u = qpxr / rxs
        crossing = ~parallel & (t >= -1e-12) & (t <= 1 + 1e-12) & (u >= -1e-12) & (u <= 1 + 1e-12)
        # Collinear overlap: parallel segments on the same line with overlapping extents.
        collinear = parallel & (np.abs(qpxr) <= eps * max(float(np.hypot(*r)), 1e-300))
        if np.any(collinear):
            rr = float(np.dot(r, r)) or 1e-300
            t0 = (qp @ r) / rr
            t1 = ((qp + s) @ r) / rr
            overlap = (np.maximum(t0, t1) >= -1e-12) & (np.minimum(t0, t1) <= 1 + 1e-12)
            crossing |= collinear & overlap
        pairs.extend((i, int(k)) for k in cand[crossing])
    return pairs


@dataclass(frozen=True)
class OutlineCheck:
    """Validation result for a closed outline.

    Attributes
    ----------
    closed : bool
        The source entity was closed (or its ends met within tolerance).
    simple : bool
        No two non-adjacent segments intersect.
    orientation : {"ccw", "cw", "degenerate"}
        Vertex order of the outline as given.
    area : float
        Absolute enclosed area, m^2.
    vertex_count : int
        Number of vertices after cleaning.
    issues : tuple of str
        Human-readable problems; empty when valid.
    """

    closed: bool
    simple: bool
    orientation: str
    area: float
    vertex_count: int
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def valid(self) -> bool:
        """True when the outline is closed, simple and has nonzero area."""
        return not self.issues


def validate_outline(points: FloatArray, closed: bool, min_area: float = 1e-8) -> OutlineCheck:
    """Check that an outline is closed, non-self-intersecting and has nonzero area.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Cleaned vertices, m, first vertex not repeated.
    closed : bool
        Whether the source entity is closed.
    min_area : float
        Smallest acceptable enclosed area, m^2.

    Returns
    -------
    OutlineCheck
        Result with a list of issues.
    """
    issues: list[str] = []
    n = len(points)
    if not closed:
        issues.append("outline is not closed")
    if n < 3:
        issues.append(f"outline has only {n} distinct vertices")
        return OutlineCheck(closed, False, "degenerate", 0.0, n, tuple(issues))
    area = signed_area(points)
    orientation = "ccw" if area > 0 else "cw" if area < 0 else "degenerate"
    if abs(area) < min_area:
        issues.append(f"outline area {abs(area):.3g} m^2 is below {min_area:.3g} m^2")
    crossings = self_intersections(points, closed=True)
    if crossings:
        i, j = crossings[0]
        issues.append(
            f"outline self-intersects ({len(crossings)} segment pair(s), first: segments {i} "
            f"and {j} near ({points[i, 0]:.4f}, {points[i, 1]:.4f}) m)"
        )
    return OutlineCheck(closed, not crossings, orientation, abs(area), n, tuple(issues))


def offset_polygon(points: FloatArray, distance: float, max_miter: float = 4.0) -> FloatArray:
    r"""Offset a closed outline by a constant distance with mitred corners.

    Each vertex moves along its corner bisector so that both adjacent edges move by
    exactly ``distance`` along their normals [Held]_:

    .. math:: \mathbf{p}' = \mathbf{p} + d\,\frac{\mathbf{n}_1 + \mathbf{n}_2}
              {1 + \mathbf{n}_1\cdot\mathbf{n}_2}

    where :math:`\mathbf{n}_{1,2}` are the unit outward normals of the incoming and
    outgoing edges. The form is stable for nearly collinear edges (dense curved outlines).
    Where the mitre would exceed ``max_miter * |d|`` the corner is bevelled by two
    vertices instead.

    Assumptions and valid range: the offset is *supported* when ``|d|`` is smaller than the
    local feature size of the outline (no edge shrinks to zero length and no two offset
    edges cross). Larger offsets may produce self-intersecting results; callers must
    validate the output with :func:`validate_outline`.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Closed outline, m, either orientation.
    distance : float
        Offset distance, m; positive moves the outline outward (grows the area), negative
        insets it.
    max_miter : float
        Mitre length limit as a multiple of ``|distance|`` (dimensionless).

    Returns
    -------
    ndarray, shape (m, 2)
        Offset outline in the same orientation as the input, m.
    """
    pts = as_points(points)
    ccw = signed_area(pts) > 0
    work = pts if ccw else pts[::-1]
    edges = np.roll(work, -1, axis=0) - work
    lengths = np.hypot(edges[:, 0], edges[:, 1])
    if np.any(lengths <= 0):
        raise ValueError("outline has zero-length edges; clean it first")
    # Outward normal of a CCW edge (dx, dy) is (dy, -dx).
    normals = np.column_stack([edges[:, 1], -edges[:, 0]]) / lengths[:, None]
    n_in = np.roll(normals, 1, axis=0)
    n_out = normals
    out: list[FloatArray] = []
    for p, n1, n2 in zip(work, n_in, n_out, strict=True):
        denom = 1.0 + float(np.dot(n1, n2))
        miter = n1 + n2
        miter_len = abs(distance) * float(np.hypot(*miter)) / denom if denom > 1e-12 else np.inf
        if miter_len <= max_miter * abs(distance):
            out.append(p + distance * miter / denom)
        else:
            out.append(p + distance * n1)
            out.append(p + distance * n2)
    result = _trim_local_loops(np.array(out))
    return result if ccw else result[::-1].copy()


def _segment_intersection(
    p: FloatArray, p2: FloatArray, q: FloatArray, q2: FloatArray
) -> FloatArray:
    r = p2 - p
    s = q2 - q
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) < 1e-300:
        return q.copy()
    t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / denom
    return np.asarray(p + t * r, dtype=np.float64)


def _trim_local_loops(points: FloatArray, max_iterations: int = 10_000) -> FloatArray:
    """Cut the loops that a raw vertex offset forms where short edges collapse.

    At each step the intersecting segment pair closest together along the outline is
    resolved by splitting the outline at the crossing point and keeping the part with the
    larger area (the swallowtail loops left by collapsed edges are small).
    """
    pts = points
    for _ in range(max_iterations):
        pairs = self_intersections(pts, closed=True)
        if not pairs:
            return pts
        n = len(pts)
        i, j = min(pairs, key=lambda pair: min(pair[1] - pair[0], n - (pair[1] - pair[0])))
        cross = _segment_intersection(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n])
        inner = np.vstack([cross[None], pts[i + 1 : j + 1]])
        outer = np.vstack([pts[: i + 1], cross[None], pts[j + 1 :]])
        pts = outer if abs(signed_area(outer)) >= abs(signed_area(inner)) else inner
        if len(pts) < 3:
            return pts
    return pts


def corner_indices(
    points: FloatArray,
    corner_angle_deg: float = DEFAULT_CORNER_ANGLE_DEG,
    window: float = 0.0,
) -> list[int]:
    """Indices of outline vertices whose turning angle exceeds a threshold.

    The turning angle at a vertex is measured between the chords to the points one
    ``window`` of arc length behind and ahead of it, so that jagged or densely digitised
    curves do not produce spurious corners. Within one window only the vertex with the
    largest turning angle is kept.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Closed outline, m, cleaned.
    corner_angle_deg : float
        Minimum absolute turning angle for a corner, deg.
    window : float
        Arc-length window, m; 0 uses the adjacent vertices.

    Returns
    -------
    list of int
        Corner vertex indices in outline order.
    """
    if window <= 0:
        back = np.roll(points, 1, axis=0)
        ahead = np.roll(points, -1, axis=0)
    else:
        closed = np.vstack([points, points[:1]])
        s = cumulative_length(closed)
        total = s[-1]
        sv = s[:-1]

        def at(arc: FloatArray) -> FloatArray:
            arc = np.mod(arc, total)
            return np.column_stack(
                [np.interp(arc, s, closed[:, 0]), np.interp(arc, s, closed[:, 1])]
            )

        back = at(sv - window)
        ahead = at(sv + window)
    v1 = points - back
    v2 = ahead - points
    cross = v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0]
    dot = np.einsum("ij,ij->i", v1, v2)
    turn = np.degrees(np.abs(np.arctan2(cross, dot)))
    candidates = [int(i) for i in np.flatnonzero(turn > corner_angle_deg)]
    if window <= 0 or not candidates:
        return candidates
    closed = np.vstack([points, points[:1]])
    s = cumulative_length(closed)
    total = s[-1]
    kept: list[int] = []
    for i in sorted(candidates, key=lambda k: -turn[k]):
        if all(min(abs(s[i] - s[k]), total - abs(s[i] - s[k])) > window for k in kept):
            kept.append(i)
    return sorted(kept)


@dataclass(frozen=True)
class OutlineEdge:
    """A named boundary edge of a finished outline, between two corners.

    Attributes
    ----------
    name : str
        Edge name (``bottom``, ``right``, ``top``, ``left`` for four-corner panels, else
        ``e0``, ``e1``, ... or ``loop`` for an outline without corners).
    points : ndarray, shape (k, 2)
        Polyline from the start corner to the end corner in counter-clockwise outline
        order, m. For a ``loop`` edge the first vertex is repeated at the end.
    closed_loop : bool
        True for a cornerless outline represented as one closed edge.
    """

    name: str
    points: FloatArray
    closed_loop: bool = False

    @property
    def length(self) -> float:
        """Edge length, m."""
        return polyline_length(self.points)


def split_edges(
    outline: FloatArray,
    corner_angle_deg: float = DEFAULT_CORNER_ANGLE_DEG,
    window: float = DEFAULT_CORNER_WINDOW,
) -> list[OutlineEdge]:
    """Split a counter-clockwise outline into edges at its corners.

    Four-corner outlines get side names from the direction of each edge's mean outward
    normal in the pattern frame (:math:`+y` up): ``bottom``, ``right``, ``top``, ``left``.
    If two edges would get the same side name, or the corner count is not four, edges are
    named ``e0``, ``e1``, ... starting from the corner nearest the bottom-left.

    Parameters
    ----------
    outline : ndarray, shape (n, 2)
        Closed counter-clockwise outline, m.
    corner_angle_deg : float
        Corner detection threshold, deg.
    window : float
        Arc-length window for corner detection, m (see :func:`corner_indices`).

    Returns
    -------
    list of OutlineEdge
        Edges in counter-clockwise order.
    """
    corners = corner_indices(outline, corner_angle_deg, window)
    n = len(outline)
    if not corners:
        loop = np.vstack([outline, outline[:1]])
        return [OutlineEdge("loop", loop, closed_loop=True)]
    # Start at the corner nearest the bottom-left of the bounding box.
    lo = outline.min(axis=0)
    hi = outline.max(axis=0)
    span = np.maximum(hi - lo, 1e-12)
    rel = (outline[corners] - lo) / span
    first = int(np.argmin(rel[:, 0] + rel[:, 1]))
    corners = corners[first:] + corners[:first]
    pieces: list[FloatArray] = []
    for k, start in enumerate(corners):
        end = corners[(k + 1) % len(corners)]
        idx = (
            list(range(start, end + 1))
            if end > start
            else list(range(start, n)) + list(range(0, end + 1))
        )
        pieces.append(outline[idx])
    names = [f"e{k}" for k in range(len(pieces))]
    if len(pieces) == 4:
        sides: list[str] = []
        for poly in pieces:
            chord = poly[-1] - poly[0]
            normal = np.array([chord[1], -chord[0]])
            angle = math.degrees(math.atan2(normal[1], normal[0])) % 360.0
            if 45.0 <= angle < 135.0:
                sides.append("top")
            elif 135.0 <= angle < 225.0:
                sides.append("left")
            elif 225.0 <= angle < 315.0:
                sides.append("bottom")
            else:
                sides.append("right")
        if len(set(sides)) == 4:
            names = sides
    return [OutlineEdge(name, poly) for name, poly in zip(names, pieces, strict=True)]


def graded_fractions(
    length: float,
    size: float,
    end_size: float | None = None,
    growth: float = 1.3,
) -> FloatArray:
    """Node fractions along a segment of given length, optionally refined at both ends.

    The local spacing is :math:`h(s) = \\min(h, h_e + (g - 1)\\,d(s))` where :math:`d` is
    the distance to the nearer end, :math:`h` the nominal size, :math:`h_e` the end size and
    :math:`g` the growth ratio; the resulting node count is rounded and the spacing
    rescaled so the last node lands exactly on the end.

    Parameters
    ----------
    length : float
        Segment length, m.
    size : float
        Nominal spacing, m.
    end_size : float, optional
        Spacing at both ends, m; defaults to ``size`` (uniform spacing).
    growth : float
        Spacing growth ratio away from the ends (dimensionless, > 1).

    Returns
    -------
    ndarray, shape (k + 1,)
        Increasing fractions from 0 to 1 (dimensionless), at least one interval.
    """
    if length <= 0:
        return np.array([0.0, 1.0])
    h_end = size if end_size is None else min(end_size, size)
    if h_end >= size:
        count = max(1, math.ceil(length / size - 1e-9))
        return np.linspace(0.0, 1.0, count + 1)
    s = [0.0]
    last_step = h_end
    while s[-1] < length - 1e-12:
        d = min(s[-1], length - s[-1])
        last_step = min(size, h_end + (growth - 1.0) * d)
        s.append(s[-1] + last_step)
    if len(s) > 2 and s[-1] - length > 0.5 * last_step:
        s.pop()
    raw = np.array(s, dtype=np.float64)
    return np.asarray(raw / raw[-1], dtype=np.float64)
