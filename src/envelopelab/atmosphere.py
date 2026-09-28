r"""International Standard Atmosphere, ideal-gas densities, lift and hydrostatic pressure.

All quantities are SI: altitude in m, temperature in K, pressure in Pa, density in kg/m^3,
volume in m^3, force in N.

Hand-calculation check (reproduced by ``tests/unit/test_atmosphere.py``)
-------------------------------------------------------------------------
Ambient 15 degC (288.15 K), internal 100 degC (373.15 K), both at sea-level pressure
p = 101 325 Pa, dry air R = 287.052 87 J/(kg K), g = 9.806 65 m/s^2:

* :math:`\rho_{amb} = 101325 / (287.05287 \cdot 288.15) = 1.2250\ \mathrm{kg/m^3}`
* :math:`\rho_{int} = 101325 / (287.05287 \cdot 373.15) = 0.9460\ \mathrm{kg/m^3}`
* :math:`\Delta\rho = 0.2790\ \mathrm{kg/m^3}`
* pressure gradient :math:`\Delta\rho\, g = 2.736\ \mathrm{Pa/m}` (≈ 2.74 Pa/m)
* gross lift of 2 610 m^3: :math:`2610 \cdot 0.2790 \cdot 9.80665 = 7142\ \mathrm{N}`
  (728.3 kgf)

References
----------
.. [ISA] ISO 2533:1975, *Standard Atmosphere*; identical to U.S. Standard Atmosphere 1976
   (NOAA/NASA/USAF) below 32 km geopotential altitude.
.. [Buck] A. L. Buck, "New equations for computing vapor pressure and enhancement factor",
   J. Appl. Meteorol. 20 (1981) 1527-1532.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

SourceTag = Literal["datasheet", "measured", "assumed"]


@dataclass(frozen=True)
class PhysicalConstant:
    """A physical constant with its unit and provenance.

    Attributes
    ----------
    value : float
        Numerical value in the SI unit given by ``unit``.
    unit : str
        SI unit string.
    source : {"datasheet", "measured", "assumed"}
        Provenance tag; standards documents are tagged ``datasheet``.
    reference : str
        Citation for the value.
    """

    value: float
    unit: str
    source: SourceTag
    reference: str


G0 = PhysicalConstant(9.80665, "m/s^2", "datasheet", "ISO 2533:1975 standard gravity")
R_DRY_AIR = PhysicalConstant(
    287.05287, "J/(kg K)", "datasheet", "ISO 2533:1975 specific gas constant of dry air"
)
R_WATER_VAPOUR = PhysicalConstant(
    461.495, "J/(kg K)", "datasheet", "CODATA R / M_H2O (18.01528 g/mol)"
)
P0 = PhysicalConstant(101325.0, "Pa", "datasheet", "ISO 2533:1975 sea-level pressure")
T0 = PhysicalConstant(288.15, "K", "datasheet", "ISO 2533:1975 sea-level temperature")
CELSIUS_OFFSET = 273.15

# (base geopotential altitude m, base temperature K, lapse rate K/m) per ISO 2533 layer.
_ISA_LAYERS: tuple[tuple[float, float, float], ...] = (
    (0.0, 288.15, -0.0065),
    (11000.0, 216.65, 0.0),
    (20000.0, 216.65, 0.001),
)
ISA_MAX_ALTITUDE = 32000.0
ISA_MIN_ALTITUDE = -5000.0
EARTH_RADIUS = PhysicalConstant(
    6356766.0, "m", "datasheet", "ISO 2533:1975 nominal Earth radius for geopotential"
)


@dataclass(frozen=True)
class AtmosphereState:
    """Thermodynamic state of the ambient air.

    Attributes
    ----------
    altitude : float
        Geopotential altitude, m.
    temperature : float
        Static temperature, K.
    pressure : float
        Static pressure, Pa.
    density : float
        Density, kg/m^3.
    """

    altitude: float
    temperature: float
    pressure: float
    density: float


def celsius_to_kelvin(temperature_c: float) -> float:
    """Convert a Celsius temperature (degC) to kelvin (K)."""
    return temperature_c + CELSIUS_OFFSET


def geometric_to_geopotential(altitude: float) -> float:
    r"""Convert geometric altitude to geopotential altitude.

    .. math:: H = \frac{r_0 z}{r_0 + z}

    Parameters
    ----------
    altitude : float
        Geometric altitude z, m.

    Returns
    -------
    float
        Geopotential altitude H, m.
    """
    r0 = EARTH_RADIUS.value
    return r0 * altitude / (r0 + altitude)


def isa(altitude: float, temperature_offset: float = 0.0) -> AtmosphereState:
    r"""ISA temperature, pressure and density at a geopotential altitude.

    Within each layer of constant lapse rate :math:`L`:

    .. math::
        T = T_b + L (h - h_b), \qquad
        p = p_b \left(\frac{T}{T_b}\right)^{-g_0/(L R)} \ (L \ne 0), \qquad
        p = p_b \exp\!\left(-\frac{g_0 (h - h_b)}{R T_b}\right) \ (L = 0)

    and :math:`\rho = p / (R T)`.

    Parameters
    ----------
    altitude : float
        Geopotential altitude, m. Valid range -5 000 m to 32 000 m.
    temperature_offset : float, optional
        ISA temperature deviation ΔT, K (e.g. ``+10`` for ISA+10). Following the aviation
        convention, pressure is the ISA pressure at ``altitude`` (pressure altitude) and only
        temperature and density change.

    Returns
    -------
    AtmosphereState
        Temperature (K), pressure (Pa) and density (kg/m^3).

    Raises
    ------
    ValueError
        If ``altitude`` is outside the valid range.

    Notes
    -----
    Assumptions: dry air, hydrostatic equilibrium, constant g0 (geopotential altitude).
    Reference: ISO 2533:1975.
    """
    if not ISA_MIN_ALTITUDE <= altitude <= ISA_MAX_ALTITUDE:
        raise ValueError(
            f"altitude {altitude} m outside ISA range [{ISA_MIN_ALTITUDE}, {ISA_MAX_ALTITUDE}] m"
        )
    g0 = G0.value
    r_air = R_DRY_AIR.value
    pressure_base = P0.value
    temperature = pressure = math.nan
    for index, (base, temperature_base, lapse) in enumerate(_ISA_LAYERS):
        is_last = index + 1 == len(_ISA_LAYERS)
        top = ISA_MAX_ALTITUDE if is_last else _ISA_LAYERS[index + 1][0]
        # Altitudes below sea level extend the first layer downward (negative height).
        height = (altitude if altitude <= top else top) - base
        temperature = temperature_base + lapse * height
        if lapse == 0.0:
            pressure = pressure_base * math.exp(-g0 * height / (r_air * temperature_base))
        else:
            pressure = pressure_base * (temperature / temperature_base) ** (-g0 / (lapse * r_air))
        if altitude <= top:
            break
        pressure_base = pressure
    temperature += temperature_offset
    return AtmosphereState(
        altitude=altitude,
        temperature=temperature,
        pressure=pressure,
        density=pressure / (r_air * temperature),
    )


def saturation_vapour_pressure(temperature: float) -> float:
    r"""Saturation vapour pressure of water over a liquid surface (Buck 1981).

    .. math:: e_s = 611.21 \exp\!\left[\left(18.678 - \frac{t}{234.5}\right)
              \frac{t}{257.14 + t}\right], \quad t \text{ in degC}

    Parameters
    ----------
    temperature : float
        Temperature, K. Valid range about 233 K to 373 K (-40 degC to 100 degC).

    Returns
    -------
    float
        Saturation vapour pressure, Pa.
    """
    t_c = temperature - CELSIUS_OFFSET
    return 611.21 * math.exp((18.678 - t_c / 234.5) * (t_c / (257.14 + t_c)))


def gas_density(pressure: float, temperature: float, relative_humidity: float = 0.0) -> float:
    r"""Ideal-gas density of (optionally humid) air.

    Dry air (default):

    .. math:: \rho = \frac{p}{R_d T}

    Humid air, with vapour partial pressure :math:`e = \phi\, e_s(T)`:

    .. math:: \rho = \frac{p - e}{R_d T} + \frac{e}{R_v T}

    Parameters
    ----------
    pressure : float
        Total static pressure, Pa.
    temperature : float
        Temperature, K.
    relative_humidity : float, optional
        Relative humidity φ as a fraction in [0, 1], dimensionless. Default 0 (dry air), which
        is the conservative choice for lift of the *ambient* air; humid air is lighter, so
        humidity reduces the ambient density and therefore lift.

    Returns
    -------
    float
        Density, kg/m^3.

    Notes
    -----
    Assumptions: ideal-gas mixture; the enhancement factor (~1.004) is neglected; the
    humidity correction is off by default. Inside the envelope combustion products (CO2,
    H2O) change the gas constant slightly; that is not modelled here. Valid range: 200 K to
    400 K, 1 kPa to 110 kPa. References: ISO 2533:1975; Buck (1981).
    """
    if temperature <= 0.0:
        raise ValueError("temperature must be positive (K)")
    if not 0.0 <= relative_humidity <= 1.0:
        raise ValueError("relative_humidity must be within [0, 1]")
    vapour = (
        relative_humidity * saturation_vapour_pressure(temperature) if relative_humidity else 0.0
    )
    if vapour >= pressure:
        raise ValueError("vapour pressure exceeds total pressure")
    return (pressure - vapour) / (R_DRY_AIR.value * temperature) + vapour / (
        R_WATER_VAPOUR.value * temperature
    )


def gross_lift(
    volume: float, ambient_density: float, internal_density: float, gravity: float = G0.value
) -> float:
    r"""Gross aerostatic lift (buoyancy minus weight of the internal gas).

    .. math:: L = V (\rho_{amb} - \rho_{int})\, g

    Parameters
    ----------
    volume : float
        Envelope gas volume V, m^3.
    ambient_density : float
        Ambient air density, kg/m^3.
    internal_density : float
        Internal gas density, kg/m^3.
    gravity : float, optional
        Gravitational acceleration, m/s^2. Default standard gravity.

    Returns
    -------
    float
        Gross lift, N. Negative when the internal gas is heavier than ambient.

    Notes
    -----
    Assumptions: uniform internal and ambient density over the envelope height (the
    density change over ~30 m is < 0.4 %). Reference: Archimedes' principle; see
    docs/theory/atmosphere.md.
    """
    if volume < 0.0:
        raise ValueError("volume must be non-negative")
    return volume * (ambient_density - internal_density) * gravity


def pressure_gradient(
    ambient_density: float, internal_density: float, gravity: float = G0.value
) -> float:
    r"""Vertical gradient of internal-minus-ambient pressure.

    .. math:: \frac{d\,\Delta p}{dh} = (\rho_{amb} - \rho_{int})\, g

    Parameters
    ----------
    ambient_density, internal_density : float
        Densities, kg/m^3.
    gravity : float, optional
        Gravitational acceleration, m/s^2.

    Returns
    -------
    float
        Pressure gradient, Pa/m.
    """
    return (ambient_density - internal_density) * gravity


def differential_pressure(
    height: float,
    mouth_height: float,
    ambient_density: float,
    internal_density: float,
    gravity: float = G0.value,
) -> float:
    r"""Hydrostatic internal-minus-ambient pressure at a height in an open envelope.

    The mouth is open, so :math:`\Delta p = 0` there; above it both columns are hydrostatic:

    .. math:: \Delta p(h) = (\rho_{amb} - \rho_{int})\, g\, (h - h_{mouth})

    Parameters
    ----------
    height : float
        Height of the point of interest, m.
    mouth_height : float
        Height of the mouth (zero-pressure level), m.
    ambient_density, internal_density : float
        Densities, kg/m^3.
    gravity : float, optional
        Gravitational acceleration, m/s^2.

    Returns
    -------
    float
        Differential pressure acting outward on the fabric, Pa.

    Notes
    -----
    Assumptions: static gas, uniform densities, no dynamic (wind, burner) pressure. Valid for
    envelope heights up to ~100 m. Reference: hydrostatics, e.g. F. M. White, *Fluid
    Mechanics*, ch. 2.
    """
    return pressure_gradient(ambient_density, internal_density, gravity) * (height - mouth_height)
