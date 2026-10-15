r"""Editing a meridian profile's control points in bulk, and simplifying a profile.

The envelope profile is a list of control points :math:`p_k = (r_k, z_k)` (m, mouth
first) joined by a spline or by straight segments
(:meth:`~envelopelab.geometry.gore.MeridianProfile.from_control_points`). Moving points
one at a time is slow when there are many, so these functions change many points at once.

Soft selection
--------------
A transform :math:`T` (move, scale or rotate) applies fully to the *selected* points and
partly to their neighbours. A neighbour moves by :math:`w_k (T(p_k) - p_k)`. The weight
depends on its distance :math:`d_k` along the control polygon to the nearest selected
point, relative to the radius :math:`R`, :math:`u = d_k / R`:

.. math::
    w(u) = \begin{cases}
        3t^2 - 2t^3,\ t = 1 - u & \text{smooth} \\
        1 - u & \text{linear} \\
        (1 - u)^2 & \text{sharp} \\
        \sqrt{1 - u^2} & \text{sphere} \\
        1 & \text{constant}
    \end{cases} \quad (u < 1), \qquad w = 0 \ (u \ge 1),

the falloff profiles of soft selection ("proportional editing") in 3D modelling tools.
Radii are clipped at 0 after every transform.

Straighten and smooth
---------------------
*Straighten* puts the points between two points on the straight line joining them, at
their original fractions of the control-polygon length between the two. *Smooth* is
Laplacian smoothing of the selected interior points,
:math:`p_k \leftarrow p_k + \lambda\,(\tfrac12(p_{k-1} + p_{k+1}) - p_k)`, repeated
``iterations`` times. Repeated smoothing also shrinks a curve, so keep the number of
iterations small; volume and length locks correct the shrinkage afterwards.

Curvature
---------
Curvature of the profile (1/m) is :math:`\kappa = d\varphi/ds`, with :math:`\varphi` the
direction of the tangent. It is computed by finite differences on the densely sampled
profile. A *curvature comb* draws :math:`\kappa` as spikes normal to the curve, so wiggles,
flat spots and kinks show (a kink is one tall spike).

Simplify
--------
*Simplify* finds fewer control points whose profile, with the same interpolation, stays
within a tolerance :math:`\varepsilon` of the original. Distance is the symmetric
Hausdorff distance between the two dense polylines
(:func:`profile_deviation`). The end points (mouth and top opening) are always kept.

* Straight segments: Ramer-Douglas-Peucker on the control points. The kept points are a
  subset, and every removed point lies within :math:`\varepsilon` of the new segments.
* Spline: greedy insertion. Start from the two ends and add the point of the original
  curve that is furthest from the current fit, until the fit is within
  :math:`\varepsilon` or ``max_points`` is reached. The new control points lie on the
  original curve.

References
----------
.. [Farin] G. Farin, *Curves and Surfaces for CAGD*, 5th ed., Morgan Kaufmann, 2002
   (curvature, fairing, interpolating splines).
.. [RDP] D. H. Douglas, T. K. Peucker, "Algorithms for the reduction of the number of
   points required to represent a digitized line or its caricature", *Cartographica*
   10(2), 1973, pp. 112-122.
.. [Taubin] G. Taubin, "A signal processing approach to fair surface design", SIGGRAPH
   1995 (Laplacian smoothing and its shrinkage).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy.spatial import cKDTree

from envelopelab.geometry.gore import MeridianProfile, ProfileInterpolation

FloatArray = npt.NDArray[np.float64]
Falloff = Literal["smooth", "linear", "sharp", "sphere", "constant"]
FALLOFFS: tuple[Falloff, ...] = ("smooth", "linear", "sharp", "sphere", "constant")
#: Soft radii up to this are no soft selection, m (1 um; below any pattern precision).
MIN_SOFT_RADIUS = 1e-6
#: Dense samples of a profile when comparing two profiles.
COMPARE_SAMPLES = 4001


def _arrays(r: npt.ArrayLike, z: npt.ArrayLike) -> tuple[FloatArray, FloatArray]:
    r_arr = np.array(r, dtype=np.float64)
    z_arr = np.array(z, dtype=np.float64)
    if r_arr.shape != z_arr.shape or r_arr.ndim != 1 or r_arr.size < 2:
        raise ValueError("r and z must be 1-D arrays of equal length (at least two points)")
    return r_arr, z_arr


def _selection(selected: Sequence[int], n: int) -> list[int]:
    out = sorted({int(i) for i in selected})
    if not out:
        raise ValueError("select at least one control point")
    if out[0] < 0 or out[-1] >= n:
        raise IndexError(f"control point index out of range 0..{n - 1}")
    return out


def polygon_stations(r: npt.ArrayLike, z: npt.ArrayLike) -> FloatArray:
    """Distance of each control point along the control polygon from the first, m."""
    r_arr, z_arr = _arrays(r, z)
    return np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(r_arr), np.diff(z_arr)))))


def falloff_weight(u: npt.ArrayLike, falloff: Falloff = "smooth") -> FloatArray:
    """Soft-selection weight of a point at relative distance ``u = d / R`` (module
    docstring), dimensionless, 1 at ``u = 0`` and 0 for ``u >= 1``."""
    u_arr = np.clip(np.asarray(u, dtype=np.float64), 0.0, None)
    inside = u_arr < 1.0
    t = np.where(inside, 1.0 - u_arr, 0.0)
    if falloff == "smooth":
        w = 3.0 * t**2 - 2.0 * t**3
    elif falloff == "linear":
        w = t
    elif falloff == "sharp":
        w = t**2
    elif falloff == "sphere":
        w = np.sqrt(np.clip(1.0 - u_arr**2, 0.0, None))
    elif falloff == "constant":
        w = np.ones_like(u_arr)
    else:
        raise ValueError(f"unknown falloff {falloff!r}; use one of {', '.join(FALLOFFS)}")
    return np.where(inside, w, 0.0)


def soft_weights(
    r: npt.ArrayLike,
    z: npt.ArrayLike,
    selected: Sequence[int],
    radius: float = 0.0,
    falloff: Falloff = "smooth",
) -> FloatArray:
    """Weight of each control point in a soft transform: 1 for the selected points, the
    falloff of the distance along the control polygon to the nearest selected point for
    the others (0 beyond ``radius``, m; ``radius`` 0: no soft selection)."""
    stations = polygon_stations(r, z)
    picked = _selection(selected, stations.size)
    if radius < 0.0 or not math.isfinite(radius):
        raise ValueError("the soft-selection radius must be a non-negative length")
    weights = np.zeros_like(stations)
    if radius > MIN_SOFT_RADIUS:
        d = np.min(np.abs(stations[:, None] - stations[None, picked]), axis=1)
        weights = falloff_weight(d / radius, falloff)
    weights[picked] = 1.0
    return weights


def _apply(
    r: FloatArray, z: FloatArray, tr: FloatArray, tz: FloatArray, w: FloatArray
) -> tuple[FloatArray, FloatArray]:
    return np.clip(r + w * (tr - r), 0.0, None), z + w * (tz - z)


def move_points(
    r: npt.ArrayLike,
    z: npt.ArrayLike,
    selected: Sequence[int],
    dr: float,
    dz: float,
    radius: float = 0.0,
    falloff: Falloff = "smooth",
) -> tuple[FloatArray, FloatArray]:
    """Move the selected control points by ``(dr, dz)`` m, their neighbours within
    ``radius`` m (along the control polygon) by the falloff fraction of it.

    Returns
    -------
    (ndarray, ndarray)
        New radii (clipped at 0) and heights, m.
    """
    r_arr, z_arr = _arrays(r, z)
    w = soft_weights(r_arr, z_arr, selected, radius, falloff)
    return _apply(r_arr, z_arr, r_arr + dr, z_arr + dz, w)


def _pivot(
    r: FloatArray, z: FloatArray, picked: list[int], pivot: tuple[float, float] | None
) -> tuple[float, float]:
    if pivot is not None:
        return float(pivot[0]), float(pivot[1])
    return float(np.mean(r[picked])), float(np.mean(z[picked]))


def scale_points(
    r: npt.ArrayLike,
    z: npt.ArrayLike,
    selected: Sequence[int],
    factor_r: float,
    factor_z: float,
    pivot: tuple[float, float] | None = None,
    radius: float = 0.0,
    falloff: Falloff = "smooth",
) -> tuple[FloatArray, FloatArray]:
    """Scale the selected control points about ``pivot`` (m; default their centroid) by
    ``factor_r`` across and ``factor_z`` up (dimensionless), with soft selection.

    Returns
    -------
    (ndarray, ndarray)
        New radii (clipped at 0) and heights, m.
    """
    r_arr, z_arr = _arrays(r, z)
    picked = _selection(selected, r_arr.size)
    if not (math.isfinite(factor_r) and math.isfinite(factor_z)):
        raise ValueError("scale factors must be finite")
    pr, pz = _pivot(r_arr, z_arr, picked, pivot)
    w = soft_weights(r_arr, z_arr, picked, radius, falloff)
    return _apply(r_arr, z_arr, pr + factor_r * (r_arr - pr), pz + factor_z * (z_arr - pz), w)


def rotate_points(
    r: npt.ArrayLike,
    z: npt.ArrayLike,
    selected: Sequence[int],
    angle: float,
    pivot: tuple[float, float] | None = None,
    radius: float = 0.0,
    falloff: Falloff = "smooth",
) -> tuple[FloatArray, FloatArray]:
    """Rotate the selected control points by ``angle`` rad (counter-clockwise in the
    (r, z) plane) about ``pivot`` (m; default their centroid), with soft selection.

    Returns
    -------
    (ndarray, ndarray)
        New radii (clipped at 0) and heights, m.
    """
    r_arr, z_arr = _arrays(r, z)
    picked = _selection(selected, r_arr.size)
    pr, pz = _pivot(r_arr, z_arr, picked, pivot)
    c, s = math.cos(angle), math.sin(angle)
    dr, dz = r_arr - pr, z_arr - pz
    w = soft_weights(r_arr, z_arr, picked, radius, falloff)
    return _apply(r_arr, z_arr, pr + c * dr - s * dz, pz + s * dr + c * dz, w)


def straighten_points(
    r: npt.ArrayLike, z: npt.ArrayLike, first: int, last: int
) -> tuple[FloatArray, FloatArray]:
    """Put the control points strictly between ``first`` and ``last`` on the straight
    line joining those two, at their fractions of the control-polygon length between them.

    Returns
    -------
    (ndarray, ndarray)
        New radii and heights, m (``first`` and ``last`` unchanged).
    """
    r_arr, z_arr = _arrays(r, z)
    first, last = sorted((int(first), int(last)))
    if first < 0 or last >= r_arr.size or last - first < 2:
        raise ValueError("straighten needs two control points with at least one between them")
    stations = polygon_stations(r_arr, z_arr)
    span = stations[last] - stations[first]
    if span <= 0.0:
        raise ValueError("the points to straighten coincide")
    t = (stations[first + 1 : last] - stations[first]) / span
    r_arr[first + 1 : last] = r_arr[first] + t * (r_arr[last] - r_arr[first])
    z_arr[first + 1 : last] = z_arr[first] + t * (z_arr[last] - z_arr[first])
    return r_arr, z_arr


def smooth_points(
    r: npt.ArrayLike,
    z: npt.ArrayLike,
    selected: Sequence[int],
    strength: float = 0.5,
    iterations: int = 1,
) -> tuple[FloatArray, FloatArray]:
    r"""Laplacian smoothing of the selected interior control points (module docstring).

    Parameters
    ----------
    r, z : array_like
        Control points, m.
    selected : sequence of int
        Points to smooth; the first and last control points never move.
    strength : float
        :math:`\lambda` in (0, 1], dimensionless.
    iterations : int
        Passes, >= 1.

    Returns
    -------
    (ndarray, ndarray)
        New radii (clipped at 0) and heights, m.
    """
    r_arr, z_arr = _arrays(r, z)
    picked = [i for i in _selection(selected, r_arr.size) if 0 < i < r_arr.size - 1]
    if not 0.0 < strength <= 1.0 or iterations < 1:
        raise ValueError("smoothing needs 0 < strength <= 1 and at least one iteration")
    idx = np.array(picked, dtype=np.int64)
    for _ in range(iterations if idx.size else 0):
        mid_r = 0.5 * (r_arr[idx - 1] + r_arr[idx + 1])
        mid_z = 0.5 * (z_arr[idx - 1] + z_arr[idx + 1])
        r_arr[idx] += strength * (mid_r - r_arr[idx])
        z_arr[idx] += strength * (mid_z - z_arr[idx])
    return np.clip(r_arr, 0.0, None), z_arr


def curvature(profile: MeridianProfile) -> FloatArray:
    r"""Signed curvature :math:`\kappa = d\varphi/ds` at each point of a densely sampled
    profile, 1/m (positive where the profile turns counter-clockwise in the (r, z)
    plane, as an envelope's convex side does going up)."""
    phi = np.unwrap(np.arctan2(np.diff(profile.z), np.diff(profile.r)))
    mids = 0.5 * (profile.s[1:] + profile.s[:-1])
    if phi.size < 2:
        return np.zeros_like(profile.s)
    k_mid = np.diff(phi) / np.diff(mids)
    # Curvature at the interior points; the ends repeat their neighbour.
    return np.concatenate(([k_mid[0]], k_mid, [k_mid[-1]]))


def _point_to_polyline(points: FloatArray, line: FloatArray, tree: cKDTree) -> FloatArray:
    """Distance from each point to a dense polyline, m: exact distance to the segments on
    either side of the nearest vertex."""
    _, j = tree.query(points)
    best = np.full(points.shape[0], np.inf)
    n = line.shape[0]
    for a_idx in (j - 1, j):
        valid = (a_idx >= 0) & (a_idx + 1 < n)
        a = line[np.clip(a_idx, 0, n - 2)]
        b = line[np.clip(a_idx + 1, 1, n - 1)]
        ab = b - a
        length2 = np.einsum("ij,ij->i", ab, ab)
        t = np.clip(
            np.einsum("ij,ij->i", points - a, ab) / np.where(length2 > 0.0, length2, 1.0),
            0.0,
            1.0,
        )
        d = np.hypot(*(points - (a + t[:, None] * ab)).T)
        best = np.where(valid, np.minimum(best, d), best)
    return best


def profile_deviation(a: MeridianProfile, b: MeridianProfile) -> float:
    """Symmetric Hausdorff distance between two densely sampled profiles, m."""
    pa = np.column_stack((a.r, a.z))
    pb = np.column_stack((b.r, b.z))
    d_ab = _point_to_polyline(pa, pb, cKDTree(pb))
    d_ba = _point_to_polyline(pb, pa, cKDTree(pa))
    return float(max(d_ab.max(), d_ba.max()))


@dataclass(frozen=True)
class Simplified:
    """Result of :func:`simplify_profile`.

    Attributes
    ----------
    r, z : ndarray
        New control points, m (the ends are the original ends).
    deviation : float
        Symmetric Hausdorff distance from the original profile, m.
    within_tolerance : bool
        Whether ``deviation`` is within the requested tolerance.
    """

    r: FloatArray
    z: FloatArray
    deviation: float
    within_tolerance: bool

    @property
    def count(self) -> int:
        """Number of control points."""
        return int(self.r.size)


def _rdp(points: FloatArray, tolerance: float) -> list[int]:
    keep = {0, points.shape[0] - 1}
    stack = [(0, points.shape[0] - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        a, b = points[i], points[j]
        ab = b - a
        inner = points[i + 1 : j]
        length = float(np.hypot(*ab))
        if length == 0.0:
            d = np.hypot(*(inner - a).T)
        else:
            t = np.clip((inner - a) @ ab / length**2, 0.0, 1.0)
            d = np.hypot(*(inner - (a + t[:, None] * ab)).T)
        k = int(np.argmax(d))
        if d[k] > tolerance:
            m = i + 1 + k
            keep.add(m)
            stack += [(i, m), (m, j)]
    return sorted(keep)


def simplify_profile(
    r: npt.ArrayLike,
    z: npt.ArrayLike,
    tolerance: float,
    interpolation: ProfileInterpolation = "spline",
    max_points: int | None = None,
) -> Simplified:
    """Fewer control points whose profile stays within ``tolerance`` m of the original
    (module docstring).

    Parameters
    ----------
    r, z : array_like
        Control points, m, mouth first.
    tolerance : float
        Largest allowed distance between the profiles, m (> 0).
    interpolation : {"spline", "linear"}
        How the design joins its control points; the result uses the same.
    max_points : int, optional
        Most control points to use (default: one fewer than now, at least 2).

    Returns
    -------
    Simplified
        The new points and the deviation actually reached. When the tolerance cannot be
        met within ``max_points``, ``within_tolerance`` is False and the best fit found
        is returned; the caller decides whether to use it.
    """
    r_arr, z_arr = _arrays(r, z)
    if not (tolerance > 0.0 and math.isfinite(tolerance)):
        raise ValueError("the tolerance must be a positive length")
    n = r_arr.size
    limit = max(2, n - 1) if max_points is None else max(2, int(max_points))
    original = MeridianProfile.from_control_points(
        r_arr, z_arr, COMPARE_SAMPLES, interpolation=interpolation
    )
    if interpolation == "linear":
        points = np.column_stack((r_arr, z_arr))
        keep = _rdp(points, tolerance)
        if len(keep) > limit:
            # The tolerance needs more points than allowed: the smallest RDP tolerance
            # that fits in ``limit`` points (bisection; the count falls as it grows).
            lo, hi = tolerance, max(tolerance, float(np.ptp(points, axis=0).max()))
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                if len(_rdp(points, mid)) > limit:
                    lo = mid
                else:
                    hi = mid
            keep = _rdp(points, hi)
        rr, zz = r_arr[keep], z_arr[keep]
        fit = MeridianProfile.from_control_points(rr, zz, COMPARE_SAMPLES, "linear")
        dev = profile_deviation(original, fit)
        return Simplified(rr, zz, dev, dev <= tolerance)
    dense = np.column_stack((original.r, original.z))
    chosen = [0, dense.shape[0] - 1]
    best: Simplified | None = None
    while True:
        rr, zz = dense[chosen, 0], dense[chosen, 1]
        fit = MeridianProfile.from_control_points(rr, zz, COMPARE_SAMPLES, "spline")
        pf = np.column_stack((fit.r, fit.z))
        gap = _point_to_polyline(dense, pf, cKDTree(pf))
        dev = max(float(gap.max()), float(_point_to_polyline(pf, dense, cKDTree(dense)).max()))
        result = Simplified(rr.copy(), zz.copy(), dev, dev <= tolerance)
        if best is None or result.deviation < best.deviation:
            best = result
        if result.within_tolerance:
            return result
        if len(chosen) >= limit:
            return best
        gap[chosen] = -1.0
        worst = int(np.argmax(gap))
        if gap[worst] <= 0.0:
            return best
        chosen = sorted({*chosen, worst})
