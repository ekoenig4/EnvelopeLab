r"""Special-shape primitive benchmarks: closed-form geometry and a preview-solver study.

Geometry cases sit on a generic spherical envelope of radius :math:`R` (tape
:math:`r = R\sin(s/R)`, :math:`z = -R\cos(s/R)`), with the primitive's axis along the
envelope normal at the equator, where the footprint and the developments have closed
forms:

* an upright cylinder of radius :math:`a` meets the sphere in a circle of radius
  :math:`a`, :math:`\delta = R - \sqrt{R^2 - a^2}` below the tangent plane, so each of
  :math:`M` panels develops to a rectangle :math:`2\pi a/M` wide and :math:`L + \delta`
  high;
* an upright frustum's generator meets the sphere :math:`e` beyond its base circle,
  :math:`(r_b + e\sin\gamma)^2 + (R - e\cos\gamma)^2 = R^2`, and its tip edge develops to
  an arc of length :math:`2\pi r_t/M`;
* a hemispherical dome of radius :math:`a` stands :math:`a` above the envelope at its
  apex and its footprint is the circle :math:`2\pi a`.

The solver study inflates a 16-gore dome on the same envelope with the preview solver at
three mesh sizes, against the same model whose skin rests in the designed shape (no
pattern strain), so the effect of the cut pattern on the inflated shape is visible.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import numpy as np

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import build_appendage
from envelopelab.features.metrics import appendage_metrics
from envelopelab.features.primitives import (
    AREA_DISTORTION_LIMIT,
    Dome,
    EnvelopeSurface,
    Placement,
    RowBand,
    Tube,
    design_primitive,
    primitive_appendage,
)
from envelopelab.geometry.gore import MeridianProfile
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions
from envelopelab.solvers.simulation import from_preview
from envelopelab.validation.analytic_geometry import BenchmarkResult, _fmt, _fmt_error
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE

SPHERE_RADIUS = 8.0  # m, generic envelope
SPHERE_GORES = 24
#: Tape positions of the envelope's mouth and crown as fractions of the half circle.
SPHERE_SPAN = (0.15, 0.97)
GEOMETRY_TOLERANCE = 1e-3  # m (AGENTS.md geometry default)
LENGTH_TOLERANCE = 1e-3  # relative (AGENTS.md default 0.1 %)
STUDY_MESH_SIZES = (0.3, 0.2, 0.15)  # m
STUDY_GORES = 16


def sphere_envelope(rows: int = 4) -> EnvelopeSurface:
    """Generic spherical envelope (radius :data:`SPHERE_RADIUS`, equal rows)."""
    s = np.linspace(SPHERE_SPAN[0], SPHERE_SPAN[1], 4001) * math.pi * SPHERE_RADIUS
    profile = MeridianProfile.from_points(
        SPHERE_RADIUS * np.sin(s / SPHERE_RADIUS), -SPHERE_RADIUS * np.cos(s / SPHERE_RADIUS)
    )
    edges = np.linspace(0.0, profile.meridian_length, rows + 1)
    bands = [
        RowBand(chr(ord("A") + k), float(a), float(b))
        for k, (a, b) in enumerate(zip(edges[:-1], edges[1:], strict=True))
    ]
    return EnvelopeSurface(profile, SPHERE_GORES, rows=bands)


def _equator(surface: EnvelopeSurface) -> float:
    return 0.5 * math.pi * SPHERE_RADIUS - SPHERE_SPAN[0] * math.pi * SPHERE_RADIUS


def _length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def geometry_benchmarks() -> list[BenchmarkResult]:
    """Closed-form footprint, development and attachment checks (see module docstring)."""
    surface = sphere_envelope()
    s_eq = _equator(surface)
    radius = SPHERE_RADIUS
    out: list[BenchmarkResult] = []

    a, length, panels = 0.8, 1.5, 4
    cyl = design_primitive(Tube("cyl", Placement(1, s_eq), a, a, length, panels), surface)
    delta = radius - math.sqrt(radius**2 - a**2)
    tag = f"Cylinder a={a:g} m, L={length:g} m on a sphere R={radius:g} m"
    depth = float(-np.min(cyl._skin.u0))
    panel = cyl.pieces[0]
    out += [
        BenchmarkResult(
            f"{tag}: footprint length",
            cyl.footprint_length,
            2 * math.pi * a,
            "m",
            "relative",
            LENGTH_TOLERANCE,
        ),
        BenchmarkResult(
            f"{tag}: footprint depth", depth, delta, "m", "absolute", GEOMETRY_TOLERANCE
        ),
        BenchmarkResult(
            f"{tag}: panel width",
            panel.size[0],
            2 * math.pi * a / panels,
            "m",
            "absolute",
            GEOMETRY_TOLERANCE,
        ),
        BenchmarkResult(
            f"{tag}: panel height",
            panel.size[1],
            length + delta,
            "m",
            "absolute",
            GEOMETRY_TOLERANCE,
        ),
    ]

    r_b, r_t = 0.8, 0.3
    cone = design_primitive(Tube("cone", Placement(1, s_eq), r_b, r_t, length, panels), surface)
    slant = math.hypot(r_b - r_t, length)
    sin_g, cos_g = (r_b - r_t) / slant, length / slant
    # (r_b + e sin g)^2 + (R - e cos g)^2 = R^2, smallest positive root.
    qa, qb, qc = 1.0, 2.0 * (r_b * sin_g - radius * cos_g), r_b**2
    ext = (-qb - math.sqrt(qb * qb - 4.0 * qa * qc)) / (2.0 * qa)
    tag = f"Frustum {r_b:g}/{r_t:g} m, L={length:g} m on a sphere R={radius:g} m"
    out += [
        BenchmarkResult(
            f"{tag}: developed tip edge",
            _length(cone.pieces[0].edges["top"]),
            2 * math.pi * r_t / panels,
            "m",
            "absolute",
            GEOMETRY_TOLERANCE,
        ),
        BenchmarkResult(
            f"{tag}: developed side edge",
            _length(cone.pieces[0].edges["right"]),
            slant + ext,
            "m",
            "absolute",
            GEOMETRY_TOLERANCE,
        ),
        BenchmarkResult(
            f"{tag}: footprint length",
            cone.footprint_length,
            2 * math.pi * (r_b + ext * sin_g),
            "m",
            "relative",
            LENGTH_TOLERANCE,
        ),
    ]

    a = 1.0
    for gores in (8, STUDY_GORES, 32):
        dome = design_primitive(Dome("dome", Placement(1, s_eq), a, a, gores), surface)
        check = {c.name: c for c in dome.checks}
        tag = f"Hemispherical dome a={a:g} m, {gores} gores"
        out.append(
            BenchmarkResult(
                f"{tag}: area distortion",
                check["area distortion"].value,
                0.0,
                "-",
                "absolute",
                1.0 if gores < STUDY_GORES else AREA_DISTORTION_LIMIT,
            )
        )
        if gores != STUDY_GORES:
            continue
        rim = sum(_length(c.rim) for c in dome.pieces if c.rim is not None)
        out += [
            BenchmarkResult(
                f"{tag}: footprint length",
                dome.footprint_length,
                2 * math.pi * a,
                "m",
                "relative",
                LENGTH_TOLERANCE,
            ),
            BenchmarkResult(
                f"{tag}: skin rim length", rim, 2 * math.pi * a, "m", "relative", LENGTH_TOLERANCE
            ),
            BenchmarkResult(
                f"{tag}: designed height",
                dome.designed_height,
                a,
                "m",
                "absolute",
                GEOMETRY_TOLERANCE,
            ),
            BenchmarkResult(
                f"{tag}: skin seam sides",
                check["skin seam match"].value,
                0.0,
                "m",
                "absolute",
                GEOMETRY_TOLERANCE,
            ),
        ]

    # Attachment marks map back onto the footprint (dome straddling a load tape and a
    # row seam).
    surface = sphere_envelope()
    s_row = surface.rows[1].s_top
    dome = design_primitive(Dome("mark", Placement(5, s_row, across=0.5), 0.9, 0.6, 8), surface)
    gap = attachment_gap(dome)
    out.append(
        BenchmarkResult(
            f"Dome on load tape and row seam ({len(dome.attachment)} panel runs): "
            "attachment marks off the footprint",
            gap,
            0.0,
            "m",
            "absolute",
            GEOMETRY_TOLERANCE,
        )
    )
    return out


def attachment_gap(design: Any) -> float:
    """Largest distance of an attachment mark, mapped back onto the envelope, from the
    footprint line, m."""
    surface = design.surface
    fp = design.footprint_points
    worst = 0.0
    labels = [r.label for r in surface.rows]
    for line in design.attachment:
        row = surface.rows[labels.index(line.row)]
        s = row.s_bottom + line.points[:, 1]
        across = line.points[:, 0] / (2.0 * surface.half_width(s))
        theta = surface.theta_at(line.gore, 0.0) + across * surface.gore_angle
        pts = surface.point(s, theta)
        a, b = fp, np.roll(fp, -1, axis=0)
        ab = b - a
        t = np.einsum("pkj,kj->pk", pts[:, None, :] - a[None], ab) / np.einsum("kj,kj->k", ab, ab)
        proj = a[None] + np.clip(t, 0.0, 1.0)[..., None] * ab[None]
        dist = np.linalg.norm(pts[:, None, :] - proj, axis=2).min(axis=1)
        worst = max(worst, float(dist.max()))
    return worst


def solve_study(mesh_sizes: tuple[float, ...] = STUDY_MESH_SIZES) -> list[dict[str, Any]]:
    """Preview-solver inflation of a 16-gore dome on the generic sphere (module docstring).

    Returns
    -------
    list of dict
        One row per mesh size plus a designed-rest reference row: nodes, status,
        projected height (m), designed height (m), skin wrinkled fraction (-), lowest
        FoS (-), chamber pressure (Pa).
    """
    surface = sphere_envelope()
    s_eq = _equator(surface)
    dome = Dome("dome", Placement(1, s_eq), 1.0, 1.2, STUDY_GORES)
    design = design_primitive(dome, surface, feed_hole_radius=0.3)
    distortion = next(c.value for c in design.checks if c.name == "area distortion")
    z_mouth = float(surface.profile.z[0])
    cond = OperatingConditions.hot_air(
        celsius_to_kelvin(100.0), mouth_height=z_mouth, self_weight=False
    )
    mats = {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC}
    rows = []
    for size in mesh_sizes:
        for rest in ("cut pattern", "designed shape") if size == 0.2 else ("cut pattern",):
            spec = primitive_appendage(design, size, load_tape=GENERIC_TAPE, rim_tape=GENERIC_TAPE)
            am = build_appendage(spec, cond, mats)
            if rest == "designed shape":
                from envelopelab.validation.meshes import facet_rest_coordinates

                r_uv = am.model.rest_uv.copy()
                r_uv[am.skin_triangles] = facet_rest_coordinates(
                    am.model.positions, am.model.triangles[am.skin_triangles]
                )
                am = replace(am, model=replace(am.model, rest_uv=r_uv))
            result = from_preview(am.model, solve(am.model))
            m = appendage_metrics(am, result)
            rows.append(
                {
                    "skin_rest": rest,
                    "mesh_size_m": size,
                    "nodes": len(am.model.positions),
                    "status": result.status,
                    "converged": result.converged,
                    "projected_height_m": m.projected_height,
                    "designed_height_m": design.designed_height,
                    "area_distortion": distortion,
                    "skin_wrinkled_fraction": m.skin_wrinkled_fraction,
                    "lowest_fos": min(m.fos.values()),
                    "chamber_pressure_pa": m.chamber_pressure,
                }
            )
    return rows


def render_geometry(results: list[BenchmarkResult]) -> list[str]:
    """Markdown lines of the geometry table."""
    lines = [
        "| Benchmark | Computed | Reference | Unit | Error | Tolerance | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        tol = (
            f"{r.tolerance * 1000:g} mm"
            if r.kind == "absolute" and r.unit == "m"
            else f"{r.tolerance:g}"
        )
        lines.append(
            f"| {r.name} | {_fmt(r.value)} | {_fmt(r.reference)} | {r.unit} | "
            f"{_fmt_error(r)} | {tol} | {'pass' if r.passed else '**FAIL**'} |"
        )
    return lines


def render_markdown(results: list[BenchmarkResult], study: list[dict[str, Any]]) -> str:
    """The generated page ``docs/validation/special-shape-primitives.md``."""
    lines = [
        "# Special-shape primitives",
        "",
        "_Auto-generated by `python scripts/generate_validation_docs.py primitives` from "
        "`envelopelab.validation.primitives`. Do not edit by hand; "
        "`tests/benchmarks/test_primitive_benchmarks.py` fails if this page is stale._",
        "",
        "## Geometry against closed form",
        "",
        f"Primitives on a generic sphere of radius {SPHERE_RADIUS:g} m with "
        f"{SPHERE_GORES} gores, axis along the envelope normal at the equator (see "
        "[Special-shape primitives](../theory/special-shape-primitives.md)). Relative "
        "errors are fractions. The 8-gore dome row only records the distortion (no limit).",
        "",
        *render_geometry(results),
        "",
        "## Inflated dome, preview solver",
        "",
        f"A {STUDY_GORES}-gore dome (base radius 1 m, height 1.2 m) on the same envelope, "
        "fed through a 0.3 m hole, 100 °C internal, generic assumed fabric and tapes. The "
        "*designed shape* row rests the skin in its designed 3D facets instead of its cut "
        "pieces, isolating what the cut pattern changes. These preview results are **not "
        "verified**: a CalculiX trial on the 0.3 m model did not converge (its tension-field "
        "states kept changing between passes), as for the special-shape fixtures.",
        "",
        "| Skin rest | Mesh (m) | Nodes | Status | Projected height (m) | Designed (m) | "
        "Deviation | Skin wrinkled | Lowest FoS | Chamber (Pa) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in study:
        dev = row["projected_height_m"] / row["designed_height_m"] - 1.0
        status = row["status"] if row["converged"] else f"**{row['status']}**"
        lines.append(
            f"| {row['skin_rest']} | {row['mesh_size_m']:g} | {row['nodes']} | {status} | "
            f"{row['projected_height_m']:.4f} | {row['designed_height_m']:.4f} | "
            f"{dev * 100:+.1f} % | {row['skin_wrinkled_fraction'] * 100:.0f} % | "
            f"{row['lowest_fos']:.0f} | {row['chamber_pressure_pa']:.1f} |"
        )
    distortion = study[0]["area_distortion"] if study else float("nan")
    lines += [
        "",
        "At the pressures of a hot-air envelope (tens of Pa) fabric strains are of order",
        "1e-4, so any difference of a cut pattern from its designed shape larger than that",
        "(here the area distortion of flattening the doubly curved gores, "
        f"{distortion * 100:.2f} %)",
        "leaves cloth the pressure cannot take up: the solver reports it as wrinkled",
        "(uniaxially tensioned) skin and as a dome slightly taller than designed. The",
        "wrinkled fraction is a mesh-dependent indicator, not a prediction of visible",
        "wrinkles; the projected height is the shape measure to read.",
        "",
    ]
    return "\n".join(lines)
