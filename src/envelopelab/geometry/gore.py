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
* Horizontal seams are straight lines across the flat gore (constant :math:`s`).
* Between adjacent tapes the fabric is a circular lobe (the gore's *loft*); its radius is
  set by the width model (:class:`GoreWidthModel`, :class:`GoreLoft`). The small-bulge
  form puts the lobe on the circle through the tapes.
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
        cls, r: npt.ArrayLike, z: npt.ArrayLike, samples: int = 4001
    ) -> MeridianProfile:
        """Interpolate control points with a parametric cubic spline and sample it densely.

        Parameters
        ----------
        r, z : array_like
            Control-point radius and height, m, ordered from mouth to top (at least 2).
        samples : int, optional
            Number of polyline points in the result. With the default 4001 the chord
            length error of a smooth profile is below 1e-7 relative.

        Returns
        -------
        MeridianProfile
            Densely sampled profile, m.
        """
        r_arr, z_arr = _as_array(r), _as_array(z)
        chord = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(r_arr), np.diff(z_arr)))))
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
    """

    label: str
    s_bottom: float
    s_top: float
    right_edge: FloatArray = field(repr=False)
    cut_outline: FloatArray = field(repr=False)
    loft: tuple[LoftStation, ...]
    side_length: float

    @property
    def finished_height(self) -> float:
        """Finished panel height along the centreline, m."""
        return self.s_top - self.s_bottom

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
        return _as_array(np.vstack((self.right_edge, mirrored)))

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
