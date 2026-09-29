r"""Special-shape feature benchmarks and a build-pack regression fixture.

The numbers behind ``docs/validation/special-shape-fixtures.md``. They are computed by
:func:`run_validation` (preview solver always; the verification solver through a
caller-supplied function, normally ``calculix_adapter.run_calculix``), stored in
``docs/validation/special-shape-fixtures.json`` and rendered by :func:`render_markdown`.
A test re-renders the page from the JSON (it must match the committed page) and slow
tests recompute the preview and CalculiX numbers against it.

Cases
-----
* **Hemispherical blister** (generic): a unit hemisphere whose rest shape is the
  hemisphere itself (a designed doubly curved skin), rim held rigidly, uniform chamber
  pressure :math:`p`. Near the apex the membrane resultant is :math:`N = p R / 2`
  (equilibrium of a pressurised sphere, AGENTS.md section 6.4); the protrusion must grow
  with :math:`p` and shrink with the fabric stiffness, in both solvers.
* **Rim-tape load transfer** (generic): a pressure-fed pod (designed cap, 0.5 m high,
  1.5 m footprint radius) on a spherical host patch (:math:`R = 8` m, 10 m above the
  mouth, 100 degC) crossed by two host load tapes. With the rim tape caught into the
  host tapes the pod load goes straight into them; without, it passes through the host
  fabric, whose largest major resultant at the rim must rise measurably.
* **Designed ease**: seams with declared ease are classified *designed ease*, never a
  seam error (the fixtures named by the caller).
* **Regression fixture** (:class:`FixtureCase`, described by the caller): imported
  feature geometry, construction checks and preview metrics of the named features,
  computed from the build pack with no design value in the source code. They check that
  a real pack runs end to end; they say nothing about its airworthiness.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import (
    AppendageModel,
    AppendageSpec,
    ChartHole,
    HostSurface,
    HostTape,
    PressureSpec,
    RimTapeSpec,
    build_appendage,
)
from envelopelab.features.metrics import appendage_metrics
from envelopelab.features.pressure import independent_chamber
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions, SolverModel
from envelopelab.solvers.simulation import SimulationResult, from_preview
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE, _isotropic

Verifier = Callable[[SolverModel, np.ndarray], SimulationResult]
#: Blister cases: (label, chamber pressure Pa, fabric stiffness Et N/m).
BLISTER_CASES = (
    ("baseline", 200.0, 1.0e5),
    ("pressure x2", 400.0, 1.0e5),
    ("stiffness x2", 200.0, 2.0e5),
)
#: Relative tolerance of preview vs verification (AGENTS.md: 5 %).
CROSS_SOLVER_TOLERANCE = 0.05
#: Smallest relative rise of the host-fabric resultant counted as measurable.
MEASURABLE_RISE = 0.20


def blister_model(pressure: float, stiffness: float, mesh_size: float = 0.15) -> AppendageModel:
    """Unit hemispherical blister on a rigid rim (see module docstring)."""
    t = np.linspace(0.0, 2.0 * math.pi, 64, endpoint=False)
    spec = AppendageSpec(
        "blister",
        np.column_stack([np.cos(t), np.sin(t)]),
        skin_mode="spherical_cap",
        cap_height=1.0,
        mesh_size=mesh_size,
        skin_zone="fabric",
        pressure=PressureSpec(
            "independent", chamber=independent_chamber("blister", pressure, 0.0, 0.0)
        ),
        intended={"dome_height_m": 1.0},
    )
    cond = OperatingConditions(1.2, 1.2, self_weight=False, label="blister, uniform pressure")
    return build_appendage(spec, cond, {"fabric": _isotropic(stiffness)})


def load_transfer_model(caught: bool, mesh_size: float = 0.3) -> AppendageModel:
    """Pressure-fed pod on a spherical host with rim tape caught or not (module docstring)."""
    t = np.linspace(0.0, 2.0 * math.pi, 200, endpoint=False)
    spec = AppendageSpec(
        "pod",
        np.column_stack([1.5 * np.cos(t), 1.5 * np.sin(t)]),
        skin_mode="spherical_cap",
        cap_height=0.5,
        host=HostSurface(8.0, 8.0, 0.0, 10.0, "generic sphere"),
        mesh_size=mesh_size,
        host_zone="host",
        skin_zone="skin",
        rim_tape=RimTapeSpec(GENERIC_TAPE, caught),
        host_tapes=[
            HostTape(f"tape u={u:+.1f}", np.array([[u, -4.0], [u, 4.0]]), GENERIC_TAPE)
            for u in (-0.8, 0.8)
        ],
        holes=[ChartHole("feed", (0.0, -0.5), 0.2)],
        pressure=PressureSpec("fed", 0.2),
    )
    cond = OperatingConditions.hot_air(
        celsius_to_kelvin(100.0), mouth_height=0.0, self_weight=False
    )
    return build_appendage(spec, cond, {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC})


def _apex_n(am: AppendageModel, result: SimulationResult) -> tuple[float, float]:
    x = result.positions
    tri = am.model.triangles
    apex = x[tri].mean(axis=1)[:, 2] > 0.8
    radius = float(np.linalg.norm(x[np.unique(tri[apex])], axis=1).mean())
    return float(result.principal[apex].mean()), radius


def _solve_both(am: AppendageModel, verify: Verifier | None) -> dict[str, SimulationResult]:
    out = {"preview": from_preview(am.model, solve(am.model))}
    if verify is not None:
        out["calculix"] = verify(am.model, out["preview"].positions)
    return out


@dataclass
class SpecialShapeData:
    """Computed benchmark data (JSON round trip)."""

    blister: list[dict[str, Any]] = field(default_factory=list)
    load_transfer: list[dict[str, Any]] = field(default_factory=list)
    ease: list[dict[str, Any]] = field(default_factory=list)
    fixture: dict[str, Any] = field(default_factory=dict)
    fixture_name: str = ""
    notes: list[str] = field(default_factory=list)
    calculix_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Plain dictionary."""
        return {
            "blister": self.blister,
            "load_transfer": self.load_transfer,
            "ease": self.ease,
            "fixture": self.fixture,
            "fixture_name": self.fixture_name,
            "notes": self.notes,
            "calculix_version": self.calculix_version,
        }

    def save(self, path: Path) -> None:
        """Write the JSON file."""
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> SpecialShapeData:
        """Read the JSON file."""
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def blister_rows(verify: Verifier | None = None) -> list[dict[str, Any]]:
    """Blister cases with both solvers (heights m, resultants N/m)."""
    rows = []
    for label, pressure, stiffness in BLISTER_CASES:
        am = blister_model(pressure, stiffness)
        for solver, res in _solve_both(am, verify).items():
            n, radius = _apex_n(am, res)
            m = appendage_metrics(am, res)
            rows.append(
                {
                    "case": label,
                    "pressure_pa": pressure,
                    "stiffness_n_per_m": stiffness,
                    "solver": solver,
                    "converged": res.converged,
                    "protrusion_m": m.projected_height,
                    "apex_n_n_per_m": n,
                    "analytic_apex_n_n_per_m": pressure * radius / 2.0,
                    "nodes": res.n_nodes,
                    "elements": res.n_elements,
                }
            )
    return rows


def load_transfer_rows(verify: Verifier | None = None) -> list[dict[str, Any]]:
    """Rim tape caught vs not caught, both solvers (N/m, N, m)."""
    rows = []
    for caught in (True, False):
        am = load_transfer_model(caught)
        for solver, res in _solve_both(am, verify).items():
            m = appendage_metrics(am, res)
            rows.append(
                {
                    "rim_tape_caught": caught,
                    "solver": solver,
                    "converged": res.converged,
                    "host_rim_max_n1_n_per_m": m.host_rim_max_n1,
                    "rim_tape_max_tension_n": m.rim_tape_max_tension,
                    "protrusion_m": m.projected_height,
                    "min_host_fos": min(m.fos["host"], m.fos["footprint"]),
                    "nodes": res.n_nodes,
                    "elements": res.n_elements,
                }
            )
    return rows


@dataclass
class FixtureCase:
    """A build-pack regression fixture and what to run on it (supplied by the caller).

    Attributes
    ----------
    name : str
        Fixture directory name under ``tests/fixtures``.
    features : tuple of str
        Features to run.
    materials, tapes : dict
        Fabric per zone and tape per tape name (generic assumed values).
    notes : list of str
        Known limitations printed on the page.
    """

    name: str
    features: tuple[str, ...]
    materials: dict[str, Any]
    tapes: dict[str, Any]
    notes: list[str] = field(default_factory=list)


def ease_rows(root: Path, fixtures: tuple[str, ...]) -> list[dict[str, Any]]:
    """Classification of every seam that declares designed ease in the fixtures."""
    from envelopelab.assembly.pipeline import import_build_pack
    from envelopelab.features.ease import classify_audit

    rows = []
    for name in fixtures:
        built = import_build_pack(root / "tests" / "fixtures" / name / "build-pack.yaml")
        classes = classify_audit(built.audit)
        for row in built.audit.rows:
            if row.designed_ease:
                rows.append(
                    {
                        "fixture": name,
                        "seam": row.seam_id,
                        "length_a_m": row.length_a,
                        "length_b_m": row.length_b,
                        "designed_ease_m": row.designed_ease,
                        "residual_m": row.mismatch,
                        "class": classes.of(row.seam_id),
                    }
                )
        rows.append(
            {
                "fixture": name,
                "seam": "(all)",
                "seam_errors": len(classes.errors),
                "class": "summary",
            }
        )
    return rows


def fixture_rows(root: Path, case: FixtureCase) -> dict[str, Any]:
    """Features of a regression fixture: geometry, construction checks, preview metrics."""
    from envelopelab.report.feature_workflow import FeatureRunConfig, feature_reality_check

    pack = root / "tests" / "fixtures" / case.name / "build-pack.yaml"
    mats, tapes = case.materials, case.tapes
    out: dict[str, Any] = {}
    for name in case.features:
        run = feature_reality_check(pack, name, FeatureRunConfig(mats, tapes))
        section = run.report.input.features[0]
        entry: dict[str, Any] = {
            "geometry": section.geometry,
            "geometry_findings": [list(f) for f in section.geometry_findings],
            "construction": [[c.check, c.severity] for c in section.construction],
            "preview": {
                "status": run.preview.status,
                "converged": run.preview.converged,
                "nodes": run.preview.n_nodes,
                "elements": run.preview.n_elements,
                "projected_height_m": run.preview_metrics.projected_height,
                "chamber_volume_m3": run.preview_metrics.chamber_volume,
                "skin_wrinkled_fraction": run.preview_metrics.skin_wrinkled_fraction,
            },
            "verified": run.report.verified,
        }
        if "preview" in section.tube:
            entry["preview"]["lean_deg"] = section.tube["preview"]["lean_deg"]
        out[name] = entry
    return out


def run_validation(
    root: Path,
    case: FixtureCase,
    verify: Verifier | None = None,
    calculix_version: str = "",
    ease_fixtures: tuple[str, ...] = ("special_shape",),
) -> SpecialShapeData:
    """Compute every row (the verification solver is optional)."""
    return SpecialShapeData(
        blister=blister_rows(verify),
        load_transfer=load_transfer_rows(verify),
        ease=ease_rows(root, (*ease_fixtures, case.name)),
        fixture=fixture_rows(root, case),
        fixture_name=case.name,
        notes=list(case.notes),
        calculix_version=calculix_version,
    )


# --------------------------------------------------------------------------------------
# Checks and page
# --------------------------------------------------------------------------------------


def blister_checks(rows: list[dict[str, Any]]) -> list[tuple[str, bool, str]]:
    """(check, passed, detail) of the blister trends and the apex resultant."""
    out = []
    solvers = sorted({r["solver"] for r in rows})
    for solver in solvers:
        by = {r["case"]: r for r in rows if r["solver"] == solver}
        base, hp, hs = by["baseline"], by["pressure x2"], by["stiffness x2"]
        conv = all(r["converged"] for r in by.values())
        out.append((f"{solver}: all blister cases converged", conv, ""))
        out.append(
            (
                f"{solver}: protrusion rises with pressure",
                conv and hp["protrusion_m"] > base["protrusion_m"],
                f"{base['protrusion_m']:.6f} -> {hp['protrusion_m']:.6f} m",
            )
        )
        out.append(
            (
                f"{solver}: protrusion falls with stiffness",
                conv and hs["protrusion_m"] < base["protrusion_m"],
                f"{base['protrusion_m']:.6f} -> {hs['protrusion_m']:.6f} m",
            )
        )
        err = abs(base["apex_n_n_per_m"] / base["analytic_apex_n_n_per_m"] - 1.0)
        out.append(
            (f"{solver}: apex resultant = p R / 2 within 2 %", err <= 0.02, f"{err * 100:.2f} %")
        )
    if len(solvers) == 2:
        for case, _, _ in BLISTER_CASES:
            a, b = (
                next(r for r in rows if r["case"] == case and r["solver"] == s) for s in solvers
            )
            rel = abs(a["protrusion_m"] - b["protrusion_m"]) / b["protrusion_m"]
            out.append(
                (
                    f"{case}: preview vs CalculiX protrusion within 5 %",
                    rel <= CROSS_SOLVER_TOLERANCE,
                    f"{rel:.2e}",
                )
            )
    return out


def load_transfer_checks(rows: list[dict[str, Any]]) -> list[tuple[str, bool, str]]:
    """(check, passed, detail): removing the rim-to-tape connection raises host stress."""
    out = []
    for solver in sorted({r["solver"] for r in rows}):
        caught = next(r for r in rows if r["solver"] == solver and r["rim_tape_caught"])
        loose = next(r for r in rows if r["solver"] == solver and not r["rim_tape_caught"])
        rise = loose["host_rim_max_n1_n_per_m"] / caught["host_rim_max_n1_n_per_m"] - 1.0
        conv = caught["converged"] and loose["converged"]
        out.append(
            (
                f"{solver}: host fabric N1 at the rim rises when the rim tape is not caught",
                conv and rise >= MEASURABLE_RISE,
                f"{caught['host_rim_max_n1_n_per_m']:.1f} -> "
                f"{loose['host_rim_max_n1_n_per_m']:.1f} N/m (+{rise * 100:.0f} %)",
            )
        )
    return out


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.4g}" if abs(v) >= 1e-3 or v == 0 else f"{v:.3e}"
    return str(v)


def render_markdown(data: SpecialShapeData) -> str:
    """The generated validation page."""
    lines = [
        "# Special-shape fixtures",
        "",
        "<!-- Generated by scripts/generate_validation_docs.py special from",
        "     envelopelab.validation.special_shapes; do not edit by hand. -->",
        "",
        "Benchmarks of the appendage model (`envelopelab.features`) and the "
        f"`{data.fixture_name}` build pack,",
        "which is a **regression fixture only**: it checks that a real special-shape pack",
        "imports, assembles, solves and reports with no design value in the source code. It",
        "is not a reference design and passing these rows says nothing about its",
        "airworthiness.",
        "",
        f"Verification solver: CalculiX {data.calculix_version or '(not run)'}. Preview =",
        "dynamic relaxation (never verified).",
        "",
        "## Hemispherical blister",
        "",
        "Unit hemisphere, rest shape = the hemisphere, rim held rigidly, uniform chamber",
        "pressure. Near the apex the resultant must be \\(N = pR/2\\).",
        "",
        "| case | p (Pa) | Et (N/m) | solver | converged | protrusion (m) | apex N (N/m) "
        "| pR/2 (N/m) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in data.blister:
        lines.append(
            f"| {r['case']} | {_fmt(r['pressure_pa'])} | {_fmt(r['stiffness_n_per_m'])} | "
            f"{r['solver']} | "
            f"{_fmt(r['converged'])} | {r['protrusion_m']:.6f} | {_fmt(r['apex_n_n_per_m'])} | "
            f"{_fmt(r['analytic_apex_n_n_per_m'])} |"
        )
    lines += ["", "| check | result | detail |", "|---|---|---|"]
    lines += [
        f"| {c} | {'PASS' if ok else 'FAIL'} | {d} |" for c, ok, d in blister_checks(data.blister)
    ]
    lines += [
        "",
        "## Rim-tape load transfer",
        "",
        "Pressure-fed pod (loss factor 0.2, assumed) on a spherical host patch crossed by two",
        "host load tapes; rim tape caught into the host tapes or stopping short of them.",
        "The CalculiX rows are the golden output of",
        "`tests/regression/test_feature_regressions.py`.",
        "",
        "| rim tape caught | solver | converged | host N1 at rim (N/m) | rim tape max (N) "
        "| min host FoS | protrusion (m) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in data.load_transfer:
        lines.append(
            f"| {_fmt(r['rim_tape_caught'])} | {r['solver']} | {_fmt(r['converged'])} | "
            f"{_fmt(r['host_rim_max_n1_n_per_m'])} | {_fmt(r['rim_tape_max_tension_n'])} | "
            f"{_fmt(r['min_host_fos'])} | {_fmt(r['protrusion_m'])} |"
        )
    lines += ["", "| check | result | detail |", "|---|---|---|"]
    lines += [
        f"| {c} | {'PASS' if ok else 'FAIL'} | {d} |"
        for c, ok, d in load_transfer_checks(data.load_transfer)
    ]
    lines += [
        "",
        "## Designed ease",
        "",
        "| fixture | seam | side A (m) | side B (m) | designed ease (m) | residual (m) | class |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in data.ease:
        if r["class"] == "summary":
            continue
        lines.append(
            f"| {r['fixture']} | {r['seam']} | {_fmt(r['length_a_m'])} | {_fmt(r['length_b_m'])} | "
            f"{_fmt(r['designed_ease_m'])} | {_fmt(r['residual_m'])} | {r['class']} |"
        )
    for r in data.ease:
        if r["class"] == "summary":
            lines.append(f"\n{r['fixture']}: {r['seam_errors']} seam errors.")
    lines += ["", f"## {data.fixture_name} (regression fixture)", ""]
    for name, entry in sorted(data.fixture.items()):
        lines += [f"### {name}", "", "| quantity | value |", "|---|---|"]
        for k, v in entry["geometry"].items():
            lines.append(f"| {k} | {_fmt(v)} |")
        for k, v in entry["preview"].items():
            lines.append(f"| preview {k} | {_fmt(v)} |")
        lines.append(f"| verified | {_fmt(entry['verified'])} |")
        lines += ["", "| construction check | result |", "|---|---|"]
        lines += [f"| {c} | {s} |" for c, s in entry["construction"]]
        for sev, msg in entry["geometry_findings"]:
            lines.append(f"\n**{sev}**: {msg}")
        lines.append("")
    lines += [
        "## Known limitations",
        "",
        *[f"- {note}" for note in data.notes],
        "- Appendage external aerodynamics and turbulent flow are outside the model scope.",
        "",
    ]
    return "\n".join(lines)
