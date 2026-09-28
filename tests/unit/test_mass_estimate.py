from __future__ import annotations

import math

import pytest

from envelopelab.atmosphere import G0, celsius_to_kelvin, gas_density
from envelopelab.geometry.gore import (
    GoreWidthModel,
    MeridianProfile,
    PanelRow,
    SeamAllowance,
    split_rows,
)
from envelopelab.mass_estimate import TapeMasses, ThreadSpec, estimate_mass, lift_margin
from envelopelab.materials.repository import MaterialProperty


def prop(value: float) -> MaterialProperty:
    return MaterialProperty(value, "assumed")


def cylinder_rows() -> list[PanelRow]:
    profile = MeridianProfile.from_points([2.0, 2.0], [0.0, 4.0])
    return split_rows(
        profile,
        GoreWidthModel(10),
        [1.0, 1.0, 2.0],
        allowance=SeamAllowance(side=0.01, bottom=0.02, top=0.02),
    )


def test_mass_estimate_hand_values() -> None:
    rows = cylinder_rows()
    width = 2 * math.pi * 2.0 / 10
    estimate = estimate_mass(
        rows,
        10,
        ["low", "low", "high"],
        {"low": prop(0.06), "high": prop(0.05)},
        TapeMasses(prop(0.010), prop(0.008), prop(0.020), prop(0.015)),
        ThreadSpec(prop(3e-5), prop(2.75), vertical_rows=2, horizontal_rows=1),
    )
    low = estimate.zones["low"]
    assert low.finished_area == pytest.approx(10 * width * 2.0)
    assert low.cut_area == pytest.approx(10 * 2 * (width + 0.02) * 1.04)
    assert low.allowance_area == pytest.approx(low.cut_area - low.finished_area)
    assert low.mass == pytest.approx(low.cut_area * 0.06)
    assert estimate.vertical_seam_length == pytest.approx(10 * 4.0)
    assert estimate.horizontal_seam_length == pytest.approx(2 * 10 * width)
    assert estimate.tape_lengths["rim"] == pytest.approx(2 * math.pi * 2.0)
    assert estimate.tape_masses["vertical"] == pytest.approx(40.0 * 0.010)
    expected_thread = 2.75 * (2 * 40.0 + 1 * 2 * 10 * width)
    assert estimate.thread_length == pytest.approx(expected_thread)
    assert estimate.thread_mass == pytest.approx(expected_thread * 3e-5)
    assert estimate.total_mass == pytest.approx(
        estimate.fabric_mass + sum(estimate.tape_masses.values()) + estimate.thread_mass
    )
    assert estimate.sources == ("assumed",)


def test_mass_estimate_rejects_unknown_zone() -> None:
    rows = cylinder_rows()
    with pytest.raises(ValueError, match="zone"):
        estimate_mass(
            rows,
            10,
            ["a", "a", "b"],
            {"a": prop(0.06)},
            TapeMasses(prop(0.01), prop(0.01), prop(0.01), prop(0.01)),
            ThreadSpec(prop(3e-5), prop(2.75), 2, 1),
        )


def test_lift_margin_hand_calculation() -> None:
    ambient = gas_density(101325.0, celsius_to_kelvin(15.0))
    internal = gas_density(101325.0, celsius_to_kelvin(100.0))
    margin = lift_margin(2610.0, ambient, internal, envelope_mass=90.0, payload_mass=500.0)
    assert margin.gross_lift == pytest.approx(7142.0, rel=1e-2)
    assert margin.lift_mass == pytest.approx(margin.gross_lift / G0.value)
    assert margin.margin == pytest.approx(728.3 - 590.0, abs=0.5)
    assert margin.ratio > 1.0
    with pytest.raises(ValueError):
        lift_margin(1.0, 1.2, 1.0, -1.0, 0.0)
