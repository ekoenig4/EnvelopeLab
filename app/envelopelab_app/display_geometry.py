"""Display-only geometry helpers: outlines thinned for drawing.

Pattern outlines carry about a thousand points (every profile station of a row), far more
than a drawing needs: a view of a 2 m panel draws about a millimetre per pixel. Drawing
them point for point is what made the pattern view slow to redraw after an edit. The
outlines are thinned here, for drawing only, with the Douglas-Peucker algorithm
[DouglasPeucker]: every dropped point lies within ``tolerance`` of the drawn polyline.
Cut files, checks and the outlines themselves are not changed.

References
----------
.. [DouglasPeucker] D. H. Douglas and T. K. Peucker, "Algorithms for the reduction of the
   number of points required to represent a digitized line or its caricature",
   Cartographica 10(2), 112-122 (1973).
"""

from __future__ import annotations

import numpy as np

#: Largest distance of a dropped point from the drawn outline, m (half a millimetre:
#: below a pixel at any usual zoom of a panel; display only).
DRAW_TOLERANCE = 5e-4
#: Thinned outlines by (bytes, shape): the same outlines are drawn on every refresh.
_THINNED: dict[tuple[bytes, tuple[int, ...]], np.ndarray] = {}
_THINNED_MAX = 1024


def thin(points: np.ndarray, tolerance: float = DRAW_TOLERANCE) -> np.ndarray:
    """``points`` (m, a polyline or closed outline) with the points that lie within
    ``tolerance`` (m) of the polyline through the others dropped (Douglas-Peucker); the
    first and last points are kept."""
    pts = np.ascontiguousarray(points, dtype=np.float64)
    if len(pts) <= 8:
        return pts
    key = (pts.tobytes(), pts.shape)
    hit = _THINNED.get(key)
    if hit is not None:
        return hit
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[a + 1 : b]
        d = pts[b] - pts[a]
        n = float(np.hypot(*d))
        if n == 0.0:
            dist = np.hypot(*(seg - pts[a]).T)
        else:
            rel = seg - pts[a]
            dist = np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0]) / n
        k = int(np.argmax(dist))
        if float(dist[k]) > tolerance:
            mid = a + 1 + k
            keep[mid] = True
            stack += [(a, mid), (mid, b)]
    out = pts[keep]
    if len(_THINNED) >= _THINNED_MAX:
        _THINNED.pop(next(iter(_THINNED)))
    _THINNED[key] = out
    return out
