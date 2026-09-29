"""From a build pack to a Reality Check report of one special-shape feature.

:func:`feature_reality_check` imports the build pack, builds the feature's sub-model from
its imported geometry (:mod:`envelopelab.features.importer`), solves it with the preview
solver, optionally verifies it (a caller-supplied function, normally
``calculix_adapter.run_calculix``: ``envelopelab`` never imports the adapter), measures the
feature, registers the reference mesh, runs the sensitivity sweep and assembles the
report. Every design value comes from the build pack's YAML file.

Reference placement
-------------------
The sub-model lives in the feature's host chart frame. It is placed in the build pack's
frame by the host surface (:math:`x + \\rho_0 e_x`, rotated about the ring axis to the
azimuth of the host panels in the as-sewn shape), then into the reference frame by a
translation that puts the mouth centre on the reference's axis and the mouth on the
reference's lowest point, a brute-force rotation about the vertical axis and ICP
(:mod:`envelopelab.io.reference_mesh`) on the host-patch points. A patch of a surface of
revolution can slide round the axis during ICP; the feature itself (the part that
differs from a surface of revolution) fixes the azimuth in the brute-force step. The
reference is then moved into the model frame for the deviation map.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from envelopelab.features.builder import AppendageModel, FeatureBuildError, build_appendage
from envelopelab.features.construction import feature_checks
from envelopelab.features.ease import classify_audit, loop_length
from envelopelab.features.importer import appendage_spec, tube_spec
from envelopelab.features.metrics import AppendageMetrics, appendage_metrics
from envelopelab.features.spec import FeatureSpec, load_features
from envelopelab.features.tube import TubeModel, build_tube, tube_metrics
from envelopelab.io.reference_mesh import (
    ReferenceMesh,
    Registration,
    coarse_align_about_axis,
    icp,
    parse_volume_notation,
    read_mesh,
    title_text,
)
from envelopelab.materials.membrane import MembraneMaterial, TapeMaterial
from envelopelab.report.reality_check import (
    FeatureSection,
    RealityCheckReport,
    ReportInput,
    VerificationPolicy,
    build_report,
)
from envelopelab.report.sensitivity import (
    SensitivityResult,
    SweepDeltas,
    SweepSettings,
    scaled_material,
    scaled_tape,
    sensitivity_sweep,
)
from envelopelab.solvers.dynamic_relaxation import enclosed_volume, solve
from envelopelab.solvers.membrane import FloatArray
from envelopelab.solvers.model import OperatingConditions, SolverModel, SolverSettings
from envelopelab.solvers.simulation import SimulationResult, from_preview

Verifier = Callable[[SolverModel, FloatArray], SimulationResult]


@dataclass
class FeatureRunConfig:
    """Materials, load case and options of a feature Reality Check (SI).

    Attributes
    ----------
    materials : mapping of str to MembraneMaterial
        Fabric per material zone.
    tapes : mapping of str to TapeMaterial
        Tape per tape name (ring seams, rim, hems).
    internal_temperature : float
        Envelope gas temperature, K.
    altitude : float
        Pressure altitude, m (ISA).
    mesh_size : float, optional
        Overrides the feature's mesh size, m.
    solver_settings : SolverSettings, optional
        Preview solver settings.
    verify : callable, optional
        ``verify(model, start_positions) -> SimulationResult`` (the verification solver).
    reference : Path, optional
        Reference mesh (overrides the build pack's ``reference.mesh``).
    reference_scale : float
        Metres per reference-mesh unit.
    sweep : bool
        Run the sensitivity sweep.
    sweep_parameters : tuple of str, optional
        Subset of the sweep parameters.
    deltas : SweepDeltas
        Sweep ranges.
    policy : VerificationPolicy
        Documented tolerances for ``verified``.
    """

    materials: Mapping[str, MembraneMaterial]
    tapes: Mapping[str, TapeMaterial]
    internal_temperature: float = 373.15
    altitude: float = 0.0
    mesh_size: float | None = None
    solver_settings: SolverSettings | None = None
    verify: Verifier | None = None
    reference: Path | None = None
    reference_scale: float = 1.0
    sweep: bool = False
    sweep_parameters: tuple[str, ...] | None = None
    deltas: SweepDeltas = field(default_factory=SweepDeltas)
    policy: VerificationPolicy = field(default_factory=VerificationPolicy)


@dataclass
class FeatureRun:
    """Everything produced for one feature (model, results, metrics, report)."""

    feature: FeatureSpec
    appendage: AppendageModel
    tube: TubeModel | None
    preview: SimulationResult
    verification: SimulationResult | None
    preview_metrics: AppendageMetrics
    verification_metrics: AppendageMetrics | None
    report: RealityCheckReport
    placement_transform: FloatArray


def _build(
    feature: FeatureSpec,
    built: Any,
    cfg: FeatureRunConfig,
    conditions: OperatingConditions,
    materials: Mapping[str, MembraneMaterial],
    tapes: Mapping[str, TapeMaterial],
    loss_factor: float | None = None,
    seam_error: float = 0.0,
) -> tuple[AppendageModel, TubeModel | None, Any, Any]:
    if feature.kind in ("reinforced_hole", "rim_tape"):
        raise FeatureBuildError(
            f"{feature.name}: a {feature.kind} is modelled as part of a pod, blister or tube "
            "(feed_holes with hem tapes, rim tape); a standalone sub-model is not supported yet"
        )
    if feature.kind in ("tubular", "line_supported"):
        tspec, placement, geo = tube_spec(
            feature, built, tapes, conditions, mesh_size=cfg.mesh_size, loss_factor=loss_factor
        )
        tm = build_tube(tspec, conditions, materials)
        return tm.appendage, tm, placement, geo
    spec, placement, geo = appendage_spec(
        feature, built, tapes, mesh_size=cfg.mesh_size, loss_factor=loss_factor
    )
    if seam_error and spec.skin_outline is not None:
        skin = spec.skin_outline
        length = loop_length(skin)
        factor = 1.0 + spec.match_points * seam_error / length
        centre = skin.mean(axis=0)
        spec = replace(spec, skin_outline=centre + (skin - centre) * factor)
    return build_appendage(spec, conditions, materials), None, placement, geo


def _conditions(cfg: FeatureRunConfig, built: Any, temperature: float) -> OperatingConditions:
    rest = built.rest_model
    z_mouth = float(rest.positions[:, 2].min())
    return OperatingConditions.hot_air(temperature, altitude=cfg.altitude, mouth_height=z_mouth)


def _placement(built: Any, feature: FeatureSpec, host: Any) -> FloatArray:
    """4x4 transform from the feature chart frame to the build pack's frame."""
    mesh = built.rest_model.mesh
    x = built.rest_model.positions
    ring = next(r for r in built.spec.rings if r.name == feature.host.ring)
    g0, g1 = feature.host.gores
    gores = (
        list(range(g0, g1 + 1))
        if g1 >= g0
        else list(range(g0, ring.gore_count + 1)) + list(range(1, g1 + 1))
    )
    rows = list(ring.rows)
    r0, r1 = (rows.index(r) for r in feature.host.rows)
    ids = [
        k
        for k, iid in enumerate(mesh.instance_ids)
        if any(iid == f"{ring.name}/{row}@{g}" for row in rows[r0 : r1 + 1] for g in gores)
    ]
    nodes = np.unique(mesh.triangles[np.isin(mesh.tri_instance, ids)])
    mouth = mesh.openings.get(ring.bottom.name)
    axis = x[np.unique(mouth)].mean(axis=0) if mouth is not None else x.mean(axis=0)
    c = x[nodes].mean(axis=0) - axis
    phi = math.atan2(c[1], c[0])
    rho0 = host.hoop_radius * math.cos(host.normal_elevation)
    rot = np.array(
        [[math.cos(phi), -math.sin(phi), 0.0], [math.sin(phi), math.cos(phi), 0.0], [0.0, 0.0, 1.0]]
    )
    m = np.eye(4)
    m[:3, :3] = rot
    m[:3, 3] = rot @ np.array([rho0, 0.0, 0.0]) + np.array([axis[0], axis[1], 0.0])
    return m


def _apply(m: FloatArray, x: FloatArray) -> FloatArray:
    out: FloatArray = x @ m[:3, :3].T + m[:3, 3]
    return out


def _register(
    am: AppendageModel,
    placement: FloatArray,
    built: Any,
    reference: ReferenceMesh,
    positions: FloatArray,
    rotate_z_deg: float | None,
) -> tuple[ReferenceMesh, Registration]:
    x = built.rest_model.positions
    ring_mouth = [o for o in built.rest_model.mesh.openings if o == built.spec.rings[0].bottom.name]
    mouth_nodes = (
        np.unique(built.rest_model.mesh.openings[ring_mouth[0]])
        if ring_mouth
        else np.arange(len(x))
    )
    shift = np.eye(4)
    centre = x[mouth_nodes].mean(axis=0)
    shift[:3, 3] = -np.array([centre[0], centre[1], x[mouth_nodes, 2].mean()]) + np.array(
        [0.0, 0.0, float(reference.vertices[:, 2].min())]
    )
    to_ref = shift @ placement
    notes = []
    if rotate_z_deg is None:
        coarse = coarse_align_about_axis(_apply(to_ref, positions), reference)
        notes.append(
            "reference frame not given (reference.rotate_z_deg): azimuth found by a "
            "brute-force search, which is ambiguous on a surface of revolution"
        )
    else:
        a = math.radians(rotate_z_deg)
        coarse = np.eye(4)
        coarse[:3, :3] = np.array(
            [
                [math.cos(a), -math.sin(a), 0.0],
                [math.sin(a), math.cos(a), 0.0],
                [0, 0, 1],
            ]
        )
        notes.append(
            f"reference frame from the build pack: rotated {rotate_z_deg:g} deg about the axis"
        )
    # Only the host outside the footprint takes part: the feature is what is compared.
    host_nodes = np.setdiff1d(
        np.unique(am.model.triangles[am.host_triangles]),
        np.unique(am.model.triangles[am.footprint_triangles]),
    )
    host_pts = _apply(coarse @ to_ref, positions[host_nodes])
    reg = icp(host_pts, reference, threshold=0.5, max_iterations=40)
    reg.notes.extend(notes)
    total = reg.matrix @ coarse @ to_ref
    inv = np.asarray(np.linalg.inv(total), dtype=np.float64)
    ref_in_model = reference.transformed(inv[:3, :3], inv[:3, 3])
    reg.notes.append("ICP refined on the host points outside the footprint")
    return ref_in_model, reg


def _sweep(
    feature: FeatureSpec, built: Any, cfg: FeatureRunConfig, base_loss: float
) -> SensitivityResult:
    def factory(
        s: SweepSettings,
    ) -> tuple[SolverModel, Callable[[SimulationResult], dict[str, float]]]:
        cond = _conditions(cfg, built, s.internal_temperature)
        mats = {
            z: scaled_material(m, s.stiffness_factor, s.weight_factor)
            for z, m in cfg.materials.items()
        }
        tapes = {k: scaled_tape(t, s.weight_factor) for k, t in cfg.tapes.items()}
        am, tm, _, _ = _build(
            feature, built, cfg, cond, mats, tapes, s.loss_factor, s.seam_length_error
        )

        def metrics(res: SimulationResult) -> dict[str, float]:
            mt = appendage_metrics(am, res)
            out = {
                "projected_height_m": mt.projected_height,
                "chamber_volume_m3": mt.chamber_volume,
                "host_rim_max_n1_n_per_m": mt.host_rim_max_n1,
                "min_fabric_fos": min(mt.fos.values()),
            }
            if tm is not None:
                tub = tube_metrics(tm, res.positions)
                out["lean_deg"] = float(tub["lean_deg"])  # type: ignore[arg-type]
            return out

        return am.model, metrics

    params = cfg.sweep_parameters
    if feature.kind in ("tubular", "line_supported"):
        # The seam-length error is defined on a rim between match points.
        params = tuple(
            p
            for p in (
                params
                or ("internal_temperature", "stiffness_factor", "weight_factor", "loss_factor")
            )
            if p != "seam_length_error"
        )
    base = SweepSettings(cfg.internal_temperature, loss_factor=base_loss)
    return sensitivity_sweep(factory, base, cfg.deltas, cfg.solver_settings, params)


def feature_reality_check(
    build_pack: str | Path, feature_name: str, cfg: FeatureRunConfig
) -> FeatureRun:
    """Reality Check of one feature of a build pack.

    Parameters
    ----------
    build_pack : str or Path
        Build-pack YAML with ``import``, ``assembly`` and ``features`` sections.
    feature_name : str
        Name of the feature.
    cfg : FeatureRunConfig
        Materials, load case, verification solver, reference and sweep options.

    Returns
    -------
    FeatureRun
        Sub-model, preview and verification results, metrics and the report.
    """
    from envelopelab.assembly.pipeline import import_build_pack

    path = Path(build_pack)
    doc = load_features(path)
    feature = next((f for f in doc.features if f.name == feature_name), None)
    if feature is None:
        raise KeyError(
            f"{path}: no feature {feature_name!r}; have {[f.name for f in doc.features]}"
        )
    built = import_build_pack(path)
    if built.rest_model is None:
        raise RuntimeError(f"{path}: no rest model")
    cond = _conditions(cfg, built, cfg.internal_temperature)
    am, tm, placement, geo = _build(feature, built, cfg, cond, cfg.materials, cfg.tapes)
    model = am.model
    preview = from_preview(model, solve(model, cfg.solver_settings))
    verification = cfg.verify(model, preview.positions) if cfg.verify is not None else None
    pm = appendage_metrics(am, preview)
    vm = appendage_metrics(am, verification) if verification is not None else None
    host = am.spec.host
    section = FeatureSection(
        name=feature.name,
        kind=feature.kind,
        geometry=dict(geo.values),
        geometry_findings=list(geo.findings),
        construction=feature_checks(feature, built, path.parent),
        preview=pm,
        verification=vm,
        as_sewn_height=pm.initial_projected_height,
        notes=list(am.notes),
        pressure=am.feed.as_dict() if am.feed is not None else am.chamber.as_dict(),
    )
    if tm is not None:
        section.tube["preview"] = tube_metrics(tm, preview.positions)
        if verification is not None:
            section.tube["verification"] = tube_metrics(tm, verification.positions)
    to_rest = _placement(built, feature, host) if host is not None else np.eye(4)
    reference = None
    registration = None
    ref_volume = None
    ref_text = ""
    ref_path = cfg.reference or (
        path.parent / str(doc.reference["mesh"]) if "mesh" in doc.reference else None
    )
    if ref_path is not None:
        scale = float(doc.reference.get("scale", cfg.reference_scale))
        mesh = read_mesh(ref_path, scale)
        rot = doc.reference.get("rotate_z_deg")
        reference, registration = _register(
            am, to_rest, built, mesh, preview.positions, None if rot is None else float(rot)
        )
        if host is not None:
            centre = am.footprint_centre
            span = 0.5 * max(float(np.ptp(am.chart[am.rim_nodes], axis=0).max()), 1e-6)
            near = np.linalg.norm(reference.vertices - centre, axis=1) < span
            if near.any():
                section.geometry["reference_projected_height_m"] = float(
                    host.height_above(reference.vertices[near]).max()
                )
    if "title_source" in doc.reference:
        text = title_text(path.parent / str(doc.reference["title_source"]))
        ref_volume = parse_volume_notation(text)
        ref_text = f"title of {doc.reference['title_source']}: {text[:120]}"
    rest = built.rest_model
    volumes = {
        "as-sewn envelope volume (initial shape, geometric)": (
            enclosed_volume(rest.positions, rest.mesh.triangles),
            "the assembled panels on the sewn-circumference surface of revolution; features "
            "not meshed in the envelope are not included; not a solved shape",
        )
    }
    seam_classes = classify_audit(built.audit)
    sensitivity = (
        _sweep(feature, built, cfg, am.feed.loss_factor if am.feed else 0.0) if cfg.sweep else None
    )
    inp = ReportInput(
        title=f"{path.stem}: {feature.name}",
        model=model,
        as_sewn=model.positions,
        preview=preview,
        verification=verification,
        reference=reference,
        registration=registration,
        reference_volume=ref_volume,
        reference_volume_text=ref_text,
        volumes=volumes,
        features=[section],
        seam_classes=seam_classes,
        sensitivity=sensitivity,
        notes=[
            f"sub-model of feature {feature.name}: host patch of the envelope with its edge "
            f"fixed; host geometry from the {host.source if host else 'rigid rim'}",
            "designed ease is a physical input (skin rest lengths), classified as designed "
            "ease, not a seam error",
        ],
        view_direction=None if host is None else host.tangent_u(np.zeros((1, 2)))[0],
        submodel=True,
    )
    report = build_report(inp, cfg.policy)
    return FeatureRun(feature, am, tm, preview, verification, pm, vm, report, to_rest)
