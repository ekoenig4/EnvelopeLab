r"""Verification benchmarks of the CalculiX adapter and the preview-vs-CalculiX study.

Three parts, all generated into ``docs/validation/preview-vs-calculix.md`` (tables) and
``docs/validation/preview-vs-calculix.svg`` (mesh-convergence plot) from the data file
``docs/validation/preview-vs-calculix.json``:

1. **Analytic benchmarks** (AGENTS.md §6.4, 2 % on stresses). Pressurised sphere
   (octant, three symmetry planes): area-weighted mean principal resultants vs
   :math:`N = p r / 2`. Closed pressurised cylinder (half length, capped): mean hoop
   resultant vs :math:`p r` and axial vs :math:`p r / 2`, with :math:`r` the mean deformed
   radius. Both start from the model's (stress-free) initial shape.
2. **Preview vs CalculiX** on the generic spherical-envelope fixture
   (``tests/fixtures/spherical_envelope``), tension field on, same model for both solvers.
   CalculiX starts from the preview's equilibrium (see
   :func:`calculix_adapter.run_calculix`, ``start_positions``) and must reach its own
   convergence criteria. Height, volume and maximum tape tension must agree within 5 % on
   the finest level; every other compared quantity is listed and flagged above 5 %.
3. **Mesh convergence** of the CalculiX result on three levels, with the observed order and
   Richardson extrapolation :math:`f_\infty \approx f_3 + (f_3 - f_2) / (r^p - 1)`,
   :math:`p = \ln((f_1 - f_2) / (f_2 - f_3)) / \ln r` (constant refinement ratio :math:`r`
   assumed; reported only when the three values are monotone).

References
----------
L. F. Richardson, "The deferred approach to the limit", Phil. Trans. R. Soc. A 226 (1927)
299-361; P. J. Roache, *Verification and Validation in Computational Science and
Engineering*, Hermosa (1998), ch. 5.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from calculix_adapter.analysis import CalculixSettings, run_calculix
from calculix_adapter.detect import require_calculix
from envelopelab.materials.membrane import MembraneMaterial
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import (
    OperatingConditions,
    PressureClosure,
    SolverModel,
    SolverSettings,
    SymmetryPlane,
)
from envelopelab.solvers.simulation import SimulationResult, from_preview
from envelopelab.validation.analytic_geometry import BenchmarkResult
from envelopelab.validation.comparison import compare_results
from envelopelab.validation.meshes import cylinder, sphere
from envelopelab.validation.preview_solver import envelope_model

FORMAT = "envelopelab.calculix-validation"
VERSION = 1
#: Target edge lengths (mm) of the CalculiX mesh-convergence study, coarse to fine.
LEVELS_MM = (1200.0, 850.0, 600.0)
#: Quantities that must agree within 5 % between the preview and CalculiX.
REQUIRED = ("height", "volume", "maximum tape tension")
TOLERANCE = 0.05
#: CalculiX settings of the envelope study: the start is the preview equilibrium, so the
#: iterative membrane properties start at the final residual stiffness.
ENVELOPE_SETTINGS = CalculixSettings(kappa_start=1e-3)


@dataclass(frozen=True)
class LevelData:
    """One mesh level of the envelope study (lengths m, volume m^3, forces N).

    ``preview`` and ``calculix`` map quantity names (``height``, ``maximum width``,
    ``volume``, ``maximum tape tension``, ...) to values; ``comparison`` lists the full
    comparison rows ``(name, preview, calculix, unit, difference, tolerance)``.
    """

    target_mm: float
    nodes: int
    triangles: int
    preview_converged: bool
    calculix_converged: bool
    calculix_passes: int
    calculix_elapsed: float
    calculix_movement: float
    preview: dict[str, float]
    calculix: dict[str, float]
    comparison: list[tuple[str, float, float, str, float, float]]
    findings: list[str] = field(default_factory=list)


@dataclass
class ValidationData:
    """Everything the generated page shows."""

    calculix_version: str
    benchmarks: list[BenchmarkResult]
    levels: list[LevelData]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary (format ``envelopelab.calculix-validation`` v1)."""
        return {
            "format": FORMAT,
            "version": VERSION,
            "calculix_version": self.calculix_version,
            "benchmarks": [asdict(b) for b in self.benchmarks],
            "levels": [asdict(lv) for lv in self.levels],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationData:
        """Inverse of :meth:`to_dict`."""
        if data.get("format") != FORMAT or data.get("version") != VERSION:
            raise ValueError(f"not a {FORMAT} v{VERSION} file")
        levels = []
        for lv in data["levels"]:
            rows = [tuple(r) for r in lv.pop("comparison")]
            levels.append(LevelData(**lv, comparison=rows))
        return cls(
            data["calculix_version"],
            [BenchmarkResult(**b) for b in data["benchmarks"]],
            levels,
        )

    def save(self, path: Path) -> None:
        """Write the JSON data file."""
        path.write_text(json.dumps(self.to_dict(), indent=1) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ValidationData:
        """Read a JSON data file."""
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @property
    def passed(self) -> bool:
        """True when every benchmark row passes."""
        return all(b.passed for b in self.benchmarks)


def _areas(x: np.ndarray, tri: np.ndarray) -> np.ndarray:
    e = x[tri]
    out: np.ndarray = 0.5 * np.linalg.norm(np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0]), axis=1)
    return out


def _isotropic() -> MembraneMaterial:
    return MembraneMaterial.isotropic("isotropic benchmark", 1.0e5, 0.3)


def _status_rows(tag: str, result: SimulationResult) -> list[BenchmarkResult]:
    residual = [h.residual for h in result.iteration_history if "out-of-balance" in h.stage]
    return [
        BenchmarkResult(
            f"{tag}: converged (0 = yes)",
            0.0 if result.converged else 1.0,
            0.0,
            "-",
            "absolute",
            0.0,
        ),
        BenchmarkResult(
            f"{tag}: relative out-of-balance",
            residual[-1] if residual and result.converged else math.inf,
            0.0,
            "-",
            "absolute",
            CalculixSettings().residual_target,
        ),
    ]


def sphere_benchmarks(settings: CalculixSettings, divisions: int = 24) -> list[BenchmarkResult]:
    """CalculiX pressurised sphere (octant) vs :math:`p r / 2`.

    Parameters
    ----------
    settings : CalculixSettings
        Adapter settings.
    divisions : int
        Subdivisions of the octant edge.

    Returns
    -------
    list of BenchmarkResult
        Mean principal resultants (N/m) vs :math:`p r / 2`, :math:`r` the mean deformed
        radius (m), plus the convergence rows.
    """
    radius, pressure = 2.0, 1000.0
    mesh = sphere(radius, divisions, octant=True)
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], tuple(np.eye(3)[k]))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        _isotropic(),
        OperatingConditions(1.2, 1.2, uniform_pressure=pressure, self_weight=False),
        symmetry=planes,
        name=f"octant sphere, {divisions} divisions",
    )
    result = run_calculix(model, settings)
    x = result.positions
    r = float(np.linalg.norm(x, axis=1).mean())
    area = _areas(x, model.triangles)
    ref = pressure * r / 2.0
    tag = f"CalculiX sphere R0=2 m, p=1 kPa, octant {divisions} div"
    return [
        BenchmarkResult(
            f"{tag}: mean N1 vs p r/2",
            float(np.average(result.principal[:, 0], weights=area)),
            ref,
            "N/m",
            "relative",
            0.02,
        ),
        BenchmarkResult(
            f"{tag}: mean N2 vs p r/2",
            float(np.average(result.principal[:, 1], weights=area)),
            ref,
            "N/m",
            "relative",
            0.02,
        ),
    ] + _status_rows(tag, result)


def cylinder_benchmarks(
    settings: CalculixSettings, n_around: int = 48, n_along: int = 16
) -> list[BenchmarkResult]:
    """CalculiX closed pressurised cylinder vs :math:`p r` (hoop) and :math:`p r / 2`.

    Parameters
    ----------
    settings : CalculixSettings
        Adapter settings.
    n_around, n_along : int
        Mesh divisions.

    Returns
    -------
    list of BenchmarkResult
        Mean hoop and axial resultants (N/m) plus the convergence rows.
    """
    pressure = 1000.0
    mesh = cylinder(1.0, 1.0, n_around, n_along)
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        _isotropic(),
        OperatingConditions(1.2, 1.2, uniform_pressure=pressure, self_weight=False),
        symmetry=[
            SymmetryPlane("z0", mesh.node_sets["bottom"], (0.0, 0.0, 1.0)),
            SymmetryPlane("x0", mesh.node_sets["x0"], (1.0, 0.0, 0.0)),
            SymmetryPlane("y0", mesh.node_sets["y0"], (0.0, 1.0, 0.0)),
        ],
        closures=[PressureClosure("end cap", mesh.node_sets["top"])],
        name="closed cylinder",
    )
    result = run_calculix(model, settings)
    x = result.positions
    r = float(np.hypot(x[:, 0], x[:, 1]).mean())
    centroid = x[model.triangles].mean(axis=1)
    hoop_dir = np.column_stack([-centroid[:, 1], centroid[:, 0], np.zeros(len(centroid))])
    hoop_dir /= np.linalg.norm(hoop_dir, axis=1)[:, None]
    hoop = np.einsum("mi,mij,mj->m", hoop_dir, result.stress, hoop_dir)
    area = _areas(x, model.triangles)
    tag = f"CalculiX cylinder R0=1 m, p=1 kPa, {n_around}x{n_along}"
    return [
        BenchmarkResult(
            f"{tag}: mean hoop N vs p r",
            float(np.average(hoop, weights=area)),
            pressure * r,
            "N/m",
            "relative",
            0.02,
        ),
        BenchmarkResult(
            f"{tag}: mean axial N vs p r/2",
            float(np.average(result.stress[:, 2, 2], weights=area)),
            pressure * r / 2.0,
            "N/m",
            "relative",
            0.02,
        ),
    ] + _status_rows(tag, result)


PEAK = "distance of the tape-tension peak from the nearest fixed node"


def _quantities(result: SimulationResult, model: SolverModel) -> dict[str, float]:
    fixed = np.concatenate([con.nodes for con in model.constraints])
    peak, where = -1.0, math.nan
    for name, edges in result.tape_edges.items():
        tension = result.tape_tensions[name]
        if len(tension) and tension.max() > peak:
            k = int(np.argmax(tension))
            middle = result.positions[edges[k]].mean(axis=0)
            where = float(np.linalg.norm(result.positions[fixed] - middle, axis=1).min())
            peak = float(tension.max())
    return {
        "height": result.height,
        "maximum width": result.max_width,
        "volume": result.volume,
        "maximum tape tension": result.max_tape_tension,
        PEAK: where,
    }


def envelope_level(
    fixture: Path, target_mm: float, settings: CalculixSettings = ENVELOPE_SETTINGS
) -> LevelData:
    """Preview and CalculiX on one mesh level of the envelope fixture.

    Parameters
    ----------
    fixture : Path
        Build-pack YAML of the generic spherical envelope.
    target_mm : float
        Target edge length, mm.
    settings : CalculixSettings
        Adapter settings.

    Returns
    -------
    LevelData
        Both solvers' quantities and the full comparison.
    """
    model = envelope_model(fixture, target_mm, seam_symmetry=True)
    preview_raw = solve(model, SolverSettings(slack_stiffness_ratio=settings.slack_stiffness_ratio))
    preview = from_preview(model, preview_raw)
    ccx = run_calculix(
        model,
        settings,
        start_positions=preview_raw.positions,
        mesh_options={"target_edge_length_mm": target_mm, "seam_symmetry": True},
    )
    comparison = compare_results(preview, ccx, TOLERANCE)
    moves = [h.residual for h in ccx.iteration_history if "movement" in h.stage]
    return LevelData(
        target_mm,
        model.n_nodes,
        model.n_triangles,
        preview.converged,
        ccx.converged,
        len(moves),
        ccx.elapsed,
        float(np.linalg.norm(ccx.positions - preview_raw.positions, axis=1).max()),
        _quantities(preview, model),
        _quantities(ccx, model),
        [
            (r.name, r.reference, r.other, r.unit, r.difference, r.tolerance)
            for r in comparison.rows
        ],
        [f.message for f in ccx.findings if f.severity == "error"],
    )


def envelope_rows(levels: list[LevelData]) -> list[BenchmarkResult]:
    """Benchmark rows of the envelope study: 5 % agreement on the finest level, all
    levels converged, and the CalculiX change between the last two levels."""
    fine = levels[-1]
    tag = f"Envelope, {fine.target_mm:g} mm mesh: CalculiX vs preview"
    rows = [
        BenchmarkResult(
            f"{tag}, {name}",
            fine.preview[name] if fine.preview_converged else math.nan,
            fine.calculix[name] if fine.calculix_converged else math.nan,
            _UNITS[name],
            "relative",
            TOLERANCE,
        )
        for name in REQUIRED
    ]
    rows.append(
        BenchmarkResult(
            "Envelope: levels not converged (preview or CalculiX)",
            float(sum(not (lv.preview_converged and lv.calculix_converged) for lv in levels)),
            0.0,
            "-",
            "absolute",
            0.0,
        )
    )
    a, b = levels[-2], levels[-1]
    for name, limit in (("height", 0.02), ("volume", 0.02)):
        rows.append(
            BenchmarkResult(
                f"Envelope, CalculiX, last two levels: {name}",
                b.calculix[name],
                a.calculix[name],
                _UNITS[name],
                "relative",
                limit,
            )
        )
    return rows


_UNITS = {
    "height": "m",
    "maximum width": "m",
    "volume": "m^3",
    "maximum tape tension": "N",
    PEAK: "m",
}


def run_validation(
    fixture: Path,
    levels_mm: tuple[float, ...] = LEVELS_MM,
    progress: Callable[[str], None] | None = None,
) -> ValidationData:
    """Run the analytic benchmarks and the envelope study with CalculiX.

    Parameters
    ----------
    fixture : Path
        Build-pack YAML of the generic spherical envelope.
    levels_mm : tuple of float
        Target edge lengths of the study, coarse to fine, mm.
    progress : callable, optional
        Receives one line per finished stage.

    Returns
    -------
    ValidationData
        Benchmark rows and per-level data.

    Raises
    ------
    calculix_adapter.CalculixNotFoundError
        When ``ccx`` is not installed.
    """
    inst = require_calculix()
    say = progress or (lambda _: None)
    start = time.perf_counter()
    settings = CalculixSettings()
    rows = sphere_benchmarks(settings)
    say(f"sphere done ({time.perf_counter() - start:.0f} s)")
    rows += cylinder_benchmarks(settings)
    say(f"cylinder done ({time.perf_counter() - start:.0f} s)")
    levels = []
    for target in levels_mm:
        levels.append(envelope_level(fixture, target))
        say(f"envelope {target:g} mm done ({time.perf_counter() - start:.0f} s)")
    rows += envelope_rows(levels)
    return ValidationData(inst.version, rows, levels)


def richardson(values: list[float], ratio: float) -> tuple[float, float] | None:
    """Observed order and extrapolated value from three levels (coarse to fine).

    Parameters
    ----------
    values : list of float
        :math:`f_1, f_2, f_3` on meshes refined by the constant ``ratio``.
    ratio : float
        Refinement ratio :math:`r > 1` (coarse size / fine size).

    Returns
    -------
    (float, float) or None
        Order :math:`p > 0` and :math:`f_\\infty`; None when the values are not monotone,
        the changes do not shrink (not in the asymptotic range) or are zero.
    """
    f1, f2, f3 = values
    d1, d2 = f1 - f2, f2 - f3
    if d1 == 0.0 or d2 == 0.0 or d1 * d2 < 0.0 or abs(d2) >= abs(d1):
        return None
    p = math.log(d1 / d2) / math.log(ratio)
    return p, f3 + (f3 - f2) / (ratio**p - 1.0)


def _ratio(levels: list[LevelData]) -> float:
    sizes = [lv.target_mm for lv in levels]
    return float(np.exp(np.mean(np.log(np.array(sizes[:-1]) / np.array(sizes[1:])))))


def _fmt(value: float) -> str:
    if not math.isfinite(value):
        return "n/a"
    # Near-zero values (differences between two converged solutions) are round-off;
    # their digits change between platforms, so only a bound is shown.
    if 0.0 < abs(value) < 1e-6:
        return "< 1e-06"
    return f"{value:.4g}"


def _fmt_mm(length: float) -> str:
    return "< 0.01" if length < 1e-5 else f"{length * 1000:.2g}"


def _fmt_error(b: BenchmarkResult) -> str:
    if not math.isfinite(b.error):
        return "not converged"
    # Tiny errors are shown as a bound so that platform-dependent round-off does not
    # change the page (converged residuals are below 1e-5 by construction).
    if b.error < 1e-5:
        return "< 1e-05" if b.error > 0.0 or b.kind == "relative" else "0"
    return f"{b.error:.1g}"


def render_markdown(data: ValidationData) -> str:
    """Render the validation page from the saved data.

    Parameters
    ----------
    data : ValidationData
        Output of :func:`run_validation` (or its saved JSON).

    Returns
    -------
    str
        Page content.
    """
    lines = [
        "# Preview vs CalculiX verification",
        "",
        "_Auto-generated by `python scripts/generate_validation_docs.py calculix` from "
        "`calculix_adapter.validation` (data: `preview-vs-calculix.json`). Do not edit by "
        "hand; `tests/calculix/test_validation.py` fails if this page is stale._",
        "",
        f"CalculiX CrunchiX {data.calculix_version}, one thread. Relative errors are",
        "fractions (0.01 = 1 %). A result that did not meet every convergence criterion",
        "of the adapter is shown as *not converged* and fails.",
        "",
        "## Benchmarks",
        "",
        "| Benchmark | Computed | Reference | Unit | Error | Tolerance | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for b in data.benchmarks:
        show = b.kind == "relative"
        lines.append(
            f"| {b.name} | {_fmt(b.value) if show else '-'} | "
            f"{_fmt(b.reference) if show else '-'} | {b.unit} | {_fmt_error(b)} | "
            f"{b.tolerance:g} | {'pass' if b.passed else '**FAIL**'} |"
        )
    fine = data.levels[-1]
    lines += [
        "",
        "In the envelope rows *Computed* is the preview value and *Reference* the CalculiX",
        "value.",
        "",
        '!!! note "What the envelope comparison verifies"',
        "    CalculiX is started from the preview's equilibrium and must meet its own",
        "    convergence criteria with its own elements, material law and equation solver.",
        "    Agreement therefore shows that the preview's shape, stresses and tape tensions",
        "    are an equilibrium of an independent finite-element model of the same design;",
        "    it is not an independent form finding (see *Known differences*: started away",
        "    from equilibrium, CalculiX's tension-field passes do not converge).",
        "",
        f"## Full comparison, {fine.target_mm:g} mm mesh",
        "",
        "Generic spherical envelope fixture (`tests/fixtures/spherical_envelope`), 100 degC",
        "internal, ISA sea level, fabric and tape weight, mouth fixed, crown closed by an",
        "unmeshed parachute, seam meridians in x = 0 and y = 0 kept on those planes,",
        "tension field on (residual stiffness 1e-3). Rows above 5 % are flagged; see the",
        "known differences below.",
        "",
        "| Quantity | Preview | CalculiX | Unit | Difference | Status |",
        "|---|---|---|---|---|---|",
    ]
    for name, a_val, b_val, unit, diff, tol in fine.comparison:
        flag = not math.isfinite(diff) or diff > tol
        lines.append(
            f"| {name} | {_fmt(a_val)} | {_fmt(b_val)} | {unit} | {diff * 100:.1f} % | "
            f"{'**beyond 5 %**' if flag else 'within 5 %'} |"
        )
    lines += [
        "",
        "## Mesh convergence (CalculiX)",
        "",
        "![CalculiX mesh convergence](preview-vs-calculix.svg)",
        "",
        "| Target edge (mm) | Nodes | Triangles | Converged | Passes | Largest CalculiX "
        "movement from the preview (mm) | Height (m) | Max width (m) | Volume (m^3) | "
        "Max tape tension (N) | Tape peak: distance from nearest fixed node (m) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for lv in data.levels:
        c = lv.calculix
        ok = "yes" if lv.calculix_converged else "**no**"
        lines.append(
            f"| {lv.target_mm:g} | {lv.nodes} | {lv.triangles} | {ok} | {lv.calculix_passes} "
            f"| {_fmt_mm(lv.calculix_movement)} | {c['height']:.4g} | "
            f"{c['maximum width']:.4g} | {c['volume']:.4g} | {c['maximum tape tension']:.4g} "
            f"| {c[PEAK]:.2g} |"
        )
    ratio = _ratio(data.levels)
    lines += [
        "",
        f"Richardson extrapolation (mean refinement ratio {ratio:.3g}):",
        "",
        "| Quantity | Observed order | Extrapolated | Finest level | Estimated error |",
        "|---|---|---|---|---|",
    ]
    for name in REQUIRED:
        vals = [lv.calculix[name] for lv in data.levels]
        est = richardson(vals, ratio) if len(vals) == 3 else None
        if est is None:
            spread = (max(vals) - min(vals)) / abs(vals[-1])
            lines.append(
                f"| {name} | not in the asymptotic range (spread {spread * 100:.2g} %) | - "
                f"| {vals[-1]:.4g} | - |"
            )
        else:
            p, f_inf = est
            err = abs(vals[-1] - f_inf) / abs(f_inf)
            lines.append(f"| {name} | {p:.2g} | {f_inf:.4g} | {vals[-1]:.4g} | {err * 100:.2g} % |")
    lines += [""]
    t_prev, t_last = (lv.calculix["maximum tape tension"] for lv in data.levels[-2:])
    change = abs(t_last - t_prev) / abs(t_prev) if t_prev else math.inf
    if change > TOLERANCE:
        lines += [
            '!!! warning "Maximum tape tension is not mesh-converged"',
            f"    It changes by {change * 100:.0f} % between the last two levels; the two",
            "    solvers agree on each level, but the value itself depends on the mesh (see",
            "    *Known differences and limitations*).",
            "",
        ]
    for lv in data.levels:
        for message in lv.findings:
            lines.append(f"* {lv.target_mm:g} mm: {message}")
    return "\n".join(lines).rstrip("\n") + "\n" + _known_differences(data)


def _known_differences(data: ValidationData) -> str:
    tape = [lv.calculix["maximum tape tension"] for lv in data.levels]
    sizes = ", ".join(f"{lv.target_mm:g}" for lv in data.levels)
    values = ", ".join(f"{v:.4g}" for v in tape)
    where = ", ".join(f"{lv.calculix[PEAK]:.2g}" for lv in data.levels)
    return f"""
## Known differences and limitations

* **Starting geometry: CalculiX checks the preview's equilibrium, it does not find it.**
  Started from the design (initial) shape of the envelope, the as-sewn misfit produces
  out-of-balance forces about 90 times the pressure load and CalculiX's release steps fail
  even with 32 continuation steps and increased stabilisation. Started 0.2 to 0.3 m away
  from equilibrium (the preview shape computed with the tension field switched the other
  way), the passes stall at
  an out-of-balance of about 10 % of the load after 60 passes: with the tension field about
  1 % of the elements change state every pass, and without it the compressed fabric has no
  stiffness against buckling. The sphere and cylinder benchmarks do start from their
  initial shape.
* **Maximum tape tension is not mesh-converged** (either solver; both agree on every
  level): {values} N at {sizes} mm, with the peak {where} m from the nearest fixed node.
  Where the peak sits on the tapes next to the fixed mouth nodes it grows with refinement,
  like a stress at an idealised point support; on the crown ring it changes by a few per
  cent between levels. Do not read a tape factor of safety at the mouth from one mesh:
  refine, or model the mouth attachment in detail. Tape tension in wrinkled regions also
  depends on the residual stiffness of wrinkled fabric (about a factor of two between 1e-3
  and 1e-2 in the preview; both solvers use 1e-3 here).
* **Displacements in wrinkled fabric** are only weakly determined (near-mechanisms) and are
  not mesh-converged (see the preview solver benchmarks).
* **Same discretisation class.** CalculiX M3D3 elements are constant-strain triangles like
  the preview's, on the same mesh with the same material law (the iterative membrane
  properties reproduce the preview's tension-field law exactly at convergence) and the
  same consistent nodal pressure loads. The comparison therefore checks the equilibrium
  and its evaluation (element forces, tape law, loads, reactions), not discretisation
  error; the mesh-convergence table addresses that.
* **Element choice.** S3 thin shells give the right sphere and cylinder, but on the sewn
  envelope they carried load through transverse shear at the seam creases and were
  rejected.
* **Pressure** enters as consistent nodal loads per pass (CalculiX 2.21 crashes with
  element pressure on M3D3); follower effects are captured by the passes.
"""


def render_svg(data: ValidationData) -> str:
    """Mesh-convergence plot: height, volume and maximum tape tension of both solvers,
    normalised by the finest CalculiX value, against the target edge length.

    Parameters
    ----------
    data : ValidationData
        Saved study data.

    Returns
    -------
    str
        SVG document (deterministic, no external fonts or scripts).
    """
    width, height, left, right, top, bottom = 640, 360, 70, 190, 30, 50
    sizes = [lv.target_mm for lv in data.levels]
    series = []
    colours = {
        "height": "#1f77b4",
        "volume": "#2ca02c",
        "maximum tape tension": "#d62728",
    }
    for name in REQUIRED:
        ref = data.levels[-1].calculix[name]
        series.append(
            (name, "CalculiX", [lv.calculix[name] / ref for lv in data.levels], colours[name])
        )
        series.append(
            (name, "preview", [lv.preview[name] / ref for lv in data.levels], colours[name])
        )
    values = [v for s in series for v in s[2] if math.isfinite(v)]
    lo = min(values + [0.95])
    hi = max(values + [1.05])
    x_lo, x_hi = min(sizes) * 0.9, max(sizes) * 1.1

    def px(size: float) -> float:
        return left + (x_hi - size) / (x_hi - x_lo) * (width - left - right)

    def py(v: float) -> float:
        return top + (hi - v) / (hi - lo) * (height - top - bottom)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" '
        f'y2="{height - bottom}" stroke="black"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="black"/>',
    ]
    for size in sizes:
        out.append(
            f'<text x="{px(size):.1f}" y="{height - bottom + 15}" '
            f'text-anchor="middle">{size:g}</text>'
        )
    ticks = np.linspace(lo, hi, 5)
    for tick in (float(v) for v in ticks):
        out.append(
            f'<line x1="{left}" y1="{py(tick):.1f}" x2="{width - right}" y2="{py(tick):.1f}" '
            'stroke="#ddd"/>'
        )
        out.append(
            f'<text x="{left - 5}" y="{py(tick) + 4:.1f}" text-anchor="end">{tick:.3f}</text>'
        )
    out.append(
        f'<text x="{(left + width - right) / 2}" y="{height - 12}" '
        'text-anchor="middle">target edge length (mm), finer to the right</text>'
    )
    out.append(
        f'<text x="15" y="{(top + height - bottom) / 2}" text-anchor="middle" '
        f'transform="rotate(-90 15 {(top + height - bottom) / 2})">'
        "value / finest CalculiX value</text>"
    )
    for k, (name, solver, vals, colour) in enumerate(series):
        dash = "" if solver == "CalculiX" else ' stroke-dasharray="5,3"'
        pts = " ".join(
            f"{px(s):.1f},{py(v):.1f}" for s, v in zip(sizes, vals, strict=True) if math.isfinite(v)
        )
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="2"{dash}/>'
        )
        for s, v in zip(sizes, vals, strict=True):
            if math.isfinite(v):
                out.append(f'<circle cx="{px(s):.1f}" cy="{py(v):.1f}" r="3" fill="{colour}"/>')
        ly = top + 16 * k
        lx = width - right + 12
        out.append(
            f'<line x1="{lx}" y1="{ly}" x2="{lx + 22}" y2="{ly}" stroke="{colour}" '
            f'stroke-width="2"{dash}/>'
        )
        out.append(f'<text x="{lx + 28}" y="{ly + 4}">{name}, {solver}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


__all__ = [
    "LEVELS_MM",
    "LevelData",
    "ValidationData",
    "cylinder_benchmarks",
    "envelope_level",
    "envelope_rows",
    "render_markdown",
    "render_svg",
    "richardson",
    "run_validation",
    "sphere_benchmarks",
]
