r"""Shape families: a normalized gore profile scaled and cut to a design by held values.

A *shape family* is one envelope shape at every size: a table of radius :math:`r` against
station :math:`s` along the load tape, both as fractions of the pole-to-pole gore length
:math:`L` (the Balloon Builders Journal "gore layout" tables are of this kind). A design
of the family is fixed by three continuous variables,

* the gore length :math:`L` (m), which scales the whole shape;
* the mouth station :math:`s_m` and the top-opening station :math:`s_t` (fractions of
  :math:`L`), where the envelope is cut,

plus the gore count :math:`N` and the seam allowance, which do not change the shape.
Holding any three quantities (variables or computed values such as the mouth diameter or
the volume) fixes the design; :func:`solve_shape` finds the free variables.

Profile from the table
----------------------
The table gives :math:`r` against tape length, so :math:`s` is arc length and

.. math:: z(s) = L \int_0^s \sqrt{1 - r'(\sigma)^2}\, d\sigma ,

with :math:`r(s)` the not-a-knot cubic spline through the table (slopes
:math:`|r'| > 1` from spline overshoot are taken as a horizontal tape). Taking each
interval as a straight chord instead would shorten the tape by
:math:`\kappa^2 \Delta s^3 / 24` per interval (2.9 mm on a 25 m sphere table with 50
intervals). The design profile is the editor's parametric cubic spline through the stations
between :math:`s_m` and :math:`s_t` (end points on :math:`r(s), z(s)`), so the
values computed here are exactly those the editor shows for the design
(:func:`envelopelab.project.gore_design.profile_from_arrays`).

Computed quantities (SI)
------------------------
``nominal_volume``
    :math:`V_n = c L^3`, closed shape from pole to pole; :math:`c` is the volume of the
    spline through all stations at :math:`L = 1` (the spreadsheets' "volume").
``envelope_volume``, ``height``, ``max_diameter``, ``tape_length``
    Of the profile from the mouth to the top opening; open ends closed by flat discs.
``mouth_diameter``, ``top_diameter``
    :math:`2 r(s_m)`, :math:`2 r(s_t)`.
``max_cut_gore_width``
    :math:`2 (\pi r_{max} / N + a)` with seam allowance :math:`a` per edge (small-bulge
    gore, :func:`envelopelab.geometry.gore.half_width_small_bulge`).

Assumptions and valid range: axisymmetric envelope with a tape on every gore seam, fabric
stretch neglected, the table smooth enough for a cubic spline between stations (error
:math:`O(\Delta s^4)`); the mouth lies below and the top opening above
the equator station. See ``docs/theory/shape-families.md``.

References
----------
.. [BBJ] Balloon Builders Journal, Issues 1 and 22: gore layout from a normalized
   natural-shape table.
.. [Brent] R. P. Brent, *Algorithms for Minimization without Derivatives*, Prentice-Hall
   (1973), ch. 4.
.. [TRF] M. A. Branch, T. F. Coleman and Y. Li, "A subspace, interior, and conjugate
   gradient method for large-scale bound-constrained minimization problems", SIAM J. Sci.
   Comput. 21 (1999) 1-23 (``scipy.optimize.least_squares``, method ``trf``).
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.optimize import brentq, least_squares

from envelopelab.design.model import DesignDocument
from envelopelab.geometry.gore import MeridianProfile
from envelopelab.project.gore_design import PROFILE_SAMPLES, VOLUME_TOLERANCE, profile_from_arrays

FloatArray = np.ndarray
Dimension = Literal["length", "volume", "fraction"]

#: The continuous design variables, in solver order.
VARIABLES: tuple[str, ...] = ("gore_length", "mouth_station", "top_station")
#: Number of quantities that must be held to fix a design.
HELD_COUNT = len(VARIABLES)
#: Length tolerance of a solve, m (AGENTS.md geometry default).
LENGTH_TOLERANCE = 1e-3
#: Station tolerance of a solve, fraction of L.
FRACTION_TOLERANCE = 1e-6
#: Relative excess of |dr| over ds accepted as rounding of the table (then dz = 0).
SLOPE_ROUNDING = 1e-4
#: Interior stations closer than this fraction of their interval to a cut are dropped, so
#: the spline does not get two nearly coincident knots.
KNOT_GAP = 0.25
#: Gauss-Legendre points per table interval for the height integral.
GAUSS_POINTS = 8
#: Margin kept between the cut stations and the poles or the equator, fraction of L.
STATION_MARGIN = 1e-3


@dataclass(frozen=True)
class Quantity:
    """A quantity that can be held or shown: name, label and dimension."""

    name: str
    label: str
    dimension: Dimension


QUANTITIES: dict[str, Quantity] = {
    q.name: q
    for q in (
        Quantity("gore_length", "Gore length, pole to pole (L)", "length"),
        Quantity("mouth_station", "Mouth station (fraction of L)", "fraction"),
        Quantity("top_station", "Top-opening station (fraction of L)", "fraction"),
        Quantity("nominal_volume", "Nominal volume (closed shape)", "volume"),
        Quantity("envelope_volume", "Envelope volume (mouth to top opening)", "volume"),
        Quantity("height", "Height (mouth to top opening)", "length"),
        Quantity("max_diameter", "Maximum diameter", "length"),
        Quantity("mouth_diameter", "Mouth diameter", "length"),
        Quantity("top_diameter", "Top-opening diameter", "length"),
        Quantity("tape_length", "Tape length (mouth to top opening)", "length"),
        Quantity("max_cut_gore_width", "Maximum cut gore width", "length"),
    )
}


def _rise(spline_r: CubicSpline, a: float, b: float) -> float:
    r"""Height gained along the tape from station a to b, fraction of L.

    :math:`\int_a^b \sqrt{1 - \min(r'(s)^2, 1)}\, ds` by 8-point Gauss-Legendre
    quadrature; a slope :math:`|r'| > 1` (spline overshoot where the tape is horizontal)
    counts as horizontal.
    """
    if b <= a:
        return 0.0
    x, w = np.polynomial.legendre.leggauss(GAUSS_POINTS)
    s = 0.5 * (b - a) * x + 0.5 * (a + b)
    slope = np.asarray(spline_r(s, 1), dtype=np.float64)
    return float(0.5 * (b - a) * np.sum(w * np.sqrt(np.clip(1.0 - slope * slope, 0.0, None))))


@dataclass(frozen=True)
class NormalizedShape:
    """Normalized meridian table of a shape family.

    Attributes
    ----------
    s : ndarray
        Stations along the tape, fraction of L, strictly increasing from 0 to 1.
    r : ndarray
        Radius at each station, fraction of L, non-negative.
    stations : mapping of str to float
        Named stations (e.g. ``mouth``, ``vent``), fraction of L.
    source : str
        Source tag of the table (``datasheet``, ``measured`` or ``assumed``).
    """

    s: FloatArray
    r: FloatArray
    stations: Mapping[str, float] = field(default_factory=dict)
    source: str = "assumed"
    z: FloatArray = field(init=False, repr=False)
    _spline_r: CubicSpline = field(init=False, repr=False)

    def __post_init__(self) -> None:
        s = np.asarray(self.s, dtype=np.float64)
        r = np.asarray(self.r, dtype=np.float64)
        if s.ndim != 1 or s.shape != r.shape or s.size < 4:
            raise ValueError("the profile needs at least 4 stations [s, r]")
        if abs(s[0]) > 1e-9 or abs(s[-1] - 1.0) > 1e-9:
            raise ValueError("profile stations must run from s = 0 (bottom) to s = 1 (top)")
        ds, dr = np.diff(s), np.diff(r)
        if np.any(ds <= 0.0):
            raise ValueError("profile stations must be strictly increasing")
        if np.any(r < 0.0):
            raise ValueError("profile radii must be non-negative")
        steep = np.abs(dr) > ds * (1.0 + SLOPE_ROUNDING)
        if np.any(steep):
            i = int(np.argmax(steep))
            raise ValueError(
                f"the radius changes by more than the tape length between s = {s[i]:g} and "
                f"s = {s[i + 1]:g}: the table is not radius against tape length"
            )
        for name, value in self.stations.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"station {name!r} = {value:g} is outside 0..1")
        spline_r = CubicSpline(s, r)
        z = np.concatenate(
            ([0.0], np.cumsum([_rise(spline_r, a, b) for a, b in zip(s[:-1], s[1:], strict=True)]))
        )
        object.__setattr__(self, "s", s)
        object.__setattr__(self, "r", r)
        object.__setattr__(self, "z", z)
        object.__setattr__(self, "_spline_r", spline_r)

    def point(self, station: float) -> tuple[float, float]:
        """Radius and height at a station, fractions of L (the module's r(s), z(s))."""
        if not -1e-9 <= station <= 1.0 + 1e-9:
            raise ValueError(f"station {station:g} is outside 0..1")
        station = min(max(station, 0.0), 1.0)
        i = min(int(np.searchsorted(self.s, station, side="right")) - 1, self.s.size - 2)
        z = float(self.z[i]) + _rise(self._spline_r, float(self.s[i]), station)
        return max(float(self._spline_r(station)), 0.0), z

    @property
    def equator_station(self) -> float:
        """Station of the largest tabulated radius, fraction of L."""
        return float(self.s[int(np.argmax(self.r))])

    @property
    def volume_coefficient(self) -> float:
        r"""Closed-shape volume at :math:`L = 1`, dimensionless (:math:`V_n = c L^3`)."""
        return profile_from_arrays(self.r, self.z).volume

    @property
    def chord_volume_coefficient(self) -> float:
        """Closed-shape volume of the polyline through the stations at L = 1, dimensionless.

        A cross-check of :attr:`volume_coefficient`: an inscribed polygon, so a lower bound
        for a convex profile.
        """
        return MeridianProfile.from_points(self.r, self.z).volume

    def resolve_station(self, value: float | str) -> float:
        """A station given as a number (fraction of L) or a station name."""
        if isinstance(value, str):
            if value not in self.stations:
                raise ValueError(
                    f"unknown station {value!r}; named stations: {', '.join(self.stations)}"
                )
            return float(self.stations[value])
        return float(value)

    def control_points(self, lower: float, upper: float) -> tuple[FloatArray, FloatArray]:
        """Control points between two stations, fractions of L (mouth first, z from mouth).

        The end points lie on the closed-shape spline; table stations closer than
        :data:`KNOT_GAP` of an interval to an end are left out.
        """
        if not 0.0 <= lower < upper <= 1.0:
            raise ValueError("stations must satisfy 0 <= mouth < top <= 1")
        gap = KNOT_GAP * float(np.min(np.diff(self.s)))
        inner = (self.s > lower + gap) & (self.s < upper - gap)
        r0, z0 = self.point(lower)
        r1, z1 = self.point(upper)
        r = np.concatenate(([r0], self.r[inner], [r1]))
        z = np.concatenate(([z0], self.z[inner], [z1]))
        return r, z - z0


@dataclass(frozen=True)
class ShapeParameters:
    """A design of a shape family.

    Attributes
    ----------
    gore_length : float
        Pole-to-pole gore length L, m.
    mouth_station, top_station : float
        Cut stations, fractions of L.
    gore_count : int
        Gores N (>= 3).
    seam_allowance : float
        Cut allowance per gore edge, m.
    """

    gore_length: float
    mouth_station: float
    top_station: float
    gore_count: int
    seam_allowance: float

    def variable(self, name: str) -> float:
        """Value of one of :data:`VARIABLES` (m or fraction of L)."""
        return float(getattr(self, name))


def design_profile(shape: NormalizedShape, params: ShapeParameters) -> MeridianProfile:
    """Meridian profile of a design from the mouth to the top opening, m."""
    r, z = shape.control_points(params.mouth_station, params.top_station)
    return profile_from_arrays(r * params.gore_length, z * params.gore_length)


def evaluate(shape: NormalizedShape, params: ShapeParameters) -> dict[str, float]:
    """All :data:`QUANTITIES` of a design, SI (m, m^3) or fractions of L.

    Parameters
    ----------
    shape : NormalizedShape
        Shape family.
    params : ShapeParameters
        Design (lengths in m).

    Returns
    -------
    dict of str to float
        Keyed by quantity name.
    """
    if params.gore_count < 3:
        raise ValueError("a design needs at least 3 gores")
    profile = design_profile(shape, params)
    length = params.gore_length
    return {
        "gore_length": length,
        "mouth_station": params.mouth_station,
        "top_station": params.top_station,
        "nominal_volume": shape.volume_coefficient * length**3,
        "envelope_volume": profile.volume,
        "height": profile.height,
        "max_diameter": profile.max_width,
        "mouth_diameter": 2.0 * float(profile.r[0]),
        "top_diameter": 2.0 * float(profile.r[-1]),
        "tape_length": profile.meridian_length,
        "max_cut_gore_width": 2.0
        * (math.pi * profile.max_width / 2.0 / params.gore_count + params.seam_allowance),
    }


@dataclass(frozen=True)
class StationPoint:
    """A named station of a design: radius, height above the mouth, tape distance (m)."""

    name: str
    station: float
    radius: float
    height: float
    tape_distance: float


def station_points(shape: NormalizedShape, params: ShapeParameters) -> list[StationPoint]:
    """Named stations of a design, in station order (m; tape distance from the mouth).

    Stations outside the mouth-to-top range are included; their height and tape distance
    are measured on the closed shape and are negative below the mouth.
    """
    length = params.gore_length
    _, z_mouth = shape.point(params.mouth_station)
    out = []
    for name, st in sorted(shape.stations.items(), key=lambda item: item[1]):
        r, z = shape.point(st)
        out.append(
            StationPoint(
                name, st, r * length, (z - z_mouth) * length, (st - params.mouth_station) * length
            )
        )
    return out


@dataclass(frozen=True)
class ShapeSolution:
    """Result of :func:`solve_shape`.

    Attributes
    ----------
    parameters : ShapeParameters
        The solved design (lengths m).
    values : dict of str to float
        All quantities of the solved design (:func:`evaluate`).
    hold : dict of str to float
        The held quantities and their targets (SI).
    free : tuple of str
        The variables that were solved for.
    converged : bool
        True when every held quantity is met within its tolerance (lengths 1 mm, volumes
        0.1 %, stations 1e-6). Never use an unconverged solution as a design.
    errors : dict of str to float
        Achieved minus target for each held quantity (m, m^3 or fraction of L).
    iterations : int
        Solver iterations (function evaluations for more than one free variable).
    message : str
        What the solver did, or why it failed.
    run_time : float
        Wall time, s.
    """

    parameters: ShapeParameters
    values: dict[str, float]
    hold: dict[str, float]
    free: tuple[str, ...]
    converged: bool
    errors: dict[str, float]
    iterations: int
    message: str
    run_time: float


def _within(name: str, error: float, target: float) -> bool:
    dimension = QUANTITIES[name].dimension
    if dimension == "length":
        return abs(error) <= LENGTH_TOLERANCE
    if dimension == "volume":
        return abs(error) <= VOLUME_TOLERANCE * abs(target)
    return abs(error) <= FRACTION_TOLERANCE


def _bounds(shape: NormalizedShape, name: str, start: float) -> tuple[float, float]:
    """Search range of a free variable (log L for the gore length)."""
    if name == "gore_length":
        return math.log(start) - math.log(1e3), math.log(start) + math.log(1e3)
    equator = shape.equator_station
    if name == "mouth_station":
        return STATION_MARGIN, equator - STATION_MARGIN
    return equator + STATION_MARGIN, 1.0 - STATION_MARGIN


def check_hold(hold: Mapping[str, float]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Free variables and target quantities of a set of held values.

    Raises
    ------
    ValueError
        When the names are unknown or the held set does not fix a design (the message
        says what to change).
    """
    unknown = [name for name in hold if name not in QUANTITIES]
    if unknown:
        raise ValueError(f"unknown quantities: {', '.join(unknown)}")
    if len(hold) != HELD_COUNT:
        raise ValueError(
            f"hold exactly {HELD_COUNT} values to fix a design ({len(hold)} held: "
            f"{', '.join(hold) or 'none'})"
        )
    free = tuple(v for v in VARIABLES if v not in hold)
    targets = tuple(name for name in hold if name not in VARIABLES)
    if "nominal_volume" in hold and "gore_length" in hold:
        raise ValueError("nominal volume and gore length fix the same thing; hold only one")
    for name, value in hold.items():
        if not math.isfinite(value) or (QUANTITIES[name].dimension != "fraction" and value <= 0):
            raise ValueError(f"{QUANTITIES[name].label} must be a positive number")
    return free, targets


def solve_shape(
    shape: NormalizedShape,
    start: ShapeParameters,
    hold: Mapping[str, float],
) -> ShapeSolution:
    """Find the design of a shape family that has the held values.

    Parameters
    ----------
    shape : NormalizedShape
        Shape family.
    start : ShapeParameters
        Starting design; its gore count and seam allowance are kept, and its variables are
        the starting point (and the search range of L is ``start.gore_length`` / 1000 to
        x 1000).
    hold : mapping of str to float
        Exactly :data:`HELD_COUNT` quantities of :data:`QUANTITIES` with their values, SI
        (m, m^3) or fractions of L. Held variables are fixed; the others are solved for so
        that the held computed values are met.

    Returns
    -------
    ShapeSolution
        Check ``converged`` before using it.

    Notes
    -----
    One free variable is found by Brent's method [Brent]_ on its whole range (a target
    outside the achievable range is reported with that range); several by bounded
    least squares [TRF]_ on relative errors from the starting design.
    """
    begin = time.perf_counter()
    free, targets = check_hold(hold)
    fixed = {name: float(hold[name]) for name in VARIABLES if name in hold}
    base = replace(start, **fixed)  # type: ignore[arg-type]
    if base.mouth_station >= base.top_station:
        raise ValueError("the mouth station must be below the top-opening station")

    def design(x: FloatArray) -> ShapeParameters:
        values = dict(zip(free, (float(v) for v in x), strict=True))
        if "gore_length" in values:
            values["gore_length"] = math.exp(values["gore_length"])
        return replace(base, **values)  # type: ignore[arg-type]

    def residuals(x: FloatArray) -> FloatArray:
        got = evaluate(shape, design(x))
        return np.array([(got[t] - hold[t]) / abs(hold[t]) for t in targets])

    x0 = np.array(
        [
            math.log(base.gore_length) if name == "gore_length" else base.variable(name)
            for name in free
        ]
    )
    bounds = [_bounds(shape, name, base.gore_length) for name in free]
    iterations = 0
    message = "all values held; nothing to solve"
    x = x0
    if len(free) == 1:
        lo, hi = bounds[0]
        f_lo, f_hi = residuals(np.array([lo]))[0], residuals(np.array([hi]))[0]
        if f_lo * f_hi > 0.0:
            target = targets[0]
            a = evaluate(shape, design(np.array([lo])))[target]
            b = evaluate(shape, design(np.array([hi])))[target]
            message = (
                f"{QUANTITIES[target].label} can only be {min(a, b):.6g} to {max(a, b):.6g} "
                f"by changing the {QUANTITIES[free[0]].name.replace('_', ' ')}; "
                f"target {hold[target]:.6g}"
            )
        else:
            root, info = brentq(
                lambda v: residuals(np.array([v]))[0], lo, hi, xtol=1e-12, full_output=True
            )
            x = np.array([root])
            iterations = int(info.iterations)
            message = f"Brent's method: {info.flag}"
    elif len(free) > 1:
        lower = np.array([b[0] for b in bounds])
        upper = np.array([b[1] for b in bounds])
        fit = least_squares(
            residuals,
            np.clip(x0, lower + 1e-9, upper - 1e-9),
            bounds=(lower, upper),
            xtol=1e-12,
            ftol=1e-12,
            gtol=1e-12,
        )
        x = fit.x
        iterations = int(fit.nfev)
        message = f"least squares: {fit.message}"
    params = design(x)
    values = evaluate(shape, params)
    errors = {name: values[name] - float(hold[name]) for name in hold}
    converged = all(_within(name, errors[name], float(hold[name])) for name in hold)
    if params.mouth_station >= params.top_station:
        converged = False
        message += "; the mouth ended above the top opening"
    return ShapeSolution(
        parameters=params,
        values=values,
        hold={name: float(v) for name, v in hold.items()},
        free=free,
        converged=converged,
        errors=errors,
        iterations=iterations,
        message=message,
        run_time=time.perf_counter() - begin,
    )


def shape_design(
    name: str,
    shape: NormalizedShape,
    solution: ShapeSolution,
    row_count: int,
    fabric_id: str = "ripstop_nylon",
    internal_temperature: float = 373.15,
    ambient_temperature: float = 288.15,
    ambient_pressure: float = 101325.0,
    payload_mass: float = 0.0,
) -> DesignDocument:
    r"""Standard-gore design document of a solved shape-family design.

    The control points are those of :func:`design_profile` (so the editor shows the same
    volume, height and diameters), the panel rows split the tape length equally, and the
    parachute seal overlap is the tape distance from the ``parachute_overlap`` station to
    the top opening when the shape names one (else the template default).

    Parameters
    ----------
    name : str
        Design name.
    shape : NormalizedShape
        Shape family.
    solution : ShapeSolution
        A converged solution of :func:`solve_shape`.
    row_count : int
        Horizontal panel rows (>= 1).
    fabric_id : str
        Fabric of the ``body`` zone.
    internal_temperature, ambient_temperature : float
        K.
    ambient_pressure : float
        Pa.
    payload_mass : float
        kg.

    Returns
    -------
    DesignDocument
        With its content hash.

    Raises
    ------
    ValueError
        When the solution did not converge (an unconverged design is never produced).
    """
    from envelopelab.project.gore_design import equal_row_heights
    from envelopelab.project.templates import new_design

    if not solution.converged:
        raise ValueError(f"the shape did not solve, so no design was made: {solution.message}")
    params = solution.parameters
    r, z = shape.control_points(params.mouth_station, params.top_station)
    length = params.gore_length
    values = solution.values
    overlap = None
    named = shape.stations.get("parachute_overlap")
    if named is not None and params.mouth_station < named < params.top_station:
        overlap = (params.top_station - named) * length
        if overlap >= values["top_diameter"] / 2.0:
            overlap = None
    return new_design(
        name=name,
        points=list(zip((r * length).tolist(), (z * length).tolist(), strict=True)),
        gore_count=params.gore_count,
        row_heights=equal_row_heights(values["tape_length"], row_count),
        mouth_diameter=values["mouth_diameter"],
        top_diameter=values["top_diameter"],
        fabric_id=fabric_id,
        seam_allowance=params.seam_allowance,
        internal_temperature=internal_temperature,
        ambient_temperature=ambient_temperature,
        ambient_pressure=ambient_pressure,
        payload_mass=payload_mass,
        seal_overlap=overlap,
    )


__all__ = [
    "HELD_COUNT",
    "PROFILE_SAMPLES",
    "QUANTITIES",
    "VARIABLES",
    "NormalizedShape",
    "Quantity",
    "ShapeParameters",
    "ShapeSolution",
    "StationPoint",
    "check_hold",
    "design_profile",
    "evaluate",
    "shape_design",
    "solve_shape",
    "station_points",
]
