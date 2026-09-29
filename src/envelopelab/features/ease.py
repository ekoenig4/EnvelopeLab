r"""Designed rim ease, match points and the classification of seam-length differences.

A feature skin whose rim is longer than the footprint line it is sewn to carries
*designed ease*: the surplus that lets a flat skin dome. With footprint rim length
:math:`L_f`, skin rim length :math:`L_s` and :math:`N` match points spaced by arc length
on both loops, segment :math:`j` holds

.. math:: e_j = \frac{L_s - L_f}{N}, \qquad
          \epsilon = \frac{L_s - L_f}{L_f}

when the ease is worked in evenly between match points. The rim correspondence is
piecewise linear in arc length between matching match points, so each footprint point at
fraction :math:`t` of segment :math:`j` meets the skin at the same fraction of skin
segment :math:`j`. Without match points (or when the builder pins in order round the rim)
the surplus accumulates in the last segment (*pooling*), which the ``pooled`` mode
reproduces for comparison.

Classification
--------------
The ordinary seam audit (:mod:`envelopelab.assembly.audit`) already subtracts declared
ease. :func:`classify_seam` names the outcome for every sewn pair:

* ``matched``: no ease declared and :math:`|L_b - L_a| \le` tolerance;
* ``designed ease``: ease declared and :math:`|(L_b - L_a) - e| \le` tolerance;
* ``seam error``: anything else (undeclared ease, or ease that differs from the declared
  value by more than the tolerance).

Designed ease is a physical input to the simulation (the skin keeps its as-cut rest
lengths), never a finding.

References
----------
.. [Poynter] D. Poynter, *Parachute Recovery Systems Design Manual*, Para Publishing
   (1991), ch. 6 (fullness and ease in sewn fabric structures).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from envelopelab.assembly.audit import SeamAudit
from envelopelab.solvers.membrane import FloatArray

SeamClass = Literal["matched", "designed ease", "seam error"]
EaseMode = Literal["match_points", "pooled"]
#: Default seam-length tolerance (AGENTS.md section 6.6), m.
DEFAULT_TOLERANCE = 3e-3


def loop_arclength(points: FloatArray) -> FloatArray:
    """Cumulative arc length of a closed polyline at each vertex, m (first value 0)."""
    seg = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)[:-1]])


def loop_length(points: FloatArray) -> float:
    """Length of a closed polyline, m."""
    return float(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum())


def point_on_loop(points: FloatArray, s: FloatArray) -> FloatArray:
    """Points at arc lengths ``s`` (m, taken modulo the length) along a closed polyline."""
    closed = np.vstack([points, points[:1]])
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
    s = np.mod(np.asarray(s, dtype=np.float64), cum[-1])
    return np.column_stack([np.interp(s, cum, closed[:, k]) for k in range(points.shape[1])])


@dataclass(frozen=True)
class RimEase:
    """Ease of one rim seam distributed over match points.

    Attributes
    ----------
    footprint_length, skin_length : float
        Finished rim lengths, m.
    match_points : int
        Number of match points, dimensionless.
    footprint_segments, skin_segments : ndarray
        Segment lengths between consecutive match points, m.
    mode : {"match_points", "pooled"}
        How the surplus is distributed.
    """

    footprint_length: float
    skin_length: float
    match_points: int
    footprint_segments: FloatArray
    skin_segments: FloatArray
    mode: EaseMode = "match_points"

    @property
    def ease(self) -> float:
        """Total surplus :math:`L_s - L_f`, m."""
        return self.skin_length - self.footprint_length

    @property
    def ease_fraction(self) -> float:
        """:math:`(L_s - L_f)/L_f`, dimensionless."""
        return self.ease / self.footprint_length

    @property
    def segment_ease(self) -> FloatArray:
        """Surplus held by each segment, m."""
        out: FloatArray = self.skin_segments - self.footprint_segments
        return out

    @property
    def max_segment_ease(self) -> float:
        """Largest surplus in one segment, m (the pucker risk)."""
        return float(self.segment_ease.max())

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dictionary (lengths in m)."""
        return {
            "footprint_length_m": self.footprint_length,
            "skin_length_m": self.skin_length,
            "ease_m": self.ease,
            "ease_fraction": self.ease_fraction,
            "match_points": self.match_points,
            "mode": self.mode,
            "segment_ease_m": [float(v) for v in self.segment_ease],
        }


def rim_ease(
    footprint_length: float, skin_length: float, match_points: int, mode: EaseMode = "match_points"
) -> RimEase:
    """Distribute the rim surplus over match points.

    Parameters
    ----------
    footprint_length, skin_length : float
        Finished rim lengths of the footprint line and the skin, m.
    match_points : int
        Number of match points :math:`N \\ge 1`.
    mode : {"match_points", "pooled"}
        ``match_points`` shares the surplus evenly; ``pooled`` puts all of it into the
        last segment (pinning in order round the rim).

    Returns
    -------
    RimEase
        Segment lengths (m).
    """
    if match_points < 1:
        raise ValueError("match_points must be at least 1")
    fp = np.full(match_points, footprint_length / match_points)
    if mode == "match_points":
        sk = np.full(match_points, skin_length / match_points)
    else:
        sk = fp.copy()
        sk[-1] += skin_length - footprint_length
    return RimEase(footprint_length, skin_length, match_points, fp, sk, mode)


def rim_correspondence(footprint_s: FloatArray, ease: RimEase) -> FloatArray:
    """Skin arc length meeting each footprint arc length.

    Parameters
    ----------
    footprint_s : ndarray
        Arc lengths along the footprint rim from match point 1, m, in
        [0, ``ease.footprint_length``).
    ease : RimEase
        Segment lengths.

    Returns
    -------
    ndarray
        Arc lengths along the skin rim from its match point 1, m.
    """
    fp_breaks = np.concatenate([[0.0], np.cumsum(ease.footprint_segments)])
    sk_breaks = np.concatenate([[0.0], np.cumsum(ease.skin_segments)])
    out: FloatArray = np.interp(np.asarray(footprint_s, dtype=np.float64), fp_breaks, sk_breaks)
    return out


def classify_seam(
    length_a: float,
    length_b: float,
    designed_ease: float = 0.0,
    tolerance: float = DEFAULT_TOLERANCE,
) -> SeamClass:
    """Classify a seam-length difference.

    Parameters
    ----------
    length_a, length_b : float
        Finished side lengths, m.
    designed_ease : float
        Declared surplus of side B, m.
    tolerance : float
        Allowed residual, m.

    Returns
    -------
    {"matched", "designed ease", "seam error"}
        See the module docstring.
    """
    residual = (length_b - length_a) - designed_ease
    if abs(residual) > tolerance:
        return "seam error"
    return "designed ease" if designed_ease != 0.0 else "matched"


@dataclass
class SeamClassification:
    """Classification of every audited seam.

    Attributes
    ----------
    rows : list of (str, str, float, float)
        (seam id, class, designed ease m, residual m).
    """

    rows: list[tuple[str, SeamClass, float, float]] = field(default_factory=list)

    def of(self, seam_id: str) -> SeamClass:
        """Class of one seam."""
        for sid, cls, _, _ in self.rows:
            if sid == seam_id:
                return cls
        raise KeyError(seam_id)

    @property
    def errors(self) -> list[str]:
        """Seams classified as ``seam error``."""
        return [sid for sid, cls, _, _ in self.rows if cls == "seam error"]

    def counts(self) -> dict[str, int]:
        """Number of seams per class."""
        out = {"matched": 0, "designed ease": 0, "seam error": 0}
        for _, cls, _, _ in self.rows:
            out[cls] += 1
        return out


def classify_audit(audit: SeamAudit) -> SeamClassification:
    """Classify every row of a seam audit (tolerance per row, from the audit).

    Parameters
    ----------
    audit : SeamAudit
        Output of :func:`envelopelab.assembly.audit.audit_seams`.

    Returns
    -------
    SeamClassification
        One entry per seam.
    """
    out = SeamClassification()
    for row in audit.rows:
        cls = classify_seam(row.length_a, row.length_b, row.designed_ease, row.tolerance)
        out.rows.append((row.seam_id, cls, row.designed_ease, row.mismatch))
    return out
