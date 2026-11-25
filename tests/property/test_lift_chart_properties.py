"""Invariants of the lift-chart equilibrium."""

from __future__ import annotations

import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from envelopelab.atmosphere import PhysicalConstant
from envelopelab.lift_chart import (
    LiftChartInputs,
    equilibrium_load,
    equilibrium_top_temperature,
)

LIMIT = PhysicalConstant(393.15, "K", "assumed", "test")

volumes = st.floats(50.0, 20000.0)
masses = st.floats(0.0, 1000.0)
altitudes = st.floats(-500.0, 6000.0)
ambients = st.floats(243.15, 318.15)
offsets = st.floats(0.0, 30.0)


@settings(max_examples=200, deadline=None)
@given(volumes, masses, altitudes, ambients, offsets, st.floats(10.0, 120.0))
def test_load_and_top_temperature_round_trip(
    volume: float, fixed: float, altitude: float, ambient: float, offset: float, rise: float
) -> None:
    inputs = LiftChartInputs(
        volume, "p", fixed, (), LIMIT, PhysicalConstant(offset, "K", "assumed", "")
    )
    top = ambient + offset + rise
    load = equilibrium_load(inputs, altitude, ambient, top).load
    if load < 0.0:
        return
    back = equilibrium_top_temperature(inputs, altitude, ambient, load)
    assert math.isclose(back.top_temperature, top, rel_tol=1e-9, abs_tol=1e-6)


@settings(max_examples=200, deadline=None)
@given(volumes, masses, altitudes, ambients, st.floats(330.0, 400.0), st.floats(1.0, 20.0))
def test_hotter_crown_lifts_more_and_higher_lifts_less(
    volume: float, fixed: float, altitude: float, ambient: float, top: float, dt: float
) -> None:
    inputs = LiftChartInputs(volume, "p", fixed, (), LIMIT)
    assume(top - inputs.top_to_mean.value > ambient + 0.5)  # the gas is lighter than air
    base = equilibrium_load(inputs, altitude, ambient, top).load
    assert equilibrium_load(inputs, altitude, ambient, top + dt).load > base
    # Same local ambient temperature, lower pressure: less lift.
    assert equilibrium_load(inputs, altitude + 500.0, ambient, top).load < base
