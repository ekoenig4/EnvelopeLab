r"""Dynamic-relaxation preview solver for as-sewn envelopes.

Finds the static equilibrium of a pressurised membrane with tapes by integrating a
fictitious damped motion until the out-of-balance forces vanish [Barnes]_.

Governing equations
-------------------
For node :math:`i` with fictitious mass :math:`m_i` and time step :math:`\Delta t = 1`,

.. math::
    R_i = F^{ext}_i(x) - F^{int}_i(x), \qquad
    v_i^{t+\frac12} = v_i^{t-\frac12} + \frac{\Delta t}{m_i} P_i R_i^t, \qquad
    x_i^{t+1} = x_i^t + \Delta t\, v_i^{t+\frac12}

where :math:`P_i` projects onto the free directions of node :math:`i` (zero for fixed
nodes, in-plane for symmetry nodes). External forces are

* hydrostatic follower pressure :math:`\Delta p(z) = p_0 + (\rho_{amb} - \rho_{int})\,g\,
  \max(z - z_{mouth}, 0)`, integrated linearly over each current triangle:
  :math:`f_a = (2p_a + p_b + p_c)\, A\, n / 12`;
* pressure on unmeshed caps (:class:`~envelopelab.solvers.model.PressureClosure`);
* fabric and tape self-weight (dead, from rest area and rest length);
* point, line and distributed dead loads.

Internal forces come from CST membrane elements (:mod:`envelopelab.solvers.membrane`)
with the tension-field law, and tension-only bars
:math:`T = EA \max(L/L_0 - 1, 0)`.

Masses and damping
------------------
Masses follow the Gershgorin bound of the tangent stiffness, :math:`m_i = \lambda\,
\Delta t^2 \sum_j |K_{ij}| / 2` (:math:`\lambda` = ``mass_factor``), which is twice the
explicit stability limit :math:`m_i \ge \Delta t^2 \sum_j |K_{ij}| / 4`; they are
recomputed at each kinetic-energy reset. *Kinetic damping* (default) tracks
:math:`KE = \sum_i \tfrac12 m_i |v_i|^2`; when it falls, the positions are moved back to
the estimated energy peak, :math:`x^\ast = x^t - \tfrac12 \Delta t\, v^{t-\frac12}`
[Topping]_, and the velocities are zeroed. *Viscous damping* uses
:math:`v^{t+\frac12} = [(1 - c/2)\, v^{t-\frac12} + R/m] / (1 + c/2)`.

Convergence
-----------
Converged when :math:`\|P R\|_2 / \|F^{ext}\|_2 <` ``tolerance`` (default :math:`10^{-6}`).
A solve that stops for any other reason (iteration or time limit, cancellation, NaN) is
returned with ``converged = False`` and an error-level warning; it is never final.

References
----------
.. [Barnes] M. R. Barnes, "Form finding and analysis of tension structures by dynamic
   relaxation", Int. J. Space Struct. 14 (1999) 89-104.
.. [Topping] B. H. V. Topping and P. Ivanyi, *Computer Aided Design of Cable Membrane
   Structures*, Saxe-Coburg (2007), ch. 3.
.. [Underwood] P. Underwood, "Dynamic relaxation", in *Computational Methods for Transient
   Analysis*, T. Belytschko and T. J. R. Hughes (eds.), North-Holland (1983) 245-265.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from envelopelab.solvers.membrane import (
    SLACK,
    TAUT,
    WRINKLED,
    FloatArray,
    IntArray,
    cauchy_resultants,
    deformation_gradient,
    element_stiffness_rowsum,
    green_strain,
    internal_forces,
    rest_geometry,
    tension_field,
)
from envelopelab.solvers.model import SolverModel, SolverSettings

SolveStatus = Literal["converged", "max_iterations", "time_limit", "cancelled", "diverged"]
Severity = Literal["info", "warning", "error"]

#: Units of every result quantity (also written into the result metadata).
UNITS: dict[str, str] = {
    "positions": "m",
    "displacements": "m",
    "reactions": "N",
    "stress_resultants": "N/m",
    "tape_tensions": "N",
    "volume": "m^3",
    "lift": "N",
    "pressure": "Pa",
    "strain": "-",
    "residual": "- (relative)",
    "run_time": "s",
}
_LARGE_STRAIN = 0.10


class CancellationToken:
    """Thread-safe cancellation flag checked by the solver every ``progress_interval``."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation (the solver stops at its next check)."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """True once :meth:`cancel` was called."""
        return self._event.is_set()


@dataclass(frozen=True)
class SolverProgress:
    """Snapshot passed to the progress callback.

    Attributes
    ----------
    iteration : int
        Iterations done.
    max_iterations : int
        Iteration limit.
    residual : float
        Relative residual, dimensionless.
    kinetic_energy : float
        Fictitious kinetic energy (fictitious units).
    elapsed : float
        Wall time, s.
    tolerance : float
        Target relative residual.
    """

    iteration: int
    max_iterations: int
    residual: float
    kinetic_energy: float
    elapsed: float
    tolerance: float

    @property
    def fraction(self) -> float:
        """Rough progress estimate in [0, 1] from the residual decade reached."""
        if self.residual <= self.tolerance:
            return 1.0
        if not math.isfinite(self.residual) or self.residual >= 1.0:
            return 0.0
        return min(1.0, math.log10(self.residual) / math.log10(self.tolerance))


ProgressCallback = Callable[[SolverProgress], None]


@dataclass(frozen=True)
class SolverWarning:
    """A finding the user must see.

    Attributes
    ----------
    code : str
        Machine-readable code (``not_converged``, ``wrinkles``, ``large_strain`` ...).
    message : str
        Human-readable text with units.
    severity : {"info", "warning", "error"}
        ``error`` findings mean the result must not be used as final.
    """

    code: str
    message: str
    severity: Severity = "warning"


@dataclass(frozen=True)
class Convergence:
    """Convergence metadata of one solve.

    Attributes
    ----------
    status : str
        ``converged``, ``max_iterations``, ``time_limit``, ``cancelled`` or ``diverged``.
    iterations : int
        Iterations performed.
    residual : float
        Final relative residual :math:`\\|PR\\|/\\|F_{ext}\\|`, dimensionless.
    tolerance : float
        Target, dimensionless.
    resets : int
        Kinetic-energy resets.
    run_time : float
        Wall time, s.
    history : list of (int, float)
        (iteration, relative residual) samples every ``progress_interval``.
    """

    status: SolveStatus
    iterations: int
    residual: float
    tolerance: float
    resets: int
    run_time: float
    history: list[tuple[int, float]]

    @property
    def converged(self) -> bool:
        """True only for status ``converged``."""
        return self.status == "converged"


@dataclass
class LoadBreakdown:
    """Resultant of each force category at the final positions, N (vectors, shape (3,))."""

    pressure: FloatArray
    closures: dict[str, FloatArray]
    fabric_weight: FloatArray
    tape_weight: FloatArray
    point_loads: dict[str, FloatArray]
    line_loads: dict[str, FloatArray]
    distributed_loads: dict[str, FloatArray]
    reactions: dict[str, FloatArray]
    unbalanced: FloatArray

    def external_total(self) -> FloatArray:
        """Sum of all applied (non-reaction) forces, N."""
        total = self.pressure + self.fabric_weight + self.tape_weight
        for group in (self.closures, self.point_loads, self.line_loads, self.distributed_loads):
            for value in group.values():
                total = total + value
        return total


@dataclass
class SolveResult:
    """Everything a solve returns (all SI; see :data:`UNITS`).

    Attributes
    ----------
    positions : ndarray, shape (n, 3)
        Equilibrium node positions, m.
    initial_positions : ndarray, shape (n, 3)
        The model's initial positions with prescribed positions applied, m (the
        reference for displacements, also after a warm start).
    reactions : ndarray, shape (n, 3)
        Support reactions, N (zero at free nodes).
    stress : ndarray, shape (m, 3, 3)
        Cauchy stress resultant tensor per triangle in global axes, N/m.
    principal : ndarray, shape (m, 2)
        Major and minor principal Cauchy resultants :math:`N_1 \\ge N_2`, N/m.
    principal_direction : ndarray, shape (m, 3)
        Unit direction of :math:`N_1` in the deformed triangle.
    fabric_resultants : ndarray, shape (m, 3)
        Cauchy resultants along the deformed warp, weft and shear (N/m).
    strain : ndarray, shape (m, 2)
        Principal Green-Lagrange strains, dimensionless.
    state : ndarray of int8, shape (m,)
        0 taut, 1 wrinkled, 2 slack (see :mod:`envelopelab.solvers.membrane`).
    trial_minor : ndarray, shape (m,)
        Minor principal trial PK2 stress before release, N/m (negative = compression
        released, i.e. probable wrinkles).
    tape_tensions : dict of str to ndarray
        Tension per cable element, N.
    tape_strain : dict of str to ndarray
        Engineering strain per cable element, dimensionless.
    node_pressure : ndarray, shape (n,)
        Differential pressure at each node, Pa.
    volume : float
        Enclosed gas volume of the modelled portion (openings closed by flat caps), m^3.
    lift : float
        Gross lift :math:`V (\\rho_{amb} - \\rho_{int}) g` of the modelled portion, N.
    loads : LoadBreakdown
        Resultants by category, N.
    convergence : Convergence
        Status, iterations, residual, run time.
    warnings : list of SolverWarning
        Findings (errors must never be hidden).
    metadata : dict
        Reproducibility data (git commit, dependency versions, content hash, material
        sources, load case, settings, mesh size, seed).
    """

    positions: FloatArray
    initial_positions: FloatArray
    reactions: FloatArray
    stress: FloatArray
    principal: FloatArray
    principal_direction: FloatArray
    fabric_resultants: FloatArray
    strain: FloatArray
    state: npt.NDArray[np.int8]
    trial_minor: FloatArray
    tape_tensions: dict[str, FloatArray]
    tape_strain: dict[str, FloatArray]
    node_pressure: FloatArray
    volume: float
    lift: float
    loads: LoadBreakdown
    convergence: Convergence
    warnings: list[SolverWarning] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def converged(self) -> bool:
        """True only when the residual reached the tolerance."""
        return self.convergence.converged

    @property
    def displacements(self) -> FloatArray:
        """Displacement from the initial positions, m, shape (n, 3)."""
        return self.positions - self.initial_positions

    @property
    def errors(self) -> list[SolverWarning]:
        """Error-level warnings (non-empty means the result is not final)."""
        return [w for w in self.warnings if w.severity == "error"]


# --------------------------------------------------------------------------------------
# Force assembly
# --------------------------------------------------------------------------------------


def _directed_boundary_edges(triangles: IntArray) -> IntArray:
    """Directed edges (a -> b, as in a counter-clockwise triangle) used by one triangle."""
    directed = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    undirected = np.sort(directed, axis=1)
    _, inverse, counts = np.unique(undirected, axis=0, return_inverse=True, return_counts=True)
    out: IntArray = directed[counts[inverse.ravel()] == 1]
    return out


def _edge_loops(edges: IntArray) -> list[IntArray]:
    """Group boundary edges into connected components (one per opening)."""
    if not len(edges):
        return []
    nodes, inverse = np.unique(edges, return_inverse=True)
    inverse = inverse.reshape(-1, 2)
    parent = np.arange(len(nodes))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i

    for a, b in inverse:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(int(a)) for a in inverse[:, 0]])
    return [edges[roots == r] for r in np.unique(roots)]


def _cap(x: FloatArray, edges: IntArray) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Fan cap over a boundary loop: centre, area normals (k, 3) and centroids (k, 3)."""
    nodes = np.unique(edges)
    centre = x[nodes].mean(axis=0)
    a = x[edges[:, 1]] - centre
    b = x[edges[:, 0]] - centre
    normals = 0.5 * np.cross(a, b)
    centroids = (centre + x[edges[:, 0]] + x[edges[:, 1]]) / 3.0
    return centre, normals, centroids


def _plane_basis(normal: FloatArray) -> FloatArray:
    return normal / np.linalg.norm(normal)


class _System:
    """Precomputed arrays and force evaluation for one model."""

    def __init__(self, model: SolverModel, settings: SolverSettings) -> None:
        self.model = model
        self.settings = settings
        self.n = model.n_nodes
        self.tri = model.triangles
        self.rest = rest_geometry(model.rest_uv, model.grain)
        mats = [model.materials[z] for z in model.zone_names]
        c_zone = np.array([m.plane_stress_matrix() for m in mats]).reshape(-1, 3, 3)
        self.c = c_zone[model.tri_zone]
        self.c_inv = np.linalg.inv(c_zone)[model.tri_zone]
        g = model.conditions.gravity
        down = np.array([0.0, 0.0, -1.0])
        areal = np.array([m.areal_mass.value for m in mats])[model.tri_zone]
        self.weight_tri = (areal * self.rest.area * g)[:, None] * down  # N per triangle

        # Cables
        x0 = model.positions
        self.cable_edges = (
            np.concatenate([c.edges for c in model.cables])
            if model.cables
            else np.zeros((0, 2), np.int64)
        )
        self.cable_slices: dict[str, slice] = {}
        l0, ea, lin = [], [], []
        start = 0
        for cable in model.cables:
            k = len(cable.edges)
            self.cable_slices[cable.name] = slice(start, start + k)
            start += k
            rest_len = (
                cable.rest_lengths
                if cable.rest_lengths is not None
                else np.linalg.norm(x0[cable.edges[:, 1]] - x0[cable.edges[:, 0]], axis=1)
            )
            if np.any(rest_len <= 0.0):
                raise ValueError(f"cable {cable.name}: zero rest length")
            l0.append(rest_len)
            ea.append(np.full(k, cable.material.axial_stiffness.value))
            lin.append(np.full(k, cable.material.linear_mass.value))
        self.cable_l0 = np.concatenate(l0) if l0 else np.zeros(0)
        self.cable_ea = np.concatenate(ea) if ea else np.zeros(0)
        cable_mass = np.concatenate(lin) * self.cable_l0 if lin else np.zeros(0)
        self.weight_cable = (cable_mass * g)[:, None] * down

        # Dead loads (fixed vectors)
        self.self_weight = model.conditions.self_weight
        self.point = {p.name: self._scatter(p.nodes, p.force) for p in model.point_loads}
        self.line = {}
        for load in model.line_loads:
            lengths = np.linalg.norm(x0[load.edges[:, 1]] - x0[load.edges[:, 0]], axis=1)
            per_node = 0.5 * lengths[:, None] * load.force_per_length
            self.line[load.name] = self._scatter(load.edges.ravel(), np.repeat(per_node, 2, axis=0))
        self.distributed = {}
        for dist in model.distributed_loads:
            share = (self.rest.area[dist.triangles] / 3.0)[:, None] * dist.traction
            self.distributed[dist.name] = self._scatter(
                self.tri[dist.triangles].ravel(), np.repeat(share, 3, axis=0)
            )
        dead = np.zeros((self.n, 3))
        for group in (self.point, self.line, self.distributed):
            for vec in group.values():
                dead += vec
        self.dead = dead

        # Constraints: per-node projector onto free directions and prescribed positions.
        proj = np.broadcast_to(np.eye(3), (self.n, 3, 3)).copy()
        prescribed = x0.copy()
        self.constraint_nodes: dict[str, IntArray] = {}
        for con in model.constraints:
            if con.positions is not None:
                prescribed[con.nodes] = con.positions
            for axis, on in enumerate(con.dofs):
                if on:
                    d = np.zeros(3)
                    d[axis] = 1.0
                    self._remove_direction(proj, con.nodes, d)
            self.constraint_nodes[con.name] = con.nodes
        self.planes: list[tuple[str, IntArray, FloatArray, FloatArray]] = []
        for plane in model.symmetry:
            normal = _plane_basis(np.asarray(plane.normal, dtype=np.float64))
            point = np.asarray(plane.point, dtype=np.float64)
            offset = (prescribed[plane.nodes] - point) @ normal
            prescribed[plane.nodes] -= offset[:, None] * normal
            self._remove_direction(proj, plane.nodes, normal)
            self.planes.append((plane.name, plane.nodes, normal, point))
        self.x_start = prescribed
        self.constrained = np.flatnonzero(np.abs(proj - np.eye(3)).sum(axis=(1, 2)) > 1e-12)
        self.proj = proj[self.constrained]

        # Boundary loops: closures carry cap pressure; all loops close the volume except
        # those lying on symmetry planes (the planes close the modelled portion).
        boundary = _directed_boundary_edges(self.tri)
        on_plane = np.zeros(len(boundary), dtype=bool)
        for _, nodes, _, _ in self.planes:
            member = np.isin(boundary, nodes)
            on_plane |= member[:, 0] & member[:, 1]
        self.volume_loops = _edge_loops(boundary[~on_plane])
        self.closures: list[tuple[str, IntArray]] = []
        for closure in model.closures:
            member = np.isin(boundary, closure.nodes)
            edges = boundary[member[:, 0] & member[:, 1]]
            if not len(edges):
                raise ValueError(f"closure {closure.name}: nodes are not on a boundary loop")
            self.closures.append((closure.name, edges))
        self.volume_origin = self._volume_origin()

    @staticmethod
    def _remove_direction(proj: FloatArray, nodes: IntArray, d: FloatArray) -> None:
        for i in nodes:
            pd = proj[i] @ d
            norm2 = float(pd @ pd)
            if norm2 > 1e-24:
                proj[i] -= np.outer(pd, pd) / norm2

    def _volume_origin(self) -> FloatArray:
        if not self.planes:
            return np.zeros(3)
        normals = np.array([p[2] for p in self.planes])
        offsets = np.array([p[2] @ p[3] for p in self.planes])
        origin, *_ = np.linalg.lstsq(normals, offsets, rcond=None)
        return np.asarray(origin, dtype=np.float64)

    def _scatter(self, nodes: IntArray, values: FloatArray) -> FloatArray:
        out = np.zeros((self.n, 3))
        for k in range(3):
            out[:, k] = np.bincount(nodes, weights=values[:, k], minlength=self.n)
        return out

    def project(self, vec: FloatArray) -> FloatArray:
        """Remove constrained components (in place on a copy)."""
        out = vec.copy()
        if len(self.constrained):
            out[self.constrained] = np.einsum("nij,nj->ni", self.proj, vec[self.constrained])
        return out

    # ---------------------------------------------------------------------------------

    def membrane(
        self, x: FloatArray
    ) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, npt.NDArray[np.int8], FloatArray]:
        xe = x[self.tri]
        f = deformation_gradient(xe, self.rest.grad_n)
        strain = green_strain(f)
        stress, state, trial_minor = tension_field(
            strain,
            self.c,
            self.c_inv,
            self.settings.slack_stiffness_ratio,
            self.settings.tension_field,
        )
        return xe, f, strain, stress, state, trial_minor

    def cables(self, x: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
        e = self.cable_edges
        d = x[e[:, 1]] - x[e[:, 0]]
        length = np.linalg.norm(d, axis=1)
        strain = length / self.cable_l0 - 1.0
        tension = self.cable_ea * np.maximum(strain, 0.0)
        unit = d / np.maximum(length, 1e-300)[:, None]
        return tension, strain, unit, length

    def pressure_corners(self, xe: FloatArray) -> tuple[FloatArray, FloatArray]:
        cond = self.model.conditions
        p = cond.pressure(xe[:, :, 2])
        normal = 0.5 * np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0])
        weights = (p + p.sum(axis=1, keepdims=True)) / 12.0  # (2 p_a + p_b + p_c) / 12
        return weights[:, :, None] * normal[:, None, :], p

    def closure_forces(self, x: FloatArray) -> dict[str, FloatArray]:
        cond = self.model.conditions
        out: dict[str, FloatArray] = {}
        for name, edges in self.closures:
            _, normals, centroids = _cap(x, edges)
            total = (cond.pressure(centroids[:, 2])[:, None] * normals).sum(axis=0)
            lengths = np.linalg.norm(x[edges[:, 1]] - x[edges[:, 0]], axis=1)
            trib = np.bincount(edges.ravel(), np.repeat(0.5 * lengths, 2), minlength=self.n)
            vec = np.zeros((self.n, 3))
            nodes = np.flatnonzero(trib)
            vec[nodes] = (trib[nodes] / trib.sum())[:, None] * total
            out[name] = vec
        return out

    def forces(self, x: FloatArray) -> tuple[FloatArray, FloatArray, dict[str, Any]]:
        """Residual R = F_ext - F_int, external force vector, and intermediate data."""
        xe, f, strain, stress, state, trial_minor = self.membrane(x)
        f_int = internal_forces(f, stress, self.rest)
        f_p, p_corner = self.pressure_corners(xe)
        corner = f_p - f_int
        ext_corner = f_p
        if self.self_weight:
            corner = corner + self.weight_tri[:, None, :] / 3.0
            ext_corner = ext_corner + self.weight_tri[:, None, :] / 3.0
        r = self._scatter(self.tri.ravel(), corner.reshape(-1, 3))
        ext = self._scatter(self.tri.ravel(), ext_corner.reshape(-1, 3))
        if len(self.cable_edges):
            tension, _, unit, _ = self.cables(x)
            pull = tension[:, None] * unit
            cable_f = np.concatenate([pull, -pull])
            if self.self_weight:
                w = 0.5 * self.weight_cable
                cable_f = cable_f + np.concatenate([w, w])
                ext += self._scatter(self.cable_edges.T.ravel(), np.concatenate([w, w]))
            r += self._scatter(self.cable_edges.T.ravel(), cable_f)
        closures = self.closure_forces(x)
        for vec in closures.values():
            r += vec
            ext += vec
        r += self.dead
        ext += self.dead
        data = {
            "xe": xe,
            "f": f,
            "strain": strain,
            "stress": stress,
            "state": state,
            "trial_minor": trial_minor,
            "closures": closures,
            "pressure_corners": f_p,
            "p_corner": p_corner,
        }
        return r, ext, data

    def masses(self, x: FloatArray, data: dict[str, Any]) -> FloatArray:
        """Gershgorin fictitious masses (Delta t = 1) at the current state."""
        # The full (taut) stiffness is used even for released triangles: a slack triangle
        # can become taut within one step, and masses sized for its slack tangent then
        # violate the stability limit (observed on stress-free starts).
        rows = element_stiffness_rowsum(
            data["f"], data["stress"], self.c, self.rest.grad_n, self.rest.area
        )
        xe = data["xe"]
        perimeter = sum(np.linalg.norm(xe[:, (k + 1) % 3] - xe[:, k], axis=1) for k in range(3))
        p_max = np.abs(data["p_corner"]).max(axis=1)
        rows = rows + (p_max * perimeter / 6.0)[:, None]
        k = np.bincount(self.tri.ravel(), rows.ravel(), minlength=self.n).astype(np.float64)
        if len(self.cable_edges):
            tension, _, _, length = self.cables(x)
            kc = 2.0 * math.sqrt(3.0) * (self.cable_ea / self.cable_l0 + tension / length)
            k += np.bincount(self.cable_edges.ravel(), np.repeat(kc, 2), minlength=self.n)
        floor = 1e-9 * float(k.max()) if k.size and k.max() > 0 else 1.0
        return self.settings.mass_factor * 0.5 * np.maximum(k, floor)

    def volume(self, x: FloatArray) -> float:
        xo = x - self.volume_origin
        e = xo[self.tri]
        vol = float(np.einsum("mi,mi->m", e[:, 0], np.cross(e[:, 1], e[:, 2])).sum()) / 6.0
        for edges in self.volume_loops:
            centre = xo[np.unique(edges)].mean(axis=0)
            a = xo[edges[:, 1]]
            b = xo[edges[:, 0]]
            vol += float(np.einsum("i,mi->m", centre, np.cross(a, b)).sum()) / 6.0
        return vol


# --------------------------------------------------------------------------------------
# Solve
# --------------------------------------------------------------------------------------


def _relative(r_free: FloatArray, ext: FloatArray) -> float:
    scale = float(np.linalg.norm(ext))
    norm = float(np.linalg.norm(r_free))
    return norm / scale if scale > 0.0 else norm


def solve(
    model: SolverModel,
    settings: SolverSettings | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancellationToken | None = None,
    initial_positions: FloatArray | None = None,
) -> SolveResult:
    """Find the inflated equilibrium of an as-sewn envelope by dynamic relaxation.

    Parameters
    ----------
    model : SolverModel
        Mesh (m), materials (N/m), tapes (N), boundary conditions, loads (N, N/m, Pa)
        and operating conditions.
    settings : SolverSettings, optional
        Tolerance, iteration limit, damping and tension-field options.
    progress : callable, optional
        Called with a :class:`SolverProgress` every ``settings.progress_interval``
        iterations (from the solving thread).
    cancel : CancellationToken, optional
        Checked at the same interval; a cancelled solve returns status ``cancelled``.
    initial_positions : ndarray, shape (n, 3), optional
        Warm start (e.g. the previous preview solve), m. Default ``model.positions``.

    Returns
    -------
    SolveResult
        Positions (m), reactions (N), stress resultants (N/m), tape tensions (N),
        volume (m^3), lift (N), load breakdown, convergence metadata and warnings.
        Unconverged results carry an error-level ``not_converged`` warning.

    Notes
    -----
    Assumptions and limits are listed in ``docs/theory/dynamic-relaxation.md``. The
    solve is deterministic (no random numbers); the seed recorded in the metadata is
    ``None``.
    """
    settings = settings or SolverSettings()
    t_start = time.perf_counter()
    system = _System(model, settings)
    x = system.x_start.copy()
    if initial_positions is not None:
        warm = np.asarray(initial_positions, dtype=np.float64).reshape(-1, 3).copy()
        if warm.shape != x.shape:
            raise ValueError("initial_positions must have one row per node")
        if len(system.constrained):
            warm[system.constrained] = x[system.constrained]
        x = warm
    # Displacements are reported from the model's initial (as-sewn guess) positions, also
    # after a warm start, so maps from successive previews stay comparable.
    x_initial = system.x_start.copy()
    r, ext, data = system.forces(x)
    r_free = system.project(r)
    mass = system.masses(x, data)
    v = np.zeros_like(x)
    v_prev = np.zeros_like(x)
    ke_prev = 0.0
    fresh = True
    resets = 0
    residual = _relative(r_free, ext)
    history: list[tuple[int, float]] = [(0, residual)]
    status: SolveStatus = "max_iterations"
    iteration = 0
    kinetic = settings.damping == "kinetic"
    c = settings.viscous_damping
    ke = 0.0
    if residual < settings.tolerance:
        status = "converged"
    else:
        for iteration in range(1, settings.max_iterations + 1):
            accel = r_free / mass[:, None]
            if kinetic:
                v = 0.5 * accel if fresh else v + accel
            else:
                v = ((1.0 - 0.5 * c) * v + accel) / (1.0 + 0.5 * c)
            fresh = False
            ke = 0.5 * float((mass[:, None] * v * v).sum())
            if kinetic and ke < ke_prev:
                x = x - 0.5 * v_prev
                v[:] = 0.0
                v_prev[:] = 0.0
                ke_prev = 0.0
                fresh = True
                resets += 1
                r, ext, data = system.forces(x)
                mass = system.masses(x, data)
            else:
                x = x + v
                v_prev = v
                ke_prev = ke
                r, ext, data = system.forces(x)
            r_free = system.project(r)
            residual = _relative(r_free, ext)
            if not math.isfinite(residual) or residual > 1e8:
                status = "diverged"
                break
            if residual < settings.tolerance:
                status = "converged"
                break
            if iteration % settings.progress_interval == 0:
                elapsed = time.perf_counter() - t_start
                history.append((iteration, residual))
                if progress is not None:
                    progress(
                        SolverProgress(
                            iteration,
                            settings.max_iterations,
                            residual,
                            ke,
                            elapsed,
                            settings.tolerance,
                        )
                    )
                if cancel is not None and cancel.cancelled:
                    status = "cancelled"
                    break
                if settings.time_limit is not None and elapsed > settings.time_limit:
                    status = "time_limit"
                    break
    run_time = time.perf_counter() - t_start
    history.append((iteration, residual))
    if progress is not None:
        progress(
            SolverProgress(
                iteration, settings.max_iterations, residual, ke, run_time, settings.tolerance
            )
        )
    convergence = Convergence(
        status, iteration, residual, settings.tolerance, resets, run_time, history
    )
    return _finish(system, x, x_initial, r, data, convergence)


def _principal_2d(
    sigma: FloatArray, e1: FloatArray, e2: FloatArray
) -> tuple[FloatArray, FloatArray]:
    s11 = np.einsum("mi,mij,mj->m", e1, sigma, e1)
    s22 = np.einsum("mi,mij,mj->m", e2, sigma, e2)
    s12 = np.einsum("mi,mij,mj->m", e1, sigma, e2)
    mean = 0.5 * (s11 + s22)
    rad = np.sqrt((0.5 * (s11 - s22)) ** 2 + s12**2)
    angle = 0.5 * np.arctan2(2.0 * s12, s11 - s22)
    direction = np.cos(angle)[:, None] * e1 + np.sin(angle)[:, None] * e2
    return np.column_stack([mean + rad, mean - rad]), direction


def _unit(v: FloatArray) -> FloatArray:
    out: FloatArray = v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-300)
    return out


def _finish(
    system: _System,
    x: FloatArray,
    x_initial: FloatArray,
    r: FloatArray,
    data: dict[str, Any],
    convergence: Convergence,
) -> SolveResult:
    from envelopelab.assembly.rest_model import dependency_versions, git_commit

    model = system.model
    settings = system.settings
    f = data["f"]
    sigma = cauchy_resultants(f, data["stress"])
    xe = data["xe"]
    normal = _unit(np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0]))
    warp = _unit(f[:, :, 0])
    weft_perp = np.cross(normal, warp)
    principal, direction = _principal_2d(sigma, warp, weft_perp)
    weft = _unit(f[:, :, 1])
    fabric = np.column_stack(
        [
            np.einsum("mi,mij,mj->m", warp, sigma, warp),
            np.einsum("mi,mij,mj->m", weft, sigma, weft),
            np.einsum("mi,mij,mj->m", warp, sigma, weft_perp),
        ]
    )
    strain = data["strain"]
    tr = 0.5 * (strain[:, 0, 0] + strain[:, 1, 1])
    rad = np.sqrt((0.5 * (strain[:, 0, 0] - strain[:, 1, 1])) ** 2 + strain[:, 0, 1] ** 2)
    principal_strain = np.column_stack([tr + rad, tr - rad])

    # Reactions: the residual components removed by the constraints.
    reactions = np.zeros_like(x)
    if len(system.constrained):
        c = system.constrained
        free = np.einsum("nij,nj->ni", system.proj, r[c])
        reactions[c] = -(r[c] - free)
    remaining = reactions.copy()
    groups: dict[str, FloatArray] = {}
    for name, nodes in system.constraint_nodes.items():
        groups[name] = remaining[nodes].sum(axis=0)
        remaining[nodes] = 0.0
    for name, nodes, normal_p, _ in system.planes:
        along = remaining[nodes] @ normal_p
        groups[name] = groups.get(name, np.zeros(3)) + (along[:, None] * normal_p).sum(axis=0)
        remaining[nodes] -= along[:, None] * normal_p
    unbalanced = system.project(r).sum(axis=0)

    tensions: dict[str, FloatArray] = {}
    tape_strain: dict[str, FloatArray] = {}
    if len(system.cable_edges):
        tension, c_strain, _, _ = system.cables(x)
        for name, sl in system.cable_slices.items():
            tensions[name] = tension[sl]
            tape_strain[name] = c_strain[sl]
    weight_on = system.self_weight
    loads = LoadBreakdown(
        pressure=data["pressure_corners"].sum(axis=(0, 1)),
        closures={k: v.sum(axis=0) for k, v in data["closures"].items()},
        fabric_weight=system.weight_tri.sum(axis=0) if weight_on else np.zeros(3),
        tape_weight=system.weight_cable.sum(axis=0) if weight_on else np.zeros(3),
        point_loads={k: v.sum(axis=0) for k, v in system.point.items()},
        line_loads={k: v.sum(axis=0) for k, v in system.line.items()},
        distributed_loads={k: v.sum(axis=0) for k, v in system.distributed.items()},
        reactions=groups,
        unbalanced=unbalanced,
    )
    volume = system.volume(x)
    cond = model.conditions
    lift = volume * cond.pressure_gradient
    node_pressure = cond.pressure(x[:, 2])
    result = SolveResult(
        positions=x,
        initial_positions=x_initial,
        reactions=reactions,
        stress=sigma,
        principal=principal,
        principal_direction=direction,
        fabric_resultants=fabric,
        strain=principal_strain,
        state=data["state"],
        trial_minor=data["trial_minor"],
        tape_tensions=tensions,
        tape_strain=tape_strain,
        node_pressure=node_pressure,
        volume=volume,
        lift=lift,
        loads=loads,
        convergence=convergence,
    )
    result.warnings = _warnings(system, result)
    result.metadata = {
        "solver": "envelopelab.solvers.dynamic_relaxation",
        "model": model.name,
        "status": "converged equilibrium (preview solver)"
        if convergence.converged
        else "NOT CONVERGED - not a valid result",
        "convergence": {
            "status": convergence.status,
            "converged": convergence.converged,
            "iterations": convergence.iterations,
            "relative_residual": convergence.residual,
            "tolerance": convergence.tolerance,
            "kinetic_energy_resets": convergence.resets,
            "run_time_s": convergence.run_time,
        },
        "mesh": {
            "nodes": model.n_nodes,
            "triangles": model.n_triangles,
            "cable_elements": len(system.cable_edges),
        },
        "load_case": cond.as_dict(),
        "settings": settings.as_dict(),
        "materials": {z: model.materials[z].sources() for z in model.zone_names},
        "tapes": {c.name: c.material.sources() for c in model.cables},
        "units": dict(UNITS),
        "git_commit": git_commit(),
        "dependencies": dependency_versions(),
        "model_content_hash": model.content_hash(),
        "design_content_hash": model.source_hash,
        "random_seed": None,
    }
    return result


def _warnings(system: _System, result: SolveResult) -> list[SolverWarning]:
    model = system.model
    settings = system.settings
    conv = result.convergence
    out: list[SolverWarning] = []
    if not conv.converged:
        out.append(
            SolverWarning(
                "not_converged",
                f"solve stopped ({conv.status}) after {conv.iterations} iterations with "
                f"relative residual {conv.residual:.2e} > tolerance {conv.tolerance:.1e}; "
                "the shape, stresses and forces are NOT an equilibrium",
                "error",
            )
        )
    if not model.constraints and not model.symmetry:
        out.append(
            SolverWarning(
                "unconstrained",
                "no constraints or symmetry planes: rigid-body motion is not suppressed",
                "error",
            )
        )
    n_tri = max(model.n_triangles, 1)
    wrinkled = int(np.sum(result.state == WRINKLED))
    slack = int(np.sum(result.state == SLACK))
    if wrinkled or slack:
        area = system.rest.area
        frac = float(area[result.state != TAUT].sum() / max(area.sum(), 1e-300))
        out.append(
            SolverWarning(
                "wrinkles",
                f"{wrinkled} wrinkled and {slack} slack triangles of {n_tri} "
                f"({frac * 100:.1f} % of the fabric area): probable wrinkle zones",
                "info",
            )
        )
    n1 = result.principal[:, 0]
    scale = float(np.max(np.abs(n1))) if n1.size else 0.0
    compression = float(np.max(np.maximum(-result.principal[:, 1], 0.0))) if n1.size else 0.0
    if settings.tension_field and scale > 0.0:
        ratio = compression / scale
        if ratio > settings.wrinkle_tolerance:
            out.append(
                SolverWarning(
                    "compression_residual",
                    f"largest residual compression {compression:.3g} N/m is "
                    f"{ratio * 100:.2f} % of the largest tension (limit "
                    f"{settings.wrinkle_tolerance * 100:.1f} %)",
                    "warning",
                )
            )
    max_strain = float(np.max(result.strain[:, 0])) if n1.size else 0.0
    if max_strain > _LARGE_STRAIN:
        out.append(
            SolverWarning(
                "large_strain",
                f"maximum fabric strain {max_strain * 100:.1f} % exceeds "
                f"{_LARGE_STRAIN * 100:.0f} %, outside the small-strain material model",
                "warning",
            )
        )
    for name, strain in result.tape_strain.items():
        slack_edges = int(np.sum(strain <= 0.0))
        if slack_edges:
            out.append(
                SolverWarning(
                    "tape_slack",
                    f"tape {name}: {slack_edges} of {len(strain)} elements carry no tension",
                    "info",
                )
            )
    t_int = model.conditions.internal_temperature
    if t_int is not None:
        for zone in model.zone_names:
            limit = model.materials[zone].max_service_temperature
            if t_int > limit.value:
                out.append(
                    SolverWarning(
                        "temperature_exceedance",
                        f"zone {zone}: internal temperature {t_int:.1f} K exceeds the "
                        f"fabric limit {limit.value:.1f} K ({limit.source})",
                        "error",
                    )
                )
    return out


# --------------------------------------------------------------------------------------
# Background solves for the GUI
# --------------------------------------------------------------------------------------


class SolverJob:
    """Run :func:`solve` on a worker thread so a GUI event loop never blocks.

    The GUI polls :meth:`done` (or waits on :meth:`result`) and calls :meth:`cancel` to
    stop; progress callbacks run on the worker thread, so a Qt GUI should forward them
    with a queued signal.

    Parameters
    ----------
    model : SolverModel
        Model to solve.
    settings : SolverSettings, optional
        Settings.
    progress : callable, optional
        Progress callback.
    initial_positions : ndarray, optional
        Warm start, m.
    """

    def __init__(
        self,
        model: SolverModel,
        settings: SolverSettings | None = None,
        progress: ProgressCallback | None = None,
        initial_positions: FloatArray | None = None,
    ) -> None:
        self.token = CancellationToken()
        self._result: SolveResult | None = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            args=(model, settings, progress, initial_positions),
            name="envelopelab-preview-solve",
            daemon=True,
        )

    def _run(
        self,
        model: SolverModel,
        settings: SolverSettings | None,
        progress: ProgressCallback | None,
        initial_positions: FloatArray | None,
    ) -> None:
        try:
            self._result = solve(model, settings, progress, self.token, initial_positions)
        except BaseException as exc:  # re-raised in result(); the thread must not die silently
            self._error = exc

    def start(self) -> SolverJob:
        """Start the worker thread and return self."""
        self._thread.start()
        return self

    def cancel(self) -> None:
        """Request cancellation; the result then has status ``cancelled``."""
        self.token.cancel()

    def done(self) -> bool:
        """True when the worker has finished."""
        return self._thread.ident is not None and not self._thread.is_alive()

    def result(self, timeout: float | None = None) -> SolveResult:
        """Wait for the result.

        Parameters
        ----------
        timeout : float, optional
            Seconds to wait.

        Returns
        -------
        SolveResult
            The solve result.

        Raises
        ------
        TimeoutError
            If the solve is still running after ``timeout``.
        """
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError("preview solve still running")
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result
