r"""Solver-independent simulation result.

Both the interactive preview solver (:mod:`envelopelab.solvers.dynamic_relaxation`) and the
verification solver adapters (``solvers/calculix_adapter``) are normalised into a
:class:`SimulationResult`, so comparison, post-processing and reporting code works on
either. All quantities are SI (see :data:`SIMULATION_UNITS`).

Derived shape measures
----------------------
* **Height** :math:`H = \max_i z_i - z_{mouth}` (m), with :math:`z_{mouth}` the mean height
  of the fixed mouth nodes (or the lowest node when none are given).
* **Maximum width** :math:`W = 2 \max_i \rho_i` (m), with :math:`\rho_i` the horizontal
  distance of node :math:`i` from the vertical axis through the mouth centre.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from envelopelab.solvers.dynamic_relaxation import SolveResult
from envelopelab.solvers.manifest import RunManifest
from envelopelab.solvers.membrane import FloatArray, IntArray
from envelopelab.solvers.model import SolverModel

Severity = Literal["info", "warning", "error"]

SIMULATION_UNITS: dict[str, str] = {
    "positions": "m",
    "stress": "N/m",
    "principal": "N/m",
    "tape_tensions": "N",
    "reactions": "N",
    "volume": "m^3",
    "lift": "N",
    "height": "m",
    "max_width": "m",
    "elapsed": "s",
    "residual": "- (solver-specific relative measure, see residual_measure)",
}


@dataclass(frozen=True)
class Finding:
    """A warning or error attached to a result (code, message, severity)."""

    code: str
    message: str
    severity: Severity = "warning"


@dataclass(frozen=True)
class IterationRecord:
    """One solver iteration or outer loop pass.

    Attributes
    ----------
    stage : str
        Solver stage (e.g. ``prestress``, ``inflation``, ``wrinkling pass 3``).
    step : int
        Step or pass number within the stage.
    increment : int
        Load increment (0 when the solver has none).
    iteration : int
        Iteration within the increment.
    residual : float
        Residual measure of that iteration (see ``SimulationResult.residual_measure``).
    """

    stage: str
    step: int
    increment: int
    iteration: int
    residual: float


@dataclass
class SimulationResult:
    """Normalised result of one structural solve.

    Attributes
    ----------
    solver : str
        Solver identifier (``envelopelab-preview`` or ``calculix``).
    solver_version : str
        Solver version string.
    status : str
        ``converged`` or the reason the solve stopped.
    converged : bool
        True only when every stage met its convergence criteria.
    positions, initial_positions : ndarray, shape (n, 3)
        Equilibrium and initial node positions, m.
    triangles : ndarray of int, shape (m, 3)
        Membrane elements.
    stress : ndarray, shape (m, 3, 3)
        Cauchy stress-resultant tensor per element in global axes, N/m.
    principal : ndarray, shape (m, 2)
        In-plane principal resultants :math:`N_1 \\ge N_2`, N/m.
    tape_tensions : dict of str to ndarray
        Tension per tape element, N.
    tape_edges : dict of str to ndarray of int
        Node pairs of each tape set.
    reactions : dict of str to ndarray
        Reaction resultant per constraint group, N, shape (3,).
    nodal_reactions : ndarray, shape (n, 3)
        Reaction per node, N.
    volume, lift : float
        Enclosed volume (m^3) and gross lift (N) of the modelled portion.
    residual_history : list of (int, float)
        (cumulative iteration, residual) samples.
    iteration_history : list of IterationRecord
        Stage/step/increment/iteration log.
    residual_measure : str
        What the residual numbers mean for this solver.
    elapsed : float
        Wall time, s.
    mouth_nodes : ndarray of int
        Nodes used as the mouth datum for height and width.
    wrinkle_state : ndarray of int8, optional
        0 taut, 1 wrinkled, 2 slack per element, when the solver reports it.
    findings : list of Finding
        Warnings and errors; errors mean the result is not final.
    chamber_volumes : dict of str to float
        Volume of the main envelope gas and of each appendage chamber, m^3 (empty
        without chambers).
    manifest : RunManifest
        Reproducibility record.
    """

    solver: str
    solver_version: str
    status: str
    converged: bool
    positions: FloatArray
    initial_positions: FloatArray
    triangles: IntArray
    stress: FloatArray
    principal: FloatArray
    tape_tensions: dict[str, FloatArray]
    tape_edges: dict[str, IntArray]
    reactions: dict[str, FloatArray]
    nodal_reactions: FloatArray
    volume: float
    lift: float
    residual_history: list[tuple[int, float]]
    iteration_history: list[IterationRecord]
    residual_measure: str
    elapsed: float
    mouth_nodes: IntArray
    manifest: RunManifest
    wrinkle_state: np.ndarray | None = None
    findings: list[Finding] = field(default_factory=list)
    chamber_volumes: dict[str, float] = field(default_factory=dict)

    @property
    def n_nodes(self) -> int:
        """Number of nodes."""
        return len(self.positions)

    @property
    def n_elements(self) -> int:
        """Number of membrane elements."""
        return len(self.triangles)

    @property
    def n_tape_elements(self) -> int:
        """Number of tape elements."""
        return int(sum(len(v) for v in self.tape_edges.values()))

    @property
    def displacements(self) -> FloatArray:
        """Displacement from the initial positions, m."""
        return self.positions - self.initial_positions

    @property
    def errors(self) -> list[Finding]:
        """Error-level findings (non-empty means the result is not final)."""
        return [f for f in self.findings if f.severity == "error"]

    def _axis(self) -> tuple[FloatArray, float]:
        x = self.positions
        if len(self.mouth_nodes):
            centre = self.initial_positions[self.mouth_nodes].mean(axis=0)
            return centre, float(x[self.mouth_nodes, 2].mean())
        centre = self.initial_positions.mean(axis=0)
        return centre, float(x[:, 2].min())

    @property
    def height(self) -> float:
        """Top of the envelope above the mouth datum, m."""
        _, z_mouth = self._axis()
        return float(self.positions[:, 2].max()) - z_mouth

    @property
    def max_width(self) -> float:
        """Twice the largest horizontal distance from the mouth axis, m."""
        centre, _ = self._axis()
        rho = np.hypot(self.positions[:, 0] - centre[0], self.positions[:, 1] - centre[1])
        return 2.0 * float(rho.max())

    @property
    def max_tape_tension(self) -> float:
        """Largest tension over all tape elements, N (0 without tapes)."""
        values = [float(v.max()) for v in self.tape_tensions.values() if len(v)]
        return max(values) if values else 0.0

    def summary(self) -> dict[str, Any]:
        """Scalar summary with units (for tables and JSON)."""
        return {
            "solver": self.solver,
            "solver_version": self.solver_version,
            "status": self.status,
            "converged": self.converged,
            "nodes": self.n_nodes,
            "elements": self.n_elements,
            "tape_elements": self.n_tape_elements,
            "height_m": self.height,
            "max_width_m": self.max_width,
            "volume_m3": self.volume,
            "lift_n": self.lift,
            "max_tape_tension_n": self.max_tape_tension,
            "max_n1_n_per_m": float(self.principal[:, 0].max()) if self.n_elements else 0.0,
            "elapsed_s": self.elapsed,
            "iterations": len(self.iteration_history),
            "final_residual": self.residual_history[-1][1] if self.residual_history else math.nan,
            "residual_measure": self.residual_measure,
        }


def principal_resultants(stress: FloatArray, triangles: IntArray, x: FloatArray) -> FloatArray:
    """In-plane principal values of global resultant tensors, shape (m, 2), N/m.

    Parameters
    ----------
    stress : ndarray, shape (m, 3, 3)
        Resultant tensors in global axes, N/m.
    triangles : ndarray of int, shape (m, 3)
        Elements.
    x : ndarray, shape (n, 3)
        Current positions used for the element planes, m.

    Returns
    -------
    ndarray, shape (m, 2)
        :math:`N_1 \\ge N_2`, N/m.
    """
    xe = x[triangles]
    e1 = xe[:, 1] - xe[:, 0]
    e1 /= np.linalg.norm(e1, axis=1)[:, None]
    nrm = np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0])
    nrm /= np.linalg.norm(nrm, axis=1)[:, None]
    e2 = np.cross(nrm, e1)
    s11 = np.einsum("mi,mij,mj->m", e1, stress, e1)
    s22 = np.einsum("mi,mij,mj->m", e2, stress, e2)
    s12 = np.einsum("mi,mij,mj->m", e1, stress, e2)
    mean = 0.5 * (s11 + s22)
    rad = np.sqrt((0.5 * (s11 - s22)) ** 2 + s12**2)
    return np.column_stack([mean + rad, mean - rad])


def mouth_nodes(model: SolverModel) -> IntArray:
    """Nodes of the constraint named ``mouth`` (else the first constraint, else none)."""
    for con in model.constraints:
        if con.name == "mouth":
            return con.nodes
    return model.constraints[0].nodes if model.constraints else np.zeros(0, dtype=np.int64)


def from_preview(
    model: SolverModel, result: SolveResult, manifest: RunManifest | None = None
) -> SimulationResult:
    """Normalise a preview-solver result.

    Parameters
    ----------
    model : SolverModel
        The solved model.
    result : SolveResult
        Preview result.
    manifest : RunManifest, optional
        Run record; built from the model and result metadata when omitted.

    Returns
    -------
    SimulationResult
        With the preview's residual history (relative residual
        :math:`\\|PR\\|/\\|F_{ext}\\|`, sampled every progress interval).
    """
    from envelopelab.solvers.manifest import manifest_for

    conv = result.convergence
    history = [IterationRecord("dynamic relaxation", 1, 0, it, res) for it, res in conv.history]
    mouth = mouth_nodes(model)
    return SimulationResult(
        solver="envelopelab-preview",
        solver_version=str(result.metadata.get("dependencies", {}).get("envelopelab", "")),
        status=conv.status,
        converged=conv.converged,
        positions=result.positions,
        initial_positions=result.initial_positions,
        triangles=model.triangles,
        stress=result.stress,
        principal=result.principal,
        tape_tensions=dict(result.tape_tensions),
        tape_edges={c.name: c.edges for c in model.cables},
        reactions=dict(result.loads.reactions),
        nodal_reactions=result.reactions,
        volume=result.volume,
        lift=result.lift,
        residual_history=list(conv.history),
        iteration_history=history,
        residual_measure="relative out-of-balance force ||P R|| / ||F_ext||",
        elapsed=conv.run_time,
        mouth_nodes=mouth,
        manifest=manifest or manifest_for(model, "envelopelab-preview", result.metadata),
        wrinkle_state=result.state,
        findings=[Finding(w.code, w.message, w.severity) for w in result.warnings],
        chamber_volumes=dict(result.chamber_volumes),
    )
