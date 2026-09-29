"""Analytic benchmarks for the atmosphere, gore and parachute geometry modules.

The same functions back ``tests/benchmarks/test_analytic_geometry.py`` and the generated
page ``docs/validation/analytic-geometry.md`` (``scripts/generate_validation_docs.py``), so
the published table is always the one the test suite checks.

Only analytic shapes (spheres, cylinders, spherical zones, flat circular parachutes) are
used here; reference designs live in ``tests/fixtures/``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from envelopelab.atmosphere import (
    celsius_to_kelvin,
    gas_density,
    gross_lift,
    isa,
    pressure_gradient,
)
from envelopelab.geometry.gore import (
    GoreWidthModel,
    MeridianProfile,
    profile_from_gore_widths,
    split_rows,
)
from envelopelab.geometry.parachute import parachute_pieces

ErrorKind = Literal["relative", "absolute"]

# Hand-calculation values, worked in the envelopelab.atmosphere module docstring.
HAND_PRESSURE_GRADIENT = 2.736  # Pa/m, 15 degC ambient, 100 degC internal, sea level
HAND_LIFT_2610 = 7142.0  # N, same conditions, V = 2 610 m^3
# ISO 2533:1975 table values.
ISO_2533_P_1000 = 89874.6  # Pa at 1 000 m
ISO_2533_RHO_1000 = 1.11164  # kg/m^3 at 1 000 m
ISO_2533_P_11000 = 22632.1  # Pa at 11 000 m
ISO_2533_P_20000 = 5474.89  # Pa at 20 000 m


@dataclass(frozen=True)
class BenchmarkResult:
    """One benchmark comparison.

    Attributes
    ----------
    name : str
        Description.
    value : float
        Computed value in ``unit``.
    reference : float
        Analytic or hand value in ``unit``.
    unit : str
        Unit of ``value`` and ``reference``.
    kind : {"relative", "absolute"}
        How the error is measured.
    tolerance : float
        Pass limit on the error (fraction for relative, ``unit`` for absolute).
    """

    name: str
    value: float
    reference: float
    unit: str
    kind: ErrorKind
    tolerance: float

    @property
    def error(self) -> float:
        """Relative (fraction) or absolute (``unit``) error."""
        difference = abs(self.value - self.reference)
        return difference / abs(self.reference) if self.kind == "relative" else difference

    @property
    def passed(self) -> bool:
        """True when the error is within tolerance."""
        return self.error <= self.tolerance


def _sphere(radius: float, lower: float, upper: float, samples: int = 2001) -> MeridianProfile:
    theta = np.linspace(lower, upper, samples)
    return MeridianProfile.from_points(radius * np.cos(theta), radius * np.sin(theta))


def _round_trip(
    profile: MeridianProfile, model: GoreWidthModel, stations: int = 150
) -> tuple[float, float]:
    s = np.linspace(0.0, profile.meridian_length, stations)
    widths = model.full_width(profile.radius_at(s))
    result = profile_from_gore_widths(s, widths, model)
    z_ref = profile.height_at(s) - profile.z[0]
    radius_error = float(np.max(np.abs(result.profile.radius_at(s) - profile.radius_at(s))))
    height_error = float(np.max(np.abs(result.profile.height_at(s) - z_ref)))
    return radius_error, height_error


def run_benchmarks() -> list[BenchmarkResult]:
    """Run every analytic benchmark.

    Returns
    -------
    list of BenchmarkResult
        Results in display order.
    """
    results: list[BenchmarkResult] = []
    radius = 8.0
    sphere = _sphere(radius, -math.pi / 2.0, math.pi / 2.0)
    results += [
        BenchmarkResult(
            "Sphere R=8 m volume",
            sphere.volume,
            4.0 / 3.0 * math.pi * radius**3,
            "m^3",
            "relative",
            1e-3,
        ),
        BenchmarkResult(
            "Sphere R=8 m area", sphere.area, 4.0 * math.pi * radius**2, "m^2", "relative", 1e-3
        ),
        BenchmarkResult(
            "Sphere R=8 m meridian length",
            sphere.meridian_length,
            math.pi * radius,
            "m",
            "relative",
            1e-3,
        ),
    ]
    cylinder = MeridianProfile.from_control_points([3.0, 3.0], [0.0, 10.0], samples=11)
    results += [
        BenchmarkResult(
            "Cylinder R=3 m H=10 m volume",
            cylinder.volume,
            math.pi * 9.0 * 10.0,
            "m^3",
            "relative",
            1e-3,
        ),
        BenchmarkResult(
            "Cylinder R=3 m H=10 m area",
            cylinder.area,
            2.0 * math.pi * 3.0 * 10.0,
            "m^2",
            "relative",
            1e-3,
        ),
    ]
    model = GoreWidthModel(24)
    length = sphere.meridian_length
    rows = split_rows(sphere, model, [length / 8.0] * 8)
    results.append(
        BenchmarkResult(
            "Sphere, 24 small-bulge gores x 8 rows: N x flat area",
            24 * sum(row.finished_area for row in rows),
            4.0 * math.pi * radius**2,
            "m^2",
            "relative",
            1e-3,
        )
    )
    zone = _sphere(radius, -math.radians(60.0), math.radians(80.0))
    for label, width_model in (
        ("small bulge", model),
        ("chord, flat", GoreWidthModel(24, "chord")),
        ("chord, bulge radius 4 m", GoreWidthModel(24, "chord", bulge_radius=0.5 * radius)),
    ):
        radius_error, height_error = _round_trip(zone, width_model)
        results += [
            BenchmarkResult(
                f"Round trip r(s), spherical zone, N=24, {label}",
                radius_error,
                0.0,
                "m",
                "absolute",
                1e-3,
            ),
            BenchmarkResult(
                f"Round trip z(s), spherical zone, N=24, {label}",
                height_error,
                0.0,
                "m",
                "absolute",
                1e-3,
            ),
        ]
    chute_radius, chute_centre = 2.86, 0.5
    for n in (8, 20):
        chute = parachute_pieces(2.0 * chute_radius, 2.0 * chute_centre, n, 0.0)
        results += [
            BenchmarkResult(
                f"Flat parachute R=2.86 m, {n} gores + disc: finished area",
                chute.finished_area,
                math.pi * chute_radius**2,
                "m^2",
                "relative",
                1e-3,
            ),
            BenchmarkResult(
                f"Flat parachute R=2.86 m, {n} gores: rim length",
                chute.rim_length,
                2.0 * math.pi * chute_radius,
                "m",
                "relative",
                1e-3,
            ),
            BenchmarkResult(
                f"Flat parachute, {n} gore ends vs centre-disc circumference",
                n * chute.gore_edges["top"],
                2.0 * math.pi * chute_centre,
                "m",
                "absolute",
                1e-3,
            ),
        ]
    ambient = gas_density(101325.0, celsius_to_kelvin(15.0))
    internal = gas_density(101325.0, celsius_to_kelvin(100.0))
    results += [
        BenchmarkResult(
            "dp gradient, 15 degC / 100 degC, sea level",
            pressure_gradient(ambient, internal),
            HAND_PRESSURE_GRADIENT,
            "Pa/m",
            "relative",
            1e-2,
        ),
        BenchmarkResult(
            "Gross lift, 2 610 m^3, 15 degC / 100 degC, sea level",
            gross_lift(2610.0, ambient, internal),
            HAND_LIFT_2610,
            "N",
            "relative",
            1e-2,
        ),
        BenchmarkResult(
            "ISA pressure at 1 000 m",
            isa(1000.0).pressure,
            ISO_2533_P_1000,
            "Pa",
            "relative",
            1e-4,
        ),
        BenchmarkResult(
            "ISA density at 1 000 m",
            isa(1000.0).density,
            ISO_2533_RHO_1000,
            "kg/m^3",
            "relative",
            1e-4,
        ),
        BenchmarkResult(
            "ISA pressure at 11 000 m",
            isa(11000.0).pressure,
            ISO_2533_P_11000,
            "Pa",
            "relative",
            1e-4,
        ),
        BenchmarkResult(
            "ISA pressure at 20 000 m",
            isa(20000.0).pressure,
            ISO_2533_P_20000,
            "Pa",
            "relative",
            1e-4,
        ),
    ]
    return results


def _fmt(value: float) -> str:
    return f"{value:.6g}"


def _fmt_error(result: BenchmarkResult) -> str:
    # Errors below 1e-6 (relative) or 1 um (absolute) are shown as bounds: their exact
    # digits depend on the platform's floating-point libraries and would make the
    # generated page differ between CI runners.
    if result.kind == "relative":
        return "< 1e-06" if result.error < 1e-6 else f"{result.error:.2g}"
    if result.error < 1e-6:
        return f"< 1e-06 {result.unit}"
    return f"{result.error * 1000:.3f} mm" if result.unit == "m" else f"{result.error:.2g}"


def _fmt_tolerance(result: BenchmarkResult) -> str:
    if result.kind == "relative":
        return f"{result.tolerance:g}"
    return f"{result.tolerance * 1000:g} mm" if result.unit == "m" else f"{result.tolerance:g}"


def render_markdown(results: list[BenchmarkResult]) -> str:
    """Render benchmark results as the Markdown validation page.

    Parameters
    ----------
    results : list of BenchmarkResult
        Output of :func:`run_benchmarks`.

    Returns
    -------
    str
        Page content.
    """
    lines = [
        "# Analytic geometry and atmosphere benchmarks",
        "",
        "_Auto-generated by `python scripts/generate_validation_docs.py` from "
        "`envelopelab.validation.analytic_geometry`. Do not edit by hand; "
        "`tests/benchmarks/test_analytic_geometry.py` fails if this page is stale._",
        "",
        "Relative errors are fractions (0.001 = 0.1 %); absolute errors are in the unit",
        "shown.",
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
        "Round-trip rows sample the profile at 150 stations, convert radius to flat gore",
        "width, then recover r(s) and z(s) with "
        "`profile_from_gore_widths` (GCV smoothing spline); the error is the maximum over",
        "the stations. The spherical zone spans -60 deg to +80 deg latitude, so the slope",
        "at the top reaches |dr/ds| = 0.98.",
        "",
        "Pending: the panel-row check against the reference fixture's panel C",
        "(bottom 1480 mm, top 1782 mm, height 1328 mm) runs once that fixture profile",
        "is added to `tests/fixtures/`.",
        "",
    ]
    return "\n".join(lines)
