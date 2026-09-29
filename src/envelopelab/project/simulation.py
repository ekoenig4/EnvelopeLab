"""From a standard-gore design to preview and CalculiX solves, with a run record.

The chain reuses the tested pattern-import pipeline so that a design is simulated exactly
the way a builder's DXF patterns would be:

1. :func:`write_build_pack` draws every panel row (finished SEW outline, CUT outline,
   label ``PANEL <row> x<N>``, grain arrow, tape paths) into a DXF file in mm and writes
   the build-pack YAML (one ring of N gores; mouth fixed, crown closed by an unmeshed
   parachute; load tapes from the design's tape classes). With ``include_parachute`` the
   parachute gores and centre disc are added as audited, unmeshed parts (radial seams,
   the centre seam and the free rim); solves leave them out, since the solver closes the
   crown with an unmeshed cap.
2. :func:`build_solver_model` runs :func:`envelopelab.assembly.pipeline.import_build_pack`
   (import, seam graph, seam audit, Gmsh, virtual sewing, initial shape) and
   :func:`envelopelab.solvers.model.model_from_rest_model` with the design's operating
   conditions (dry-air densities at the ambient pressure and the ambient and internal
   temperatures).
3. :func:`solve_preview` returns a
   :class:`~envelopelab.solvers.simulation.SimulationResult`; the optional CalculiX adapter
   (``calculix_adapter.run_calculix``, which ``envelopelab`` never imports) solves the same
   :class:`BuiltModel.model`. :func:`run_record` turns either result into a
   :class:`~envelopelab.project.model.RunRecord`.

Materials: fabric areal mass and service temperature come from the fabric library with its
source tags; membrane stiffness, strength and seam efficiency, and tape stiffness and mass,
are the generic ``assumed`` values below (the library does not hold membrane stiffness per
width yet). Every run records these sources.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from ezdxf.filemanagement import new as new_dxf

from envelopelab.assembly.pipeline import BuildPackResult, import_build_pack
from envelopelab.assembly.spec import MeshOptions
from envelopelab.assembly.transfer import SolvedShape, transfer_positions
from envelopelab.atmosphere import gas_density
from envelopelab.design.model import DesignDocument
from envelopelab.geometry.gore import PanelRow
from envelopelab.geometry.polygon import FloatArray, offset_polygon
from envelopelab.materials.membrane import MaterialValue, MembraneMaterial, TapeMaterial
from envelopelab.materials.repository import (
    FabricCatalog,
    FabricLibraryRepository,
    MaterialProperty,
    SourceTag,
)
from envelopelab.project.gore_design import (
    ParachutePiece,
    design_parachute,
    panel_rows,
    parachute_allowance,
    parachute_pattern,
    parachute_zone,
    row_allowance,
    row_zone,
)
from envelopelab.project.model import PatternSet, RunFinding, RunRecord, utc_now
from envelopelab.solvers.dynamic_relaxation import (
    CancellationToken,
    ProgressCallback,
    solve,
)
from envelopelab.solvers.model import (
    OperatingConditions,
    SolverModel,
    SolverSettings,
    model_from_rest_model,
)
from envelopelab.solvers.simulation import SimulationResult, from_preview

MM = 1000.0
#: Piece ids of the parachute gore and centre disc in a build pack.
PARACHUTE_GORE_PIECE = "PCG"
PARACHUTE_CENTRE_PIECE = "PCC"
#: Default target edge length of the preview mesh, mm.
DEFAULT_MESH_MM = 800.0


def _assumed(value: float, unit: str, note: str = "generic preview value") -> MaterialValue:
    return MaterialValue(value, unit, "assumed", note)


def _tag(
    prop: MaterialProperty, unit: str, scale: float = 1.0, offset: float = 0.0
) -> MaterialValue:
    """Library value converted to SI; a source other than datasheet/measured is assumed."""
    first = prop.source.split()[0].strip(" -").lower() if prop.source else "assumed"
    tag: SourceTag = (
        "datasheet" if first == "datasheet" else "measured" if first == "measured" else "assumed"
    )
    return MaterialValue(prop.value * scale + offset, unit, tag, f"fabric library: {prop.source}")


def membrane_for_fabric(
    fabric_id: str, fabrics: FabricLibraryRepository | FabricCatalog | None
) -> MembraneMaterial:
    """Membrane material of a zone (module docstring: which values are assumed).

    Parameters
    ----------
    fabric_id : str
        Fabric library id.
    fabrics : FabricLibraryRepository, optional
        Library; without it (or for an unknown id) every value is assumed.

    Returns
    -------
    MembraneMaterial
        Stiffness and strength N/m, areal mass kg/m^2, service temperature K.
    """
    fabric = fabrics.fabric(fabric_id) if fabrics is not None else None
    areal = (
        _assumed(0.065, "kg/m^2")
        if fabric is None
        else _tag(fabric.areal_mass, "kg/m^2", scale=1e-3)
    )
    service = (
        _assumed(393.15, "K")
        if fabric is None
        else _tag(fabric.max_service_temperature, "K", offset=273.15)
    )
    return MembraneMaterial(
        name=f"{fabric.name if fabric else fabric_id} (preview stiffness assumed)",
        stiffness_warp=_assumed(1.0e5, "N/m"),
        stiffness_weft=_assumed(0.8e5, "N/m"),
        shear_stiffness=_assumed(5.0e3, "N/m"),
        poisson_warp_weft=_assumed(0.3, "-"),
        areal_mass=areal,
        strength_warp=_assumed(1.5e4, "N/m"),
        strength_weft=_assumed(1.4e4, "N/m"),
        seam_efficiency=_assumed(0.8, "-"),
        max_service_temperature=service,
    )


def tape_material(name: str, strength: float) -> TapeMaterial:
    """Load tape of a design tape class: breaking strength from the design (N, entered by
    the user without a source tag, so ``assumed``), stiffness and mass assumed."""
    return TapeMaterial(
        name=name,
        axial_stiffness=_assumed(5.0e4, "N"),
        breaking_strength=_assumed(strength, "N", "design tape class"),
        linear_mass=_assumed(0.02, "kg/m"),
    )


def operating_conditions(design: DesignDocument, mouth_height: float) -> OperatingConditions:
    """Load case of a design: dry-air densities at the ambient pressure (Pa) and the
    ambient and internal temperatures (K), zero pressure at the mouth (m)."""
    op = design.operating
    return OperatingConditions(
        ambient_density=gas_density(op.ambient_pressure, op.ambient_temperature),
        internal_density=gas_density(op.ambient_pressure, op.internal_temperature),
        mouth_height=mouth_height,
        self_weight=True,
        internal_temperature=op.internal_temperature,
        ambient_temperature=op.ambient_temperature,
        source="assumed",
        label=(
            f"hot air {op.internal_temperature - 273.15:.0f} degC internal, "
            f"{op.ambient_temperature - 273.15:.0f} degC ambient, "
            f"{op.ambient_pressure:.0f} Pa"
        ),
    )


def finished_outline(row: PanelRow, patterns: PatternSet) -> np.ndarray:
    """Finished outline of a row, m (the manual override when present)."""
    manual = patterns.row(row.label).manual_outline
    if manual is None:
        return row.finished_outline
    return np.asarray(manual.points, dtype=np.float64)


def _grain(angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return (round(math.cos(a), 12), round(math.sin(a), 12))


def write_build_pack(
    design: DesignDocument,
    patterns: PatternSet,
    out_dir: str | Path,
    mesh_mm: float = DEFAULT_MESH_MM,
    rows: list[PanelRow] | None = None,
    include_parachute: bool = False,
) -> Path:
    """Write the DXF patterns and build-pack YAML of a standard-gore design.

    Parameters
    ----------
    design : DesignDocument
        Gore design (m).
    patterns : PatternSet
        Row annotations: zones, grain angles (degrees), allowances (m), tape paths and
        manual outline overrides (m).
    out_dir : str or Path
        Directory for ``design.dxf`` and ``build-pack.yaml``.
    mesh_mm : float
        Target mesh edge length, mm.
    rows : list of PanelRow, optional
        Precomputed :func:`~envelopelab.project.gore_design.panel_rows`.
    include_parachute : bool
        Add the design's parachute (if any) as audited, unmeshed parts.

    Returns
    -------
    Path
        The YAML file.
    """
    assert design.gores is not None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = rows if rows is not None else panel_rows(design, patterns)
    n = design.gores.count
    doc = new_dxf("R2010", setup=False)
    doc.header["$INSUNITS"] = 4
    for layer in ("CUT", "SEW", "TAPE", "GRAIN", "NOTES"):
        doc.layers.add(layer)
    msp = doc.modelspace()
    x = 0.0
    pieces: dict[str, Any] = {}
    for row in rows:
        allowance = row_allowance(design, patterns, row.label)
        finished = finished_outline(row, patterns)
        manual = patterns.row(row.label).manual_outline is not None
        cut = offset_polygon(finished, allowance) if manual else row.cut_outline
        width = float(cut[:, 0].max() - cut[:, 0].min()) * MM
        x += width / 2 + 200.0

        def pts(points: np.ndarray, x0: float = x) -> list[tuple[float, float]]:
            return [(float(px * MM + x0), float(py * MM)) for px, py in points]

        msp.add_lwpolyline(pts(cut), close=True, dxfattribs={"layer": "CUT"})
        msp.add_lwpolyline(pts(finished), close=True, dxfattribs={"layer": "SEW"})
        msp.add_text(
            f"PANEL {row.label} x{n}",
            height=60.0,
            dxfattribs={"layer": "NOTES", "insert": (x - 150.0, row.finished_height * MM / 2)},
        )
        ann = patterns.row(row.label)
        for tape in ann.tape_paths:
            msp.add_lwpolyline(pts(np.asarray(tape.points)), dxfattribs={"layer": "TAPE"})
        pieces[row.label] = {
            "material_zone": row_zone(design, patterns, row.label),
            "grain": list(_grain(ann.grain_angle_deg)),
            "seam_allowance_mm": round(allowance * MM, 6),
        }
        if manual:
            # Hand-moved vertices bend a side by more than the default 30 deg corner
            # threshold; a gore panel's real corners turn by far more than 60 deg.
            pieces[row.label]["corner_angle_deg"] = 60.0
        x += width / 2
    parachute = design_parachute(design, patterns) if include_parachute else None
    if parachute is not None:
        parachute_parts: list[tuple[str, ParachutePiece, FloatArray, FloatArray, int]] = [
            (
                PARACHUTE_GORE_PIECE,
                "gore",
                parachute.gore_finished,
                parachute.gore_cut,
                parachute.n_gores,
            ),
            (PARACHUTE_CENTRE_PIECE, "centre", parachute.centre_finished, parachute.centre_cut, 1),
        ]
        for piece_id, key, finished, cut, quantity in parachute_parts:
            width = float(np.ptp(cut[:, 0])) * MM
            x += width / 2 + 200.0
            x0 = x - float(cut[:, 0].mean()) * MM
            msp.add_lwpolyline(
                [(float(px * MM + x0), float(py * MM)) for px, py in cut],
                close=True,
                dxfattribs={"layer": "CUT"},
            )
            msp.add_lwpolyline(
                [(float(px * MM + x0), float(py * MM)) for px, py in finished],
                close=True,
                dxfattribs={"layer": "SEW"},
            )
            centre = finished.mean(axis=0) * MM
            msp.add_text(
                f"PANEL {piece_id} x{quantity}",
                height=40.0,
                dxfattribs={"layer": "NOTES", "insert": (x0 + centre[0] - 150.0, centre[1])},
            )
            ann = parachute_pattern(patterns, key)
            pieces[piece_id] = {
                "material_zone": parachute_zone(design, patterns, key),
                "grain": list(_grain(ann.grain_angle_deg)),
                "seam_allowance_mm": round(parachute_allowance(design, patterns, key) * MM, 6),
            }
            x += width / 2
    doc.saveas(out / "design.dxf")
    tapes = design.tapes
    allowance_mm = round(row_allowance(design, patterns, rows[0].label) * MM, 6)
    config: dict[str, Any] = {
        "import": {
            "mapping_version": f"envelopelab-design/{design.compute_content_hash()[:12]}",
            "units": "auto",
            "seam_allowance_mm": allowance_mm,
            "default_grain": [1.0, 0.0],
            "layers": {
                "cut": ["CUT"],
                "sew": ["SEW"],
                "tape": ["TAPE"],
                "grain": ["GRAIN"],
                "label": ["NOTES"],
            },
            "labels": [{"pattern": r"^PANEL\s+(?P<panel>[A-Z]+)\s+x(?P<quantity>\d+)$"}],
            "sources": [{"file": "design.dxf"}],
            "pieces": pieces,
        },
        "assembly": {
            "kind": "standard_gore",
            "rings": [
                {
                    "name": "body",
                    "gore_count": n,
                    "rows": [row.label for row in rows],
                    "bottom": {
                        "name": "mouth",
                        "kind": "mouth",
                        "hem": {"load_tape": tapes.rim.tape_class},
                    },
                    "top": {
                        "name": "crown",
                        "kind": "parachute_opening",
                        "hem": {"load_tape": tapes.hole.tape_class},
                    },
                    "horizontal_seam": {
                        "allowance_mm": allowance_mm,
                        "load_tape": tapes.horizontal.tape_class,
                        "construction_order": 1,
                    },
                    "vertical_seam": {
                        "allowance_mm": allowance_mm,
                        "load_tape": tapes.vertical.tape_class,
                        "construction_order": 2,
                    },
                }
            ],
            "mesh": {"target_edge_length_mm": mesh_mm},
        },
    }
    if parachute is not None:
        allowance = parachute_allowance(design, patterns, "gore") * MM
        config["assembly"].update(_parachute_assembly(parachute.n_gores, design, allowance))
    target = out / "build-pack.yaml"
    target.write_text(
        "# Generated by EnvelopeLab from a design document; do not edit by hand.\n"
        + yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    return target


def _parachute_assembly(n: int, design: DesignDocument, allowance_mm: float) -> dict[str, Any]:
    """Unmeshed parachute parts, their seams and the free rim (build-pack YAML data)."""
    reason = "the parachute is audited only: the solver closes the crown with an unmeshed cap"
    gores = [f"parachute/g{i}" for i in range(1, n + 1)]
    allowance = round(allowance_mm, 6)
    parts = [
        {"name": g, "piece": PARACHUTE_GORE_PIECE, "mesh": False, "reason": reason} for g in gores
    ]
    parts.append(
        {
            "name": "parachute/centre",
            "piece": PARACHUTE_CENTRE_PIECE,
            "mesh": False,
            "reason": reason,
        }
    )
    tapes = design.tapes
    seams: list[dict[str, Any]] = [
        {
            "name": f"parachute:radial@{i + 1}",
            "type": "vertical_gore",
            "a": [{"instance": gores[i], "edge": "right"}],
            "b": [{"instance": gores[(i + 1) % n], "edge": "left"}],
            "allowance_mm": allowance,
            "load_tape": tapes.vertical.tape_class,
        }
        for i in range(n)
    ]
    seams.append(
        {
            "name": "parachute:centre",
            "type": "horizontal_panel",
            "a": [{"instance": g, "edge": "top"} for g in gores],
            "b": [{"instance": "parachute/centre", "edge": "loop"}],
            "allowance_mm": allowance,
        }
    )
    openings = [
        {
            "name": "parachute_rim",
            "kind": "parachute_rim",
            "edges": [{"instance": g, "edge": "bottom"} for g in gores],
            "hem": {"load_tape": tapes.hole.tape_class},
            "reason": "the parachute rim overlaps the crown hole to seal it; it is not sewn",
        }
    ]
    return {"parts": parts, "seams": seams, "openings": openings}


class BuildError(RuntimeError):
    """The design could not be turned into a solver model (the message says why)."""


@dataclass
class BuiltModel:
    """A solver model built from a design, with the intermediate results.

    Attributes
    ----------
    model : SolverModel
        The model (``source_hash`` is the design content hash).
    build : BuildPackResult
        Import, seam audit and mesh results.
    mesh_mm : float
        Target edge length, mm.
    design_hash : str
        Design content hash.
    findings : list of RunFinding
        Import and audit warnings and errors.
    """

    model: SolverModel
    build: BuildPackResult
    mesh_mm: float
    design_hash: str
    findings: list[RunFinding] = field(default_factory=list)

    @property
    def material_sources(self) -> list[str]:
        """Distinct source tags of every material and tape value."""
        tags: set[str] = set()
        for material in self.model.materials.values():
            tags.update(str(v["source"]) for v in material.sources().values())
        for cable in self.model.cables:
            tags.update(str(v["source"]) for v in cable.material.sources().values())
        return sorted(tags)


def build_solver_model(
    design: DesignDocument,
    patterns: PatternSet,
    work_dir: str | Path,
    mesh_mm: float = DEFAULT_MESH_MM,
    fabrics: FabricLibraryRepository | FabricCatalog | None = None,
) -> BuiltModel:
    """Solver model of a standard-gore design (module docstring).

    Parameters
    ----------
    design : DesignDocument
        Gore design.
    patterns : PatternSet
        Row annotations.
    work_dir : str or Path
        Directory for the generated build pack.
    mesh_mm : float
        Target mesh edge length, mm.
    fabrics : FabricLibraryRepository, optional
        Fabric library (areal mass, service temperature).

    Returns
    -------
    BuiltModel
        Model with import and audit findings.

    Raises
    ------
    BuildError
        For a special-shape design, invalid rows, or a failed import or mesh.
    """
    if design.gores is None:
        raise BuildError("simulation of special shapes needs panels; this design has none yet")
    try:
        rows = panel_rows(design, patterns)
    except ValueError as exc:
        raise BuildError(str(exc)) from exc
    config = write_build_pack(design, patterns, work_dir, mesh_mm, rows)
    options = MeshOptions(
        target_edge_length_mm=mesh_mm,
        seam_edge_length_mm=mesh_mm,
        corner_edge_length_mm=0.5 * mesh_mm,
    )
    try:
        build = import_build_pack(config, mesh_options=options)
    except Exception as exc:  # import and meshing raise several error types
        raise BuildError(f"build pack import failed: {exc}") from exc
    findings = [
        RunFinding(code=w.code, severity=w.severity, message=w.message) for w in build.warnings
    ]
    for row in build.audit.rows:
        for f in row.findings:
            findings.append(
                RunFinding(code="seam_audit", severity="warning", message=f"{row.seam_id}: {f}")
            )
    if build.mesh_report is not None and not build.mesh_report.passed:
        failed = [name for name, ok in build.mesh_report.as_dict()["checks"].items() if not ok]
        findings.append(
            RunFinding(
                code="mesh_check",
                severity="error",
                message=f"mesh check failed at {mesh_mm:g} mm: {', '.join(failed)} "
                "(refine the mesh)",
            )
        )
    if build.rest_model is None:
        raise BuildError("meshing produced no rest model")
    z_mouth = float(build.rest_model.positions[:, 2].min())
    conditions = operating_conditions(design, z_mouth)
    materials = {zone: membrane_for_fabric(fid, fabrics) for zone, fid in design.zones.items()}
    t = design.tapes
    tapes = {
        spec.tape_class: tape_material(spec.tape_class, spec.strength)
        for spec in (t.vertical, t.horizontal, t.rim, t.hole)
    }
    try:
        model = model_from_rest_model(
            build.rest_model,
            materials,
            conditions,
            tapes,
            fixed_openings=("mouth",),
            closed_openings=("crown",),
            name=f"{design.meta.name}, {mesh_mm:g} mm mesh",
        )
    except ValueError as exc:
        raise BuildError(str(exc)) from exc
    design_hash = design.compute_content_hash()
    model.source_hash = design_hash
    return BuiltModel(model, build, mesh_mm, design_hash, findings)


def solve_preview(
    built: BuiltModel,
    settings: SolverSettings | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancellationToken | None = None,
) -> SimulationResult:
    """Preview (dynamic-relaxation) solve of a built model."""
    result = solve(built.model, settings, progress, cancel)
    return from_preview(built.model, result)


#: Stage name of the CalculiX adapter's per-pass relative out-of-balance record.
CALCULIX_BALANCE_STAGE = "pass: relative out-of-balance"


def final_residual(result: SimulationResult) -> tuple[float, str]:
    """Final residual of a solve and what it measures.

    Preview: the last relative residual :math:`\\|PR\\|/\\|F_{ext}\\|`. CalculiX: the
    relative out-of-balance :math:`\\|f_{ext} - f_{int}\\|/\\|f_{ext}\\|` of the last pass
    (the quantity its convergence criterion uses), not the last Newton iteration of a job.

    Returns
    -------
    (float, str)
        Residual (dimensionless, NaN when none was recorded) and its meaning.
    """
    if result.solver == "calculix":
        passes = [r for r in result.iteration_history if r.stage == CALCULIX_BALANCE_STAGE]
        if passes:
            return (
                float(passes[-1].residual),
                "relative out-of-balance ||f_ext - f_int|| / ||f_ext|| after the last pass",
            )
        return math.nan, "no CalculiX pass completed"
    if result.residual_history:
        return float(result.residual_history[-1][1]), result.residual_measure
    return math.nan, result.residual_measure


def start_from_run(arrays: dict[str, np.ndarray], built: BuiltModel) -> np.ndarray | None:
    """Starting positions for ``built`` from a saved run's result arrays, m.

    The run's shape is used as is when it has the same mesh, and is transferred through
    the flat patterns (:func:`envelopelab.assembly.transfer.transfer_positions`) when it
    was solved on another mesh of the same build pack. A start is only a guess: the new
    solve is accepted on its own convergence criteria.

    Returns
    -------
    ndarray, shape (n, 3), or None
        None when the run lacks the flat mesh data (runs saved by older versions) or does
        not belong to this build pack.
    """
    positions = np.asarray(arrays["positions"], dtype=np.float64)
    if positions.shape == built.model.positions.shape and np.array_equal(
        np.asarray(arrays["triangles"]), built.model.triangles
    ):
        return positions
    mesh = built.build.rest_model.mesh if built.build.rest_model is not None else None
    if mesh is None or not {"rest_uv", "tri_instance", "instance_ids"} <= set(arrays):
        return None
    shape = SolvedShape(
        np.asarray(arrays["triangles"], dtype=np.int64),
        np.asarray(arrays["rest_uv"], dtype=np.float64),
        np.asarray(arrays["tri_instance"], dtype=np.int64),
        [str(v) for v in arrays["instance_ids"]],
        positions,
    )
    try:
        return transfer_positions(shape, mesh)
    except ValueError:
        return None


def run_record(
    result: SimulationResult,
    built: BuiltModel,
    input_fingerprint: str,
) -> tuple[RunRecord, dict[str, np.ndarray]]:
    """Run record and result arrays of a solve.

    Parameters
    ----------
    result : SimulationResult
        Normalised result of either solver.
    built : BuiltModel
        The solved model.
    input_fingerprint : str
        Fingerprint of the ``simulation`` artifact of the solved design state.

    Returns
    -------
    (RunRecord, dict of str to ndarray)
        Record, and positions / initial positions (m), triangles, principal resultants
        (N/m) and wrinkle state for the 3D view, and the residual history (iteration or
        CalculiX increment, relative residual; shape (k, 2)) to diagnose convergence,
        and the flat mesh data (``rest_uv`` m, ``tri_instance``, ``instance_ids``) that lets
        the shape seed a solve on another mesh (:func:`start_from_run`).
    """
    iterations = (
        int(result.residual_history[-1][0])
        if result.solver == "envelopelab-preview" and result.residual_history
        else len(result.residual_history)
    )
    residual, measure = final_residual(result)
    findings = [
        RunFinding(code=f.code, severity=f.severity, message=f.message) for f in result.findings
    ]
    if not result.converged and not any(f.severity == "error" for f in findings):
        findings.append(
            RunFinding(
                code="not_converged", severity="error", message=f"not converged: {result.status}"
            )
        )
    record = RunRecord(
        run_id=f"{utc_now().strftime('%Y%m%dT%H%M%S')}-{result.solver}-{uuid.uuid4().hex[:6]}",
        created=utc_now(),
        solver=result.solver,  # type: ignore[arg-type]
        solver_version=result.solver_version,
        status=result.status,
        converged=result.converged,
        residual=residual,
        residual_measure=measure,
        iterations=iterations,
        run_time=result.elapsed,
        n_nodes=result.n_nodes,
        n_elements=result.n_elements,
        n_tape_elements=result.n_tape_elements,
        mesh_target_mm=built.mesh_mm,
        load_case=built.model.conditions.label,
        material_sources=built.material_sources,
        design_content_hash=built.design_hash,
        input_fingerprint=input_fingerprint,
        volume=result.volume,
        lift=result.lift,
        height=result.height,
        max_width=result.max_width,
        findings=findings,
        manifest=result.manifest.to_dict(),
    )
    arrays: dict[str, np.ndarray] = {
        "positions": np.asarray(result.positions, dtype=np.float64),
        "initial_positions": np.asarray(result.initial_positions, dtype=np.float64),
        "triangles": np.asarray(result.triangles, dtype=np.int64),
        "principal": np.asarray(result.principal, dtype=np.float64),
    }
    if result.wrinkle_state is not None:
        arrays["wrinkle_state"] = np.asarray(result.wrinkle_state, dtype=np.int8)
    mesh = built.build.rest_model.mesh if built.build.rest_model is not None else None
    if mesh is not None and mesh.triangles.shape == np.asarray(result.triangles).shape:
        arrays["rest_uv"] = np.asarray(mesh.rest_uv, dtype=np.float64)
        arrays["tri_instance"] = np.asarray(mesh.tri_instance, dtype=np.int64)
        arrays["instance_ids"] = np.asarray(mesh.instance_ids, dtype=np.str_)
    arrays["residual_history"] = np.asarray(
        [(float(i), float(r)) for i, r in result.residual_history], dtype=np.float64
    ).reshape(-1, 2)
    return record, arrays
