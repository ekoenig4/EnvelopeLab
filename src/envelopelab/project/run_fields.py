r"""Result fields of a stored run, for colouring the 3D view.

A run keeps its result arrays in the project's run directory (positions, initial positions,
triangles, principal resultants, and for preview runs the warp/weft resultants and the
wrinkle state; see :func:`envelopelab.project.simulation.run_record`). This module turns
them into named scalar fields with units. Nothing is recomputed from the solver: every
field is read from the stored arrays, except the factor of safety, which divides the
stored yarn resultants by the zone strengths of the solved model
(:func:`envelopelab.solvers.results.triangle_factors_of_safety`).

A field that cannot be made from a run (an older run without warp/weft resultants, a
CalculiX run, which does not report them, or no solved model to take strengths from) is
left out, and :func:`missing_fields` says why, so the view can say so instead of showing
something else.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from envelopelab.design.model import DesignDocument
from envelopelab.solvers.model import SolverModel
from envelopelab.solvers.results import (
    ResultField,
    factors_from_strengths,
    triangle_factors_of_safety,
)

#: Field keys in display order, with their labels (unit in brackets, SI).
FIELD_LABELS = {
    "fos_warp": "Factor of safety, warp [-]",
    "fos_weft": "Factor of safety, weft [-]",
    "n1": "Major principal resultant [N/m]",
    "n2": "Minor principal resultant [N/m]",
    "n_warp": "Warp resultant [N/m]",
    "n_weft": "Weft resultant [N/m]",
    "wrinkle_state": "Wrinkling (0 taut, 1 wrinkled, 2 slack) [-]",
    "displacement": "Displacement from the as-sewn shape [m]",
    "deviation": "Deviation from design, + outside [m]",
}
#: Fields that are factors of safety (a lower value is worse; a limit applies).
SAFETY_FIELDS = ("fos_warp", "fos_weft")


def _model_matches(arrays: Mapping[str, np.ndarray], model: SolverModel | None) -> bool:
    return model is not None and len(model.triangles) == len(arrays["triangles"])


def run_fields(
    arrays: Mapping[str, np.ndarray],
    model: SolverModel | None = None,
    design: DesignDocument | None = None,
) -> dict[str, ResultField]:
    """The scalar fields that can be shown for a run.

    Parameters
    ----------
    arrays : mapping of str to ndarray
        The run's result arrays: ``positions`` and ``initial_positions`` (m, shape (n, 3)),
        ``triangles`` (shape (m, 3)) and optionally ``principal`` (N/m, shape (m, 2)),
        ``fabric_resultants`` (N/m, shape (m, 3)) and ``wrinkle_state`` (shape (m,)).
    model : SolverModel, optional
        The solved model of the run, for the zone strengths of the factor of safety. Pass
        it only when the run is current (solved from the same design state); a model with
        another number of triangles is ignored.
    design : DesignDocument, optional
        The design the run was solved from, for the deviation from it
        (:func:`envelopelab.project.deviation.envelope_deviation`). Pass it only when the
        run is current.

    Returns
    -------
    dict of str to ResultField
        Keys of :data:`FIELD_LABELS` that the arrays allow, in that order. Units:
        ``displacement`` and ``deviation`` m (per node), resultants N/m, factors of safety
        and wrinkle state dimensionless (per triangle).
    """
    out: dict[str, ResultField] = {}
    fabric = arrays.get("fabric_resultants")
    if fabric is not None and model is not None and _model_matches(arrays, model):
        fos = triangle_factors_of_safety(model, fabric)
        out["fos_warp"] = ResultField(
            "fos_warp", "triangle", fos[:, 0], "-", "warp strength / warp resultant"
        )
        out["fos_weft"] = ResultField(
            "fos_weft", "triangle", fos[:, 1], "-", "weft strength / weft resultant"
        )
    if "principal" in arrays:
        principal = np.asarray(arrays["principal"], dtype=np.float64)
        out["n1"] = ResultField(
            "n1", "triangle", principal[:, 0], "N/m", "major principal Cauchy resultant"
        )
        out["n2"] = ResultField(
            "n2", "triangle", principal[:, 1], "N/m", "minor principal Cauchy resultant"
        )
    if fabric is not None:
        f = np.asarray(fabric, dtype=np.float64)
        out["n_warp"] = ResultField(
            "n_warp", "triangle", f[:, 0], "N/m", "resultant along the deformed warp"
        )
        out["n_weft"] = ResultField(
            "n_weft", "triangle", f[:, 1], "N/m", "resultant along the deformed weft"
        )
    if "wrinkle_state" in arrays:
        out["wrinkle_state"] = ResultField(
            "wrinkle_state",
            "triangle",
            np.asarray(arrays["wrinkle_state"], dtype=np.float64),
            "-",
            "tension-field state: 0 taut, 1 wrinkled, 2 slack",
        )
    if "initial_positions" in arrays:
        moved = np.asarray(arrays["positions"]) - np.asarray(arrays["initial_positions"])
        out["displacement"] = ResultField(
            "displacement",
            "node",
            np.linalg.norm(moved, axis=1),
            "m",
            "displacement from the initial (as-sewn) positions",
        )
    if design is not None and design.gores is not None and "positions" in arrays:
        from envelopelab.project.deviation import envelope_deviation

        out["deviation"] = ResultField(
            "deviation",
            "node",
            envelope_deviation(design, np.asarray(arrays["positions"])),
            "m",
            "normal distance from the designed surface: + outside, - inside",
        )
    return out


def shape_run_fields(
    arrays: Mapping[str, np.ndarray],
    designed_points: np.ndarray | None = None,
    designed_triangles: np.ndarray | None = None,
) -> dict[str, ResultField]:
    """The scalar fields of a special shape's stored simulation (its skin).

    Parameters
    ----------
    arrays : mapping of str to ndarray
        The shape run's arrays (:func:`envelopelab.project.shape_runs.shape_run_record`):
        ``points`` (m) and ``triangles`` of the solved skin, and, from this version on,
        ``skin_principal``, ``skin_strength``, ``skin_fabric_resultants`` (N/m),
        ``skin_wrinkle_state`` and ``skin_initial_points`` (m).
    designed_points, designed_triangles : ndarray, optional
        The shape's designed skin in the same (envelope) frame, m, for the deviation from
        it (:func:`envelopelab.project.deviation.deviation_at_nodes`). Pass it only when
        the simulation is current.

    Returns
    -------
    dict of str to ResultField
        As :func:`run_fields`, for the fields the arrays allow.
    """
    out: dict[str, ResultField] = {}
    fabric = arrays.get("skin_fabric_resultants")
    strength = arrays.get("skin_strength")
    if fabric is not None and strength is not None:
        fos = factors_from_strengths(fabric, strength)
        out["fos_warp"] = ResultField(
            "fos_warp", "triangle", fos[:, 0], "-", "warp strength / warp resultant"
        )
        out["fos_weft"] = ResultField(
            "fos_weft", "triangle", fos[:, 1], "-", "weft strength / weft resultant"
        )
    if "skin_principal" in arrays:
        principal = np.asarray(arrays["skin_principal"], dtype=np.float64)
        out["n1"] = ResultField(
            "n1", "triangle", principal[:, 0], "N/m", "major principal Cauchy resultant"
        )
        out["n2"] = ResultField(
            "n2", "triangle", principal[:, 1], "N/m", "minor principal Cauchy resultant"
        )
    if fabric is not None:
        f = np.asarray(fabric, dtype=np.float64)
        out["n_warp"] = ResultField(
            "n_warp", "triangle", f[:, 0], "N/m", "resultant along the deformed warp"
        )
        out["n_weft"] = ResultField(
            "n_weft", "triangle", f[:, 1], "N/m", "resultant along the deformed weft"
        )
    if "skin_wrinkle_state" in arrays:
        out["wrinkle_state"] = ResultField(
            "wrinkle_state",
            "triangle",
            np.asarray(arrays["skin_wrinkle_state"], dtype=np.float64),
            "-",
            "tension-field state: 0 taut, 1 wrinkled, 2 slack",
        )
    points = np.asarray(arrays["points"], dtype=np.float64)
    if "skin_initial_points" in arrays:
        moved = points - np.asarray(arrays["skin_initial_points"], dtype=np.float64)
        out["displacement"] = ResultField(
            "displacement",
            "node",
            np.linalg.norm(moved, axis=1),
            "m",
            "displacement from the initial (as-sewn) positions",
        )
    if designed_points is not None and designed_triangles is not None:
        from envelopelab.project.deviation import deviation_at_nodes

        out["deviation"] = ResultField(
            "deviation",
            "node",
            deviation_at_nodes(points, designed_points, designed_triangles),
            "m",
            "normal distance from the designed skin: + outside, - inside",
        )
    return {k: out[k] for k in FIELD_LABELS if k in out}


def shape_missing_fields(arrays: Mapping[str, np.ndarray], current: bool = True) -> dict[str, str]:
    """Fields :func:`shape_run_fields` cannot give for a shape run, and why.

    Parameters
    ----------
    arrays : mapping of str to ndarray
        The shape run's arrays.
    current : bool
        Whether the simulation is current (the deviation needs the design it was solved
        from).
    """
    shown = set(shape_run_fields(arrays))
    if current:
        shown.add("deviation")
    old = "skin_principal" not in arrays
    reasons: dict[str, str] = {}
    for key in FIELD_LABELS:
        if key in shown:
            continue
        if key == "deviation":
            reasons[key] = "only for a current simulation (the design it was solved from)"
        elif old:
            reasons[key] = "this simulation has no stored skin results (run it again)"
        elif key in SAFETY_FIELDS or key in ("n_warp", "n_weft"):
            reasons[key] = "the solver did not report warp/weft resultants"
        else:
            reasons[key] = "not stored with this simulation"
    return reasons


def missing_fields(
    arrays: Mapping[str, np.ndarray],
    model: SolverModel | None = None,
    solver: str = "",
    design: DesignDocument | None = None,
) -> dict[str, str]:
    """Fields of :data:`FIELD_LABELS` that :func:`run_fields` leaves out, and why.

    Parameters
    ----------
    arrays, model, design
        As for :func:`run_fields`.
    solver : str
        The run's solver id (``envelopelab-preview`` or ``calculix``), for the reason.

    Returns
    -------
    dict of str to str
        Field key to a one-line reason.
    """
    shown = set(run_fields(arrays, model))  # without the deviation: it is not cheap
    if design is not None and design.gores is not None and "positions" in arrays:
        shown.add("deviation")
    if "fabric_resultants" not in arrays:
        why_fabric = (
            "CalculiX does not report warp/weft resultants"
            if solver == "calculix"
            else "this run has no warp/weft resultants (run it again)"
        )
    else:
        why_fabric = ""
    reasons: dict[str, str] = {}
    for key in FIELD_LABELS:
        if key in shown:
            continue
        if key in SAFETY_FIELDS:
            reasons[key] = why_fabric or "only for a current run (zone strengths of its model)"
        elif key in ("n_warp", "n_weft"):
            reasons[key] = why_fabric
        elif key == "deviation":
            reasons[key] = "only for a current run (the design it was solved from)"
        elif key == "wrinkle_state":
            reasons[key] = "the solver did not report a wrinkle state"
        else:
            reasons[key] = "not stored with this run"
    return reasons
