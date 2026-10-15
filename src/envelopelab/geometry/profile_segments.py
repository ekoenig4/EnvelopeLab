r"""Segment-based meridian profiles: straight lines, circular arcs and smooth curves.

A segment profile keeps the control points :math:`p_0 \dots p_n` (m, mouth first) as the
*joints* and says how each span :math:`p_k \to p_{k+1}` is drawn (one
:class:`Segment` per span), as in a CAD sketch:

``line``
    The straight segment :math:`p_k p_{k+1}` (a cone or cylinder section of the envelope).
``arc``
    A circular arc from :math:`p_k` to :math:`p_{k+1}` given by its *bulge*
    :math:`b = \tan(\theta/4)`, with :math:`\theta` the included angle, positive
    counter-clockwise in the (r, z) plane (the DXF convention). Going up the right-hand
    side of an envelope, a positive bulge bows outward (a convex shoulder). The radius is
    :math:`R = c/(2\sin(\theta/2))` for the chord length :math:`c`. :math:`b = 0` is a
    straight line and :math:`|b| = 1` a half circle.
``curve``
    Consecutive ``curve`` spans form one *run*: a parametric cubic spline through their
    points with the chord-length parameter, continuous in tangent and curvature (C2)
    inside the run. A profile whose spans are all curves is exactly the ``spline``
    interpolation, and one whose spans are all lines is exactly ``linear``.

Joints
------
``Segment.smooth`` asks for a tangent-continuous (G1) joint at the segment's *start*
point. Spans are resolved from the mouth up, and the more flexible span of a joint adapts
to the more fixed one:

* A **line** is fixed by its points.
* An **arc** with a smooth start takes the end tangent of the span before it, which
  fixes its bulge, :math:`b = \tan\bigl((\gamma - \tau)/2\bigr)`, with :math:`\gamma` the
  chord direction and :math:`\tau` the incoming tangent direction. Otherwise, if the
  next span is a line with a smooth start, the arc is made tangent to that line at its
  end, :math:`b = \tan\bigl((\tau' - \gamma)/2\bigr)`. Otherwise it keeps its own
  bulge.
* A **curve run** with a smooth start is clamped to the incoming tangent (first
  derivative = unit tangent). It is clamped to the next span's direction at its end when
  that span is a line with a smooth start. Otherwise its ends are "not-a-knot", like the
  spline interpolation.

A smooth joint that cannot be met, for example between two lines that are not
collinear, is a *kink*. :func:`segment_kinks` reports every smooth joint whose tangents
differ by more than :data:`KINK_TOLERANCE`. Joints are tangent-continuous only (G1).
Curvature continuity (G2) holds inside curve runs, not across joints with lines or arcs.

Each span is sampled in proportion to its length. The result is a dense polyline
:class:`~envelopelab.geometry.gore.MeridianProfile`, as for the other interpolations.

References
----------
.. [Farin] G. Farin, *Curves and Surfaces for CAGD*, 5th ed., Morgan Kaufmann, 2002
   (continuity, interpolating splines).
.. [DXF] Autodesk, *DXF Reference*, LWPOLYLINE group code 42 (bulge).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy.interpolate import CubicSpline

FloatArray = npt.NDArray[np.float64]
SegmentKind = Literal["line", "arc", "curve"]
SEGMENT_KINDS: tuple[SegmentKind, ...] = ("line", "arc", "curve")
#: Largest |bulge| accepted (an arc of about 337 degrees), dimensionless.
MAX_BULGE = 5.0
#: A smooth joint whose tangents differ by more than this is a kink, rad (0.1 degree).
KINK_TOLERANCE = math.radians(0.1)


@dataclass(frozen=True)
class Segment:
    """How one span between two consecutive control points is drawn.

    Attributes
    ----------
    kind : {"line", "arc", "curve"}
        Straight line, circular arc or part of a smooth spline run.
    bulge : float
        Arc only: :math:`\\tan(\\theta/4)` of the included angle, positive
        counter-clockwise in (r, z), dimensionless. Ignored for other kinds, and when the
        arc is made tangent to a neighbour (module docstring).
    smooth : bool
        The joint at the span's start point is tangent-continuous (G1).
    """

    kind: SegmentKind = "curve"
    bulge: float = 0.0
    smooth: bool = True

    def __post_init__(self) -> None:
        if self.kind not in SEGMENT_KINDS:
            raise ValueError(f"unknown segment kind {self.kind!r}")
        if not (math.isfinite(self.bulge) and abs(self.bulge) <= MAX_BULGE):
            raise ValueError(f"arc bulge must be finite and at most {MAX_BULGE} in size")


@dataclass(frozen=True)
class ResolvedSpan:
    """A span after its joints are resolved.

    Attributes
    ----------
    kind : {"line", "arc", "curve"}
    bulge : float
        Bulge actually used (arcs), dimensionless.
    start_tangent, end_tangent : float
        Tangent directions at the span's ends, rad (atan2 of dz, dr).
    points : ndarray, shape (m, 2)
        Samples (r, z) from the start point to the end point, m.
    """

    kind: SegmentKind
    bulge: float
    start_tangent: float
    end_tangent: float
    points: FloatArray


def _wrap(angle: float) -> float:
    """Angle in (-pi, pi], rad."""
    return math.atan2(math.sin(angle), math.cos(angle))


def arc_points(p0: FloatArray, p1: FloatArray, bulge: float, samples: int) -> FloatArray:
    """Points of the arc from ``p0`` to ``p1`` (m) with bulge ``bulge`` (module
    docstring), ``samples`` >= 2 points including both ends, m."""
    if abs(bulge) < 1e-12:
        t = np.linspace(0.0, 1.0, samples)[:, None]
        return p0 + t * (p1 - p0)
    theta = 4.0 * math.atan(bulge)
    chord = p1 - p0
    c = float(np.hypot(*chord))
    mid = 0.5 * (p0 + p1)
    left = np.array([-chord[1], chord[0]]) / c
    centre = mid + left * (0.5 * c / math.tan(0.5 * theta))
    radius = float(np.hypot(*(p0 - centre)))
    a0 = math.atan2(p0[1] - centre[1], p0[0] - centre[0])
    a = a0 + np.linspace(0.0, theta, samples)
    out = centre + radius * np.column_stack((np.cos(a), np.sin(a)))
    out[0], out[-1] = p0, p1
    return out


def arc_radius(chord: float, bulge: float) -> float:
    """Radius of an arc with chord ``chord`` (m) and bulge ``bulge``, m (inf for 0)."""
    if bulge == 0.0:
        return math.inf
    return chord / (2.0 * abs(math.sin(2.0 * math.atan(bulge))))


def _chord_angle(p0: FloatArray, p1: FloatArray) -> float:
    return math.atan2(float(p1[1] - p0[1]), float(p1[0] - p0[0]))


def _spline_run(
    pts: FloatArray,
    start: float | None,
    end: float | None,
    counts: Sequence[int],
) -> tuple[list[FloatArray], list[float]]:
    """Sample a curve run through ``pts`` (m); ``start``/``end`` clamp the tangent
    directions (rad) or None for not-a-knot. Returns samples per span and the tangent
    direction at every point of the run (rad)."""
    chord = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))))
    n = pts.shape[0]
    if n == 2 and start is None and end is None:
        spans = [arc_points(pts[0], pts[1], 0.0, counts[0])]
        angle = _chord_angle(pts[0], pts[1])
        return spans, [angle, angle]
    if start is None and end is None and n == 3:
        # Not-a-knot through three points is the parabola through them.
        bc: object = "not-a-knot"
    else:
        lo = (1, (math.cos(start), math.sin(start))) if start is not None else None
        hi = (1, (math.cos(end), math.sin(end))) if end is not None else None
        if lo is None and hi is None:
            bc = "not-a-knot"
        else:
            # A free end next to a clamped one: the second derivative is zero there.
            bc = (lo or (2, (0.0, 0.0)), hi or (2, (0.0, 0.0)))
    spline = CubicSpline(chord, pts, bc_type=bc)
    spans = []
    for k in range(n - 1):
        t = np.linspace(chord[k], chord[k + 1], counts[k])
        samples = np.asarray(spline(t), dtype=np.float64)
        samples[0], samples[-1] = pts[k], pts[k + 1]
        spans.append(samples)
    d = np.asarray(spline(chord, 1), dtype=np.float64)
    return spans, [math.atan2(v[1], v[0]) for v in d]


def resolve_segments(
    r: npt.ArrayLike, z: npt.ArrayLike, segments: Sequence[Segment], samples: int = 4001
) -> list[ResolvedSpan]:
    """Resolve the joints (module docstring) and sample every span.

    Parameters
    ----------
    r, z : array_like
        Control points (joints), m, mouth first, at least two.
    segments : sequence of Segment
        One per span (``len(r) - 1``).
    samples : int
        About this many points over the whole profile, shared by span length.

    Returns
    -------
    list of ResolvedSpan
        One per span, mouth first.
    """
    pts = np.column_stack((np.asarray(r, dtype=np.float64), np.asarray(z, dtype=np.float64)))
    n = pts.shape[0]
    if n < 2 or len(segments) != n - 1:
        raise ValueError(f"{n} control points need {max(n - 1, 0)} segments, got {len(segments)}")
    lengths = np.hypot(*np.diff(pts, axis=0).T)
    if np.any(lengths <= 0.0):
        raise ValueError("consecutive control points must be distinct")
    counts = [max(4, int(round(samples * float(c) / float(lengths.sum())))) for c in lengths]
    out: list[ResolvedSpan | None] = [None] * (n - 1)
    k = 0
    prev_end: float | None = None
    while k < n - 1:
        seg = segments[k]
        incoming = prev_end if (seg.smooth and k > 0) else None
        nxt = segments[k + 1] if k + 1 < n - 1 else None
        if seg.kind == "line":
            angle = _chord_angle(pts[k], pts[k + 1])
            out[k] = ResolvedSpan(
                "line", 0.0, angle, angle, arc_points(pts[k], pts[k + 1], 0.0, counts[k])
            )
            prev_end = angle
            k += 1
        elif seg.kind == "arc":
            gamma = _chord_angle(pts[k], pts[k + 1])
            bulge = seg.bulge
            if incoming is not None:
                bulge = math.tan(_wrap(gamma - incoming) / 2.0)
            elif nxt is not None and nxt.kind == "line" and nxt.smooth:
                tau = _chord_angle(pts[k + 1], pts[k + 2])
                bulge = math.tan(_wrap(tau - gamma) / 2.0)
            bulge = float(np.clip(bulge, -MAX_BULGE, MAX_BULGE))
            half = 2.0 * math.atan(bulge)  # theta / 2
            out[k] = ResolvedSpan(
                "arc",
                bulge,
                _wrap(gamma - half),
                _wrap(gamma + half),
                arc_points(pts[k], pts[k + 1], bulge, counts[k]),
            )
            prev_end = _wrap(gamma + half)
            k += 1
        else:
            m = k
            while m + 1 < n - 1 and segments[m + 1].kind == "curve":
                m += 1
            after = segments[m + 1] if m + 1 < n - 1 else None
            end = (
                _chord_angle(pts[m + 1], pts[m + 2])
                if after is not None and after.kind == "line" and after.smooth
                else None
            )
            spans, tangents = _spline_run(pts[k : m + 2], incoming, end, counts[k : m + 1])
            for j, span in enumerate(spans):
                out[k + j] = ResolvedSpan("curve", 0.0, tangents[j], tangents[j + 1], span)
            prev_end = tangents[-1]
            k = m + 1
    return [s for s in out if s is not None]


def segment_points(
    r: npt.ArrayLike, z: npt.ArrayLike, segments: Sequence[Segment], samples: int = 4001
) -> tuple[FloatArray, FloatArray]:
    """Dense (r, z) samples of a segment profile, m, mouth first, radii clipped at 0."""
    spans = resolve_segments(r, z, segments, samples)
    pts = np.vstack([spans[0].points] + [s.points[1:] for s in spans[1:]])
    return np.clip(pts[:, 0], 0.0, None), pts[:, 1]


def segment_kinks(
    r: npt.ArrayLike, z: npt.ArrayLike, segments: Sequence[Segment]
) -> list[tuple[int, float]]:
    """Smooth joints that are not met: (control-point index, tangent change in rad)."""
    spans = resolve_segments(r, z, segments, samples=400)
    out = []
    for k in range(1, len(spans)):
        if not segments[k].smooth:
            continue
        turn = abs(_wrap(spans[k].start_tangent - spans[k - 1].end_tangent))
        if turn > KINK_TOLERANCE:
            out.append((k, turn))
    return out


def split_segment(segment: Segment) -> tuple[Segment, Segment]:
    """Two segments that draw the same as ``segment`` when a point is put at its middle:
    an arc of bulge :math:`\\tan(\\theta/4)` becomes two of :math:`\\tan(\\theta/8)`; the
    new middle joint is smooth (it is on the same line, arc or curve)."""
    if segment.kind == "arc":
        half = math.tan(math.atan(segment.bulge) / 2.0)
        return (
            Segment("arc", half, segment.smooth),
            Segment("arc", half, True),
        )
    return Segment(segment.kind, segment.bulge, segment.smooth), Segment(segment.kind, 0.0, True)


def merge_segments(first: Segment, second: Segment) -> Segment:
    """The segment replacing two neighbours when the point between them is deleted: a
    curve if either is one, a line if both are lines, else an arc whose included angle
    is the sum of theirs."""
    if "curve" in (first.kind, second.kind):
        return Segment("curve", 0.0, first.smooth)
    if first.kind == second.kind == "line":
        return Segment("line", 0.0, first.smooth)
    total = sum(4.0 * math.atan(s.bulge) for s in (first, second) if s.kind == "arc")
    bulge = float(np.clip(math.tan(total / 4.0), -MAX_BULGE, MAX_BULGE))
    return Segment("arc", bulge, first.smooth)
