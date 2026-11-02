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

from envelopelab.solvers.model import SolverModel
from envelopelab.solvers.results import ResultField, triangle_factors_of_safety

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
}
#: Fields that are factors of safety (a lower value is worse; a limit applies).
SAFETY_FIELDS = ("fos_warp", "fos_weft")


def _model_matches(arrays: Mapping[str, np.ndarray], model: SolverModel | None) -> bool:
    return model is not None and len(model.triangles) == len(arrays["triangles"])


def run_fields(
    arrays: Mapping[str, np.ndarray], model: SolverModel | None = None
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

    Returns
    -------
    dict of str to ResultField
        Keys of :data:`FIELD_LABELS` that the arrays allow, in that order. Units:
        ``displacement`` m (per node), resultants N/m, factors of safety and wrinkle state
        dimensionless (per triangle).
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
    return out


def missing_fields(
    arrays: Mapping[str, np.ndarray], model: SolverModel | None = None, solver: str = ""
) -> dict[str, str]:
    """Fields of :data:`FIELD_LABELS` that :func:`run_fields` leaves out, and why.

    Parameters
    ----------
    arrays, model
        As for :func:`run_fields`.
    solver : str
        The run's solver id (``envelopelab-preview`` or ``calculix``), for the reason.

    Returns
    -------
    dict of str to str
        Field key to a one-line reason.
    """
    shown = run_fields(arrays, model)
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
        elif key == "wrinkle_state":
            reasons[key] = "the solver did not report a wrinkle state"
        else:
            reasons[key] = "not stored with this run"
    return reasons
