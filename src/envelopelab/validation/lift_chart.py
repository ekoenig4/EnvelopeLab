r"""Lift-chart benchmarks: equilibrium load, top temperature and ceiling vs hand values.

The same functions back ``tests/benchmarks/test_lift_chart_benchmarks.py`` and the generated
page ``docs/validation/lift-chart-benchmarks.md`` (``scripts/generate_validation_docs.py``).

Hand calculation (written out below, independent of :mod:`envelopelab.lift_chart`):
envelope 2 610 m^3, envelope + rigging 200 kg, top-to-mean offset 20 K, limit 120 degC;
dry air :math:`R_d = 287.05287` J/(kg K).

* Sea level, 15 degC ambient, top 120 degC (mean 100 degC):
  :math:`\rho_{amb} = 101325/(287.05287 \cdot 288.15) = 1.22500`,
  :math:`\rho_{int} = 101325/(287.05287 \cdot 373.15) = 0.94594` kg/m^3, so the balloon
  lifts :math:`2610 \cdot 0.27906 = 728.3` kg and floats a load of 528.3 kg.
* 2 000 m pressure altitude:
  :math:`p = 101325\,(1 - 0.0065 \cdot 2000/288.15)^{5.25588} = 79\,495.2` Pa.
* Top temperature for a load: :math:`T_{mean} = (1/T_{amb} - R_d m/(pV))^{-1}`, the
  inverse of the first case, must return 120 degC.
* Ceiling: at the computed altitude the spare lift, recomputed from the ISA formula above,
  must vanish.

Builders' spreadsheet (gross lift in US units, :func:`spreadsheet_lift`): the "Envelope
lifting capacity" spreadsheet of the Balloon Builders Journal (issue 8) computes

.. math::
    L\,[\mathrm{lb}] = \frac{V\,p}{R}\left(\frac{1}{T_{amb}} - \frac{1}{T_{env}}\right),
    \qquad p = 2116 \left(\frac{288.15}{288.15 - 0.00198\,h}\right)^{-5.25587}

with :math:`V` in ft^3, :math:`h` in ft, :math:`p` in lbf/ft^2, :math:`R = 53.34`
ft lbf/(lb degR) and temperatures in degR = degF + 459 (one uniform envelope
temperature). With its own constants it is 0.23 % to 0.27 % above EnvelopeLab (+459
instead of +459.67 is +0.24 %, R = 53.34 instead of 53.352 is +0.02 %); with exact
constants the two agree to 1e-4, so the spreadsheet's envelope temperature is
EnvelopeLab's mean gas temperature.
"""

from __future__ import annotations

import math

from envelopelab.atmosphere import PhysicalConstant
from envelopelab.lift_chart import (
    LiftChartInputs,
    equilibrium_altitude,
    equilibrium_load,
    equilibrium_top_temperature,
    lift_mass,
)
from envelopelab.validation.analytic_geometry import (
    BenchmarkResult,
    _fmt,
    _fmt_error,
    _fmt_tolerance,
)

R_D = 287.05287  # J/(kg K), ISO 2533
P0 = 101325.0  # Pa
G0_VALUE = 9.80665  # m/s^2, ISO 2533
T0 = 288.15  # K
VOLUME = 2610.0  # m^3
FIXED = 200.0  # kg
OFFSET = 20.0  # K
LIMIT = 393.15  # K (120 degC)

INPUTS = LiftChartInputs(
    volume=VOLUME,
    volume_note="benchmark",
    fixed_mass=FIXED,
    fixed_mass_sources=("assumed",),
    top_limit=PhysicalConstant(LIMIT, "K", "assumed", "benchmark"),
    top_to_mean=PhysicalConstant(OFFSET, "K", "assumed", "benchmark"),
)


def _isa_troposphere(h: float, offset: float = 0.0) -> tuple[float, float]:
    """(pressure Pa, temperature K) of the ISA troposphere, written out by hand."""
    t = T0 - 0.0065 * h
    p = P0 * (t / T0) ** (9.80665 / (0.0065 * R_D))
    return p, t + offset


def _hand_load(p: float, t_amb: float, t_top: float) -> float:
    return VOLUME * (p / (R_D * t_amb) - p / (R_D * (t_top - OFFSET))) - FIXED


#: Spreadsheet constants as published, and the exact values they approximate.
SHEET_CONSTANTS = {"rankine": 459.0, "r": 53.34, "p0": 2116.0, "lapse": 0.00198}
EXACT_CONSTANTS = {
    "rankine": 459.67,  # degR = degF + 459.67 (definition)
    "r": R_D * 0.45359237 / (4.4482216152605 * 0.3048) / 1.8,  # ft lbf/(lb degR)
    "p0": P0 / (4.4482216152605 / 0.3048**2),  # lbf/ft2
    "lapse": 0.0065 * 0.3048,  # K/ft
}
SHEET_VOLUME_FT3 = 92000.0
#: The spreadsheet's cases: (ambient degF, altitude ft MSL).
SHEET_CASES = ((40.0, 300.0), (50.0, 300.0), (50.0, 6000.0), (90.0, 2000.0), (90.0, 6000.0))


def spreadsheet_lift(
    volume_ft3: float,
    ambient_f: float,
    envelope_f: float,
    altitude_ft: float,
    rankine: float,
    r: float,
    p0: float,
    lapse: float,
) -> float:
    """Gross lift of the builders' spreadsheet (module docstring), lb.

    Parameters
    ----------
    volume_ft3 : float
        Envelope volume, ft^3.
    ambient_f, envelope_f : float
        Ambient and (uniform) envelope temperatures, degF.
    altitude_ft : float
        Pressure altitude, ft.
    rankine, r, p0, lapse : float
        degF-to-degR offset; gas constant, ft lbf/(lb degR); sea-level pressure, lbf/ft^2;
        lapse rate, K/ft.

    Returns
    -------
    float
        Gross lift, lb (lbm; numerically lbf at standard gravity).
    """
    p = p0 * float((288.15 / (288.15 - lapse * altitude_ft)) ** -5.25587)
    return volume_ft3 * p / r * (1.0 / (ambient_f + rankine) - 1.0 / (envelope_f + rankine))


def _app_lift_lb(ambient_f: float, envelope_f: float, altitude_ft: float) -> float:
    def kelvin(f: float) -> float:
        return (f - 32.0) / 1.8 + 273.15

    volume = SHEET_VOLUME_FT3 * 0.3048**3
    kg = lift_mass(volume, altitude_ft * 0.3048, kelvin(ambient_f), kelvin(envelope_f))
    return kg / 0.45359237


def _spreadsheet_benchmarks() -> list[BenchmarkResult]:
    out = []
    for ambient, altitude in SHEET_CASES:
        for envelope in (130.0, 200.0, 280.0):
            app = _app_lift_lb(ambient, envelope, altitude)
            args = (SHEET_VOLUME_FT3, ambient, envelope, altitude)
            case = f"{ambient:.0f} degF, {altitude:,.0f} ft, envelope {envelope:.0f} degF"
            out.append(
                BenchmarkResult(
                    f"Spreadsheet 92,000 ft3 (exact constants): {case}",
                    app,
                    spreadsheet_lift(*args, **EXACT_CONSTANTS),
                    "lb",
                    "relative",
                    1e-4,
                )
            )
            out.append(
                BenchmarkResult(
                    f"Spreadsheet 92,000 ft3 (as published): {case}",
                    app,
                    spreadsheet_lift(*args, **SHEET_CONSTANTS),
                    "lb",
                    "relative",
                    5e-3,
                )
            )
    return out


def _stratification_benchmarks() -> list[BenchmarkResult]:
    r"""Level-1 stratification vs closed forms and independent quadrature.

    * Cylinder (radius 1 m, height 10 m), linear profile from :math:`a` (mouth) to
      :math:`a + b` (crown): :math:`T_{eff} = b / \ln(1 + b/a)`.
    * Sphere (radius 5 m, mouth at the bottom): :math:`1/T_{eff} = \int \pi (R^2 - y^2)
      / T(y)\,dy \,/\, (4\pi R^3/3)` by adaptive quadrature (scipy ``quad``).
    * Pressure at the crown: the closed form of :meth:`StratificationModel.pressure_profile`
      vs trapezoidal integration of :math:`(\rho_{amb} - \rho(h))\,g`.
    * Floor: with a 30 K floor on the cylinder, the mean is exactly 30 K below the crown.
    """
    import numpy as np
    from scipy.integrate import quad

    from envelopelab.stratification import StratificationModel, VolumeDistribution

    t_amb, t_top, phi = 288.15, 393.15, 0.5
    excess = PhysicalConstant(phi, "-", "assumed", "benchmark")
    a = t_amb + (t_top - t_amb) * phi
    b = t_top - a
    zs = np.linspace(0.0, 10.0, 11)
    cylinder = VolumeDistribution.from_profile(np.ones_like(zs), zs)
    cyl = StratificationModel(cylinder, excess)
    radius = 5.0
    theta = np.linspace(-np.pi / 2, np.pi / 2, 4001)
    sphere = StratificationModel(
        VolumeDistribution.from_profile(radius * np.cos(theta), radius * np.sin(theta)), excess
    )

    def temp(y: float) -> float:  # y from the centre
        return t_amb + (t_top - t_amb) * (phi + (1 - phi) * (y + radius) / (2 * radius))

    integral, _err = quad(lambda y: math.pi * (radius**2 - y**2) / temp(y), -radius, radius)
    sphere_ref = (4.0 / 3.0 * math.pi * radius**3) / integral
    h = np.linspace(0.0, 10.0, 200001)
    rho = P0 / (R_D * cyl.temperatures(t_top, t_amb, h))
    trapezoid = float(np.trapezoid((P0 / (R_D * t_amb) - rho) * G0_VALUE, h))
    floored = StratificationModel(cylinder, excess, PhysicalConstant(30.0, "K", "assumed", ""))
    return [
        BenchmarkResult(
            "Stratification: cylinder volume pi r^2 H",
            cylinder.total,
            math.pi * 10.0,
            "m^3",
            "relative",
            1e-9,
        ),
        BenchmarkResult(
            "Stratification: cylinder T_eff = b / ln(1 + b/a)",
            cyl.effective_mean(t_top, t_amb),
            b / math.log(1.0 + b / a),
            "K",
            "absolute",
            1e-3,
        ),
        BenchmarkResult(
            "Stratification: sphere T_eff vs quadrature",
            sphere.effective_mean(t_top, t_amb),
            sphere_ref,
            "K",
            "absolute",
            1e-2,
        ),
        BenchmarkResult(
            "Stratification: uniform envelope (phi = 1) has no offset",
            StratificationModel(cylinder, PhysicalConstant(1.0, "-", "assumed", "")).offset(
                t_top, t_amb
            ),
            0.0,
            "K",
            "absolute",
            1e-9,
        ),
        BenchmarkResult(
            "Stratification: crown pressure, closed form vs trapezoid",
            float(cyl.pressure_profile(t_top, t_amb, P0, [10.0])[0]),
            trapezoid,
            "Pa",
            "relative",
            1e-6,
        ),
        BenchmarkResult(
            "Stratification: 30 K floor gives mean = top - 30 K",
            floored.offset(t_top, t_amb),
            30.0,
            "K",
            "absolute",
            1e-6,
        ),
        BenchmarkResult(
            "Stratification: floored profile reproduces the floored mean",
            floored.effective_mean(t_top, t_amb, floored.excess_used(t_top, t_amb)),
            t_top - 30.0,
            "K",
            "absolute",
            1e-6,
        ),
    ]


def run_benchmarks() -> list[BenchmarkResult]:
    """Run every lift-chart benchmark (display order)."""
    t15, t120 = 288.15, 393.15
    sea = equilibrium_load(INPUTS, 0.0, t15, t120)
    p2000, _ = _isa_troposphere(2000.0)
    t5 = 278.15
    high = equilibrium_load(INPUTS, 2000.0, t5, t120)
    back = equilibrium_top_temperature(INPUTS, 0.0, t15, 528.3)
    hand_top = 1.0 / (1.0 / t15 - R_D * (FIXED + 528.3) / (P0 * VOLUME)) + OFFSET
    hot = equilibrium_top_temperature(INPUTS, 2000.0, 303.15, 300.0)
    hand_hot = 1.0 / (1.0 / 303.15 - R_D * (FIXED + 300.0) / (p2000 * VOLUME)) + OFFSET
    ceiling = equilibrium_altitude(INPUTS, 10.0, t120, 400.0)
    p_c, t_c = _isa_troposphere(ceiling.altitude, 10.0)
    spare = _hand_load(p_c, t_c, t120) - 400.0
    return [
        BenchmarkResult(
            "Load at sea level, 15 degC, top 120 degC (hand 528.3 kg)",
            sea.load,
            528.3,
            "kg",
            "absolute",
            0.1,
        ),
        BenchmarkResult(
            "Load at sea level, 15 degC, top 120 degC (closed form)",
            sea.load,
            _hand_load(P0, t15, t120),
            "kg",
            "relative",
            1e-3,
        ),
        BenchmarkResult(
            "ISA pressure at 2 000 m (hand 79 495.2 Pa)",
            p2000,
            79495.2,
            "Pa",
            "relative",
            1e-5,
        ),
        BenchmarkResult(
            "Load at 2 000 m, 5 degC, top 120 degC",
            high.load,
            _hand_load(p2000, t5, t120),
            "kg",
            "relative",
            1e-3,
        ),
        BenchmarkResult(
            "Top temperature for 528.3 kg at sea level, 15 degC (inverse)",
            back.top_temperature,
            hand_top,
            "K",
            "absolute",
            0.01,
        ),
        BenchmarkResult(
            "Top temperature for 528.3 kg round trip (120 degC)",
            back.top_temperature,
            t120,
            "K",
            "absolute",
            0.05,
        ),
        BenchmarkResult(
            "Top temperature for 300 kg at 2 000 m, 30 degC",
            hot.top_temperature,
            hand_hot,
            "K",
            "absolute",
            0.01,
        ),
        BenchmarkResult(
            "Ceiling, ISA+10, 400 kg, top 120 degC: spare lift at the ceiling",
            spare,
            0.0,
            "kg",
            "absolute",
            0.05,
        ),
        *_spreadsheet_benchmarks(),
        *_stratification_benchmarks(),
    ]


def render_markdown(results: list[BenchmarkResult]) -> str:
    """Render the lift-chart benchmark page (Markdown)."""
    lines = [
        "# Lift-chart benchmarks",
        "",
        "_Auto-generated by `python scripts/generate_validation_docs.py` from "
        "`envelopelab.validation.lift_chart`. Do not edit by hand; "
        "`tests/benchmarks/test_lift_chart_benchmarks.py` fails if this page is stale._",
        "",
        "Envelope 2 610 m³, envelope + rigging 200 kg, mean gas temperature 20 K below the",
        "top temperature, limit 120 degC, dry air (R_d = 287.052 87 J/(kg K)). Reference",
        "values are the closed-form hand calculations of the module docstring: ISA",
        "troposphere pressure written out, densities from the ideal-gas law, equilibrium",
        "V (rho_amb - rho_int) = envelope + rigging + load. Relative errors are fractions;",
        "absolute errors are in the unit shown.",
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
        "The ceiling row recomputes the spare lift at the solved altitude from the",
        "hand-written ISA formula; it must vanish to within 0.05 kg.",
        "",
        "The spreadsheet rows compare EnvelopeLab's gross lift, read against the mean gas",
        "temperature, with the Balloon Builders Journal 'Envelope lifting capacity'",
        "spreadsheet formula (92,000 ft3; its five ambient/altitude cases at 130, 200 and",
        "280 degF). With exact constants (degR = degF + 459.67, R = 53.352 ft lbf/(lb degR),",
        "2116.22 lbf/ft2, 0.0019812 K/ft) they agree within 1e-4. As published (+459,",
        "R = 53.34, 2116, 0.00198) the spreadsheet is 0.23 % to 0.27 % higher, almost all",
        "from +459; tolerance 0.5 %. The spreadsheet's single envelope temperature is the",
        "mean gas temperature; see docs/theory/lift-charts.md.",
        "",
        "The stratification rows check the level-1 temperature profile",
        "(`envelopelab.stratification`, docs/theory/stratification.md): ambient 15 degC,",
        "crown 120 degC, mouth excess 0.5; a cylinder r = 1 m, H = 10 m against the closed",
        "form, a sphere R = 5 m against adaptive quadrature, the consistent pressure at the",
        "crown against trapezoidal integration, and the offset floor.",
        "",
    ]
    return "\n".join(lines)


__all__ = ["INPUTS", "render_markdown", "run_benchmarks", "spreadsheet_lift"]
