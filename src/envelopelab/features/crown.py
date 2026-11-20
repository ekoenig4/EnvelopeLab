r"""Crown outlines: the shape of a special shape's cap seen from above (ADR-0054).

A shape's gores or panels meet round a cap at the crown. By default the cap is a circle
(its diameter, :mod:`envelopelab.features.primitives`). A *crown outline* gives it another
shape, seen from above the shape (along its axis), round the point where the panels meet:

* the shape's own **footprint**, centred on the meeting point and scaled to the cap's size;
* an **ellipse** of a width (across the gores) and a length (up the tape), turned;
* a **polygon** through corner points, with straight or smoothed edges;
* an **imported outline** read from a DXF or SVG file (:mod:`envelopelab.io.outline_file`),
  scaled to the cap's size and turned.

Coordinates are plan coordinates in metres: *across* towards the next gore and *up* the
tape, from the meeting point. Every outline becomes one closed polygon
:math:`\mathbf{v}_0, \dots, \mathbf{v}_{n-1}` turning anticlockwise (across to up). The cap
is the part of the skin inside the prism of that polygon along the shape's axis, so the
polygon must be *star-shaped* from the meeting point: every direction from it crosses the
edge once. Its radius in direction :math:`\theta` is the exact ray-edge intersection,

.. math:: r(\theta) = \frac{\mathbf{v}_i \times (\mathbf{v}_{i+1} - \mathbf{v}_i)}
          {\mathbf{d}(\theta) \times (\mathbf{v}_{i+1} - \mathbf{v}_i)},
          \qquad \mathbf{d} = (\cos\theta, \sin\theta),

for the edge :math:`i` whose angles bracket :math:`\theta` (:math:`\times` the 2D cross
product). A point at plan position :math:`\mathbf{q}` from the meeting point is inside the
cap when :math:`|\mathbf{q}| < r(\operatorname{atan2}(q_y, q_x))`.

The *size* of a footprint or imported outline is its widest width (the largest distance
between two of its points), which is the cap's diameter for a circle.

Valid range: closed outlines of at least three points, star-shaped from the meeting point
(the origin strictly inside, angles strictly increasing once round). Smoothed polygons are
closed Catmull-Rom curves through the corners (centripetal, no overshoot at sharp corners
[Yuksel]_), sampled finely; they must be star-shaped too.

References
----------
.. [Yuksel] C. Yuksel, S. Schaefer and J. Keyser, "Parameterization and applications of
   Catmull-Rom curves", Computer-Aided Design 43(7) (2011) 747-755.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from envelopelab.solvers.membrane import FloatArray

#: Points of an ellipse outline (source: assumed; chord sagitta below 0.03 % of its size).
ELLIPSE_POINTS = 256
#: Samples per edge of a smoothed polygon (source: assumed).
SMOOTH_SAMPLES = 24
#: Least angle step round a star-shaped outline, rad (source: assumed).
MIN_ANGLE_STEP = 1e-9


class CrownOutlineError(ValueError):
    """An outline that cannot shape a crown cap (the message says why)."""


def _cross(a: FloatArray, b: FloatArray) -> FloatArray:
    out: FloatArray = a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]
    return out


def _closed_points(points: ArrayLike) -> FloatArray:
    """Points as an (n, 2) float array without a repeated last point."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if len(p) > 1 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    if len(p) < 3 or not np.all(np.isfinite(p)):
        raise CrownOutlineError("a crown outline needs at least three points")
    return p


def widest_width(points: ArrayLike) -> float:
    """Largest distance between two points of an outline, m (the size of a cap)."""
    p = _closed_points(points)
    if len(p) > 600:  # the widest pair lies on the convex hull
        from scipy.spatial import ConvexHull

        p = p[ConvexHull(p).vertices]
    d = np.linalg.norm(p[:, None, :] - p[None, :, :], axis=2)
    return float(d.max())


@dataclass(frozen=True)
class CrownOutline:
    """A closed star-shaped outline round the meeting point (module docstring).

    Attributes
    ----------
    points : ndarray, shape (n, 2)
        Corners anticlockwise (across, up) from the meeting point, m, last not repeated.
    """

    points: FloatArray

    @classmethod
    def from_points(cls, points: ArrayLike) -> CrownOutline:
        """An outline through ``points`` (m, from the meeting point, either direction).

        Raises
        ------
        CrownOutlineError
            When the outline is not star-shaped from the meeting point.
        """
        p = _closed_points(points)
        area2 = float(np.sum(_cross(p, np.roll(p, -1, axis=0))))
        if area2 < 0.0:
            p = p[::-1].copy()
        ang = np.unwrap(np.arctan2(p[:, 1], p[:, 0]))
        steps = np.diff(np.append(ang, ang[0] + 2.0 * math.pi))
        turn = float(ang[-1] - ang[0] + steps[-1])
        if (
            np.any(np.hypot(p[:, 0], p[:, 1]) <= 0.0)
            or np.any(steps <= MIN_ANGLE_STEP)
            or abs(turn - 2.0 * math.pi) > 1e-6
        ):
            raise CrownOutlineError(
                "the crown outline must be seen whole from where the panels meet "
                "(star-shaped round that point); move the point inside it or simplify it"
            )
        return cls(p)

    @property
    def angles(self) -> FloatArray:
        """Corner angles (rad), increasing from the first corner over one turn."""
        out: FloatArray = np.unwrap(np.arctan2(self.points[:, 1], self.points[:, 0]))
        return out

    def radius(self, theta: ArrayLike) -> FloatArray:
        """Distance from the meeting point to the outline in plan directions ``theta``
        (rad from across towards up), m (module docstring)."""
        theta = np.asarray(theta, dtype=np.float64)
        ang = self.angles
        rel = np.mod(theta - ang[0], 2.0 * math.pi) + ang[0]
        i = np.clip(np.searchsorted(ang, rel, side="right") - 1, 0, len(ang) - 1)
        v0 = self.points[i]
        v1 = self.points[(i + 1) % len(self.points)]
        edge = v1 - v0
        d = np.stack([np.cos(theta), np.sin(theta)], axis=-1)
        out: FloatArray = _cross(v0, edge) / _cross(d, edge)
        return out

    def inside(self, across: ArrayLike, up: ArrayLike) -> FloatArray:
        """Signed distance-like test of plan points (m from the meeting point): positive
        inside the outline, negative outside, ``r(theta) - |q|``, m."""
        a = np.asarray(across, dtype=np.float64)
        u = np.asarray(up, dtype=np.float64)
        out: FloatArray = self.radius(np.arctan2(u, a)) - np.hypot(a, u)
        return out

    @property
    def size(self) -> float:
        """Widest width, m."""
        return widest_width(self.points)

    def turned(self, degrees: float) -> CrownOutline:
        """The outline turned anticlockwise (from across towards up) by ``degrees``."""
        t = math.radians(degrees)
        rot = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
        return CrownOutline(self.points @ rot.T)


def ellipse(width: float, length: float, turn_deg: float = 0.0) -> CrownOutline:
    """An ellipse ``width`` across the gores by ``length`` up the tape (m), turned by
    ``turn_deg`` (deg, from across towards up), centred on the meeting point."""
    if not (width > 0.0 and length > 0.0):
        raise CrownOutlineError("an elliptical crown needs a positive width and length")
    t = np.linspace(0.0, 2.0 * math.pi, ELLIPSE_POINTS, endpoint=False)
    base = np.column_stack([0.5 * width * np.cos(t), 0.5 * length * np.sin(t)])
    return CrownOutline(base).turned(turn_deg)


def _catmull_rom(corners: FloatArray, samples: int = SMOOTH_SAMPLES) -> FloatArray:
    """Closed centripetal Catmull-Rom curve through ``corners`` [Yuksel], m."""
    p = corners
    n = len(p)
    out = []
    for i in range(n):
        p0, p1, p2, p3 = p[(i - 1) % n], p[i], p[(i + 1) % n], p[(i + 2) % n]
        t0 = 0.0
        t1 = t0 + max(float(np.linalg.norm(p1 - p0)) ** 0.5, 1e-12)
        t2 = t1 + max(float(np.linalg.norm(p2 - p1)) ** 0.5, 1e-12)
        t3 = t2 + max(float(np.linalg.norm(p3 - p2)) ** 0.5, 1e-12)
        t = np.linspace(t1, t2, samples, endpoint=False)[:, None]
        a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
        b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
        out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    result: FloatArray = np.vstack(out)
    return result


def polygon(points: ArrayLike, smooth: bool = False) -> CrownOutline:
    """A polygon through corner ``points`` (m, across and up from the meeting point),
    with straight edges or a smooth curve through the corners."""
    p = _closed_points(points)
    return CrownOutline.from_points(_catmull_rom(p) if smooth else p)


def scaled(points: ArrayLike, size: float, turn_deg: float = 0.0) -> CrownOutline:
    """``points`` (any units) centred on their area centroid, scaled to a widest width of
    ``size`` (m) and turned by ``turn_deg`` (deg): a footprint or an imported outline."""
    if not size > 0.0:
        raise CrownOutlineError("a shaped crown needs a positive size")
    p = _closed_points(points)
    cross = _cross(p, np.roll(p, -1, axis=0))
    area = 0.5 * float(cross.sum())
    if abs(area) < 1e-300:
        raise CrownOutlineError("the crown outline encloses no area")
    centroid = ((p + np.roll(p, -1, axis=0)) * cross[:, None]).sum(axis=0) / (6.0 * area)
    q = (p - centroid) * (size / widest_width(p))
    t = math.radians(turn_deg)
    rot = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    return CrownOutline.from_points(q @ rot.T)


#: Kinds of crown outline (module docstring).
CROWN_KINDS = ("footprint", "ellipse", "polygon", "outline")


@dataclass(frozen=True)
class CrownShape:
    """How a crown cap is shaped (module docstring); resolved to a :class:`CrownOutline`
    by :meth:`outline` once the shape's footprint is known.

    Attributes
    ----------
    kind : {"footprint", "ellipse", "polygon", "outline"}
        Kind of outline.
    size : float
        Widest width of a footprint or imported outline, m.
    width, length : float
        An ellipse's width across the gores and length up the tape, m.
    turn_deg : float
        Turn of an ellipse or imported outline, deg (from across towards up).
    points : tuple of (float, float)
        A polygon's corners (m, across and up from the meeting point), or an imported
        outline's points (any units; scaled to ``size``).
    smooth : bool
        A polygon's edges are a smooth curve through its corners.
    """

    kind: str
    size: float = 0.0
    width: float = 0.0
    length: float = 0.0
    turn_deg: float = 0.0
    points: tuple[tuple[float, float], ...] = ()
    smooth: bool = False

    def outline(self, footprint: FloatArray | None = None) -> CrownOutline:
        """The outline round the meeting point, m.

        Parameters
        ----------
        footprint : ndarray, shape (n, 2), optional
            The shape's footprint seen from above (across, up; m), for ``footprint``.

        Raises
        ------
        CrownOutlineError
            For missing or unusable values.
        """
        if self.kind == "ellipse":
            return ellipse(self.width, self.length, self.turn_deg)
        if self.kind == "polygon":
            return polygon(np.asarray(self.points, dtype=np.float64), self.smooth)
        if self.kind == "outline":
            return scaled(np.asarray(self.points, dtype=np.float64), self.size, self.turn_deg)
        if self.kind == "footprint":
            if footprint is None:
                raise CrownOutlineError("the footprint is not known yet")
            return scaled(footprint, self.size, self.turn_deg)
        raise CrownOutlineError(f"unknown crown outline {self.kind!r}")
