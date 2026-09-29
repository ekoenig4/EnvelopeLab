r"""Reality Check report: intended reference shape vs the shape predicted from the patterns.

The report puts three states side by side:

1. **As-sewn rest shape**: the assembled patterns in their starting geometry (a geometric
   placement, never a solved shape);
2. **Inflated predicted shape**: the preview solver (dynamic relaxation), always labelled
   *preview*;
3. **Inflated verified shape**: the CalculiX verification solve, labelled *verified* only
   when :class:`VerificationPolicy` accepts it.

For each state it gives the signed distance to the registered reference mesh (heat map
and statistics), height, width, volume and the projected feature dimensions; then the
critical load paths, factors of safety, findings, construction checks, seam-length
classification, solver convergence and the sensitivity sweep. It exports HTML (inline
SVG), PDF (vector, :mod:`envelopelab.report.pdf`), JSON and CSV.

Verification rule
-----------------
The report is ``verified`` only when a CalculiX result is present, its solver reported
``converged`` (every pass settled, the exact-law held job below the residual target and
the global force balance closed), it carries no error finding, and the solver settings
it ran with are at least as strict as the documented tolerances (residual target
:math:`\le 10^{-5}` relative, force balance :math:`\le 0.5\,\%`; AGENTS.md section 6.4).
A preview result is never ``verified``, whatever its convergence. An unconverged result is
shown with a *not converged* label in every view and export.

Scope: appendage external aerodynamics (wind, climb, turbulent flow round the appendage)
are outside the model; the report says so in its findings.
"""

from __future__ import annotations

import csv
import html
import io
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from envelopelab.features.construction import ConstructionCheck
from envelopelab.features.ease import SeamClassification
from envelopelab.features.metrics import REQUIRED_FOS, AppendageMetrics
from envelopelab.io.reference_mesh import (
    DeviationStats,
    ReferenceMesh,
    Registration,
    deviation_stats,
    signed_distance,
)
from envelopelab.report.pdf import PdfCanvas
from envelopelab.report.sensitivity import PARAMETERS, SensitivityResult
from envelopelab.solvers.membrane import FloatArray, IntArray
from envelopelab.solvers.model import SolverModel
from envelopelab.solvers.simulation import SimulationResult

StateKind = Literal["as_sewn", "preview", "verification"]
Severity = Literal["info", "warning", "error"]

SCOPE_NOTE = (
    "Appendage external aerodynamics (wind, climb, turbulent flow round appendages) are "
    "outside the model scope; shapes and loads are for still air."
)
#: Diverging palette (inside/blue - neutral - outside/red) for signed distance.
DIVERGING = ["#184f95", "#6da7ec", "#f0efec", "#ec8a86", "#b3302f"]
#: Sequential palette (light to dark blue) for stress resultants.
SEQUENTIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#104281"]
NEUTRAL = "#c8c7c2"
STATUS = {"good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b"}


@dataclass(frozen=True)
class VerificationPolicy:
    """Documented tolerances a CalculiX result must meet to be called verified.

    Attributes
    ----------
    residual_target : float
        Largest allowed relative out-of-balance the solver may have used, -.
    balance_tolerance : float
        Largest allowed global force-balance tolerance, - (AGENTS.md: 0.5 %).
    """

    residual_target: float = 1e-5
    balance_tolerance: float = 5e-3

    def check(self, result: SimulationResult | None) -> tuple[bool, str]:
        """(verified, reason) for a result (see module docstring)."""
        if result is None:
            return False, "no CalculiX verification solve"
        if result.solver != "calculix":
            return False, f"{result.solver} is not the verification solver"
        if not result.converged:
            return False, f"CalculiX solve not converged (status: {result.status})"
        if result.errors:
            return False, "CalculiX result has errors: " + "; ".join(
                f.message for f in result.errors
            )
        s = result.manifest.solver_settings
        target = float(s.get("residual_target", math.inf))
        balance = float(s.get("balance_tolerance", math.inf))
        if target > self.residual_target or balance > self.balance_tolerance:
            return False, (
                f"CalculiX ran with residual target {target:g} / balance {balance:g}, looser "
                f"than the documented {self.residual_target:g} / {self.balance_tolerance:g}"
            )
        return True, (f"CalculiX converged (residual target {target:g}, force balance {balance:g})")


@dataclass
class ShapeState:
    """One of the three states compared by the report.

    Attributes
    ----------
    kind : {"as_sewn", "preview", "verification"}
        State.
    positions : ndarray, shape (n, 3)
        Node positions, m.
    triangles : ndarray of int, shape (m, 3)
        Elements.
    result : SimulationResult, optional
        The solve behind a preview or verification state.
    verified : bool
        Only for an accepted verification state.
    """

    kind: StateKind
    positions: FloatArray
    triangles: IntArray
    result: SimulationResult | None = None
    verified: bool = False

    @property
    def label(self) -> str:
        """Label shown on every view and export of this state."""
        if self.kind == "as_sewn":
            return "AS-SEWN REST SHAPE (geometry, not solved)"
        if self.result is None:
            return "NOT AVAILABLE"
        if self.kind == "preview":
            if self.result.converged:
                return "PREDICTED - PREVIEW SOLVER (converged, not verified)"
            return f"PREVIEW - NOT CONVERGED ({self.result.status}); not a prediction"
        if self.verified:
            return "VERIFIED - CalculiX (converged within documented tolerances)"
        if self.result.converged:
            return "CalculiX - NOT VERIFIED (see findings)"
        return f"CalculiX - NOT CONVERGED ({self.result.status}); NOT VERIFIED"


@dataclass
class FeatureSection:
    """Everything the report shows for one feature.

    Attributes
    ----------
    name, kind : str
        Feature.
    geometry : dict
        Measured imported geometry (units in keys).
    geometry_findings : list of (str, str)
        (severity, message).
    construction : list of ConstructionCheck
        Construction-sequence checks.
    preview, verification : AppendageMetrics, optional
        Metrics of each solve.
    as_sewn_height : float, optional
        Projected height of the as-sewn state, m.
    tube : dict of str to dict
        Tube metrics per solver (``preview``, ``verification``).
    notes : list of str
        Build notes (mesh conformity adjustments).
    pressure : dict
        Chamber pressure derivation.
    """

    name: str
    kind: str
    geometry: dict[str, Any] = field(default_factory=dict)
    geometry_findings: list[tuple[str, str]] = field(default_factory=list)
    construction: list[ConstructionCheck] = field(default_factory=list)
    preview: AppendageMetrics | None = None
    verification: AppendageMetrics | None = None
    as_sewn_height: float | None = None
    tube: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    pressure: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportInput:
    """Inputs of one Reality Check report (all SI).

    Attributes
    ----------
    title : str
        Report title.
    model : SolverModel
        The model the states belong to (a whole envelope or a feature sub-model).
    as_sewn : ndarray, shape (n, 3)
        As-sewn rest positions, m.
    preview, verification : SimulationResult, optional
        Solves of ``model``.
    reference : ReferenceMesh, optional
        Reference mesh already moved into the model frame.
    registration : Registration, optional
        How it was registered.
    reference_volume : float, optional
        Volume written in the reference's title, m^3.
    reference_volume_text : str
        Where it came from.
    volumes : dict of str to (float, str)
        Further volumes to compare, m^3, with an explanation (e.g. the as-sewn envelope).
    features : list of FeatureSection
        Feature results.
    seam_classes : SeamClassification, optional
        Seam-length classification of the build pack.
    sensitivity : SensitivityResult, optional
        Sweep.
    notes : list of str
        Extra findings (info).
    view_direction : ndarray, shape (3,), optional
        Horizontal viewing direction of the side views (default chosen from the model).
    submodel : bool
        The model is a feature sub-model (a host patch): whole-model extents and the
        capped patch volume are not reported, and the reference is compared locally.
    """

    title: str
    model: SolverModel
    as_sewn: FloatArray
    preview: SimulationResult | None = None
    verification: SimulationResult | None = None
    reference: ReferenceMesh | None = None
    registration: Registration | None = None
    reference_volume: float | None = None
    reference_volume_text: str = ""
    volumes: dict[str, tuple[float, str]] = field(default_factory=dict)
    features: list[FeatureSection] = field(default_factory=list)
    seam_classes: SeamClassification | None = None
    sensitivity: SensitivityResult | None = None
    notes: list[str] = field(default_factory=list)
    view_direction: FloatArray | None = None
    submodel: bool = False


@dataclass
class Finding:
    """A report finding (severity, source, message)."""

    severity: Severity
    source: str
    message: str


@dataclass
class RealityCheckReport:
    """The computed report (build with :func:`build_report`)."""

    input: ReportInput
    states: list[ShapeState]
    verified: bool
    verification_reason: str
    dimensions: list[dict[str, Any]]
    deviation: dict[str, FloatArray]
    deviation_stats: dict[str, DeviationStats]
    load_paths: list[dict[str, Any]]
    fos: list[dict[str, Any]]
    convergence: list[dict[str, Any]]
    findings: list[Finding]

    @property
    def status_line(self) -> str:
        """One-line verification status for banners and file headers."""
        if self.verified:
            return f"VERIFIED: {self.verification_reason}"
        return f"NOT VERIFIED: {self.verification_reason}"

    # ---------------------------------------------------------------- exports

    def to_dict(self) -> dict[str, Any]:
        """Machine-readable report (units in keys)."""
        inp = self.input
        return {
            "format": "envelopelab.reality-check",
            "format_version": 1,
            "title": inp.title,
            "verified": self.verified,
            "verification": self.status_line,
            "states": [
                {
                    "kind": s.kind,
                    "label": s.label,
                    "solver": s.result.solver if s.result else None,
                    "status": s.result.status if s.result else "geometry",
                    "converged": s.result.converged if s.result else None,
                    "verified": s.verified,
                }
                for s in self.states
            ],
            "dimensions": self.dimensions,
            "deviation": {k: v.as_dict() for k, v in self.deviation_stats.items()},
            "registration": inp.registration.as_dict() if inp.registration else None,
            "reference": {
                "source": inp.reference.source if inp.reference else None,
                "mesh_volume_m3": inp.reference.volume if inp.reference else None,
                "title_volume_m3": inp.reference_volume,
                "title_text": inp.reference_volume_text,
            },
            "volumes": {k: {"value_m3": v, "note": n} for k, (v, n) in inp.volumes.items()},
            "load_paths": self.load_paths,
            "fos": self.fos,
            "required_fos": REQUIRED_FOS,
            "required_fos_source": "assumed",
            "convergence": self.convergence,
            "features": [_feature_dict(f) for f in inp.features],
            "seam_classification": inp.seam_classes.counts() if inp.seam_classes else None,
            "seam_errors": inp.seam_classes.errors if inp.seam_classes else [],
            "sensitivity": inp.sensitivity.as_dict() if inp.sensitivity else None,
            "findings": [f.__dict__ for f in self.findings],
            "scope": SCOPE_NOTE,
        }

    def to_json(self, path: str | Path) -> Path:
        """Write the JSON export."""
        p = Path(path)
        p.write_text(json.dumps(_clean(self.to_dict()), indent=2), encoding="utf-8")
        return p

    def csv_tables(self) -> dict[str, list[list[Any]]]:
        """CSV tables (file name -> rows, header first)."""
        tables: dict[str, list[list[Any]]] = {}
        header: list[Any] = ["state", "label", "solver", "status", "converged", "verified"]
        tables["states.csv"] = [header] + [
            [
                s.kind,
                s.label,
                s.result.solver if s.result else "",
                s.result.status if s.result else "geometry",
                s.result.converged if s.result else "",
                s.verified,
            ]
            for s in self.states
        ]
        tables["dimensions.csv"] = [
            ["quantity", "unit", "as_sewn", "preview", "verification", "reference", "note"]
        ] + [
            [
                d["quantity"],
                d["unit"],
                d.get("as_sewn"),
                d.get("preview"),
                d.get("verification"),
                d.get("reference"),
                d.get("note", ""),
            ]
            for d in self.dimensions
        ]
        tables["deviation.csv"] = [
            ["state", "mean_m", "rms_m", "max_outside_m", "max_inside_m", "p95_abs_m", "count"]
        ] + [
            [k, v.mean, v.rms, v.max_outside, v.max_inside, v.p95_abs, v.count]
            for k, v in self.deviation_stats.items()
        ]
        tables["load_paths.csv"] = [
            ["state", "tape", "max_tension_n", "breaking_strength_n", "fos", "source"]
        ] + [
            [
                r["state"],
                r["tape"],
                r["max_tension_n"],
                r["breaking_strength_n"],
                r["fos"],
                r["source"],
            ]
            for r in self.load_paths
        ]
        tables["fos.csv"] = [
            ["state", "zone", "max_n1_n_per_m", "strength_n_per_m", "fos", "required", "passed"]
        ] + [
            [
                r["state"],
                r["zone"],
                r["max_n1_n_per_m"],
                r["strength_n_per_m"],
                r["fos"],
                REQUIRED_FOS,
                r["passed"],
            ]
            for r in self.fos
        ]
        tables["convergence.csv"] = [
            [
                "state",
                "solver",
                "status",
                "converged",
                "iterations",
                "final_residual",
                "residual_measure",
                "nodes",
                "elements",
                "elapsed_s",
            ]
        ] + [
            [
                c["state"],
                c["solver"],
                c["status"],
                c["converged"],
                c["iterations"],
                c["final_residual"],
                c["residual_measure"],
                c["nodes"],
                c["elements"],
                c["elapsed_s"],
            ]
            for c in self.convergence
        ]
        feat: list[list[Any]] = [
            ["feature", "solver", "status", "converged", "verified", "quantity", "value", "unit"]
        ]
        for f in self.input.features:
            for m in (f.preview, f.verification):
                if m is None:
                    continue
                for q, v, u in m.rows():
                    feat.append([f.name, m.solver, m.status, m.converged, m.verified, q, v, u])
            for solver, values in f.tube.items():
                for key, value in values.items():
                    if isinstance(value, float):
                        feat.append([f.name, solver, "", "", "", key, value, ""])
        tables["features.csv"] = feat
        sens = [
            [
                "parameter",
                "metric",
                "low_value",
                "high_value",
                "metric_low",
                "metric_baseline",
                "metric_high",
                "converged",
                "slope",
                "solver",
            ]
        ]
        if self.input.sensitivity is not None:
            for r in self.input.sensitivity.sensitivities():
                sens.append(
                    [
                        r["parameter"],
                        r["metric"],
                        r["low_value"],
                        r["high_value"],
                        r["metric_low"],
                        r["metric_baseline"],
                        r["metric_high"],
                        r["converged"],
                        r["slope"],
                        self.input.sensitivity.solver,
                    ]
                )
        tables["sensitivity.csv"] = sens
        tables["findings.csv"] = [["severity", "source", "message"]] + [
            [f.severity, f.source, f.message] for f in self.findings
        ]
        return tables

    def write_csv(self, directory: str | Path) -> list[Path]:
        """Write every CSV table into ``directory``; each starts with the status line."""
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        out = []
        for name, rows in self.csv_tables().items():
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow([f"# {self.status_line}"])
            writer.writerows(rows)
            p = d / name
            p.write_text(buffer.getvalue(), encoding="utf-8")
            out.append(p)
        return out

    def to_html(self, path: str | Path) -> Path:
        """Write the self-contained HTML report."""
        p = Path(path)
        p.write_text(render_html(self), encoding="utf-8")
        return p

    def to_pdf(self, path: str | Path) -> Path:
        """Write the vector PDF report."""
        return render_pdf(self).save(path)

    def write_all(self, directory: str | Path, stem: str = "reality-check") -> dict[str, Path]:
        """Write HTML, PDF, JSON and CSV exports into ``directory``."""
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        out = {
            "html": self.to_html(d / f"{stem}.html"),
            "pdf": self.to_pdf(d / f"{stem}.pdf"),
            "json": self.to_json(d / f"{stem}.json"),
        }
        for p in self.write_csv(d / f"{stem}-csv"):
            out[p.name] = p
        return out


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    if isinstance(value, np.floating | float):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _feature_dict(f: FeatureSection) -> dict[str, Any]:
    return {
        "name": f.name,
        "kind": f.kind,
        "geometry": f.geometry,
        "geometry_findings": [{"severity": s, "message": m} for s, m in f.geometry_findings],
        "construction": [c.__dict__ for c in f.construction],
        "as_sewn_projected_height_m": f.as_sewn_height,
        "preview": f.preview.as_dict() if f.preview else None,
        "verification": f.verification.as_dict() if f.verification else None,
        "tube": f.tube,
        "notes": f.notes,
        "pressure": f.pressure,
    }


# --------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------


def _extent(x: FloatArray) -> tuple[float, float]:
    height = float(x[:, 2].max() - x[:, 2].min())
    xy = x[:, :2] - x[:, :2].mean(axis=0)
    _, _, vt = np.linalg.svd(xy, full_matrices=False)
    widths = [float(np.ptp(xy @ v)) for v in vt]
    return height, max(widths)


def _zone_fos(model: SolverModel, result: SimulationResult, state: str) -> list[dict[str, Any]]:
    out = []
    for zi, zone in enumerate(model.zone_names):
        tris = np.flatnonzero(model.tri_zone == zi)
        if not len(tris):
            continue
        mat = model.materials[zone]
        strength = min(mat.strength_warp.value, mat.strength_weft.value)
        n1 = float(result.principal[tris, 0].max())
        fos = strength / n1 if n1 > 0 else math.inf
        out.append(
            {
                "state": state,
                "zone": zone,
                "max_n1_n_per_m": n1,
                "strength_n_per_m": strength,
                "fos": fos,
                "passed": result.converged and fos >= REQUIRED_FOS,
                "source": mat.strength_warp.source,
            }
        )
    return out


def _load_paths(
    model: SolverModel, result: SimulationResult, state: str, top: int = 8
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cable in model.cables:
        t = result.tape_tensions.get(cable.name)
        if t is None or not len(t):
            continue
        tmax = float(t.max())
        strength = cable.material.breaking_strength.value
        rows.append(
            {
                "state": state,
                "tape": cable.name,
                "max_tension_n": tmax,
                "breaking_strength_n": strength,
                "fos": strength / tmax if tmax > 0 else math.inf,
                "source": cable.material.breaking_strength.source,
            }
        )
    rows.sort(key=lambda r: -float(r["max_tension_n"]))
    return rows[:top]


def build_report(inp: ReportInput, policy: VerificationPolicy | None = None) -> RealityCheckReport:
    """Compute the Reality Check report.

    Parameters
    ----------
    inp : ReportInput
        Model, states, reference and feature results.
    policy : VerificationPolicy, optional
        Documented tolerances for ``verified`` (defaults in the class).

    Returns
    -------
    RealityCheckReport
        Dimensions (m, m^3), signed deviations (m), load paths (N), factors of safety,
        convergence rows and findings.
    """
    policy = policy or VerificationPolicy()
    verified, reason = policy.check(inp.verification)
    tri = inp.model.triangles
    states = [ShapeState("as_sewn", inp.as_sewn, tri)]
    if inp.preview is not None:
        states.append(ShapeState("preview", inp.preview.positions, tri, inp.preview))
    if inp.verification is not None:
        states.append(
            ShapeState("verification", inp.verification.positions, tri, inp.verification, verified)
        )

    from envelopelab.solvers.dynamic_relaxation import ModelEvaluator

    ev = ModelEvaluator(inp.model)
    dims: list[dict[str, Any]] = []
    rows: dict[str, dict[str, Any]] = {}

    def put(quantity: str, unit: str, state: str, value: float | None, note: str = "") -> None:
        row = rows.setdefault(quantity, {"quantity": quantity, "unit": unit, "note": note})
        row[state] = value
        if note:
            row["note"] = note

    for s in states:
        if not inp.submodel:
            h, w = _extent(s.positions)
            put("height (vertical extent)", "m", s.kind, h)
            put("width (largest horizontal extent)", "m", s.kind, w)
            volume = s.result.volume if s.result else ev.volume(s.positions)
            put("gas volume of the model", "m^3", s.kind, volume)
        chambers = s.result.chamber_volumes if s.result else ev.chamber_volumes(s.positions)
        for name, v in chambers.items():
            if name != "envelope":
                put(f"volume of {name}", "m^3", s.kind, v)
    if inp.reference is not None and not inp.submodel:
        h, w = _extent(inp.reference.vertices)
        put("height (vertical extent)", "m", "reference", h, "registered reference mesh")
        put("width (largest horizontal extent)", "m", "reference", w)
    for name, (value, note) in inp.volumes.items():
        put(name, "m^3", "as_sewn", value, note)
    if inp.reference_volume is not None:
        put(
            "reference volume (title notation)",
            "m^3",
            "reference",
            inp.reference_volume,
            inp.reference_volume_text,
        )
        if inp.reference is not None:
            put(
                "reference mesh volume",
                "m^3",
                "reference",
                inp.reference.volume,
                "divergence theorem",
            )
    for f in inp.features:
        q = f"{f.name}: projected height"
        if f.as_sewn_height is not None:
            put(q, "m", "as_sewn", f.as_sewn_height)
        for kind, m in (("preview", f.preview), ("verification", f.verification)):
            if m is not None:
                put(q, "m", kind, m.projected_height)
        if "reference_projected_height_m" in f.geometry:
            put(
                q,
                "m",
                "reference",
                f.geometry["reference_projected_height_m"],
                "measured on the registered reference mesh",
            )
        intended = f.preview or f.verification
        if intended is not None:
            for key, value in intended.intended.items():
                if key.endswith("_m") and "height" in key:
                    put(f"{f.name}: intended projected height", "m", "reference", value, key)
        for kind, values in f.tube.items():
            for key in ("lean_deg", "length_m", "tip_displacement_m", "base_reaction_n"):
                if key in values:
                    unit = {"lean_deg": "deg", "base_reaction_n": "N"}.get(key, "m")
                    put(
                        f"{f.name}: {key.rsplit('_', 1)[0].replace('_', ' ')}",
                        unit,
                        kind,
                        values[key],
                    )
            if "intended_lean_deg" in values:
                put(f"{f.name}: lean", "deg", "reference", values["intended_lean_deg"], "intended")
        for key in ("footprint_width_m", "footprint_height_m", "footprint_rim_m", "skin_rim_m"):
            if key in f.geometry:
                put(
                    f"{f.name}: {key[:-2].replace('_', ' ')}",
                    "m",
                    "as_sewn",
                    f.geometry[key],
                    "from the patterns",
                )
    dims = list(rows.values())

    deviation: dict[str, FloatArray] = {}
    stats: dict[str, DeviationStats] = {}
    if inp.reference is not None:
        for s in states:
            d = signed_distance(s.positions, inp.reference)
            deviation[s.kind] = d
            stats[s.kind] = deviation_stats(d)

    load_paths: list[dict[str, Any]] = []
    fos: list[dict[str, Any]] = []
    convergence: list[dict[str, Any]] = []
    findings: list[Finding] = []
    for s in states[1:]:
        assert s.result is not None
        r = s.result
        load_paths += _load_paths(inp.model, r, s.kind)
        fos += _zone_fos(inp.model, r, s.kind)
        convergence.append(
            {
                "state": s.kind,
                "solver": r.solver,
                "solver_version": r.solver_version,
                "status": r.status,
                "converged": r.converged,
                "iterations": len(r.iteration_history),
                "final_residual": r.residual_history[-1][1] if r.residual_history else math.nan,
                "residual_measure": r.residual_measure,
                "nodes": r.n_nodes,
                "elements": r.n_elements,
                "elapsed_s": r.elapsed,
                "label": s.label,
            }
        )
        if not r.converged:
            findings.append(
                Finding(
                    "error",
                    r.solver,
                    f"{s.label}: its shape, stresses and forces are NOT an equilibrium",
                )
            )
        for solver_finding in r.findings:
            findings.append(Finding(solver_finding.severity, r.solver, solver_finding.message))
    if inp.verification is not None and not verified:
        findings.append(Finding("error", "verification", reason))
    elif inp.verification is None:
        findings.append(
            Finding(
                "warning", "verification", "no CalculiX solve: nothing in this report is verified"
            )
        )
    for row in fos:
        if row["fos"] < REQUIRED_FOS:
            findings.append(
                Finding(
                    "error",
                    "factor of safety",
                    f"{row['state']}: zone {row['zone']} FoS {row['fos']:.2f} below the required "
                    f"{REQUIRED_FOS:g} (assumed)",
                )
            )
    for row in load_paths:
        if row["fos"] < REQUIRED_FOS:
            findings.append(
                Finding(
                    "error",
                    "factor of safety",
                    f"{row['state']}: tape {row['tape']} FoS {row['fos']:.2f} below "
                    f"{REQUIRED_FOS:g}",
                )
            )
    for f in inp.features:
        for sev, msg in f.geometry_findings:
            findings.append(Finding("error" if sev == "error" else "warning", f.name, msg))
        for c in f.construction:
            if c.severity != "ok":
                findings.append(
                    Finding(c.severity, f"{f.name} construction", f"{c.check}: {c.message}")
                )
        for m in (f.preview, f.verification):
            if m is None:
                continue
            if m.pucker_segments:
                findings.append(
                    Finding(
                        "warning",
                        f.name,
                        f"{m.solver}: predicted pucker at rim segments {m.pucker_segments}",
                    )
                )
            for zone, value in m.fos.items():
                if value < REQUIRED_FOS:
                    findings.append(
                        Finding(
                            "error",
                            f.name,
                            f"{m.solver}: {zone} FoS {value:.2f} below {REQUIRED_FOS:g}",
                        )
                    )
        for note in f.notes:
            findings.append(Finding("info", f"{f.name} mesh", note))
    if inp.seam_classes is not None:
        for sid in inp.seam_classes.errors:
            findings.append(
                Finding(
                    "error",
                    "seam audit",
                    f"seam {sid}: length mismatch beyond tolerance (seam error)",
                )
            )
    if inp.registration is not None:
        reg = inp.registration
        findings.append(
            Finding(
                "info" if reg.converged else "warning",
                "registration",
                f"ICP ({reg.backend}): RMS {reg.rmse * 1000:.1f} mm, fitness {reg.fitness:.2f}, "
                f"{reg.iterations} iterations" + ("" if reg.converged else " (not converged)"),
            )
        )
    for note in inp.notes:
        findings.append(Finding("info", "report", note))
    findings.append(Finding("info", "scope", SCOPE_NOTE))
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: order[f.severity])
    return RealityCheckReport(
        inp,
        states,
        verified,
        reason,
        dims,
        deviation,
        stats,
        load_paths,
        fos,
        convergence,
        findings,
    )


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------


def _hex(color: str) -> tuple[float, float, float]:
    return (int(color[1:3], 16) / 255, int(color[3:5], 16) / 255, int(color[5:7], 16) / 255)


def _ramp(
    values: FloatArray, lo: float, hi: float, palette: Sequence[str]
) -> list[tuple[float, float, float]]:
    stops = np.array([_hex(c) for c in palette])
    t = np.clip((values - lo) / max(hi - lo, 1e-300), 0.0, 1.0) * (len(palette) - 1)
    k = np.minimum(t.astype(int), len(palette) - 2)
    f = (t - k)[:, None]
    rgb = stops[k] * (1 - f) + stops[k + 1] * f
    return [tuple(map(float, c)) for c in rgb]  # type: ignore[misc]


@dataclass
class _View:
    polygons: list[tuple[list[tuple[float, float]], tuple[float, float, float]]]
    label: str
    kind: str


def _views(report: RealityCheckReport) -> tuple[list[_View], str, tuple[float, float], list[str]]:
    inp = report.input
    all_pts = np.vstack([s.positions for s in report.states])
    d = inp.view_direction
    if d is None:
        # Look along the horizontal direction of least spread (see the widest profile).
        xy = all_pts[:, :2] - all_pts[:, :2].mean(axis=0)
        _, _, vt = np.linalg.svd(xy, full_matrices=False)
        d = np.array([vt[1, 0], vt[1, 1], 0.0])
    d = np.asarray(d, dtype=np.float64)
    d = d / np.linalg.norm(d)
    e1 = np.cross(np.array([0.0, 0.0, 1.0]), d)
    e1 /= np.linalg.norm(e1)
    if report.deviation:
        span = max(float(np.percentile(np.abs(v), 98)) for v in report.deviation.values()) or 1.0
        mode, rng, pal = "deviation", (-span, span), DIVERGING
    else:
        vals = [s.result.principal[:, 0] for s in report.states if s.result is not None]
        top = max((float(np.percentile(v, 98)) for v in vals), default=1.0) or 1.0
        mode, rng, pal = "n1", (0.0, top), SEQUENTIAL
    views = []
    for s in report.states:
        x = s.positions
        tri = s.triangles
        depth = x[tri].mean(axis=1) @ d
        order = np.argsort(depth)[::-1]
        if mode == "deviation":
            per_tri = report.deviation[s.kind][tri].mean(axis=1)
            colors = _ramp(per_tri, rng[0], rng[1], pal)
        elif s.result is not None:
            colors = _ramp(s.result.principal[:, 0], rng[0], rng[1], pal)
        else:
            colors = [_hex(NEUTRAL)] * len(tri)
        polys = []
        for t in order:
            pts = [(float(x[i] @ e1), float(x[i, 2])) for i in tri[t]]
            polys.append((pts, colors[t]))
        views.append(_View(polys, s.label, s.kind))
    return views, mode, rng, list(pal)


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float | np.floating):
        if not math.isfinite(float(v)):
            return "-"
        a = abs(float(v))
        return f"{v:.4g}" if a >= 1e-3 or a == 0 else f"{v:.3e}"
    return str(v)


def _svg_view(
    view: _View, bounds: tuple[float, float, float, float], width: int = 300, height: int = 300
) -> str:
    x0, y0, x1, y1 = bounds
    scale = min((width - 20) / max(x1 - x0, 1e-9), (height - 20) / max(y1 - y0, 1e-9))
    parts = []
    for pts, color in view.polygons:
        coords = " ".join(
            f"{10 + (px - x0) * scale:.1f},{height - 10 - (py - y0) * scale:.1f}" for px, py in pts
        )
        fill = "#{:02x}{:02x}{:02x}".format(*(int(round(c * 255)) for c in color))
        parts.append(
            f'<polygon points="{coords}" fill="{fill}" stroke="{fill}" stroke-width="0.3"/>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="{html.escape(view.label)}">' + "".join(parts) + "</svg>"
    )


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(_fmt(c))}</td>" for c in r) + "</tr>" for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _banner_color(kind: str, state: ShapeState) -> str:
    if kind == "as_sewn":
        return NEUTRAL
    if state.result is None or not state.result.converged:
        return STATUS["critical"]
    if kind == "verification" and state.verified:
        return STATUS["good"]
    return STATUS["warning"]


def render_html(report: RealityCheckReport) -> str:
    """Self-contained HTML report (inline SVG views, tables, status labels)."""
    inp = report.input
    views, mode, rng, pal = _views(report)
    pts = [p for v in views for poly, _ in v.polygons for p in poly]
    arr = np.array(pts) if pts else np.zeros((1, 2))
    bounds = (
        float(arr[:, 0].min()),
        float(arr[:, 1].min()),
        float(arr[:, 0].max()),
        float(arr[:, 1].max()),
    )
    banner = STATUS["good"] if report.verified else STATUS["critical"]
    panels = []
    for view, state in zip(views, report.states, strict=True):
        color = _banner_color(view.kind, state)
        panels.append(
            f'<figure class="state"><div class="tag" style="border-color:{color}">'
            f'<span class="dot" style="background:{color}"></span>{html.escape(view.label)}</div>'
            f"{_svg_view(view, bounds)}</figure>"
        )
    unit = (
        "signed distance to reference, m (blue inside, red outside)"
        if mode == "deviation"
        else "major principal resultant N1, N/m"
    )
    stops = ", ".join(f"{c} {k * 100 / (len(pal) - 1):.0f}%" for k, c in enumerate(pal))
    legend = (
        f'<div class="legend"><span>{_fmt(rng[0])}</span>'
        f'<span class="bar" style="background:linear-gradient(90deg,{stops})"></span>'
        f"<span>{_fmt(rng[1])}</span><span class='muted'>{html.escape(unit)}</span></div>"
    )
    dim_rows = [
        [
            d["quantity"],
            d["unit"],
            d.get("as_sewn"),
            d.get("preview"),
            d.get("verification"),
            d.get("reference"),
            d.get("note", ""),
        ]
        for d in report.dimensions
    ]
    dev_rows = [
        [k, v.mean, v.rms, v.max_outside, v.max_inside, v.p95_abs, v.count]
        for k, v in report.deviation_stats.items()
    ]
    feat_html = []
    for f in inp.features:
        rows = []
        for m in (f.preview, f.verification):
            if m is not None:
                label = (
                    "VERIFIED"
                    if m.verified
                    else ("preview" if m.solver != "calculix" else "CalculiX, not verified")
                )
                rows += [
                    [f"{m.solver} ({label}{'' if m.converged else ', NOT CONVERGED'})", q, v, u]
                    for q, v, u in m.rows()
                ]
        for solver, values in f.tube.items():
            rows += [[solver, k, v, ""] for k, v in values.items() if isinstance(v, float)]
        geo = [[k, v] for k, v in f.geometry.items()]
        cons = [[c.check, c.severity, c.message] for c in f.construction]
        feat_html.append(
            f"<h3>{html.escape(f.name)} ({html.escape(f.kind)})</h3>"
            + _table(["solver", "quantity", "value", "unit"], rows)
            + "<h4>Imported geometry</h4>"
            + _table(["quantity", "value"], geo)
            + (
                "<h4>Construction sequence</h4>" + _table(["check", "result", "detail"], cons)
                if cons
                else ""
            )
        )
    sens_html = ""
    if inp.sensitivity is not None:
        srows = [
            [
                PARAMETERS[r["parameter"]][0],
                r["metric"],
                r["low_value"],
                r["high_value"],
                r["metric_low"],
                r["metric_baseline"],
                r["metric_high"],
                r["converged"],
                r["slope"],
            ]
            for r in inp.sensitivity.sensitivities()
        ]
        sens_html = (
            "<h2>Sensitivity sweep <small>(preview solver - not verified)</small></h2>"
            + _table(
                [
                    "parameter",
                    "metric",
                    "low",
                    "high",
                    "metric at low",
                    "baseline",
                    "metric at high",
                    "both converged",
                    "slope",
                ],
                srows,
            )
        )
    find_rows = [[fd.severity.upper(), fd.source, fd.message] for fd in report.findings]
    seam_html = ""
    if inp.seam_classes is not None:
        seam_html = "<h2>Seam-length classification</h2>" + _table(
            ["class", "seams"], list(inp.seam_classes.counts().items())
        )
    css = """
:root{--bg:#fcfcfb;--ink:#1f1f1d;--muted:#6b6a65;--line:#dcdbd6}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#1a1a19;--ink:#ecebe7;--muted:#a3a29c;--line:#3a3a37}}
:root[data-theme="dark"]{--bg:#1a1a19;--ink:#ecebe7;--muted:#a3a29c;--line:#3a3a37}
body{background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif;
  margin:0 auto;max-width:1200px;padding:16px}
.banner{border-left:8px solid;padding:10px 14px;margin:12px 0;font-weight:600}
.states{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.state{margin:0;border:1px solid var(--line);border-radius:6px;padding:8px}
.tag{font-size:12px;font-weight:600;border-left:4px solid;padding-left:6px;min-height:32px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:12.5px;display:block;
  overflow-x:auto}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}.muted{color:var(--muted)}
.legend{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px}
.bar{display:inline-block;width:200px;height:10px;border-radius:2px}
"""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Reality Check</title><style>{css}</style></head><body>"
        f"<h1>Reality Check - {html.escape(inp.title)}</h1>"
        f'<div class="banner" style="border-color:{banner}">{html.escape(report.status_line)}</div>'
        "<p class='muted'>EnvelopeLab is a design aid, not certified engineering software. "
        "Preview results are never verified; unconverged results are not predictions.</p>"
        f'<h2>Shape states</h2><div class="states">{"".join(panels)}</div>{legend}'
        "<h2>Dimensions</h2>"
        + _table(
            ["quantity", "unit", "as-sewn", "preview", "verification", "reference", "note"],
            dim_rows,
        )
        + (
            "<h2>Deviation from the reference</h2>"
            + _table(
                [
                    "state",
                    "mean m",
                    "RMS m",
                    "max outside m",
                    "max inside m",
                    "95 % |d| m",
                    "points",
                ],
                dev_rows,
            )
            if dev_rows
            else ""
        )
        + "<h2>Critical load paths</h2>"
        + _table(
            ["state", "tape", "max tension N", "breaking strength N", "FoS", "source"],
            [
                [
                    r["state"],
                    r["tape"],
                    r["max_tension_n"],
                    r["breaking_strength_n"],
                    r["fos"],
                    r["source"],
                ]
                for r in report.load_paths
            ],
        )
        + f"<h2>Fabric factor of safety <small>(required {REQUIRED_FOS:g}, assumed)</small></h2>"
        + _table(
            ["state", "zone", "max N1 N/m", "strength N/m", "FoS", "passed"],
            [
                [
                    r["state"],
                    r["zone"],
                    r["max_n1_n_per_m"],
                    r["strength_n_per_m"],
                    r["fos"],
                    r["passed"],
                ]
                for r in report.fos
            ],
        )
        + "<h2>Solver convergence</h2>"
        + _table(
            [
                "state",
                "solver",
                "status",
                "converged",
                "iterations",
                "final residual",
                "residual measure",
                "nodes",
                "elements",
                "time s",
            ],
            [
                [
                    c["state"],
                    c["solver"],
                    c["status"],
                    c["converged"],
                    c["iterations"],
                    c["final_residual"],
                    c["residual_measure"],
                    c["nodes"],
                    c["elements"],
                    c["elapsed_s"],
                ]
                for c in report.convergence
            ],
        )
        + "<h2>Findings</h2>"
        + _table(["severity", "source", "message"], find_rows)
        + "<h2>Features</h2>"
        + "".join(feat_html)
        + seam_html
        + sens_html
        + "</body></html>"
    )


def render_pdf(report: RealityCheckReport) -> PdfCanvas:
    """Vector PDF: status, the three states with heat map and legend, then the tables."""
    pdf = PdfCanvas()
    w, h = pdf.width, pdf.height
    pdf.text(36, h - 40, f"Reality Check - {report.input.title}", 16, bold=True)
    banner = _hex(STATUS["good"] if report.verified else STATUS["critical"])
    pdf.rect(36, h - 70, 6, 18, fill=banner)
    pdf.text(48, h - 64, report.status_line[:150], 10, bold=True)
    views, mode, rng, pal = _views(report)
    pts = [p for v in views for poly, _ in v.polygons for p in poly]
    arr = np.array(pts) if pts else np.zeros((1, 2))
    x0, y0 = float(arr[:, 0].min()), float(arr[:, 1].min())
    x1, y1 = float(arr[:, 0].max()), float(arr[:, 1].max())
    panel_w, panel_h = (w - 72 - 24) / 3, 330.0
    scale = min((panel_w - 16) / max(x1 - x0, 1e-9), (panel_h - 60) / max(y1 - y0, 1e-9))
    for k, (view, state) in enumerate(zip(views, report.states, strict=True)):
        px = 36 + k * (panel_w + 12)
        py = h - 90 - panel_h
        pdf.rect(px, py, panel_w, panel_h, stroke=_hex("#dcdbd6"))
        pdf.rect(px + 6, py + panel_h - 22, 5, 14, fill=_hex(_banner_color(view.kind, state)))
        words = view.label
        pdf.text(px + 15, py + panel_h - 12, words[:60], 7, bold=True)
        if len(words) > 60:
            pdf.text(px + 15, py + panel_h - 20, words[60:120], 7, bold=True)
        for poly, color in view.polygons:
            pdf.polygon(
                [(px + 8 + (a - x0) * scale, py + 8 + (b - y0) * scale) for a, b in poly],
                fill=color,
            )
    # Legend.
    ly = h - 90 - panel_h - 22
    for k in range(40):
        c = _ramp(np.array([rng[0] + (rng[1] - rng[0]) * k / 39]), rng[0], rng[1], pal)[0]
        pdf.rect(36 + k * 4, ly, 4, 8, fill=c)
    unit = (
        "signed distance to reference, m (blue inside, red outside)"
        if mode == "deviation"
        else "N1, N/m"
    )
    pdf.text(200, ly + 1, f"{_fmt(rng[0])} .. {_fmt(rng[1])}  {unit}", 8)
    pdf.text(
        36,
        30,
        "Design aid only. Preview results are never verified; unconverged results are "
        "not predictions.",
        7,
    )
    # Tables: the same rows as the CSV export.
    lines: list[tuple[str, bool]] = []
    for name, rows in report.csv_tables().items():
        if len(rows) < 2:
            continue
        lines.append((name.removesuffix(".csv").replace("_", " ").title(), True))
        lines.append((" | ".join(str(c) for c in rows[0]), False))
        lines += [(" | ".join(_fmt(c) for c in row), False) for row in rows[1:]]
    pdf.new_page()
    y = h - 40
    for text, bold in lines:
        if y < 40:
            pdf.new_page()
            y = h - 40
        for chunk_start in range(0, max(len(text), 1), 150):
            pdf.text(36, y, text[chunk_start : chunk_start + 150], 10 if bold else 7.5, bold=bold)
            y -= 14 if bold else 10
    return pdf
