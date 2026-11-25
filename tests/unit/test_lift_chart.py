"""Lift-chart equilibrium: load, top temperature and ceiling (envelopelab.lift_chart)."""

from __future__ import annotations

import math

import pytest

from envelopelab.atmosphere import PhysicalConstant, gas_density, gross_lift, isa
from envelopelab.lift_chart import (
    DEFAULT_TOP_TO_MEAN,
    LiftChartInputs,
    equilibrium_altitude,
    equilibrium_load,
    equilibrium_top_temperature,
    lift_chart,
    mean_temperature,
    nice_step,
)

LIMIT = PhysicalConstant(393.15, "K", "assumed", "test")
INPUTS = LiftChartInputs(2610.0, "test", 200.0, ("assumed",), LIMIT)


def test_default_offset_is_tagged_assumed() -> None:
    assert DEFAULT_TOP_TO_MEAN.source == "assumed"
    assert DEFAULT_TOP_TO_MEAN.unit == "K"
    assert INPUTS.top_to_mean is DEFAULT_TOP_TO_MEAN


def test_mean_is_top_minus_offset() -> None:
    assert mean_temperature(393.15, 20.0) == pytest.approx(373.15)


def test_load_matches_documented_hand_calculation() -> None:
    # atmosphere.py hand check: 2 610 m^3 at 15/100 degC lifts 728.3 kgf.
    point = equilibrium_load(INPUTS, 0.0, 288.15, 393.15)
    assert point.status == "ok"
    assert point.mean_temperature == pytest.approx(373.15)
    assert point.load == pytest.approx(728.3 - 200.0, abs=0.1)
    rho_a, rho_i = gas_density(101325.0, 288.15), gas_density(101325.0, 373.15)
    assert point.gross_lift == pytest.approx(gross_lift(2610.0, rho_a, rho_i), rel=1e-12)


def test_top_temperature_inverts_load() -> None:
    load = equilibrium_load(INPUTS, 1500.0, 280.0, 380.0).load
    back = equilibrium_top_temperature(INPUTS, 1500.0, 280.0, load)
    assert back.top_temperature == pytest.approx(380.0, abs=1e-9)
    assert back.status == "ok"


def test_above_limit_is_flagged_not_hidden() -> None:
    hot = equilibrium_load(INPUTS, 0.0, 288.15, 403.15)
    assert hot.status == "above_limit" and hot.load > 0.0
    heavy = equilibrium_top_temperature(INPUTS, 0.0, 303.15, 900.0)
    assert heavy.status == "above_limit"
    assert heavy.top_temperature > LIMIT.value


def test_no_equilibrium_when_mass_exceeds_displaced_air() -> None:
    # V rho_amb ~ 3 197 kg at sea level, 15 degC: no temperature lifts 4 000 kg.
    point = equilibrium_top_temperature(INPUTS, 0.0, 288.15, 4000.0)
    assert point.status == "no_equilibrium"
    assert math.isnan(point.top_temperature) and math.isnan(point.gross_lift)


def test_negative_load_means_envelope_cannot_lift_itself() -> None:
    point = equilibrium_load(INPUTS, 0.0, 303.15, 313.15)  # mean 20 degC, below ambient
    assert point.load < 0.0 and point.status == "no_equilibrium"


def test_ceiling_balances_the_mass() -> None:
    point = equilibrium_altitude(INPUTS, 0.0, 393.15, 400.0)
    assert point.status == "ok"
    spare = equilibrium_load(INPUTS, point.altitude, isa(point.altitude).temperature, 393.15)
    assert spare.load == pytest.approx(400.0, abs=0.01)
    assert point.ambient_temperature == pytest.approx(isa(point.altitude).temperature)


def test_ceiling_statuses() -> None:
    assert equilibrium_altitude(INPUTS, 0.0, 393.15, 2000.0).status == "no_equilibrium"
    far = equilibrium_altitude(INPUTS, -20.0, 393.15, 0.0, max_altitude=2000.0)
    assert far.status == "beyond_range" and math.isnan(far.altitude)


def test_heavier_load_lower_ceiling() -> None:
    light = equilibrium_altitude(INPUTS, 0.0, 393.15, 300.0).altitude
    heavy = equilibrium_altitude(INPUTS, 0.0, 393.15, 450.0).altitude
    assert heavy < light


def test_grid_keeps_every_point() -> None:
    chart = lift_chart(
        INPUTS, (0.0, 1000.0), (273.15, 293.15), (373.15, 393.15), (0.0, 300.0, 5000.0), (0.0,)
    )
    assert len(chart.loads_at_top) == 2 * 2 * 2
    assert len(chart.tops_for_load) == 2 * 2 * 3
    assert len(chart.ceilings) == 3
    assert len(chart.points()) == 8 + 12 + 3
    assert any(p.status == "no_equilibrium" for p in chart.tops_for_load)


@pytest.mark.parametrize(
    "changes",
    [{"volume": 0.0}, {"fixed_mass": -1.0}],
)
def test_inputs_are_validated(changes: dict[str, float]) -> None:
    values = {"volume": 2610.0, "fixed_mass": 200.0} | changes
    with pytest.raises(ValueError):
        LiftChartInputs(values["volume"], "x", values["fixed_mass"], (), LIMIT)


def test_negative_offset_and_load_are_refused() -> None:
    with pytest.raises(ValueError):
        LiftChartInputs(1.0, "x", 0.0, (), LIMIT, PhysicalConstant(-1.0, "K", "assumed", ""))
    with pytest.raises(ValueError):
        equilibrium_top_temperature(INPUTS, 0.0, 288.15, -1.0)


@pytest.mark.parametrize(
    ("span", "step"),
    [(800.0, 100.0), (550.0, 100.0), (400.0, 50.0), (37.0, 5.0), (0.0, 1.0), (1.2, 0.2)],
)
def test_nice_step(span: float, step: float) -> None:
    assert nice_step(span) == pytest.approx(step)
