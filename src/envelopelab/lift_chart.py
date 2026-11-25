r"""Lift charts: equilibrium of a hot-air balloon over top temperature, ambient
temperature, altitude and load.

A balloon floats in equilibrium when its gross lift carries exactly its own mass and its
load:

.. math::
    V \left(\rho_{amb} - \rho_{int}\right) = m_{fixed} + m_{load},
    \qquad
    \rho_{amb} = \frac{p}{R_d T_{amb}},\quad \rho_{int} = \frac{p}{R_d T_{mean}}

with :math:`V` the envelope volume (m^3), :math:`p` the ambient static pressure at the
(pressure) altitude (Pa, ISA, :func:`envelopelab.atmosphere.isa`), :math:`T_{amb}` the
ambient air temperature *at that altitude* (K), :math:`T_{mean}` the volume-mean gas
temperature inside the envelope (K), :math:`m_{fixed}` the envelope and rigging mass and
:math:`m_{load}` everything else (basket, burners, fuel, occupants), kg.

The left-hand side is the gross lift as a mass, :func:`lift_mass`: everything the
balloon can carry, its own envelope and rigging included.

Pilots read the **top (crown) temperature**, and the fabric limit applies there; the gas
below the crown is cooler, and the lift depends on the volume-mean temperature. The mean
temperature is either a fixed offset below the top (:data:`DEFAULT_TOP_TO_MEAN`,
tagged ``assumed`` unless replaced by a measured value), or follows from the envelope's
shape and an assumed linear temperature profile (:mod:`envelopelab.stratification`,
``LiftChartInputs.stratification``), never less than that offset below the top
(:meth:`LiftChartInputs.mean_of`). A lift spreadsheet that enters
one uniform "envelope temperature" (e.g. the Balloon Builders Journal's) uses the mean
temperature: with exact constants it equals :func:`lift_mass`
(``envelopelab.validation.lift_chart``); reading the crown sensor into it overstates lift.

.. math:: T_{mean} = T_{top} - \Delta T_{top \to mean}
    \quad\text{or}\quad T_{mean} = \min(T_{eff}(T_{top}, T_{amb}),\ T_{top} - \Delta T_{min})

Any three of top temperature, ambient temperature, altitude and load fix the fourth:

* load at a top temperature (:func:`equilibrium_load`), closed form;
* top temperature for a load (:func:`equilibrium_top_temperature`), closed form:

  .. math::
      \frac{1}{T_{mean}} = \frac{1}{T_{amb}} - \frac{R_d\,(m_{fixed} + m_{load})}{p\,V},
      \qquad\text{no equilibrium when the right-hand side is} \le 0;

* equilibrium altitude (ceiling) for a load and top temperature in an ISA atmosphere
  shifted by :math:`\Delta T_{ISA}` (:func:`equilibrium_altitude`), found numerically
  (scan, then Brent's method) because lift need not fall monotonically with height on hot
  days (it grows with height while :math:`T_{amb} > 0.81\,T_{mean}` in the troposphere).

Assumptions
-----------
* Static equilibrium (no climb, descent or wind; no aerodynamic drag or added mass).
* Uniform ambient and internal densities over the envelope height (< 0.4 % over 30 m).
* Dry ideal-gas air inside and out (combustion products and humidity are not modelled:
  humid ambient air is lighter, so on a humid day the real lift is slightly lower).
* Internal pressure equal to ambient (open mouth; the hydrostatic overpressure, a few
  tens of Pa, changes density by < 0.05 %).
* A constant top-to-mean temperature offset; real stratification depends on burner
  pattern, envelope porosity and heat loss.
* The volume is a fixed input (the design's lofted volume unless a solved volume is
  given); the inflated shape changes little with temperature.

Valid range: altitude -5 000 m to 11 000 m (ISA troposphere and below), temperatures
200 K to 420 K.

References
----------
* ISO 2533:1975, *Standard Atmosphere*.
* FAA, *Balloon Flying Handbook*, FAA-H-8083-11 (aerostatics, and the flight-manual
  loading charts of maximum gross mass vs ambient temperature and altitude).
* Archimedes' principle; see ``docs/theory/lift-charts.md``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from scipy.optimize import brentq

from envelopelab.atmosphere import G0, R_DRY_AIR, PhysicalConstant, gas_density, isa
from envelopelab.stratification import StratificationModel

#: Crown (top) minus volume-mean gas temperature, K. A generic engineering assumption,
#: not a measured value: a larger offset predicts less lift and a hotter crown, so a
#: generous offset errs on the safe side. Replace it with a value measured on the envelope
#: (e.g. crown sensor vs. temperatures logged at several heights).
DEFAULT_TOP_TO_MEAN = PhysicalConstant(
    20.0,
    "K",
    "assumed",
    "generic crown-to-mean gas temperature difference; replace with a measured value",
)

#: Highest altitude the equilibrium-altitude search covers, m (top of the ISA troposphere).
MAX_SEARCH_ALTITUDE = 11000.0
#: Altitude step of the equilibrium-altitude scan before refinement, m.
_SCAN_STEP = 100.0

Status = Literal["ok", "above_limit", "no_equilibrium", "beyond_range"]
SolvedFor = Literal["load", "top_temperature", "altitude"]


@dataclass(frozen=True)
class LiftChartInputs:
    """What every equilibrium of one envelope shares.

    Attributes
    ----------
    volume : float
        Envelope gas volume, m^3.
    volume_note : str
        Where the volume comes from (e.g. "lofted design profile, not a solved shape").
    fixed_mass : float
        Envelope plus rigging mass, kg (the load is added to it).
    fixed_mass_sources : tuple of str
        Source tags of the values behind ``fixed_mass``.
    top_limit : PhysicalConstant
        Highest permitted top temperature, K, with its source (the fabrics' service
        temperature, or the project's own limit).
    top_to_mean : PhysicalConstant
        Top minus mean internal temperature, K, with its source: the offset itself
        without ``stratification``, its floor with it.
    stratification : StratificationModel, optional
        The envelope's level-1 stratification (:mod:`envelopelab.stratification`): the
        mean follows from the envelope's shape and an assumed temperature profile, never
        less than ``top_to_mean`` below the top. Its ``minimum_offset`` must be
        ``top_to_mean``. None: a fixed offset.
    fabric_limit : PhysicalConstant, optional
        Lowest service temperature of the design's fabrics, K, when ``top_limit`` was set
        separately (for the warning when the limit exceeds it).
    """

    volume: float
    volume_note: str
    fixed_mass: float
    fixed_mass_sources: tuple[str, ...]
    top_limit: PhysicalConstant
    top_to_mean: PhysicalConstant = DEFAULT_TOP_TO_MEAN
    stratification: StratificationModel | None = None
    fabric_limit: PhysicalConstant | None = None

    @property
    def limit_above_fabric(self) -> bool:
        """Whether the top-temperature limit exceeds the fabrics' service temperature
        (not conservative: every output says so)."""
        return self.fabric_limit is not None and self.top_limit.value > self.fabric_limit.value

    def mean_of(self, top_temperature: float, ambient_temperature: float) -> float:
        """Mean gas temperature for a crown temperature, K (ambient K matters only with
        stratification)."""
        if self.stratification is None:
            return mean_temperature(top_temperature, self.top_to_mean.value)
        return self.stratification.mean_from_top(top_temperature, ambient_temperature)

    def top_of(self, mean_temperature_k: float, ambient_temperature: float) -> float:
        """Crown temperature for a mean gas temperature, K (inverse of :meth:`mean_of`)."""
        if self.stratification is None:
            return mean_temperature_k + self.top_to_mean.value
        return self.stratification.top_from_mean(mean_temperature_k, ambient_temperature)

    def __post_init__(self) -> None:
        if not self.volume > 0.0:
            raise ValueError("volume must be positive (m^3)")
        if self.fixed_mass < 0.0:
            raise ValueError("fixed mass must be non-negative (kg)")
        if self.top_to_mean.value < 0.0:
            raise ValueError("top-to-mean temperature offset must be non-negative (K)")
        if self.top_limit.value <= 0.0:
            raise ValueError("top temperature limit must be positive (K)")
        if (
            self.stratification is not None
            and self.stratification.minimum_offset.value != self.top_to_mean.value
        ):
            raise ValueError("the stratification floor must be the top-to-mean offset")


@dataclass(frozen=True)
class EquilibriumPoint:
    """One equilibrium state (all four variables, whichever was solved for).

    Attributes
    ----------
    solved_for : {"load", "top_temperature", "altitude"}
        The unknown; the other three were given.
    altitude : float
        Pressure altitude, m (``nan`` when no equilibrium altitude was found).
    ambient_temperature : float
        Ambient air temperature at ``altitude``, K (``nan`` with ``altitude``).
    top_temperature : float
        Crown temperature, K (``nan`` when no top temperature gives equilibrium).
    mean_temperature : float
        Mean internal gas temperature, K (``nan`` with ``top_temperature``).
    load : float
        Load carried besides the envelope and rigging, kg. Negative when the envelope
        cannot lift its own mass at the given conditions.
    gross_lift : float
        Gross lift at equilibrium, N (``nan`` when there is none).
    status : {"ok", "above_limit", "no_equilibrium", "beyond_range"}
        ``above_limit``: the top temperature exceeds the limit (not a permitted state);
        ``no_equilibrium``: no top temperature, or no altitude above the start, balances
        the mass (or the load is negative); ``beyond_range``: the equilibrium altitude is
        above :data:`MAX_SEARCH_ALTITUDE`.
    isa_offset : float
        ISA temperature deviation of the atmosphere, K (``nan`` unless
        ``solved_for == "altitude"``).
    """

    solved_for: SolvedFor
    altitude: float
    ambient_temperature: float
    top_temperature: float
    mean_temperature: float
    load: float
    gross_lift: float
    status: Status
    isa_offset: float = math.nan


def mean_temperature(top_temperature: float, top_to_mean: float) -> float:
    r"""Mean internal gas temperature from the top temperature.

    .. math:: T_{mean} = T_{top} - \Delta T_{top \to mean}
    \quad\text{or}\quad T_{mean} = \min(T_{eff}(T_{top}, T_{amb}),\ T_{top} - \Delta T_{min})

    Parameters
    ----------
    top_temperature : float
        Crown temperature, K.
    top_to_mean : float
        Top minus mean temperature, K.

    Returns
    -------
    float
        Mean internal temperature, K.
    """
    return top_temperature - top_to_mean


def lift_mass(
    volume: float, altitude: float, ambient_temperature: float, internal_temperature: float
) -> float:
    r"""Gross lift expressed as liftable mass, :math:`V(\rho_{amb} - \rho_{int})`.

    Parameters
    ----------
    volume : float
        Envelope volume, m^3.
    altitude : float
        Pressure altitude, m (ISA pressure; -5 000 m to 32 000 m).
    ambient_temperature : float
        Ambient air temperature at ``altitude``, K.
    internal_temperature : float
        Mean internal gas temperature, K.

    Returns
    -------
    float
        Liftable mass, kg (negative when the gas is colder than ambient).
    """
    pressure = isa(altitude).pressure
    return volume * (
        gas_density(pressure, ambient_temperature) - gas_density(pressure, internal_temperature)
    )


def equilibrium_load(
    inputs: LiftChartInputs, altitude: float, ambient_temperature: float, top_temperature: float
) -> EquilibriumPoint:
    r"""Load the balloon floats with at a top temperature.

    .. math:: m_{load} = V\,(\rho_{amb} - \rho_{int}) - m_{fixed}

    Parameters
    ----------
    inputs : LiftChartInputs
        Volume (m^3), fixed mass (kg) and temperature offset and limit (K).
    altitude : float
        Pressure altitude, m.
    ambient_temperature : float
        Ambient temperature at ``altitude``, K.
    top_temperature : float
        Crown temperature, K.

    Returns
    -------
    EquilibriumPoint
        ``load`` in kg (negative: cannot lift the envelope, status ``no_equilibrium``);
        status ``above_limit`` when ``top_temperature`` exceeds the limit.
    """
    t_mean = inputs.mean_of(top_temperature, ambient_temperature)
    lift = lift_mass(inputs.volume, altitude, ambient_temperature, t_mean)
    load = lift - inputs.fixed_mass
    status: Status = "ok"
    if top_temperature > inputs.top_limit.value:
        status = "above_limit"
    elif load < 0.0:
        status = "no_equilibrium"
    return EquilibriumPoint(
        "load",
        altitude,
        ambient_temperature,
        top_temperature,
        t_mean,
        load,
        lift * G0.value,
        status,
    )


def equilibrium_top_temperature(
    inputs: LiftChartInputs, altitude: float, ambient_temperature: float, load: float
) -> EquilibriumPoint:
    r"""Top temperature that floats a load.

    .. math::
        T_{mean} = \left(\frac{1}{T_{amb}} - \frac{R_d (m_{fixed}+m_{load})}{p V}\right)^{-1},
        \qquad T_{top} = T_{mean} + \Delta T_{top \to mean}

    Parameters
    ----------
    inputs : LiftChartInputs
        Volume (m^3), fixed mass (kg) and temperature offset and limit (K).
    altitude : float
        Pressure altitude, m.
    ambient_temperature : float
        Ambient temperature at ``altitude``, K.
    load : float
        Load besides envelope and rigging, kg (non-negative).

    Returns
    -------
    EquilibriumPoint
        ``top_temperature`` in K; ``nan`` with status ``no_equilibrium`` when no finite
        temperature lifts the mass (the mass exceeds :math:`V\rho_{amb}`); status
        ``above_limit`` when the temperature needed exceeds the limit.
    """
    if load < 0.0:
        raise ValueError("load must be non-negative (kg)")
    pressure = isa(altitude).pressure
    total = inputs.fixed_mass + load
    inverse = 1.0 / ambient_temperature - R_DRY_AIR.value * total / (pressure * inputs.volume)
    if inverse <= 0.0:
        return EquilibriumPoint(
            "top_temperature",
            altitude,
            ambient_temperature,
            math.nan,
            math.nan,
            load,
            math.nan,
            "no_equilibrium",
        )
    t_mean = 1.0 / inverse
    top = inputs.top_of(t_mean, ambient_temperature)
    return EquilibriumPoint(
        "top_temperature",
        altitude,
        ambient_temperature,
        top,
        t_mean,
        load,
        total * G0.value,
        "above_limit" if top > inputs.top_limit.value else "ok",
    )


def equilibrium_altitude(
    inputs: LiftChartInputs,
    isa_offset: float,
    top_temperature: float,
    load: float,
    start_altitude: float = 0.0,
    max_altitude: float = MAX_SEARCH_ALTITUDE,
) -> EquilibriumPoint:
    r"""Altitude at which the balloon floats a load at a top temperature (its ceiling).

    The ambient temperature follows the ISA shifted by ``isa_offset``,
    :math:`T_{amb}(h) = T_{ISA}(h) + \Delta T_{ISA}`, and the equilibrium is the lowest
    altitude above ``start_altitude`` where the spare lift
    :math:`V(\rho_{amb}-\rho_{int}) - m_{fixed} - m_{load}` turns negative.

    Parameters
    ----------
    inputs : LiftChartInputs
        Volume (m^3), fixed mass (kg) and temperature offset and limit (K).
    isa_offset : float
        ISA temperature deviation, K.
    top_temperature : float
        Crown temperature, K.
    load : float
        Load besides envelope and rigging, kg.
    start_altitude : float, optional
        Altitude the balloon starts from (e.g. the launch field), m.
    max_altitude : float, optional
        Highest altitude searched, m.

    Returns
    -------
    EquilibriumPoint
        ``altitude`` in m. Status ``no_equilibrium`` (altitude ``nan``) when the balloon
        cannot lift the load at ``start_altitude``; ``beyond_range`` when it still has
        spare lift at ``max_altitude``; ``above_limit`` when ``top_temperature``
        exceeds the limit (the altitude is still given).
    """
    total = inputs.fixed_mass + load

    def spare(h: float) -> float:
        # With stratification the mean depends on the ambient temperature at h.
        t_amb = isa(h, isa_offset).temperature
        return lift_mass(inputs.volume, h, t_amb, inputs.mean_of(top_temperature, t_amb)) - total

    def point(h: float, status: Status) -> EquilibriumPoint:
        t_amb = isa(h if math.isfinite(h) else start_altitude, isa_offset).temperature
        t_mean = inputs.mean_of(top_temperature, t_amb)
        if not math.isfinite(h):
            t_amb = math.nan
        lift = total * G0.value if status != "no_equilibrium" else math.nan
        return EquilibriumPoint(
            "altitude", h, t_amb, top_temperature, t_mean, load, lift, status, isa_offset
        )

    limit_status: Status = "above_limit" if top_temperature > inputs.top_limit.value else "ok"
    if spare(start_altitude) < 0.0:
        return point(math.nan, "no_equilibrium")
    low = start_altitude
    while low < max_altitude:
        high = min(low + _SCAN_STEP, max_altitude)
        if spare(high) < 0.0:
            root = float(brentq(spare, low, high, xtol=1e-3, rtol=1e-12))
            return point(root, limit_status)
        low = high
    return point(math.nan, "beyond_range")


@dataclass(frozen=True)
class LiftChart:
    """Equilibrium points of one envelope over a grid of conditions.

    Attributes
    ----------
    inputs : LiftChartInputs
    loads_at_top : list of EquilibriumPoint
        :func:`equilibrium_load` for every (altitude, ambient, top temperature).
    tops_for_load : list of EquilibriumPoint
        :func:`equilibrium_top_temperature` for every (altitude, ambient, load).
    ceilings : list of EquilibriumPoint
        :func:`equilibrium_altitude` for every (ISA offset, load) at the top-temperature
        limit.
    """

    inputs: LiftChartInputs
    loads_at_top: list[EquilibriumPoint]
    tops_for_load: list[EquilibriumPoint]
    ceilings: list[EquilibriumPoint]

    def points(self) -> list[EquilibriumPoint]:
        """Every equilibrium point, in the order above."""
        return [*self.loads_at_top, *self.tops_for_load, *self.ceilings]


def lift_chart(
    inputs: LiftChartInputs,
    altitudes: Sequence[float],
    ambient_temperatures: Sequence[float],
    top_temperatures: Sequence[float],
    loads: Sequence[float],
    isa_offsets: Sequence[float] = (),
) -> LiftChart:
    """Equilibrium points over a grid of altitudes, temperatures and loads.

    Parameters
    ----------
    inputs : LiftChartInputs
        Volume (m^3), fixed mass (kg) and temperature offset and limit (K).
    altitudes : sequence of float
        Pressure altitudes, m.
    ambient_temperatures : sequence of float
        Ambient temperatures at those altitudes, K.
    top_temperatures : sequence of float
        Crown temperatures, K.
    loads : sequence of float
        Loads besides envelope and rigging, kg.
    isa_offsets : sequence of float, optional
        ISA deviations for the ceiling points, K (none by default).

    Returns
    -------
    LiftChart
        The points; none is dropped, failures carry their status.
    """
    return LiftChart(
        inputs,
        [
            equilibrium_load(inputs, h, t_a, t_top)
            for h in altitudes
            for t_a in ambient_temperatures
            for t_top in top_temperatures
        ],
        [
            equilibrium_top_temperature(inputs, h, t_a, m)
            for h in altitudes
            for t_a in ambient_temperatures
            for m in loads
        ],
        [
            equilibrium_altitude(inputs, dt, inputs.top_limit.value, m)
            for dt in isa_offsets
            for m in loads
        ],
    )


def nice_step(span: float, count: int = 8) -> float:
    """A 1-2-2.5-5 x 10^k step that divides ``span`` into about ``count`` parts.

    Parameters
    ----------
    span : float
        Range to divide, any unit (positive).
    count : int, optional
        Target number of parts.

    Returns
    -------
    float
        Step, same unit as ``span``.
    """
    if not span > 0.0:
        return 1.0
    raw = span / count
    base = 10.0 ** math.floor(math.log10(raw))
    for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
        if mult * base >= raw:
            return mult * base
    return 10.0 * base
