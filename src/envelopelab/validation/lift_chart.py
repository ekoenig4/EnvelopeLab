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
"""

from __future__ import annotations

from envelopelab.atmosphere import PhysicalConstant
from envelopelab.lift_chart import (
    LiftChartInputs,
    equilibrium_altitude,
    equilibrium_load,
    equilibrium_top_temperature,
)
from envelopelab.validation.analytic_geometry import (
    BenchmarkResult,
    _fmt,
    _fmt_error,
    _fmt_tolerance,
)

R_D = 287.05287  # J/(kg K), ISO 2533
P0 = 101325.0  # Pa
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
    ]
    return "\n".join(lines)


__all__ = ["INPUTS", "run_benchmarks", "render_markdown"]
