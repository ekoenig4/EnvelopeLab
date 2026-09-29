r"""Compare two :class:`~envelopelab.solvers.simulation.SimulationResult` objects.

Typically the interactive preview solver against the verification solver. Meshes are
aligned first: when both results share the node set (same initial positions) the mapping
is the identity; otherwise every node of the second mesh is matched to the nearest node of
the first by initial position, and elements by nearest centroid. The largest matching
distance is reported so that a poor alignment is visible.

Compared quantities and their relative difference :math:`|b - a| / |a|`:

* height above the mouth, maximum width, enclosed volume;
* nodal displacement: maximum magnitude, and the RMS of the nodal difference relative to
  the largest displacement of the first result;
* stress resultants: area-weighted mean and 99th percentile of :math:`N_1` (the 99th
  percentile is used instead of the maximum because single-element peaks are
  mesh-dependent);
* tape tension: maximum and mean over all tape elements.

Every row above ``tolerance`` (default 5 %, AGENTS.md "preview vs. verification solver")
is flagged. A comparison involving an unconverged result is never reported as passing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree

from envelopelab.solvers.membrane import FloatArray, IntArray
from envelopelab.solvers.simulation import SimulationResult

DEFAULT_TOLERANCE = 0.05


@dataclass(frozen=True)
class ComparisonRow:
    """One compared quantity.

    Attributes
    ----------
    name : str
        Quantity.
    reference : float
        Value of the first (reference) result, in ``unit``.
    other : float
        Value of the second result, in ``unit``.
    unit : str
        Unit.
    difference : float
        Relative difference, dimensionless.
    tolerance : float
        Flag limit, dimensionless.
    """

    name: str
    reference: float
    other: float
    unit: str
    difference: float
    tolerance: float

    @property
    def flagged(self) -> bool:
        """True when the difference exceeds the tolerance (or is not finite)."""
        return not math.isfinite(self.difference) or self.difference > self.tolerance


@dataclass
class Comparison:
    """Result of :func:`compare_results`.

    Attributes
    ----------
    reference_solver, other_solver : str
        Solver names.
    rows : list of ComparisonRow
        Compared quantities.
    identical_mesh : bool
        True when both results use the same nodes.
    max_alignment_distance : float
        Largest node matching distance, m (0 for an identical mesh).
    both_converged : bool
        Whether both inputs converged.
    notes : list of str
        Alignment and validity notes.
    """

    reference_solver: str
    other_solver: str
    rows: list[ComparisonRow]
    identical_mesh: bool
    max_alignment_distance: float
    both_converged: bool
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> list[ComparisonRow]:
        """Rows beyond tolerance."""
        return [r for r in self.rows if r.flagged]

    @property
    def passed(self) -> bool:
        """True only when both results converged and no row is flagged."""
        return self.both_converged and not self.flagged

    def row(self, name: str) -> ComparisonRow:
        """The row called ``name``."""
        for r in self.rows:
            if r.name == name:
                return r
        raise KeyError(name)

    def to_markdown(self) -> str:
        """Markdown table of the comparison."""
        lines = [
            f"| Quantity | {self.reference_solver} | {self.other_solver} | Unit | "
            "Difference | Tolerance | Status |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in self.rows:
            status = "**beyond tolerance**" if r.flagged else "within tolerance"
            lines.append(
                f"| {r.name} | {r.reference:.4g} | {r.other:.4g} | {r.unit} | "
                f"{r.difference * 100:.1f} % | {r.tolerance * 100:g} % | {status} |"
            )
        return "\n".join(lines)


def _relative(a: float, b: float) -> float:
    if a == 0.0:
        return 0.0 if b == 0.0 else math.inf
    return abs(b - a) / abs(a)


def _areas(x: FloatArray, tri: IntArray) -> FloatArray:
    e = x[tri]
    out: FloatArray = 0.5 * np.linalg.norm(np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0]), axis=1)
    return out


def align_nodes(a: SimulationResult, b: SimulationResult) -> tuple[IntArray, float, bool]:
    """Index into ``a`` of the node nearest to each node of ``b`` (initial positions).

    Returns
    -------
    mapping : ndarray of int, shape (n_b,)
        Node of ``a`` matched to each node of ``b``.
    distance : float
        Largest matching distance, m.
    identical : bool
        True when both node sets coincide (within 1 um).
    """
    if a.n_nodes == b.n_nodes and np.allclose(
        a.initial_positions, b.initial_positions, atol=1e-6, rtol=0.0
    ):
        return np.arange(b.n_nodes), 0.0, True
    dist, idx = cKDTree(a.initial_positions).query(b.initial_positions)
    return np.asarray(idx, dtype=np.int64), float(np.max(dist)), False


def compare_results(
    reference: SimulationResult,
    other: SimulationResult,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Comparison:
    """Compare two simulation results (see module docstring).

    Parameters
    ----------
    reference : SimulationResult
        First result (normally the preview solver).
    other : SimulationResult
        Second result (normally the verification solver).
    tolerance : float
        Relative difference above which a row is flagged, dimensionless.

    Returns
    -------
    Comparison
        Rows, alignment data and validity.
    """
    mapping, distance, identical = align_nodes(reference, other)
    notes: list[str] = []
    if not identical:
        notes.append(
            f"meshes differ: nodes matched by nearest initial position (largest distance "
            f"{distance * 1000:.1f} mm)"
        )
    both = reference.converged and other.converged
    if not both:
        notes.append("at least one result did not converge: the comparison is NOT valid")
    ua, ub = reference.displacements, other.displacements
    diff = ub - ua[mapping]
    scale = float(np.max(np.linalg.norm(ua, axis=1))) or 1.0
    rms = float(np.sqrt(np.mean(np.sum(diff**2, axis=1)))) / scale
    wa = _areas(reference.positions, reference.triangles)
    wb = _areas(other.positions, other.triangles)
    n1a, n1b = reference.principal[:, 0], other.principal[:, 0]

    def tapes(r: SimulationResult) -> FloatArray:
        values = [v for v in r.tape_tensions.values() if len(v)]
        return np.concatenate(values) if values else np.zeros(0)

    ta, tb = tapes(reference), tapes(other)
    rows = [
        ("height", reference.height, other.height, "m"),
        ("maximum width", reference.max_width, other.max_width, "m"),
        ("volume", reference.volume, other.volume, "m^3"),
        (
            "maximum displacement",
            float(np.max(np.linalg.norm(ua, axis=1))),
            float(np.max(np.linalg.norm(ub, axis=1))),
            "m",
        ),
        (
            "mean N1 (area-weighted)",
            float(np.average(n1a, weights=wa)),
            float(np.average(n1b, weights=wb)),
            "N/m",
        ),
        (
            "N1, 99th percentile",
            float(np.percentile(n1a, 99)),
            float(np.percentile(n1b, 99)),
            "N/m",
        ),
        (
            "maximum tape tension",
            float(ta.max()) if ta.size else 0.0,
            float(tb.max()) if tb.size else 0.0,
            "N",
        ),
        (
            "mean tape tension",
            float(ta.mean()) if ta.size else 0.0,
            float(tb.mean()) if tb.size else 0.0,
            "N",
        ),
    ]
    out = [ComparisonRow(n, a, b, u, _relative(a, b), tolerance) for n, a, b, u in rows]
    out.insert(
        4,
        ComparisonRow(
            "nodal displacement difference (RMS / max displacement)",
            0.0,
            rms,
            "-",
            rms,
            tolerance,
        ),
    )
    return Comparison(reference.solver, other.solver, out, identical, distance, both, notes)
