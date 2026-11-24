"""Editing a revolved shape's profile by hand: moving, scaling and inserting its points,
and placing its horizontal splits on the drawn curve.

A revolved shape (:class:`envelopelab.project.shapes.RevolvedShape`) is the profile
:math:`p_k = (\\rho_k, \\zeta_k)` (m, base first) spun about its axis. These functions
change the points as the visual profile editor does, and keep the profile one the shape
accepts:

* the base point stays on the base circle, :math:`\\zeta_0 = 0`;
* a profile that ends on the axis (:math:`\\rho_{n-1} = 0`, a point or a cap) keeps
  its last point there;
* every other point keeps at least :data:`MIN_RADIUS` from the axis.

The moves and scales are those of the envelope's profile editor
(:mod:`envelopelab.geometry.profile_editing`, soft selection included).

Horizontal splits are fractions :math:`f` of the skin meridian's arc length :math:`S`
from the base circle to the tip (or the edge of a centred cap): split :math:`i` lies at
arc length :math:`f_i S` (:func:`envelopelab.features.primitives.split_heights`).
:func:`split_points` gives where they lie on the curve and :func:`split_fraction_at` the
fraction of the curve point nearest a picked point.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from envelopelab.features.primitives import Placement, Revolved
from envelopelab.geometry import profile_editing
from envelopelab.geometry.profile_editing import Falloff, FloatArray
from envelopelab.project.shapes import RevolvedShape, to_primitive

#: Least distance of a profile point (other than an end on the axis) from the axis, m
#: (source: assumed; a point dragged onto the axis would close the skin there).
MIN_RADIUS = 1e-3
#: Splits stay this fraction of the arc length away from the base, the tip and each
#: other (source: assumed; keeps every tier a sewable band while dragging).
SPLIT_MARGIN = 0.02

Profile = list[tuple[float, float]]


def _arrays(profile: Sequence[tuple[float, float]]) -> tuple[FloatArray, FloatArray]:
    pts = np.asarray(profile, dtype=np.float64).reshape(-1, 2)
    if len(pts) < 2:
        raise ValueError("a profile needs at least two points")
    return pts[:, 0].copy(), pts[:, 1].copy()


def _keep_valid(r: FloatArray, z: FloatArray, on_axis: bool) -> Profile:
    """The rules of the module docstring applied to new radii and heights, m."""
    r = np.maximum(r, MIN_RADIUS)
    z = z.copy()
    z[0] = 0.0
    if on_axis:
        r[-1] = 0.0
    return [(float(a), float(b)) for a, b in zip(r, z, strict=True)]


def move_profile_points(
    profile: Sequence[tuple[float, float]],
    selected: Sequence[int],
    d_rho: float,
    d_zeta: float,
    radius: float = 0.0,
    falloff: Falloff = "smooth",
) -> Profile:
    """Move the selected points by :math:`(\\Delta\\rho, \\Delta\\zeta)`, with soft selection.

    Parameters
    ----------
    profile : sequence of (float, float)
        Profile points :math:`(\\rho, \\zeta)`, m, base first.
    selected : sequence of int
        Indices of the points that move fully.
    d_rho, d_zeta : float
        Move away from the axis and up, m.
    radius : float
        Soft-selection radius along the control polygon, m (0: only the selection).
    falloff : Falloff
        Soft-selection falloff (:func:`envelopelab.geometry.profile_editing.falloff_weight`).

    Returns
    -------
    list of (float, float)
        New profile points, m, kept valid (module docstring).
    """
    r, z = _arrays(profile)
    on_axis = r[-1] == 0.0
    nr, nz = profile_editing.move_points(r, z, selected, d_rho, d_zeta, radius, falloff)
    return _keep_valid(nr, nz, on_axis)


def scale_profile(
    profile: Sequence[tuple[float, float]],
    factor_rho: float,
    factor_zeta: float,
    selected: Sequence[int] = (),
    radius: float = 0.0,
    falloff: Falloff = "smooth",
) -> Profile:
    """Scale the profile, or part of it, by :math:`(s_\\rho, s_\\zeta)`.

    With no selection the whole shape is scaled about the centre of its base
    (:math:`\\rho' = s_\\rho \\rho`, :math:`\\zeta' = s_\\zeta \\zeta`), so it stays on
    its base point and grows (or shrinks) in proportion when both factors are equal.
    With a selection only those points are scaled, about their centroid (e.g. a larger
    ball on top of a stalk), with soft selection.

    Parameters
    ----------
    profile : sequence of (float, float)
        Profile points :math:`(\\rho, \\zeta)`, m, base first.
    factor_rho, factor_zeta : float
        Scale factors across (radius) and up (height), dimensionless, finite and positive.
    selected : sequence of int
        Points to scale (empty: all of them, about the base centre).
    radius : float
        Soft-selection radius along the control polygon, m.
    falloff : Falloff
        Soft-selection falloff.

    Returns
    -------
    list of (float, float)
        New profile points, m, kept valid (module docstring).

    Raises
    ------
    ValueError
        For a factor that is not finite and positive.
    """
    if (
        not (np.isfinite(factor_rho) and np.isfinite(factor_zeta))
        or min(factor_rho, factor_zeta) <= 0.0
    ):
        raise ValueError("scale factors must be finite and positive")
    r, z = _arrays(profile)
    on_axis = r[-1] == 0.0
    if selected:
        nr, nz = profile_editing.scale_points(
            r, z, selected, factor_rho, factor_zeta, None, radius, falloff
        )
    else:
        nr, nz = factor_rho * r, factor_zeta * z
    return _keep_valid(nr, nz, on_axis)


def insert_profile_point(
    profile: Sequence[tuple[float, float]], rho: float, zeta: float
) -> tuple[Profile, int]:
    """Insert a point at :math:`(\\rho, \\zeta)` (m) into the nearest side of the control
    polygon.

    Returns
    -------
    (list of (float, float), int)
        New profile points, m, and the new point's index (never 0: the base stays first).
    """
    r, z = _arrays(profile)
    a = np.column_stack([r[:-1], z[:-1]])
    b = np.column_stack([r[1:], z[1:]])
    p = np.array([rho, zeta], dtype=np.float64)
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.einsum("ij,ij->i", ab, ab), 0.0, 1.0)
    d = np.linalg.norm(a + t[:, None] * ab - p, axis=1)
    k = int(np.argmin(d)) + 1
    out = [(float(x), float(y)) for x, y in zip(r, z, strict=True)]
    out.insert(k, (max(float(rho), MIN_RADIUS), float(zeta)))
    return out, k


def remove_profile_point(profile: Sequence[tuple[float, float]], index: int) -> Profile:
    """The profile without point ``index``.

    Raises
    ------
    ValueError
        For the base point, or a profile of only two points (it needs at least two).
    """
    pts = [(float(a), float(b)) for a, b in profile]
    if not 0 < index < len(pts):
        raise ValueError("the base point stays (it is where the shape meets the envelope)")
    if len(pts) <= 2:
        raise ValueError("a profile needs at least two points")
    del pts[index]
    return pts


def profile_curve(
    profile: Sequence[tuple[float, float]], smooth: bool = True, count: int = 401
) -> FloatArray:
    """The curve a revolved shape's profile draws, base to tip, for showing it.

    It is the shape's own meridian without a cap (:meth:`envelopelab.features.
    primitives.Revolved.meridian`): a cubic spline through the points in their chord
    length when ``smooth`` (and there are more than two), else the straight control
    polygon.

    Parameters
    ----------
    profile : sequence of (float, float)
        Profile points :math:`(\\rho, \\zeta)`, m, base first.
    smooth : bool
        Spline through the points (True) or straight segments.
    count : int
        Number of curve points.

    Returns
    -------
    ndarray of shape (count, 2)
        Curve points :math:`(\\rho, \\zeta)`, m.
    """
    points = tuple((float(r), float(z)) for r, z in profile)
    shape = Revolved("profile", Placement(gore=1, tape_position=1.0), points, smooth=smooth)
    rho, zeta = shape.meridian(count)
    out: FloatArray = np.column_stack([rho, zeta])
    return out


def _skin_meridian(spec: RevolvedShape) -> tuple[FloatArray, FloatArray]:
    """The skin meridian the splits are measured on (to the tip or the centred cap), m,
    and its arc length from the base circle, m."""
    prim = to_primitive(spec)
    if not isinstance(prim, Revolved):
        raise TypeError(f"{spec.name!r} is not a revolved shape")
    rho, zeta = prim.meridian()
    pts = np.column_stack([rho, zeta])
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return pts, arc


def split_points(spec: RevolvedShape) -> FloatArray:
    """Where the shape's horizontal splits lie on its profile curve.

    Returns
    -------
    ndarray of shape (k, 2)
        :math:`(\\rho, \\zeta)` of each split, m, base first.
    """
    pts, arc = _skin_meridian(spec)
    s = np.asarray(spec.splits, dtype=np.float64) * arc[-1]
    out: FloatArray = np.column_stack([np.interp(s, arc, pts[:, 0]), np.interp(s, arc, pts[:, 1])])
    return out


def split_fraction_at(spec: RevolvedShape, rho: float, zeta: float) -> float:
    """The split fraction of the profile-curve point nearest :math:`(\\rho, \\zeta)` (m).

    Returns
    -------
    float
        Arc length from the base circle to that point over the whole arc length,
        dimensionless, kept within [:data:`SPLIT_MARGIN`, 1 - :data:`SPLIT_MARGIN`].
    """
    pts, arc = _skin_meridian(spec)
    i = int(np.argmin(np.hypot(pts[:, 0] - rho, pts[:, 1] - zeta)))
    f = float(arc[i] / arc[-1])
    return min(max(f, SPLIT_MARGIN), 1.0 - SPLIT_MARGIN)


def move_split(splits: Sequence[float], index: int, fraction: float) -> list[float]:
    """Splits with split ``index`` moved to ``fraction`` (dimensionless), kept in order
    between its neighbours with :data:`SPLIT_MARGIN` to spare.

    Raises
    ------
    IndexError
        For a split that does not exist.
    """
    out = [float(f) for f in splits]
    if not 0 <= index < len(out):
        raise IndexError(f"no split {index}")
    lo = (out[index - 1] if index > 0 else 0.0) + SPLIT_MARGIN
    hi = (out[index + 1] if index + 1 < len(out) else 1.0) - SPLIT_MARGIN
    out[index] = min(max(float(fraction), lo), hi)
    return out
