"""Rigging benchmarks: parachute, shroud lines, flying wires and turning vents vs hand values.

The same functions back ``tests/benchmarks/test_rigging_benchmarks.py`` and the generated page
``docs/validation/rigging-benchmarks.md`` (``scripts/generate_validation_docs.py``).
Only analytic shapes are used (a spherical zone and a cylinder); every reference value is
a closed-form expression written out below.
"""

from __future__ import annotations

import math

import numpy as np

from envelopelab.atmosphere import G0, celsius_to_kelvin, gas_density, pressure_gradient
from envelopelab.geometry.gore import MeridianProfile
from envelopelab.rigging.flying_wires import wire_geometry, wire_tensions
from envelopelab.rigging.parachute import crown_force, opening, seated_geometry, shroud_tension
from envelopelab.rigging.turning_vents import vent_jet
from envelopelab.validation.analytic_geometry import (
    BenchmarkResult,
    _fmt,
    _fmt_error,
    _fmt_tolerance,
)

# Load case of the hand calculations: sea level, 15 degC ambient, 100 degC internal.
T_AMB = celsius_to_kelvin(15.0)
T_INT = celsius_to_kelvin(100.0)
P_AMB = 101325.0
LOAD_FACTOR = 1.4


def _sphere_zone(radius: float, lower: float, upper: float) -> MeridianProfile:
    theta = np.linspace(lower, upper, 4001)
    return MeridianProfile.from_points(radius * np.cos(theta), radius * np.sin(theta))


def _parachute_benchmarks() -> list[BenchmarkResult]:
    radius, lower, upper = 8.0, -math.pi / 3.0, math.radians(75.0)
    overlap, attach, depth, billow, n = 0.5, 3.0, 3.0, 0.1, 12
    prof = _sphere_zone(radius, lower, upper)
    geom = seated_geometry(prof, overlap, billow, attach, depth)
    z0 = radius * math.sin(lower)
    theta_e = upper - overlap / radius
    theta_a = theta_e - attach / radius
    r_h, z_t = radius * math.cos(upper), radius * math.sin(upper) - z0
    r_e, z_e = radius * math.cos(theta_e), radius * math.sin(theta_e) - z0
    z_a = radius * math.sin(theta_a) - z0
    h = billow * 2.0 * r_h
    shroud = 2.0 * radius * math.sin(attach / (2.0 * radius))
    central = math.hypot(r_e, z_e - (z_t - depth))
    area = 2.0 * math.pi * radius * (z_t - z_e) + math.pi * (r_h**2 + h**2)
    grad = pressure_gradient(gas_density(P_AMB, T_AMB), gas_density(P_AMB, T_INT))
    force_hand = grad * (z_t + h) * math.pi * r_h**2
    tension_hand = LOAD_FACTOR * force_hand / (n * (z_e - z_a) / shroud)
    force = crown_force(geom, grad, float(prof.height_at(0.0)))
    tension = shroud_tension(geom, LOAD_FACTOR * force, n)
    op = opening(geom, prof, overlap)
    out = [
        BenchmarkResult(
            "Parachute edge radius (sphere R=8 m)", geom.edge_radius, r_e, "m", "absolute", 1e-3
        ),
        BenchmarkResult(
            "Shroud line length = chord 2R sin(a/2R)",
            geom.shroud_length,
            shroud,
            "m",
            "absolute",
            1e-3,
        ),
        BenchmarkResult(
            "Centralising line length", geom.centralizing_length, central, "m", "absolute", 1e-3
        ),
        BenchmarkResult(
            "Parachute fabric area (zone + cap)", geom.area, area, "m^2", "relative", 1e-3
        ),
        BenchmarkResult(
            "Crown force dp(z_t + h) pi r_h^2", force, force_hand, "N", "relative", 1e-3
        ),
        BenchmarkResult(
            "Shroud limit tension 1.4 F / (n sin a)", tension, tension_hand, "N", "relative", 1e-3
        ),
    ]
    if op.seal_open_travel is None or op.full_open_travel is None:
        raise RuntimeError("benchmark parachute does not open; the fixture is inconsistent")
    # Kinematic closure at full opening: both lines keep their lengths.
    k = int(np.argmin(np.abs(op.path_travel - op.full_open_travel)))
    r, z = op.path_edge_radius[k], op.path_edge_height[k]
    z_c = geom.confluence_height - op.path_travel[k]
    out += [
        BenchmarkResult(
            "Opening path: shroud length kept",
            math.hypot(r - geom.attachment_radius, z - geom.attachment_height),
            geom.shroud_length,
            "m",
            "absolute",
            1e-3,
        ),
        BenchmarkResult(
            "Opening path: centralising length kept",
            math.hypot(r, z - z_c),
            geom.centralizing_length,
            "m",
            "absolute",
            1e-3,
        ),
    ]
    return out


def _wire_benchmarks() -> list[BenchmarkResult]:
    mass, r_m, r_f, drop = 400.0, 2.5, 0.8, 3.0
    geom = wire_geometry(4, r_m, 0.0, 4, 4, r_f, drop, 90.0, 0.0)
    wires, _ = wire_tensions(geom, LOAD_FACTOR * mass * G0.value)
    theta = math.atan2(r_m - r_f, drop)
    t_hand = LOAD_FACTOR * mass * G0.value / (4.0 * math.cos(theta))
    crow = wire_geometry(12, r_m, 0.0, 4, 4, r_f, drop, 45.0, 0.4)
    r_c = r_m * math.sin(math.pi * 3 / 12) / (3 * math.sin(math.pi / 12))
    _, legs = wire_tensions(crow, LOAD_FACTOR * mass * G0.value)
    # Vertical components of one crow's foot's legs add up to its wire's share.
    vertical = float(np.sum(legs[:3] * np.cos(crow.leg_angles[:3])))
    return [
        BenchmarkResult(
            "Flying wire length (4 wires, direct)",
            float(geom.wire_lengths[0]),
            math.hypot(r_m - r_f, drop),
            "m",
            "absolute",
            1e-3,
        ),
        BenchmarkResult(
            "Flying wire limit tension 1.4 W / (4 cos t)",
            float(wires.max()),
            t_hand,
            "N",
            "relative",
            1e-3,
        ),
        BenchmarkResult(
            "Crow's-foot carabiner radius (3 tapes)",
            float(np.hypot(*crow.carabiners[0][:2])),
            r_c,
            "m",
            "absolute",
            1e-3,
        ),
        BenchmarkResult(
            "Crow's-foot vertical balance",
            vertical,
            LOAD_FACTOR * mass * G0.value / 4.0,
            "N",
            "relative",
            1e-3,
        ),
    ]


def _vent_benchmarks() -> list[BenchmarkResult]:
    radius, z0, z1, width, cd = 3.0, 2.0, 5.0, 0.2, 0.61
    cyl = MeridianProfile.from_control_points([radius, radius], [0.0, 10.0], samples=11)
    rho_a, rho_i = gas_density(P_AMB, T_AMB), gas_density(P_AMB, T_INT)
    grad = pressure_gradient(rho_a, rho_i)
    jet = vent_jet(cyl, z0, z1, width, cd, rho_a, rho_i, T_AMB, T_INT, True)
    thrust = cd * width * grad * (z1**2 - z0**2)
    flow = cd * width * math.sqrt(2.0 * rho_i * grad) * 2.0 / 3.0 * (z1**1.5 - z0**1.5)
    return [
        BenchmarkResult(
            "Turning vent thrust (cylinder, linear dp)", jet.thrust, thrust, "N", "relative", 1e-3
        ),
        BenchmarkResult(
            "Turning vent torque R F", jet.torque, radius * thrust, "N m", "relative", 1e-3
        ),
        BenchmarkResult("Turning vent mass flow", jet.mass_flow, flow, "kg/s", "relative", 1e-3),
    ]


def run_benchmarks() -> list[BenchmarkResult]:
    """Run every rigging benchmark (display order)."""
    return _parachute_benchmarks() + _wire_benchmarks() + _vent_benchmarks()


def render_markdown(results: list[BenchmarkResult]) -> str:
    """Render the rigging benchmark page (Markdown)."""
    lines = [
        "# Rigging benchmarks",
        "",
        "_Auto-generated by `python scripts/generate_validation_docs.py` from "
        "`envelopelab.validation.rigging`. Do not edit by hand; "
        "`tests/benchmarks/test_rigging_benchmarks.py` fails if this page is stale._",
        "",
        "Load case: sea level (101 325 Pa), 15 degC ambient, 100 degC internal, limit load",
        "factor 1.4. Parachute rows use a spherical zone R = 8 m from -60 deg to +75 deg",
        "latitude, seal overlap 0.5 m, shroud attachment 3 m, confluence 3 m below the rim,",
        "billow 0.1 and 12 shroud lines. Flying-wire rows use a 2.5 m mouth radius, a",
        "0.8 m frame radius 3 m below the mouth and a 400 kg payload. The turning-vent rows",
        "use a 0.2 m wide slot from 2 m to 5 m above the mouth of a 3 m radius cylinder,",
        "C_d = 0.61. Relative errors are fractions; absolute errors are in the unit shown.",
        "",
        "| Benchmark | Computed | Reference | Unit | Error | Tolerance | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in results:
        value = _fmt(result.value) if result.kind == "relative" else "-"
        reference = _fmt(result.reference) if result.kind == "relative" else "-"
        status = "pass" if result.passed else "**FAIL**"
        lines.append(
            f"| {result.name} | {value} | {reference} | {result.unit} | "
            f"{_fmt_error(result)} | {_fmt_tolerance(result)} | {status} |"
        )
    lines += [
        "",
        "The opening-path rows check that the red-line kinematics keep both line lengths at",
        "the full-open travel (taut, inextensible lines).",
        "",
    ]
    return "\n".join(lines)
