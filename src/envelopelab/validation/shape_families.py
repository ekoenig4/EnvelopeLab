"""Shape-family benchmarks: an analytic sphere family and shape-file fixtures.

The sphere family :math:`r(s) = \\sin(\\pi s)/\\pi` (tape length :math:`L = \\pi R`) has
closed-form volume, height, diameters and tape length. Fixtures compare a solved shape
file with the values its source spreadsheet computes (the file's ``published`` block).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from envelopelab.io.shape_file import ShapeFile, load_shape_file, parse_quantity
from envelopelab.project.gore_design import design_profile as document_profile
from envelopelab.project.shape_family import (
    NormalizedShape,
    ShapeParameters,
    evaluate,
    shape_design,
    solve_shape,
    station_points,
)
from envelopelab.validation.analytic_geometry import BenchmarkResult, _fmt, _fmt_error

#: Shape-file fixtures (name, path relative to the repository root).
FIXTURES: tuple[tuple[str, str], ...] = (("smalley_90k", "tests/fixtures/smalley_90k/shape.yaml"),)
#: Tolerance on the comparison of the spline volume coefficient with a published one.
#: The published coefficient comes from the source's own (undocumented) integration; the
#: inscribed polygon through the same stations is a lower bound and lies 0.05 % above the
#: published value for the fixture, the spline 0.15 %, so 0.3 % tests the transcription
#: and the profile construction rather than the source's quadrature.
PUBLISHED_COEFFICIENT_TOLERANCE = 3e-3
SPHERE_RADIUS = 8.0  # m
SPHERE_STATIONS = 51


def sphere_shape(stations: int = SPHERE_STATIONS) -> NormalizedShape:
    """Normalized sphere, ``stations`` equally spaced stations."""
    s = np.linspace(0.0, 1.0, stations)
    return NormalizedShape(s=s, r=np.sin(math.pi * s) / math.pi, source="assumed")


def sphere_benchmarks() -> list[BenchmarkResult]:
    """Sphere family against closed form (AGENTS.md default tolerances)."""
    shape = sphere_shape()
    radius = SPHERE_RADIUS
    lo, hi = 0.2, 0.9
    params = ShapeParameters(math.pi * radius, lo, hi, 24, 0.0)
    got = evaluate(shape, params)
    z_lo, z_hi = -radius * math.cos(math.pi * lo), -radius * math.cos(math.pi * hi)
    segment = math.pi * (radius**2 * (z_hi - z_lo) - (z_hi**3 - z_lo**3) / 3.0)
    mouth = 2.0 * radius * math.sin(math.pi * lo)
    solved = solve_shape(
        shape, params, {"mouth_diameter": 5.0, "mouth_station": lo, "top_station": hi}
    )
    tag = f"Sphere R={radius:g} m, {SPHERE_STATIONS} stations"
    return [
        BenchmarkResult(
            f"{tag}: volume coefficient",
            shape.volume_coefficient,
            4 / (3 * math.pi**2),
            "-",
            "relative",
            1e-3,
        ),
        BenchmarkResult(
            f"{tag}, cut at s=0.2/0.9: volume",
            got["envelope_volume"],
            segment,
            "m^3",
            "relative",
            1e-3,
        ),
        BenchmarkResult(
            f"{tag}, cut at s=0.2/0.9: height", got["height"], z_hi - z_lo, "m", "absolute", 1e-3
        ),
        BenchmarkResult(
            f"{tag}, cut at s=0.2/0.9: mouth diameter",
            got["mouth_diameter"],
            mouth,
            "m",
            "absolute",
            1e-3,
        ),
        BenchmarkResult(
            f"{tag}, cut at s=0.2/0.9: tape length",
            got["tape_length"],
            math.pi * radius * (hi - lo),
            "m",
            "absolute",
            1e-3,
        ),
        BenchmarkResult(
            f"{tag}: solve L for a 5 m mouth (converged={solved.converged})",
            solved.parameters.gore_length if solved.converged else math.nan,
            math.pi * 2.5 / math.sin(math.pi * lo),
            "m",
            "absolute",
            1e-3,
        ),
    ]


def _published_length(shape_file: ShapeFile, key: str, value: object) -> float:
    return parse_quantity(value, "length", f"published.{key}")


def fixture_benchmarks(name: str, shape_file: ShapeFile) -> list[BenchmarkResult]:
    """A shape-file fixture against its ``published`` block.

    Recognised keys: ``volume_coefficient`` ({value, source}), ``gore_length`` and, per
    named station, ``radius``, ``sewn_half_gore`` and ``cut_half_gore`` (lengths with
    units). Missing keys give no row.
    """
    pub = shape_file.published
    shape = shape_file.shape
    solution = shape_file.solve()
    params = solution.parameters
    out: list[BenchmarkResult] = []
    if "volume_coefficient" in pub:
        c = float(pub["volume_coefficient"]["value"])
        out.append(
            BenchmarkResult(
                f"{name}: volume coefficient, polygon through stations",
                shape.chord_volume_coefficient,
                c,
                "-",
                "relative",
                1e-3,
            )
        )
        out.append(
            BenchmarkResult(
                f"{name}: volume coefficient, design spline",
                shape.volume_coefficient,
                c,
                "-",
                "relative",
                PUBLISHED_COEFFICIENT_TOLERANCE,
            )
        )
    out.append(
        BenchmarkResult(
            f"{name}: design solve converged ({solution.message})",
            float(solution.converged),
            1.0,
            "-",
            "absolute",
            0.0,
        )
    )
    if "gore_length" in pub:
        out.append(
            BenchmarkResult(
                f"{name}: gore length L",
                params.gore_length,
                _published_length(shape_file, "gore_length", pub["gore_length"]),
                "m",
                "relative",
                1e-3,
            )
        )
    points = {p.name: p for p in station_points(shape, params)}
    for station, values in (pub.get("stations") or {}).items():
        if station not in points:
            continue
        radius = points[station].radius
        half = math.pi * radius / params.gore_count
        for key, got in (
            ("radius", radius),
            ("sewn_half_gore", half),
            ("cut_half_gore", half + params.seam_allowance),
        ):
            if key in values:
                ref = _published_length(shape_file, f"stations.{station}.{key}", values[key])
                out.append(
                    BenchmarkResult(
                        f"{name}: {station} {key.replace('_', ' ')}",
                        got,
                        ref,
                        "m",
                        "relative",
                        1e-3,
                    )
                )
    if solution.converged:
        document = shape_design(shape_file.name, shape, solution, row_count=10)
        out.append(
            BenchmarkResult(
                f"{name}: design document volume = solved envelope volume",
                document_profile(document).volume,
                solution.values["envelope_volume"],
                "m^3",
                "relative",
                1e-9,
            )
        )
        mouth = 1.1 * solution.values["mouth_diameter"]
        variant = shape_file.solve(
            {
                "mouth_diameter": mouth,
                "mouth_station": params.mouth_station,
                "top_station": params.top_station,
            }
        )
        out.append(
            BenchmarkResult(
                f"{name}: hold a 10 % larger mouth, solve L (converged={variant.converged})",
                variant.parameters.gore_length if variant.converged else math.nan,
                1.1 * params.gore_length,
                "m",
                "absolute",
                1e-3,
            )
        )
    return out


def run_benchmarks(repo_root: Path) -> list[BenchmarkResult]:
    """All shape-family benchmarks (sphere family, then each fixture)."""
    results = sphere_benchmarks()
    for name, rel in FIXTURES:
        results += fixture_benchmarks(name, load_shape_file(repo_root / rel))
    return results


def render_markdown(results: list[BenchmarkResult]) -> str:
    """The generated page ``docs/validation/shape-families.md``."""
    lines = [
        "# Shape-family benchmarks",
        "",
        "_Auto-generated by `python scripts/generate_validation_docs.py shapes` from "
        "`envelopelab.validation.shape_families`. Do not edit by hand; "
        "`tests/benchmarks/test_shape_families.py` fails if this page is stale._",
        "",
        "Sphere rows compare a normalized sphere table with closed form. Fixture rows",
        "compare the solved design of a shape file in `tests/fixtures/` with the values",
        "its source spreadsheet computes (the file's `published` block). Relative errors",
        "are fractions (0.001 = 0.1 %).",
        "",
        "| Benchmark | Computed | Reference | Unit | Error | Tolerance | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in results:
        value = _fmt(result.value) if result.kind == "relative" else "-"
        reference = _fmt(result.reference) if result.kind == "relative" else "-"
        tolerance = (
            f"{result.tolerance * 1000:g} mm"
            if result.kind == "absolute" and result.unit == "m"
            else f"{result.tolerance:g}"
        )
        status = "pass" if result.passed else "**FAIL**"
        lines.append(
            f"| {result.name} | {value} | {reference} | {result.unit} | "
            f"{_fmt_error(result)} | {tolerance} | {status} |"
        )
    lines += [
        "",
        "The published volume coefficient is compared with a 0.3 % tolerance instead of",
        "the 0.1 % default: the source's integration is not documented, the polygon",
        "through the stations (a lower bound for a convex profile) is within 0.1 % of it,",
        "and the design spline encloses about 0.1 % more than the polygon. Lengths",
        "computed from the held volume therefore differ from the spreadsheet by about a",
        "third of the coefficient difference (0.05 % for `smalley_90k`); hold",
        "`gore_length` instead to cut exactly the spreadsheet's gores.",
        "",
    ]
    return "\n".join(lines)
