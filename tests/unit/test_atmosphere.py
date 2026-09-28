"""Unit tests for envelopelab.atmosphere.

Hand calculation (also in the module docstring): 15 degC ambient, 100 degC internal,
p = 101 325 Pa, R = 287.05287 J/(kg K), g = 9.80665 m/s^2:
rho_amb = 1.2250 kg/m^3, rho_int = 0.9460 kg/m^3, gradient 2.736 Pa/m,
lift of 2 610 m^3 = 7142 N.
"""

from __future__ import annotations

import math

import pytest

from envelopelab.atmosphere import (
    G0,
    R_DRY_AIR,
    celsius_to_kelvin,
    differential_pressure,
    gas_density,
    geometric_to_geopotential,
    gross_lift,
    isa,
    pressure_gradient,
    saturation_vapour_pressure,
)

AMBIENT = gas_density(101325.0, celsius_to_kelvin(15.0))
INTERNAL = gas_density(101325.0, celsius_to_kelvin(100.0))


def test_isa_sea_level() -> None:
    state = isa(0.0)
    assert state.temperature == pytest.approx(288.15)
    assert state.pressure == pytest.approx(101325.0)
    assert state.density == pytest.approx(1.225, rel=1e-4)


@pytest.mark.parametrize(
    ("altitude", "temperature", "pressure", "density"),
    [
        (1000.0, 281.65, 89874.6, 1.11164),
        (5000.0, 255.65, 54019.9, 0.736116),
        (11000.0, 216.65, 22632.1, 0.363918),
        (15000.0, 216.65, 12044.6, 0.193674),
        (20000.0, 216.65, 5474.89, 0.0880349),
        (32000.0, 228.65, 868.019, 0.0132250),
    ],
)
def test_isa_matches_iso_2533_table(
    altitude: float, temperature: float, pressure: float, density: float
) -> None:
    state = isa(altitude)
    assert state.temperature == pytest.approx(temperature, abs=1e-9)
    # Table values follow the U.S. 1976 printing, whose air gas constant (from R* and M0)
    # differs from ISO 2533's 287.05287 J/(kg K) by ~3e-6 relative.
    assert state.pressure == pytest.approx(pressure, rel=1e-5)
    assert state.density == pytest.approx(density, rel=2e-5)


def test_isa_below_sea_level_and_range() -> None:
    assert isa(-500.0).pressure > 101325.0
    with pytest.raises(ValueError):
        isa(40000.0)


def test_isa_temperature_offset_keeps_pressure() -> None:
    hot = isa(1000.0, temperature_offset=10.0)
    assert hot.pressure == pytest.approx(isa(1000.0).pressure)
    assert hot.temperature == pytest.approx(291.65)
    assert hot.density < isa(1000.0).density


def test_geopotential_conversion() -> None:
    assert geometric_to_geopotential(0.0) == 0.0
    assert geometric_to_geopotential(11000.0) == pytest.approx(10981.0, abs=1.0)


def test_hand_calculation_densities() -> None:
    assert AMBIENT == pytest.approx(1.2250, abs=1e-4)
    assert INTERNAL == pytest.approx(0.9460, abs=1e-4)


def test_hand_calculation_pressure_gradient() -> None:
    assert pressure_gradient(AMBIENT, INTERNAL) == pytest.approx(2.74, rel=5e-3)
    assert differential_pressure(10.0, 0.0, AMBIENT, INTERNAL) == pytest.approx(27.36, rel=1e-3)
    assert differential_pressure(0.0, 0.0, AMBIENT, INTERNAL) == 0.0


def test_hand_calculation_lift() -> None:
    assert gross_lift(2610.0, AMBIENT, INTERNAL) == pytest.approx(7142.0, rel=1e-2)
    # And against the fully written-out formula.
    expected = 2610.0 * 101325.0 / R_DRY_AIR.value * (1 / 288.15 - 1 / 373.15) * G0.value
    assert gross_lift(2610.0, AMBIENT, INTERNAL) == pytest.approx(expected, rel=1e-12)


def test_humidity_correction_off_by_default_and_reduces_density() -> None:
    temperature = celsius_to_kelvin(30.0)
    dry = gas_density(101325.0, temperature)
    assert gas_density(101325.0, temperature, relative_humidity=0.0) == dry
    humid = gas_density(101325.0, temperature, relative_humidity=1.0)
    # Saturated air at 30 degC is about 1.0-1.5 % lighter than dry air.
    assert 0.98 < humid / dry < 0.995


def test_saturation_vapour_pressure_reference_values() -> None:
    # Buck (1981) reproduces the WMO tables: 611.2 Pa at 0 degC, ~2339 Pa at 20 degC.
    assert saturation_vapour_pressure(273.15) == pytest.approx(611.21)
    assert saturation_vapour_pressure(293.15) == pytest.approx(2339.0, rel=2e-3)


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        gas_density(101325.0, 0.0)
    with pytest.raises(ValueError):
        gas_density(101325.0, 300.0, relative_humidity=1.5)
    with pytest.raises(ValueError):
        gross_lift(-1.0, 1.2, 1.0)
    assert math.isclose(gross_lift(0.0, 1.2, 1.0), 0.0)
