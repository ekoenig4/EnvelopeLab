r"""Gore envelope geometry: meridian profile, flat gore widths, panel rows and the inverse fit.

Coordinates and units
---------------------
All lengths are in m, areas in m^2 and volumes in m^3.

* The meridian profile is the curve traced by a load tape: radius :math:`r` from the
  envelope axis and height :math:`z`, parameterised by arc length :math:`s` measured along
  the tape from the mouth (:math:`s = 0`) to the top edge (crown or parachute hole).
* A flat gore is drawn with its centreline on the :math:`y` axis (:math:`y = s`) and its
  half-width :math:`w(s)` on :math:`x`. Panels use local coordinates with :math:`y = 0` on
  their finished bottom seam line.

Assumptions (see docs/theory/gore-geometry.md for the full statement)
---------------------------------------------------------------------
* Axisymmetric envelope with ``n_gores`` identical gores and a tape on every gore seam.
* Gore length coordinate equals tape arc length; fabric stretch is neglected.
* Horizontal seams are straight lines across the flat gore (constant :math:`s`), except in
  the flat-chord construction with a crest loft, where they bow outward
  (:func:`flat_chord_rows`).
* Between adjacent tapes the fabric is a circular lobe (the gore's *loft*); its radius is
  set by the width model (:class:`GoreWidthModel`, :class:`GoreLoft`). The small-bulge
  form puts the lobe on the circle through the tapes. The flat-chord construction
  (:func:`flat_chord_rows`, :class:`CrestLoft`) instead cuts every row as a flat
  tape-to-tape trapezoid and lofts the gore lengthwise.
* :attr:`MeridianProfile.volume` and :attr:`MeridianProfile.area` are those of the
  surface of revolution through the tapes; :func:`lofted_volume` and :func:`lofted_area`
  add the lobes. Open ends (mouth, crown hole) are closed by flat discs for the volume.

References
----------
.. [Struik] D. J. Struik, *Lectures on Classical Differential Geometry*, 2nd ed., Dover
   (1988), surfaces of revolution (volume, area, meridian arc length).
.. [GS] P. J. Green and B. W. Silverman, *Nonparametric Regression and Generalized Linear
   Models*, Chapman & Hall (1994) — smoothing splines and GCV.
.. [Hampel] F. R. Hampel, "The influence curve and its role in robust estimation",
   J. Am. Stat. Assoc. 69 (1974) 383-393 — MAD-based outlier scores.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy.interpolate import CubicSpline, make_smoothing_spline

FloatArray = npt.NDArray[np.float64]
WidthForm = Literal["small_bulge", "chord"]
ProfileInterpolation = Literal["spline", "linear"]
CornerTreatment = Literal["miter", "bevel"]
DEFAULT_LOFT_FRACTIONS: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
LENGTH_TOLERANCE = 1e-3  # m; AGENTS.md default geometry tolerance


def _as_array(values: npt.ArrayLike) -> FloatArray:
    return np.asarray(values, dtype=np.float64)


def _polyline_length(x: FloatArray, y: FloatArray) -> float:
    return float(np.sum(np.hypot(np.diff(x), np.diff(y))))


def polygon_area(points: FloatArray) -> float:
    """Area of a simple closed polygon (shoelace formula).

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Vertices in m, first vertex not repeated.

    Returns
    -------
    float
        Enclosed area, m^2 (positive for either orientation).
    """
    x, y = points[:, 0], points[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


@dataclass(frozen=True)
class MeridianProfile:
    r"""Meridian curve :math:`(r(s), z(s))` of an axisymmetric envelope.

    The curve is a polyline; construct it densely (:meth:`from_control_points` samples a
    cubic spline) so that the polyline error is negligible.

    Attributes
    ----------
    s : ndarray
        Arc length from the mouth, m, strictly increasing, ``s[0] == 0``.
    r : ndarray
        Radius from the axis, m, non-negative.
    z : ndarray
        Height, m.
    """

    s: FloatArray
    r: FloatArray
    z: FloatArray

    def __post_init__(self) -> None:
        if not (self.s.shape == self.r.shape == self.z.shape) or self.s.ndim != 1:
            raise ValueError("s, r and z must be 1-D arrays of equal length")
        if self.s.size < 2:
            raise ValueError("a profile needs at least two points")
        if np.any(np.diff(self.s) <= 0.0):
            raise ValueError("profile points must be distinct (s strictly increasing)")
        if np.any(self.r < 0.0):
            raise ValueError("radius must be non-negative")

    @classmethod
    def from_points(cls, r: npt.ArrayLike, z: npt.ArrayLike) -> MeridianProfile:
        """Build a polyline profile from ordered points (mouth first).

        Parameters
        ----------
        r, z : array_like
            Radius and height of each point, m.

        Returns
        -------
        MeridianProfile
            Profile with ``s`` equal to the cumulative chord length, m.
        """
        r_arr, z_arr = _as_array(r), _as_array(z)
        s = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(r_arr), np.diff(z_arr)))))
        return cls(s=s, r=r_arr, z=z_arr)

    @classmethod
    def from_control_points(
        cls,
        r: npt.ArrayLike,
        z: npt.ArrayLike,
        samples: int = 4001,
        interpolation: ProfileInterpolation = "spline",
    ) -> MeridianProfile:
        """Interpolate control points and sample the curve densely.

        Parameters
        ----------
        r, z : array_like
            Control-point radius and height, m, ordered from mouth to top (at least 2).
        samples : int, optional
            Number of evenly spaced polyline points in the result (``"linear"`` adds the
            control points themselves). With the default 4001 the chord length error of a
            smooth spline profile is below 1e-7 relative.
        interpolation : {"spline", "linear"}, optional
            ``"spline"``: parametric cubic spline (chord-length parameter). ``"linear"``:
            straight tape segments between the control points, as in a pattern whose
            panels have straight sides between row corners (:func:`flat_chord_rows`).

        Returns
        -------
        MeridianProfile
            Densely sampled profile, m.
        """
        r_arr, z_arr = _as_array(r), _as_array(z)
        chord = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(r_arr), np.diff(z_arr)))))
        if interpolation not in ("spline", "linear"):
            raise ValueError(f"unknown profile interpolation: {interpolation}")
        if interpolation == "linear":
            even = np.linspace(0.0, chord[-1], samples)
            # Drop even samples that would sit within 1 um of a control point.
            gap = np.min(np.abs(even[:, None] - chord[None, :]), axis=1)
            t = np.union1d(even[gap > 1e-6], chord)
            return cls.from_points(np.interp(t, chord, r_arr), np.interp(t, chord, z_arr))
        if r_arr.size == 2:
            t = np.linspace(0.0, chord[-1], samples)
            return cls.from_points(np.interp(t, chord, r_arr), np.interp(t, chord, z_arr))
        spline_r = CubicSpline(chord, r_arr)
        spline_z = CubicSpline(chord, z_arr)
        t = np.linspace(0.0, chord[-1], samples)
        radius = np.clip(_as_array(spline_r(t)), 0.0, None)
        return cls.from_points(radius, _as_array(spline_z(t)))

    @property
    def meridian_length(self) -> float:
        """Tape length from mouth to top, m."""
        return float(self.s[-1])

    @property
    def height(self) -> float:
        """Vertical extent of the profile, m."""
        return float(np.max(self.z) - np.min(self.z))

    @property
    def max_width(self) -> float:
        """Maximum diameter 2 max(r), m."""
        return 2.0 * float(np.max(self.r))

    @property
    def volume(self) -> float:
        r"""Enclosed volume, m^3, by exact conical-frustum integration of the polyline.

        .. math:: V = \sum_i \frac{\pi}{3}(r_i^2 + r_i r_{i+1} + r_{i+1}^2)(z_{i+1} - z_i)

        Open ends are closed by flat discs. Valid for profiles whose closing discs do not
        cross the surface (e.g. z monotonic, or a curve that turns back only once).
        """
        r0, r1 = self.r[:-1], self.r[1:]
        dz = np.diff(self.z)
        return abs(float(np.sum(math.pi / 3.0 * (r0 * r0 + r0 * r1 + r1 * r1) * dz)))

    @property
    def area(self) -> float:
        r"""Lateral surface area (fabric surface through the tapes), m^2.

        .. math:: A = \sum_i \pi (r_i + r_{i+1})\, \Delta s_i
        """
        return float(np.sum(math.pi * (self.r[:-1] + self.r[1:]) * np.diff(self.s)))

    def radius_at(self, s: npt.ArrayLike) -> FloatArray:
        """Radius at arc-length stations, m (linear on the polyline).

        Parameters
        ----------
        s : array_like
            Arc length from the mouth, m, within ``[0, meridian_length]``.
        """
        return _as_array(np.interp(_as_array(s), self.s, self.r))

    def height_at(self, s: npt.ArrayLike) -> FloatArray:
        """Height at arc-length stations, m (linear on the polyline)."""
        return _as_array(np.interp(_as_array(s), self.s, self.z))


def half_width_small_bulge(radius: npt.ArrayLike, n_gores: int) -> FloatArray:
    r"""Flat gore half-width with the fabric on the circle through the tapes.

    .. math:: w(s) = \frac{\pi\, r(s)}{N}

    Parameters
    ----------
    radius : array_like
        Tape radius r, m.
    n_gores : int
        Number of gores N (>= 3).

    Returns
    -------
    ndarray
        Half-width, m.

    Notes
    -----
    Exact when each lobe's cross-section is an arc of the circle of radius r (bulge radius
    equal to r); a good approximation for N >= 12 with small lobes.
    """
    _check_gores(n_gores)
    return math.pi * _as_array(radius) / n_gores


def half_width_chord(
    radius: npt.ArrayLike, n_gores: int, bulge_radius: npt.ArrayLike = math.inf
) -> FloatArray:
    r"""Flat gore half-width with a circular lobe of given radius between adjacent tapes.

    Adjacent tapes are :math:`c = 2 r \sin(\pi/N)` apart (chord). The fabric between them is
    an arc of radius :math:`\rho` through both tapes, so its half arc length is

    .. math:: w = \rho \arcsin\!\left(\frac{r \sin(\pi/N)}{\rho}\right)

    with limits :math:`w = r\sin(\pi/N)` (flat chord, :math:`\rho \to \infty`) and
    :math:`w = \pi r / N` (:math:`\rho = r`).

    Parameters
    ----------
    radius : array_like
        Tape radius r, m.
    n_gores : int
        Number of gores N (>= 3).
    bulge_radius : array_like, optional
        Lobe radius ρ, m (scalar or per station). ``inf`` (default) gives a flat chord.
        Must satisfy ρ >= r sin(π/N) (minor arc).

    Returns
    -------
    ndarray
        Half-width, m.
    """
    _check_gores(n_gores)
    half_chord = _as_array(radius) * math.sin(math.pi / n_gores)
    rho = np.broadcast_to(_as_array(bulge_radius), half_chord.shape)
    if np.any(rho < half_chord * (1.0 - 1e-12)):
        raise ValueError("bulge radius must be >= r*sin(pi/N) (half the tape spacing)")
    with np.errstate(invalid="ignore", divide="ignore"):
        arc = rho * np.arcsin(np.clip(half_chord / rho, 0.0, 1.0))
    # Where the tapes meet (r = 0) a lobe radius proportional to r is 0 too: no width.
    arc = np.where(half_chord == 0.0, 0.0, arc)
    return _as_array(np.where(np.isinf(rho), half_chord, arc))


def lobe_area_factor(n_gores: int, ratio: npt.ArrayLike) -> FloatArray:
    r"""Cross-section area of a lofted envelope relative to the circle through the tapes.

    The section is the regular N-gon through the tapes (circumradius r) plus N circular
    segments of radius :math:`\rho = k r` on its sides:

    .. math::

        \frac{A}{\pi r^2} = \frac{N}{\pi}\left[\sin\frac{\pi}{N}\cos\frac{\pi}{N}
            + k^2(\theta - \sin\theta\cos\theta)\right],
        \qquad \theta = \arcsin\frac{\sin(\pi/N)}{k}

    with :math:`\theta` the half-angle of each lobe arc. The factor is 1 for :math:`k = 1`
    (the small-bulge circle) and :math:`N\sin(2\pi/N)/(2\pi)` for flat gores
    (:math:`k \to \infty`).

    Parameters
    ----------
    n_gores : int
        Number of gores N (>= 3).
    ratio : array_like
        Lobe-radius ratio :math:`k = \rho/r`, dimensionless, >= sin(π/N); ``inf`` for flat.

    Returns
    -------
    ndarray
        Area factor, dimensionless.

    References
    ----------
    Circular-segment area: any geometry handbook, e.g. CRC Standard Mathematical Tables,
    31st ed. (2003), sec. 4.5.
    """
    _check_gores(n_gores)
    k = _as_array(ratio)
    sin_n, cos_n = math.sin(math.pi / n_gores), math.cos(math.pi / n_gores)
    if np.any(k < sin_n * (1.0 - 1e-12)):
        raise ValueError("lobe-radius ratio must be >= sin(pi/N)")
    finite = np.isfinite(k)
    k_safe = np.where(finite, k, 1.0)
    theta = np.arcsin(np.clip(sin_n / k_safe, 0.0, 1.0))
    segment = np.where(finite, k_safe**2 * (theta - np.sin(theta) * np.cos(theta)), 0.0)
    return _as_array(n_gores / math.pi * (sin_n * cos_n + segment))


def _check_gores(n_gores: int) -> None:
    if n_gores < 3:
        raise ValueError("n_gores must be >= 3")


@dataclass(frozen=True)
class GoreLoft:
    r"""Loft of a gore: the lobe-radius ratio :math:`k = \rho / r` along the tape.

    The fabric between two adjacent tapes bulges as a circular lobe of radius
    :math:`\rho = k(f)\, r(s)`, with :math:`f = s / L_t` the fraction of the tape length
    :math:`L_t` (mouth to top opening). :math:`k` is interpolated linearly between the
    stations and held constant beyond the first and last one. :math:`k = 1` is the
    small-bulge form (lobe on the circle through the tapes); a larger :math:`k` is a
    flatter lobe and a narrower gore, a smaller one a fuller lobe and a wider gore, down to
    a half-circle lobe at :math:`k = \sin(\pi/N)`.

    Attributes
    ----------
    stations : tuple of float
        Fractions of the tape length, dimensionless, strictly increasing in [0, 1].
    ratios : tuple of float
        Lobe-radius ratio k at each station, dimensionless, positive and finite.
    """

    stations: tuple[float, ...]
    ratios: tuple[float, ...]

    def __post_init__(self) -> None:
        f = np.asarray(self.stations, dtype=np.float64)
        k = np.asarray(self.ratios, dtype=np.float64)
        if f.ndim != 1 or f.size < 1 or f.shape != k.shape:
            raise ValueError("a loft needs one or more stations, each with a ratio")
        if np.any(f < 0.0) or np.any(f > 1.0):
            raise ValueError("loft stations are fractions of the tape length (0..1)")
        if np.any(np.diff(f) <= 0.0):
            raise ValueError("loft stations must be strictly increasing")
        if not np.all(np.isfinite(k)) or np.any(k <= 0.0):
            raise ValueError("loft ratios must be positive and finite")
        object.__setattr__(self, "stations", tuple(float(v) for v in f))
        object.__setattr__(self, "ratios", tuple(float(v) for v in k))

    @classmethod
    def constant(cls, ratio: float) -> GoreLoft:
        """The same lobe-radius ratio (dimensionless) along the whole gore."""
        return cls(stations=(0.0,), ratios=(float(ratio),))

    @property
    def min_ratio(self) -> float:
        """Smallest lobe-radius ratio, dimensionless."""
        return min(self.ratios)

    def ratio_at(self, fraction: npt.ArrayLike) -> FloatArray:
        """Lobe-radius ratio k (dimensionless) at fractions of the tape length."""
        return _as_array(
            np.interp(_as_array(fraction), np.array(self.stations), np.array(self.ratios))
        )


def loft_extra_width(n_gores: int, ratio: npt.ArrayLike) -> FloatArray:
    r"""Extra flat gore width of a lobe over the flat tape-to-tape chord, fraction.

    .. math:: e = \frac{k \arcsin(\sin(\pi/N)/k)}{\sin(\pi/N)} - 1

    Parameters
    ----------
    n_gores : int
        Number of gores N (>= 3).
    ratio : array_like
        Lobe-radius ratio k, dimensionless (>= sin(π/N)); ``inf`` gives 0.

    Returns
    -------
    ndarray
        Extra width as a fraction of the chord width, dimensionless (0.01 = 1 %).
    """
    _check_gores(n_gores)
    sin_n = math.sin(math.pi / n_gores)
    k = _as_array(ratio)
    return _as_array(half_width_chord(1.0, n_gores, k) / sin_n - 1.0)


@dataclass(frozen=True)
class GoreWidthModel:
    """Maps tape radius to flat gore width and back.

    Attributes
    ----------
    n_gores : int
        Number of gores N.
    form : {"small_bulge", "chord"}
        Width formula; see :func:`half_width_small_bulge` and :func:`half_width_chord`.
    bulge_radius : float or None
        Chord form only: constant lobe radius ρ, m. ``None`` with ``bulge_ratio`` and
        ``loft`` also ``None`` means a flat chord (ρ = ∞).
    bulge_ratio : float or None
        Chord form only: lobe radius as a multiple of the local tape radius, ρ = k r,
        dimensionless.
    loft : GoreLoft or None
        Chord form only: lobe-radius ratio k varying along the tape. The width then
        depends on the station as well as the radius, so the ``fraction`` argument of
        :meth:`half_width` is required. At most one of ``bulge_radius``, ``bulge_ratio``
        and ``loft`` is given.
    """

    n_gores: int
    form: WidthForm = "small_bulge"
    bulge_radius: float | None = None
    bulge_ratio: float | None = None
    loft: GoreLoft | None = None

    def __post_init__(self) -> None:
        _check_gores(self.n_gores)
        given = [v for v in (self.bulge_radius, self.bulge_ratio, self.loft) if v is not None]
        if len(given) > 1:
            raise ValueError("give at most one of bulge_radius, bulge_ratio and loft")
        if self.form == "small_bulge" and given:
            raise ValueError("bulge parameters apply to the chord form only")
        min_ratio = math.sin(math.pi / self.n_gores)
        if self.bulge_ratio is not None and self.bulge_ratio < min_ratio:
            raise ValueError("bulge_ratio must be >= sin(pi/N)")
        if self.loft is not None and self.loft.min_ratio < min_ratio:
            raise ValueError(
                f"loft ratio {self.loft.min_ratio:g} is below sin(pi/N) = {min_ratio:.4f} "
                f"for {self.n_gores} gores (a lobe cannot be more than a half circle)"
            )
        if self.bulge_radius is not None and self.bulge_radius <= 0.0:
            raise ValueError("bulge_radius must be positive")

    @classmethod
    def lofted(cls, n_gores: int, loft: GoreLoft | None) -> GoreWidthModel:
        """Width model of a gore with ``loft``; ``None`` is the small-bulge form (k = 1)."""
        if loft is None:
            return cls(n_gores=n_gores, form="small_bulge")
        return cls(n_gores=n_gores, form="chord", loft=loft)

    def lobe_ratio(
        self, radius: npt.ArrayLike, fraction: npt.ArrayLike | None = None
    ) -> FloatArray:
        """Lobe-radius ratio k = ρ/r (dimensionless; ``inf`` for a flat chord).

        Parameters
        ----------
        radius : array_like
            Tape radius, m.
        fraction : array_like, optional
            Fraction of the tape length, dimensionless; required with a ``loft``.
        """
        r = _as_array(radius)
        if self.form == "small_bulge":
            return _as_array(np.ones_like(r))
        if self.loft is not None:
            if fraction is None:
                raise ValueError("a lofted width model needs the station fraction")
            return _as_array(np.broadcast_to(self.loft.ratio_at(fraction), r.shape))
        if self.bulge_ratio is not None:
            return _as_array(np.full_like(r, self.bulge_ratio))
        if self.bulge_radius is None:
            return _as_array(np.full_like(r, math.inf))
        with np.errstate(divide="ignore"):
            return _as_array(self.bulge_radius / r)

    def half_width(
        self, radius: npt.ArrayLike, fraction: npt.ArrayLike | None = None
    ) -> FloatArray:
        """Flat half-width, m, for tape radius ``radius`` (m).

        ``fraction`` (of the tape length, dimensionless) is required with a ``loft``.
        """
        if self.form == "small_bulge":
            return half_width_small_bulge(radius, self.n_gores)
        r = _as_array(radius)
        if self.loft is not None:
            return half_width_chord(r, self.n_gores, self.lobe_ratio(r, fraction) * r)
        if self.bulge_ratio is not None:
            return half_width_chord(r, self.n_gores, self.bulge_ratio * r)
        rho = math.inf if self.bulge_radius is None else self.bulge_radius
        return half_width_chord(r, self.n_gores, rho)

    def full_width(
        self, radius: npt.ArrayLike, fraction: npt.ArrayLike | None = None
    ) -> FloatArray:
        """Flat full width 2w, m, for tape radius ``radius`` (m); see :meth:`half_width`."""
        return 2.0 * self.half_width(radius, fraction)

    def radius_from_full_width(
        self, width: npt.ArrayLike, fraction: npt.ArrayLike | None = None
    ) -> FloatArray:
        r"""Invert :meth:`full_width`: tape radius, m, from flat full gore width, m.

        Small bulge: :math:`r = N w_{full} / (2\pi)`. Chord form with constant ρ:
        :math:`r = \rho \sin(w/\rho) / \sin(\pi/N)`; with ρ = k r (``bulge_ratio`` or
        a ``loft``, which needs ``fraction``):
        :math:`r = w / (k \arcsin(\sin(\pi/N)/k))`, where :math:`w` is the half-width.
        """
        half = 0.5 * _as_array(width)
        n = self.n_gores
        if self.form == "small_bulge":
            return half * n / math.pi
        sin_n = math.sin(math.pi / n)
        if self.loft is not None:
            ratio = self.lobe_ratio(half, fraction)
            return _as_array(half / (ratio * np.arcsin(sin_n / ratio)))
        if self.bulge_ratio is not None:
            k = self.bulge_ratio
            return _as_array(half / (k * math.asin(sin_n / k)))
        if self.bulge_radius is None:
            return _as_array(half / sin_n)
        rho = self.bulge_radius
        if np.any(half > rho * math.pi / 2.0):
            raise ValueError("width exceeds a half-circle lobe of the given bulge radius")
        return _as_array(rho * np.sin(half / rho) / sin_n)


@dataclass(frozen=True)
class SeamAllowance:
    """Seam allowances added outside the finished panel outline.

    Attributes
    ----------
    side : float
        Allowance on the vertical (gore) seams, m.
    bottom : float
        Allowance on the bottom horizontal seam, m.
    top : float
        Allowance on the top horizontal seam, m.
    """

    side: float = 0.0
    bottom: float = 0.0
    top: float = 0.0

    def __post_init__(self) -> None:
        if min(self.side, self.bottom, self.top) < 0.0:
            raise ValueError("seam allowances must be non-negative")


@dataclass(frozen=True)
class LoftStation:
    """One line of a panel loft table.

    Attributes
    ----------
    fraction : float
        Position as a fraction of the finished panel height, dimensionless.
    y : float
        Height above the finished bottom seam line, m.
    width : float
        Finished full width, m.
    """

    fraction: float
    y: float
    width: float


@dataclass(frozen=True)
class PanelRow:
    """One horizontal row of a gore (a single panel), finished and cut.

    Attributes
    ----------
    label : str
        Row label, e.g. ``"C"``.
    s_bottom, s_top : float
        Tape arc length at the finished bottom and top seam lines, m.
    right_edge : ndarray, shape (n, 2)
        Finished right-hand side (sewn line) from bottom to top in panel coordinates, m.
    cut_outline : ndarray, shape (m, 2)
        Cut polygon including seam allowances, m, counter-clockwise.
    loft : tuple of LoftStation
        Finished widths at the requested fractions of the height.
    side_length : float
        Finished length of one side (vertical seam line), m.
    bottom_bow, top_bow : float
        Depth of the bottom and top seam lines at the centreline beyond the straight
        corner-to-corner line, m, positive outward (down at the bottom, up at the top).
        The seam is the parabola :math:`d(x) = b (1 - (x/w_c)^2)` with :math:`w_c` the
        corner half-width (:func:`bowed_seam`). Zero (the default) is a straight seam.
    """

    label: str
    s_bottom: float
    s_top: float
    right_edge: FloatArray = field(repr=False)
    cut_outline: FloatArray = field(repr=False)
    loft: tuple[LoftStation, ...]
    side_length: float
    bottom_bow: float = 0.0
    top_bow: float = 0.0

    @property
    def finished_height(self) -> float:
        """Tape length of the row, m (the centreline height of a lobe-gore row)."""
        return self.s_top - self.s_bottom

    @property
    def corner_height(self) -> float:
        """Height of the top corners above the bottom corners, m."""
        return float(self.right_edge[-1, 1] - self.right_edge[0, 1])

    @property
    def centre_height(self) -> float:
        """Finished height along the centreline, bows included, m."""
        return self.corner_height + self.bottom_bow + self.top_bow

    @property
    def bottom_seam_length(self) -> float:
        """Finished length of the bottom seam line, m (its width when straight)."""
        if self.bottom_bow == 0.0:
            return self.bottom_width
        return _polyline_length(*bowed_seam(float(self.right_edge[0, 0]), self.bottom_bow).T)

    @property
    def top_seam_length(self) -> float:
        """Finished length of the top seam line, m (its width when straight)."""
        if self.top_bow == 0.0:
            return self.top_width
        return _polyline_length(*bowed_seam(float(self.right_edge[-1, 0]), self.top_bow).T)

    @property
    def bottom_width(self) -> float:
        """Finished full width at the bottom seam line, m."""
        return 2.0 * float(self.right_edge[0, 0])

    @property
    def top_width(self) -> float:
        """Finished full width at the top seam line, m."""
        return 2.0 * float(self.right_edge[-1, 0])

    @property
    def finished_outline(self) -> FloatArray:
        """Finished polygon, m, counter-clockwise from the bottom-right corner."""
        mirrored = self.right_edge[::-1] * np.array([-1.0, 1.0])
        parts = [self.right_edge]
        if self.top_bow != 0.0:
            top = bowed_seam(float(self.right_edge[-1, 0]), self.top_bow)
            parts.append(top[1:-1] + [0.0, float(self.right_edge[-1, 1])])
        parts.append(mirrored)
        if self.bottom_bow != 0.0:
            bottom = bowed_seam(float(self.right_edge[0, 0]), -self.bottom_bow)[::-1]
            parts.append(bottom[1:-1] + [0.0, float(self.right_edge[0, 1])])
        return _as_array(np.vstack(parts))

    @property
    def finished_area(self) -> float:
        """Finished panel area, m^2."""
        return polygon_area(self.finished_outline)

    @property
    def cut_area(self) -> float:
        """Cut panel area including allowances, m^2."""
        return polygon_area(self.cut_outline)


def gore_half_widths(
    profile: MeridianProfile, width_model: GoreWidthModel, s: npt.ArrayLike | None = None
) -> tuple[FloatArray, FloatArray]:
    """Flat gore half-width along the tape.

    Parameters
    ----------
    profile : MeridianProfile
        Meridian profile, m.
    width_model : GoreWidthModel
        Width formula and gore count.
    s : array_like, optional
        Stations, m. Defaults to the profile's own nodes.

    Returns
    -------
    (ndarray, ndarray)
        Stations s (m) and half-widths w (m).
    """
    stations = profile.s if s is None else _as_array(s)
    fraction = stations / profile.meridian_length
    return stations, width_model.half_width(profile.radius_at(stations), fraction)


def lofted_volume(profile: MeridianProfile, width_model: GoreWidthModel) -> float:
    r"""Enclosed volume of the lofted envelope (tapes plus fabric lobes), m^3.

    Each horizontal section is the circle through the tapes scaled by the lobe area
    factor :math:`c(k, N)` (:func:`lobe_area_factor`), so

    .. math:: V = \sum_i c_{i+\frac12}\, \frac{\pi}{3}(r_i^2 + r_i r_{i+1} + r_{i+1}^2)
              (z_{i+1} - z_i)

    with :math:`c` evaluated at the middle of each polyline segment. The small-bulge form
    (:math:`c = 1`) returns :attr:`MeridianProfile.volume` exactly.

    Parameters
    ----------
    profile : MeridianProfile
        Meridian (tape) profile, m.
    width_model : GoreWidthModel
        Gore count and lobe shape.

    Returns
    -------
    float
        Volume, m^3; open ends closed by flat discs.

    Notes
    -----
    The lobe is taken in the horizontal section, as the width model takes it across the
    flat gore; both are exact for a vertical tape and good while the lobes are shallow
    compared with the meridian curvature radius.
    """
    if width_model.form == "small_bulge":
        return profile.volume
    s_mid = 0.5 * (profile.s[:-1] + profile.s[1:])
    r_mid = 0.5 * (profile.r[:-1] + profile.r[1:])
    k = width_model.lobe_ratio(r_mid, s_mid / profile.meridian_length)
    factor = lobe_area_factor(width_model.n_gores, k)
    r0, r1 = profile.r[:-1], profile.r[1:]
    dz = np.diff(profile.z)
    return abs(float(np.sum(factor * math.pi / 3.0 * (r0 * r0 + r0 * r1 + r1 * r1) * dz)))


def lofted_area(profile: MeridianProfile, width_model: GoreWidthModel) -> float:
    r"""Fabric area of the lofted envelope (N flat gores, finished), m^2.

    .. math:: A = 2N \int_0^{L_t} w(s)\, ds \approx N \sum_i (w_i + w_{i+1})\, \Delta s_i

    The small-bulge form returns :attr:`MeridianProfile.area` exactly.

    Parameters
    ----------
    profile : MeridianProfile
        Meridian (tape) profile, m.
    width_model : GoreWidthModel
        Gore count and lobe shape.

    Returns
    -------
    float
        Area, m^2.
    """
    if width_model.form == "small_bulge":
        return profile.area
    _, half = gore_half_widths(profile, width_model)
    return float(width_model.n_gores * np.sum((half[:-1] + half[1:]) * np.diff(profile.s)))


def _row_stations(profile: MeridianProfile, s0: float, s1: float, minimum: int) -> FloatArray:
    inner = profile.s[(profile.s > s0) & (profile.s < s1)]
    return _as_array(np.unique(np.concatenate((np.linspace(s0, s1, minimum), inner))))


def _offset_polyline(points: FloatArray, distance: float) -> FloatArray:
    """Offset an open polyline to its right by ``distance`` with mitred interior joints."""
    tangents = np.diff(points, axis=0)
    tangents /= np.linalg.norm(tangents, axis=1)[:, None]
    normals = np.column_stack((tangents[:, 1], -tangents[:, 0]))
    vertex_normals = np.vstack((normals[:1], normals[:-1] + normals[1:], normals[-1:]))
    vertex_normals /= np.linalg.norm(vertex_normals, axis=1)[:, None]
    # Scale interior joints so each segment stays exactly `distance` from its original.
    cos_half = np.ones(len(points))
    cos_half[1:-1] = np.einsum("ij,ij->i", vertex_normals[1:-1], normals[:-1])
    return _as_array(points + distance * vertex_normals / cos_half[:, None])


def _cross_horizontal(a: FloatArray, b: FloatArray, level: float) -> FloatArray:
    t = (level - a[1]) / (b[1] - a[1])
    return _as_array(a + t * (b - a))


def _clip_between(curve: FloatArray, y_low: float, y_high: float) -> FloatArray:
    """Clip a y-increasing polyline to the band ``y_low <= y <= y_high``."""
    y = curve[:, 1]
    lo = int(np.flatnonzero(y >= y_low)[0])
    hi = int(np.flatnonzero(y <= y_high)[-1])
    parts = [curve[lo : hi + 1]]
    if lo > 0:
        parts.insert(0, _cross_horizontal(curve[lo - 1], curve[lo], y_low)[None, :])
    if hi < len(y) - 1:
        parts.append(_cross_horizontal(curve[hi], curve[hi + 1], y_high)[None, :])
    return _as_array(np.vstack(parts))


def _extend_to_level(point: FloatArray, tangent: FloatArray, level: float) -> FloatArray:
    if abs(tangent[1]) < 1e-9 * float(np.linalg.norm(tangent)):
        raise ValueError("panel side is parallel to its horizontal seam; cannot mitre")
    return _as_array(point + (level - point[1]) / tangent[1] * tangent)


def cut_outline(
    right_edge: FloatArray,
    allowance: SeamAllowance,
    corner: CornerTreatment = "miter",
) -> FloatArray:
    """Cut outline of a symmetric panel from its finished right edge.

    Parameters
    ----------
    right_edge : ndarray, shape (n, 2)
        Finished right-hand edge from bottom (y = 0) to top (y = h), m, x > 0, y increasing.
    allowance : SeamAllowance
        Side, bottom and top allowances, m.
    corner : {"miter", "bevel"}
        ``"miter"`` extends the offset side line along its end tangent to meet the offset
        horizontal line (sharp corner). ``"bevel"`` cuts the corner with a straight line
        from the side-offset point normal to the finished corner to the point on the
        offset horizontal line directly above/below the finished corner, so no fabric lies
        farther than the allowances from the finished corner. Where the offset side
        already crosses the offset horizontal line (a panel side leaning outward over the
        seam) both treatments trim at that crossing.

    Returns
    -------
    ndarray, shape (m, 2)
        Counter-clockwise cut polygon, m, starting at the bottom-left corner.
    """
    if corner not in ("miter", "bevel"):
        raise ValueError(f"unknown corner treatment: {corner}")
    height = float(right_edge[-1, 1])
    y_low, y_high = -allowance.bottom, height + allowance.top
    side = _offset_polyline(right_edge, allowance.side) if allowance.side > 0 else right_edge
    right = _clip_between(side, y_low, y_high)
    if side[0, 1] > y_low:
        if corner == "miter":
            start = _extend_to_level(side[0], side[1] - side[0], y_low)
        else:
            start = np.array([right_edge[0, 0], y_low])
        right = np.vstack((start, right))
    if side[-1, 1] < y_high:
        if corner == "miter":
            end = _extend_to_level(side[-1], side[-1] - side[-2], y_high)
        else:
            end = np.array([right_edge[-1, 0], y_high])
        right = np.vstack((right, end))
    left = right[::-1] * np.array([-1.0, 1.0])
    return _as_array(np.vstack((left[-1:], right, left[:-1])))


def split_rows(
    profile: MeridianProfile,
    width_model: GoreWidthModel,
    row_heights: Sequence[float],
    labels: Sequence[str] | None = None,
    allowance: SeamAllowance | None = None,
    corner: CornerTreatment = "miter",
    start: float = 0.0,
    require_full_coverage: bool = True,
    loft_fractions: Sequence[float] = DEFAULT_LOFT_FRACTIONS,
    min_edge_points: int = 65,
) -> list[PanelRow]:
    """Split a gore into horizontal panel rows, mouth first.

    Parameters
    ----------
    profile : MeridianProfile
        Meridian profile, m.
    width_model : GoreWidthModel
        Width formula and gore count.
    row_heights : sequence of float
        Finished row heights along the tape, m, from the mouth upward.
    labels : sequence of str, optional
        Row labels; default ``"A"``, ``"B"``, ... from the mouth.
    allowance : SeamAllowance, optional
        Seam allowances, m; default none (cut = finished).
    corner : {"miter", "bevel"}
        Corner treatment of the cut outline; see :func:`cut_outline`.
    start : float, optional
        Tape arc length of the bottom of the first row, m.
    require_full_coverage : bool, optional
        If true, the rows must end at the top of the profile within 1 mm.
    loft_fractions : sequence of float, optional
        Fractions of each row height for the loft table, dimensionless.
    min_edge_points : int, optional
        Minimum number of points on each finished side edge.

    Returns
    -------
    list of PanelRow
        Rows from the mouth upward.
    """
    heights = [float(h) for h in row_heights]
    if not heights or min(heights) <= 0.0:
        raise ValueError("row heights must be positive")
    if labels is None:
        labels = [_default_label(i) for i in range(len(heights))]
    if len(labels) != len(heights):
        raise ValueError("labels and row_heights differ in length")
    end = start + sum(heights)
    if end > profile.meridian_length + LENGTH_TOLERANCE:
        raise ValueError(
            f"rows end at {end:.4f} m, beyond the meridian length {profile.meridian_length:.4f} m"
        )
    if require_full_coverage and abs(end - profile.meridian_length) > LENGTH_TOLERANCE:
        raise ValueError(
            f"rows cover {start:.4f}-{end:.4f} m but the meridian is "
            f"{profile.meridian_length:.4f} m long"
        )
    allowance = allowance or SeamAllowance()
    boundaries = np.concatenate(([start], start + np.cumsum(heights)))
    boundaries = np.minimum(boundaries, profile.meridian_length)
    rows: list[PanelRow] = []
    for label, s0, s1 in zip(labels, boundaries[:-1], boundaries[1:], strict=True):
        stations = _row_stations(profile, float(s0), float(s1), min_edge_points)
        _, half = gore_half_widths(profile, width_model, stations)
        right_edge = _as_array(np.column_stack((half, stations - s0)))
        height = float(s1 - s0)
        loft = tuple(
            LoftStation(
                fraction=float(f),
                y=float(f) * height,
                width=float(
                    width_model.full_width(
                        profile.radius_at(s0 + float(f) * height),
                        (s0 + float(f) * height) / profile.meridian_length,
                    )
                ),
            )
            for f in loft_fractions
        )
        rows.append(
            PanelRow(
                label=str(label),
                s_bottom=float(s0),
                s_top=float(s1),
                right_edge=right_edge,
                cut_outline=cut_outline(right_edge, allowance, corner),
                loft=loft,
                side_length=_polyline_length(right_edge[:, 0], right_edge[:, 1]),
            )
        )
    return rows


# --------------------------------------------------------------------------------------
# Flat-chord gores with a crest loft
# --------------------------------------------------------------------------------------


def bowed_seam(half_width: float, bow: float, points: int = 65) -> FloatArray:
    r"""A bowed horizontal seam line from the right corner to the left corner, m.

    .. math:: y(x) = b \left(1 - \left(\frac{x}{w_c}\right)^2\right), \qquad
              x \in [w_c, -w_c]

    relative to the straight line through the corners (docs/theory/gore-geometry.md).

    Parameters
    ----------
    half_width : float
        Corner half-width :math:`w_c`, m.
    bow : float
        Ordinate :math:`b` at the centreline, m (positive up).
    points : int, optional
        Number of points (odd, so the centreline is one of them).

    Returns
    -------
    ndarray, shape (points, 2)
        Seam line, m, from (w_c, 0) to (-w_c, 0).
    """
    x = np.linspace(half_width, -half_width, points)
    if half_width == 0.0:
        return _as_array(np.column_stack((x, np.zeros_like(x))))
    return _as_array(np.column_stack((x, bow * (1.0 - (x / half_width) ** 2))))


@dataclass(frozen=True)
class CrestLoft:
    r"""Lengthwise loft of a flat-chord gore: the crest offset along the tape.

    Each gore is cut as flat tape-to-tape trapezoids (corner widths
    :math:`2 r \sin(\pi/N)`), and its centreline is made longer than the flat strip so the
    fabric between two tapes stands out as a crest. The crest stands
    :math:`\delta(s) = \lambda\, \tau(f)\, r(s)` outside the flat chord, with
    :math:`\lambda` the loft fraction and :math:`\tau(f)` a taper (0 to 1) given at
    stations :math:`f = s / L_t` (fraction of the tape length from the mouth),
    interpolated linearly and held beyond the first and last station.

    Attributes
    ----------
    fraction : float
        Loft fraction :math:`\lambda`: crest offset over tape radius where the taper is 1,
        dimensionless (0.02 = "2 % of radius").
    stations : tuple of float
        Fractions of the tape length, dimensionless, strictly increasing in [0, 1].
    taper : tuple of float
        Taper :math:`\tau` at each station, dimensionless, >= 0.
    """

    fraction: float
    stations: tuple[float, ...] = (0.0,)
    taper: tuple[float, ...] = (1.0,)

    def __post_init__(self) -> None:
        f = np.asarray(self.stations, dtype=np.float64)
        tau = np.asarray(self.taper, dtype=np.float64)
        if f.ndim != 1 or f.size < 1 or f.shape != tau.shape:
            raise ValueError("a crest loft needs one or more stations, each with a taper")
        if np.any(f < 0.0) or np.any(f > 1.0):
            raise ValueError("crest-loft stations are fractions of the tape length (0..1)")
        if np.any(np.diff(f) <= 0.0):
            raise ValueError("crest-loft stations must be strictly increasing")
        if not np.all(np.isfinite(tau)) or np.any(tau < 0.0):
            raise ValueError("crest-loft taper values must be finite and >= 0")
        if not math.isfinite(self.fraction) or self.fraction < 0.0:
            raise ValueError("the crest-loft fraction must be finite and >= 0")
        object.__setattr__(self, "fraction", float(self.fraction))
        object.__setattr__(self, "stations", tuple(float(v) for v in f))
        object.__setattr__(self, "taper", tuple(float(v) for v in tau))

    def offset(self, fraction: npt.ArrayLike, radius: npt.ArrayLike) -> FloatArray:
        """Crest offset :math:`\\delta`, m, at fractions of the tape length and tape radii, m."""
        tau = np.interp(_as_array(fraction), np.array(self.stations), np.array(self.taper))
        return _as_array(self.fraction * tau * _as_array(radius))


def _turning_angles(profile: MeridianProfile) -> FloatArray:
    """Signed turning angle of the tape at every profile node, rad (+ towards the axis)."""
    d = np.column_stack((np.diff(profile.r), np.diff(profile.z)))
    cross = d[:-1, 0] * d[1:, 1] - d[:-1, 1] * d[1:, 0]
    dot = np.einsum("ij,ij->i", d[:-1], d[1:])
    return _as_array(np.concatenate(([0.0], np.arctan2(cross, dot), [0.0])))


def crest_bows(
    profile: MeridianProfile, boundaries: npt.ArrayLike, crest: CrestLoft
) -> list[tuple[float, float]]:
    r"""Seam bows of a crest-lofted flat-chord gore, m, one (bottom, top) pair per row.

    Offsetting the tape outward by :math:`\delta` lengthens it by
    :math:`2\delta\tan(\varphi/2)` at a node where it turns by :math:`\varphi`
    (:math:`\int \delta\kappa\, ds` for a smooth profile). Each node's excess goes to the
    nearest row boundary between two rows, and a boundary that collects an excess
    :math:`e_j` bows both seam lines that meet there by :math:`\beta_j = e_j/2`, so the two
    sides of every horizontal seam have the same shape. The mouth and the top opening stay
    straight; excess next to them goes to the first interior boundary.

    Parameters
    ----------
    profile : MeridianProfile
        Tape profile, m.
    boundaries : array_like
        Row boundaries along the tape, m, mouth first (rows + 1 values).
    crest : CrestLoft
        Crest offset along the tape.

    Returns
    -------
    list of (float, float)
        (bottom bow, top bow) of each row, m, positive outward.
    """
    b = np.asarray(boundaries, dtype=np.float64)
    rows = len(b) - 1
    if rows < 1:
        raise ValueError("a gore needs at least one row")
    beta = np.zeros(rows + 1)
    if rows >= 2:
        phi = _turning_angles(profile)
        inside = (profile.s > b[0]) & (profile.s < b[-1]) & (phi != 0.0)
        s = profile.s[inside]
        delta = crest.offset(s / profile.meridian_length, profile.r[inside])
        excess = 2.0 * delta * np.tan(phi[inside] / 2.0)
        row = np.clip(np.searchsorted(b, s, side="right") - 1, 0, rows - 1)
        upper = (s - b[row]) > (b[row + 1] - s)
        nearest = np.clip(row + upper.astype(np.int64), 1, rows - 1)
        np.add.at(beta, nearest, 0.5 * excess)
    return [(float(beta[k]), float(beta[k + 1])) for k in range(rows)]


def _boundary_weights(profile: MeridianProfile, b: FloatArray) -> FloatArray:
    r"""Sum of :math:`2\tan(\varphi_i/2)` over the profile nodes that :func:`crest_bows`
    gives to each row boundary (zero at the mouth and the top opening)."""
    rows = len(b) - 1
    weight = np.zeros(rows + 1)
    if rows >= 2:
        phi = _turning_angles(profile)
        inside = (profile.s > b[0]) & (profile.s < b[-1]) & (phi != 0.0)
        s = profile.s[inside]
        row = np.clip(np.searchsorted(b, s, side="right") - 1, 0, rows - 1)
        upper = (s - b[row]) > (b[row + 1] - s)
        nearest = np.clip(row + upper.astype(np.int64), 1, rows - 1)
        np.add.at(weight, nearest, 2.0 * np.tan(phi[inside] / 2.0))
    return weight


def crest_offsets_from_bows(
    profile: MeridianProfile,
    boundaries: npt.ArrayLike,
    bows: Sequence[tuple[float, float]],
    min_turn: float = 1e-3,
) -> FloatArray:
    r"""Crest offset at each row boundary implied by seam bows, m (inverse of
    :func:`crest_bows`).

    :func:`crest_bows` gives boundary :math:`j` the bow
    :math:`\beta_j = \tfrac12\sum_i 2\delta_i\tan(\varphi_i/2)` over the profile nodes
    nearest to it. Taking :math:`\delta` constant over those nodes,

    .. math:: \delta_j = \frac{2\beta_j}{\sum_i 2\tan(\varphi_i/2)},

    with :math:`\beta_j` the mean of the two seam lines that meet there (they differ for a
    measured pattern). It reproduces the crest offset of a crest loft at the boundaries to
    first order in the variation of :math:`\delta` between them.

    Parameters
    ----------
    profile : MeridianProfile
        Tape profile, m.
    boundaries : array_like
        Row boundaries along the tape, m, mouth first (rows + 1 values).
    bows : sequence of (float, float)
        (bottom, top) bow of each row, m, positive outward.
    min_turn : float
        Smallest total tape turn at a boundary, rad, that carries an offset: where the
        tape is straight (a cylinder), seam bows cannot be shown as an offset and the
        offset is 0.

    Returns
    -------
    ndarray, shape (rows + 1,)
        Crest offset :math:`\delta_j`, m, positive outward; 0 at the mouth and the top
        opening, which stay straight.
    """
    b = np.asarray(boundaries, dtype=np.float64)
    rows = len(b) - 1
    if len(bows) != rows:
        raise ValueError("one (bottom, top) bow pair per row")
    weight = _boundary_weights(profile, b)
    delta = np.zeros(rows + 1)
    for j in range(1, rows):
        beta = 0.5 * (bows[j - 1][1] + bows[j][0])
        if abs(weight[j]) >= min_turn:
            delta[j] = 2.0 * beta / weight[j]
    return _as_array(delta)


def _line_intersection(p: FloatArray, d: FloatArray, q: FloatArray, e: FloatArray) -> FloatArray:
    """Intersection of the lines p + t d and q + u e (m)."""
    det = d[0] * (-e[1]) - d[1] * (-e[0])
    if abs(det) < 1e-12 * float(np.linalg.norm(d) * np.linalg.norm(e)):
        raise ValueError("panel side is parallel to its seam line; cannot mitre")
    t = ((q[0] - p[0]) * (-e[1]) - (q[1] - p[1]) * (-e[0])) / det
    return _as_array(p + t * d)


def bowed_cut_outline(
    right_edge: FloatArray, bottom_bow: float, top_bow: float, allowance: SeamAllowance
) -> FloatArray:
    """Cut outline of a symmetric panel with bowed horizontal seams, mitred corners.

    Each finished edge (bottom seam, right side, top seam, left side) is offset outward by
    its allowance (mitred joints within the edge) and neighbouring offset edges are
    extended along their end segments to meet at the corners.

    Parameters
    ----------
    right_edge : ndarray, shape (n, 2)
        Finished right-hand side from the bottom corner to the top corner, m.
    bottom_bow, top_bow : float
        Outward seam bows at the centreline, m (see :class:`PanelRow`).
    allowance : SeamAllowance
        Side, bottom and top allowances, m.

    Returns
    -------
    ndarray, shape (m, 2)
        Counter-clockwise cut polygon, m, starting at the bottom-left corner.
    """
    w0, y0 = float(right_edge[0, 0]), float(right_edge[0, 1])
    w1, y1 = float(right_edge[-1, 0]), float(right_edge[-1, 1])
    bottom = bowed_seam(w0, -bottom_bow)[::-1] + [0.0, y0]
    top = bowed_seam(w1, top_bow) + [0.0, y1]
    left = right_edge[::-1] * np.array([-1.0, 1.0])
    edges = [
        (bottom, allowance.bottom),
        (right_edge, allowance.side),
        (top, allowance.top),
        (left, allowance.side),
    ]
    offset = [_offset_polyline(pts, a) if a > 0.0 else pts.copy() for pts, a in edges]
    corners = []
    for i in range(4):
        a, b = offset[i], offset[(i + 1) % 4]
        corners.append(_line_intersection(a[-1], a[-1] - a[-2], b[0], b[1] - b[0]))
    parts = []
    for i in range(4):
        parts.append(corners[i - 1][None, :])
        parts.append(offset[i][1:-1])
    return _as_array(np.vstack(parts))


def flat_chord_rows(
    profile: MeridianProfile,
    n_gores: int,
    row_heights: Sequence[float],
    labels: Sequence[str] | None = None,
    bows: Sequence[tuple[float, float]] | None = None,
    crest: CrestLoft | None = None,
    allowance: SeamAllowance | None = None,
    start: float = 0.0,
    require_full_coverage: bool = True,
    loft_fractions: Sequence[float] = DEFAULT_LOFT_FRACTIONS,
    min_edge_points: int = 65,
) -> list[PanelRow]:
    r"""Split a flat-chord gore into rows: straight-sided trapezoids with bowed seams.

    Row :math:`k` runs along the tape from :math:`s_k` to :math:`s_{k+1}`. Its corners lie
    a flat chord apart, :math:`w_j = r(s_j)\sin(\pi/N)` either side of the centreline, and
    its sides are straight lines of the tape length
    :math:`L_k = s_{k+1} - s_k` (the tape is sewn along them), so the top corners stand
    :math:`h_k = \sqrt{L_k^2 - (w_{k+1} - w_k)^2}` above the bottom ones. The bottom and
    top seams bow outward by the given ordinates (:func:`bowed_seam`), measured or from a
    crest loft (:func:`crest_bows`); the centreline is then
    :math:`h_k + b_{bottom} + b_{top}` long.

    Parameters
    ----------
    profile : MeridianProfile
        Tape profile, m (straight segments between row corners for an exact match with
        straight panel sides, :meth:`MeridianProfile.from_control_points` ``"linear"``).
    n_gores : int
        Number of gores N (>= 3).
    row_heights : sequence of float
        Tape length of each row, m, from the mouth upward.
    labels : sequence of str, optional
        Row labels; default ``"A"``, ``"B"``, ...
    bows : sequence of (float, float), optional
        Measured (bottom, top) seam bows of each row, m, positive outward.
    crest : CrestLoft, optional
        Crest loft the bows are computed from (not with ``bows``). Neither: straight seams.
    allowance : SeamAllowance, optional
        Seam allowances, m; default none.
    start : float, optional
        Tape arc length of the bottom of the first row, m.
    require_full_coverage : bool, optional
        If true, the rows must end at the top of the profile within 1 mm.
    loft_fractions : sequence of float, optional
        Fractions of each row's corner height for the loft table, dimensionless.
    min_edge_points : int, optional
        Number of points on each finished side edge.

    Returns
    -------
    list of PanelRow
        Rows from the mouth upward; ``s_bottom``/``s_top`` are the corner stations.
    """
    _check_gores(n_gores)
    heights = [float(h) for h in row_heights]
    if not heights or min(heights) <= 0.0:
        raise ValueError("row heights must be positive")
    if labels is None:
        labels = [_default_label(i) for i in range(len(heights))]
    if len(labels) != len(heights):
        raise ValueError("labels and row_heights differ in length")
    if bows is not None and crest is not None:
        raise ValueError("give measured bows or a crest loft, not both")
    if bows is not None and len(bows) != len(heights):
        raise ValueError("bows and row_heights differ in length")
    end = start + sum(heights)
    if end > profile.meridian_length + LENGTH_TOLERANCE:
        raise ValueError(
            f"rows end at {end:.4f} m, beyond the meridian length {profile.meridian_length:.4f} m"
        )
    if require_full_coverage and abs(end - profile.meridian_length) > LENGTH_TOLERANCE:
        raise ValueError(
            f"rows cover {start:.4f}-{end:.4f} m but the meridian is "
            f"{profile.meridian_length:.4f} m long"
        )
    allowance = allowance or SeamAllowance()
    boundaries = np.minimum(
        np.concatenate(([start], start + np.cumsum(heights))), profile.meridian_length
    )
    half = profile.radius_at(boundaries) * math.sin(math.pi / n_gores)
    if crest is not None:
        bows = crest_bows(profile, boundaries, crest)
    bow_pairs = list(bows) if bows is not None else [(0.0, 0.0)] * len(heights)
    rows: list[PanelRow] = []
    for k, label in enumerate(labels):
        s0, s1 = float(boundaries[k]), float(boundaries[k + 1])
        w0, w1 = float(half[k]), float(half[k + 1])
        length = s1 - s0
        # |w1 - w0| = |r1 - r0| sin(pi/N) <= length on any tape profile.
        rise = math.sqrt(length * length - (w1 - w0) ** 2)
        t = np.linspace(0.0, 1.0, max(min_edge_points, 2))
        right_edge = _as_array(np.column_stack((w0 + t * (w1 - w0), t * rise)))
        bottom_bow, top_bow = (float(v) for v in bow_pairs[k])
        loft = tuple(
            LoftStation(
                fraction=float(f), y=float(f) * rise, width=2.0 * (w0 + float(f) * (w1 - w0))
            )
            for f in loft_fractions
        )
        if bottom_bow == 0.0 and top_bow == 0.0:
            outline = cut_outline(right_edge, allowance)
        else:
            outline = bowed_cut_outline(right_edge, bottom_bow, top_bow, allowance)
        rows.append(
            PanelRow(
                label=str(label),
                s_bottom=s0,
                s_top=s1,
                right_edge=right_edge,
                cut_outline=outline,
                loft=loft,
                side_length=length,
                bottom_bow=bottom_bow,
                top_bow=top_bow,
            )
        )
    return rows


def _default_label(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _loo_residuals(s: FloatArray, values: FloatArray, half_window: int = 3) -> FloatArray:
    """Leave-one-out residuals of a local quadratic through the nearest neighbours."""
    n = s.size
    window = min(2 * half_window, n - 1)
    residuals = np.empty(n)
    for i in range(n):
        lo = min(max(i - half_window, 0), n - window - 1)
        neighbours = [j for j in range(lo, lo + window + 1) if j != i]
        coefficients = np.polyfit(s[neighbours] - s[i], values[neighbours], 2)
        residuals[i] = values[i] - coefficients[-1]
    return _as_array(residuals)


def _prescreen(
    s: FloatArray, values: FloatArray, threshold: float, min_scale: float
) -> npt.NDArray[np.bool_]:
    """Flag gross outliers one at a time, worst first.

    A fit that still contains an outlier is pulled towards it and makes its neighbours look
    bad too, so each flagged station is removed before the residuals are recomputed.
    """
    flags = np.zeros(s.size, dtype=bool)
    while np.count_nonzero(~flags) > s.size // 2 + 3:
        keep = np.flatnonzero(~flags)
        residuals = _loo_residuals(s[keep], values[keep])
        centre = float(np.median(residuals))
        scale = max(1.4826 * float(np.median(np.abs(residuals - centre))), min_scale)
        score = np.abs(residuals - centre) / scale
        worst = int(np.argmax(score))
        if score[worst] <= threshold:
            break
        flags[keep[worst]] = True
    return flags


def _robust_flags(
    residuals: FloatArray, threshold: float, min_scale: float, reference: npt.NDArray[np.bool_]
) -> npt.NDArray[np.bool_]:
    centre = float(np.median(residuals[reference]))
    mad = float(np.median(np.abs(residuals[reference] - centre)))
    scale = max(1.4826 * mad, min_scale)
    return np.abs(residuals - centre) / scale > threshold


@dataclass(frozen=True)
class InverseResult:
    """Profile recovered from measured gore widths.

    Attributes
    ----------
    profile : MeridianProfile
        Reconstructed meridian, m, with ``z = 0`` at the first station.
    stations : ndarray
        Measurement stations s, m (shifted so the first is 0).
    measured_radius : ndarray
        Radius implied by each measured width, m.
    fitted_radius : ndarray
        Smoothing-spline radius at each station, m.
    residuals : ndarray
        ``measured_radius - fitted_radius``, m.
    outliers : ndarray of bool
        Stations rejected by the robust residual test.
    rms_residual : float
        RMS residual of the inliers, m.
    slope_clipped : int
        Number of dense samples where |dr/ds| > 1 had to be clipped (non-physical data).
    """

    profile: MeridianProfile
    stations: FloatArray
    measured_radius: FloatArray
    fitted_radius: FloatArray
    residuals: FloatArray
    outliers: npt.NDArray[np.bool_]
    rms_residual: float
    slope_clipped: int


def profile_from_gore_widths(
    stations: npt.ArrayLike,
    widths: npt.ArrayLike,
    width_model: GoreWidthModel,
    smoothing: float | None = None,
    outlier_threshold: float = 3.5,
    min_residual_scale: float = 1e-3,
    max_iterations: int = 5,
    samples: int = 2001,
) -> InverseResult:
    r"""Recover the meridian profile from measured flat gore widths.

    1. Radius from width: :math:`r_i = N w_i / (2\pi)` (small bulge) or the chord-form
       inverse of ``width_model``.
    2. Fit a cubic smoothing spline :math:`r(s)` (penalised second derivative, weight
       ``smoothing``; ``None`` selects it by generalised cross-validation).
    3. Flag outliers where the robust score :math:`|e_i - \tilde e| / (1.4826\,\mathrm{MAD})`
       exceeds ``outlier_threshold``. A first pass removes gross outliers one at a time
       using leave-one-out local quadratic residuals; then the spline is refitted on the
       inliers and every station is re-tested against it until the outlier set is stable.
    4. Height from arc length: :math:`z(s) = \int_0^s \sqrt{1 - r'(\sigma)^2}\, d\sigma`.

    Parameters
    ----------
    stations : array_like
        Tape arc length of each measurement, m, strictly increasing (at least 8).
    widths : array_like
        Measured flat full gore widths, m.
    width_model : GoreWidthModel
        Width formula and gore count used to convert widths to radii.
    smoothing : float or None, optional
        Smoothing-spline penalty λ, m^3 (≥ 0); ``None`` uses GCV.
    outlier_threshold : float, optional
        Robust z-score above which a station is an outlier, dimensionless.
    min_residual_scale : float, optional
        Floor for the robust residual scale, m (radius), so that near-exact data do not flag
        sub-resolution deviations; default 1 mm, about a tape-measure reading.
    max_iterations : int, optional
        Maximum refit iterations.
    samples : int, optional
        Number of points in the reconstructed profile.

    Returns
    -------
    InverseResult
        Reconstructed profile, residuals (m) and outlier mask.

    Notes
    -----
    Assumes z increases monotonically with s (true of gore balloons from mouth to crown);
    a profile that turns downward cannot be recovered from widths alone.
    """
    s_raw = _as_array(stations)
    s = s_raw - s_raw[0]
    measured = width_model.radius_from_full_width(
        widths, None if width_model.loft is None else s / s[-1]
    )
    if s.size < 8 or s.shape != measured.shape:
        raise ValueError("need at least 8 stations with one width each")
    if np.any(np.diff(s) <= 0.0):
        raise ValueError("stations must be strictly increasing")
    outliers = _prescreen(s, measured, outlier_threshold, min_residual_scale)
    for _ in range(max_iterations):
        spline = make_smoothing_spline(s[~outliers], measured[~outliers], lam=smoothing)
        fitted = _as_array(spline(s))
        residuals = measured - fitted
        # Re-test every station against the inlier fit so wrongly flagged ones are readmitted.
        new_outliers = _robust_flags(residuals, outlier_threshold, min_residual_scale, ~outliers)
        if np.array_equal(new_outliers, outliers):
            break
        outliers = new_outliers
    dense_s = np.linspace(0.0, float(s[-1]), samples)
    dense_r = np.clip(_as_array(spline(dense_s)), 0.0, None)
    slope = _as_array(spline.derivative()(dense_s))
    clipped = int(np.count_nonzero(np.abs(slope) > 1.0))
    dz_ds = np.sqrt(np.clip(1.0 - slope * slope, 0.0, None))
    z = np.concatenate(([0.0], np.cumsum(0.5 * (dz_ds[1:] + dz_ds[:-1]) * np.diff(dense_s))))
    profile = MeridianProfile(s=dense_s, r=dense_r, z=_as_array(z))
    inlier_res = residuals[~outliers]
    return InverseResult(
        profile=profile,
        stations=s,
        measured_radius=measured,
        fitted_radius=fitted,
        residuals=residuals,
        outliers=outliers,
        rms_residual=float(np.sqrt(np.mean(inlier_res * inlier_res))),
        slope_clipped=clipped,
    )
