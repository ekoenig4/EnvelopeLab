"""Special-shape simulations kept with a project: record, display arrays and mesh size.

A shape simulation solves the shape's sub-model, whose skin is sewn from the shape's cut
pieces (:func:`envelopelab.features.primitives.primitive_appendage`). The project keeps
the latest one of every shape as a :class:`~envelopelab.project.model.ShapeRunRecord`
(summary, metrics and provenance) and a result file holding the skin as solved, split
into its pieces with its seams and rim (:class:`~envelopelab.features.scene.ShapeDisplay`,
envelope frame, m), which is all a viewer needs to draw the shape as sewn and inflated.

:func:`auto_mesh_size` picks the target element size of an automatic simulation from
the footprint length :math:`L_f`,

.. math:: h = \\min\\bigl(\\max(L_f / N_f,\\ h_{min}),\\ h_{max}\\bigr),

so that the rim has about :data:`AUTO_MESH_RIM_ELEMENTS` elements: fine enough for the
preview solver to follow the skin's shape (a 23 m rim with 0.25 m elements converged
for a 1.3 m pod) and coarse enough to solve in minutes. All three constants are
**assumed** (no study fixes them); a builder can always solve with a chosen size.
"""

from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING, Any

import numpy as np

from envelopelab.features.scene import ShapeDisplay, simulated_display
from envelopelab.project.model import RunFinding, ShapeRunRecord, utc_now

if TYPE_CHECKING:
    from envelopelab.features.builder import AppendageModel
    from envelopelab.features.metrics import AppendageMetrics
    from envelopelab.features.primitives import PrimitiveDesign
    from envelopelab.solvers.simulation import SimulationResult

#: Rim elements an automatic shape simulation aims for (source: assumed).
AUTO_MESH_RIM_ELEMENTS = 100
#: Smallest and largest automatic element size, m (source: assumed).
AUTO_MESH_MIN = 0.06
AUTO_MESH_MAX = 0.30


def auto_mesh_size(design: PrimitiveDesign) -> float:
    """Target element size of an automatic simulation of a placed shape, m.

    Parameters
    ----------
    design : PrimitiveDesign
        Placed shape.

    Returns
    -------
    float
        :math:`\\min(\\max(L_f/N_f, h_{min}), h_{max})`, m, rounded to 1 mm (module
        docstring).
    """
    size = design.footprint_length / AUTO_MESH_RIM_ELEMENTS
    return round(min(max(size, AUTO_MESH_MIN), AUTO_MESH_MAX), 3)


def model_material_sources(appendage: AppendageModel) -> list[str]:
    """Distinct source tags of every material and tape value of a sub-model."""
    model = appendage.model
    tags: set[str] = set()
    for material in model.materials.values():
        tags.update(str(v["source"]) for v in material.sources().values())
    for cable in model.cables:
        tags.update(str(v["source"]) for v in cable.material.sources().values())
    return sorted(tags)


def shape_run_record(
    shape: str,
    simulation_key: str,
    design: PrimitiveDesign,
    appendage: AppendageModel,
    result: SimulationResult,
    metrics: AppendageMetrics,
    mesh_size: float,
    design_content_hash: str,
) -> tuple[ShapeRunRecord, dict[str, np.ndarray]]:
    """Record and display arrays of a solved shape sub-model.

    Parameters
    ----------
    shape, simulation_key : str
        Shape name and the key of its inputs (see :class:`ShapeRunRecord`).
    design : PrimitiveDesign
        The placed shape that was solved.
    appendage : AppendageModel
        Its sub-model.
    result : SimulationResult
        The solve.
    metrics : AppendageMetrics
        :func:`envelopelab.features.metrics.appendage_metrics` of the solve.
    mesh_size : float
        Target element size used, m.
    design_content_hash : str
        Design document hash at solve time.

    Returns
    -------
    (ShapeRunRecord, dict of str to ndarray)
        Record, and the skin as solved (:func:`display_arrays`).
    """
    iterations, residual = (
        (int(result.residual_history[-1][0]), float(result.residual_history[-1][1]))
        if result.residual_history
        else (0, math.nan)
    )
    findings = [
        RunFinding(code=f.code, severity=f.severity, message=f.message) for f in result.findings
    ]
    if not result.converged and not any(f.severity == "error" for f in findings):
        findings.append(
            RunFinding(
                code="not_converged", severity="error", message=f"not converged: {result.status}"
            )
        )
    stamp = utc_now()
    record = ShapeRunRecord(
        run_id=f"{stamp.strftime('%Y%m%dT%H%M%S')}-shape-{uuid.uuid4().hex[:6]}",
        created=stamp,
        shape=shape,
        simulation_key=simulation_key,
        solver=result.solver,
        solver_version=result.solver_version,
        status=result.status,
        converged=result.converged,
        residual=residual,
        residual_measure=result.residual_measure,
        iterations=iterations,
        run_time=result.elapsed,
        n_nodes=result.n_nodes,
        n_elements=result.n_elements,
        mesh_target_mm=round(1000.0 * mesh_size, 3),
        load_case=appendage.model.conditions.label,
        material_sources=model_material_sources(appendage),
        design_content_hash=design_content_hash,
        pieces=design.primitive.pieces,
        metrics={
            "projected_height_m": float(metrics.projected_height),
            "initial_projected_height_m": float(metrics.initial_projected_height),
            "chamber_pressure_pa": float(metrics.chamber_pressure),
            "skin_wrinkled_fraction": float(metrics.skin_wrinkled_fraction),
            "rim_tape_max_tension_n": float(metrics.rim_tape_max_tension),
            "footprint_max_normal_displacement_m": float(metrics.footprint_max_normal_displacement),
        },
        fos={k: float(v) for k, v in metrics.fos.items()},
        findings=findings,
        manifest=result.manifest.to_dict(),
    )
    return record, display_arrays(simulated_display(design, appendage, result))


def display_arrays(display: ShapeDisplay) -> dict[str, np.ndarray]:
    """A shape display as flat arrays for a result file (m; seams concatenated).

    ``seam_points`` holds every seam's points one after the other and ``seam_offsets``
    where each starts (with the total at the end).
    """
    lengths = [len(s) for s in display.seams]
    return {
        "points": np.asarray(display.points, dtype=np.float64),
        "triangles": np.asarray(display.triangles, dtype=np.int64),
        "piece": np.asarray(display.piece, dtype=np.int64),
        "pieces": np.array([display.pieces], dtype=np.int64),
        "seam_points": (
            np.vstack(display.seams).astype(np.float64) if display.seams else np.zeros((0, 3))
        ),
        "seam_offsets": np.concatenate([[0], np.cumsum(lengths)]).astype(np.int64),
        "rim": np.asarray(display.rim, dtype=np.float64).reshape(-1, 3),
    }


def display_from_arrays(arrays: dict[str, Any]) -> ShapeDisplay:
    """The shape display of :func:`display_arrays` (inverse)."""
    offsets = np.asarray(arrays["seam_offsets"], dtype=np.int64)
    seam_points = np.asarray(arrays["seam_points"], dtype=np.float64).reshape(-1, 3)
    seams = [seam_points[a:b] for a, b in zip(offsets[:-1], offsets[1:], strict=True)]
    return ShapeDisplay(
        np.asarray(arrays["points"], dtype=np.float64),
        np.asarray(arrays["triangles"], dtype=np.int64),
        np.asarray(arrays["piece"], dtype=np.int64),
        int(np.asarray(arrays["pieces"]).ravel()[0]),
        seams,
        np.asarray(arrays["rim"], dtype=np.float64).reshape(-1, 3),
    )
