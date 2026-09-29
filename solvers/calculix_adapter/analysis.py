r"""Staged CalculiX verification solve of an EnvelopeLab :class:`SolverModel`.

Model
-----
CalculiX M3D3 membrane elements carry the fabric (one orientation per element, local axis 1
= warp; anisotropic material ``*ELASTIC,TYPE=ANISO``); the flat rest triangles enter
through an initial stress (the reference geometry is not the rest geometry); tapes are
tension-only SPRINGA elements; all loads (hydrostatic pressure, closure caps, fabric and
tape weight, point, line and area loads) are nodal forces evaluated with the same
definitions as the preview solver
(:class:`~envelopelab.solvers.dynamic_relaxation.ModelEvaluator`).

Stages
------
Every *pass* solves the equilibrium of one frozen state: reference geometry, element
materials and nodal loads. A pass consists of two CalculiX jobs.

* **Held job.** Every node is held at the reference; the printed nodal forces (``RF``) are
  the fabric's internal forces for the initial stress. ``RF`` leaves out spring elements,
  so the adapter adds the tape forces (same force-elongation law as the deck) to obtain
  :math:`f_{int}`, and the out-of-balance force is :math:`B = f_{int} - f_{ext}`.
* **Release job.** A first static NLGEOM step applies :math:`f_{ext} + B` (a balanced start)
  and ``ramp_steps`` further steps release :math:`B` to zero (continuation: CalculiX ramps
  linearly between steps). Soft springs (SPRING1) tie every node to its reference position
  so that the Newton system stays positive definite on the near-mechanisms of released
  fabric.

1. **Prestress establishment and inflation (pass 1).** Reference = the start geometry (the
   model's initial shape, or ``start_positions``); initial stress = the as-sewn misfit
   :math:`\sigma_0 = J^{-1} F (D:E) F^T` between the flat rest triangles and that shape;
   loads = full hydrostatic inflation.
2. **Nonlinear static equilibrium passes.** Reference = the previous equilibrium; initial
   stress = the exact rest-to-reference stress of the pass material; loads re-evaluated at
   the reference (follower pressure, cap loads). With the tension field on, each element's
   material follows the *iterative membrane properties* model [Liu]_ with the wrinkle
   direction :math:`n` frozen for the pass (taut: :math:`\mathbb{C}`; wrinkled:
   :math:`(1-\kappa) E_n v v^T + \kappa\mathbb{C}`, :math:`v = (n_1^2, n_2^2, n_1 n_2)`;
   slack: :math:`\kappa\mathbb{C}`), which is the preview solver's tension-field law at a
   fixed point; states use the preview's criterion on the rest-to-current strain, and
   :math:`\kappa` may be lowered pass by pass from ``kappa_start`` to its final value.
3. **Continuation.** A release job that does not complete is retried with twice the ramp
   steps, then with four times the stabilisation, then with half the first increment.

Convergence
-----------
Because the springs are re-anchored every pass, their force at the end of a pass is the
out-of-balance force of the real (unstabilised) problem at the new positions for
CalculiX's stresses; force normal to a symmetry plane at its nodes is that plane's
reaction and is not counted. A pass *settles* when this out-of-balance, relative to the
external load, is below ``residual_target``, no node moved more than
``position_tolerance``, at most ``state_tolerance`` of the elements changed tension-field
state, CalculiX's stresses match the exact rest-to-current stresses within
``stress_tolerance`` and :math:`\kappa` has reached its final value. The result is
``converged`` only when the held job of the following pass, which evaluates CalculiX's
internal force for the *exact* material law at the settled geometry, is also below
``residual_target`` and the global force balance closes within ``balance_tolerance``.
The springs start at ``stabilization_ratio`` times the fabric stiffness, decay by
``stabilization_decay`` after every pass and grow by ``stabilization_growth`` when a pass
made the out-of-balance worse.

References
----------
.. [Liu] X. Liu, C. H. Jenkins and W. W. Schur, "Large deflection analysis of pneumatic
   envelopes using a penalty parameter modified material model", Finite Elements in
   Analysis and Design 37 (2001) 233-251.
.. [Dhondt] G. Dhondt, *The Finite Element Method for Three-Dimensional Thermomechanical
   Applications*, Wiley (2004); CalculiX CrunchiX User's Manual, version 2.21.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from calculix_adapter.deck import DeckInput, FloatArray, IntArray, LoadStep, write_deck
from calculix_adapter.detect import CalculixInstallation, require_calculix
from calculix_adapter.results import (
    read_cvg,
    read_displacements,
    read_element_stress,
    read_reactions,
    steps_completed,
)
from envelopelab.solvers.dynamic_relaxation import ModelEvaluator
from envelopelab.solvers.manifest import manifest_for
from envelopelab.solvers.membrane import (
    SLACK,
    TAUT,
    WRINKLED,
    trial_principal,
    uniaxial_stiffness,
)
from envelopelab.solvers.model import SolverModel, SolverSettings
from envelopelab.solvers.simulation import (
    Finding,
    IterationRecord,
    SimulationResult,
    mouth_nodes,
    principal_resultants,
)

JOB = "job"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalculixSettings:
    """Settings of a CalculiX verification solve.

    Attributes
    ----------
    executable : str, optional
        ``ccx`` to use (default: ``$ENVELOPELAB_CCX`` or ``PATH``).
    thickness : float
        Nominal membrane thickness used to convert resultants to stresses, m. Results do
        not depend on it.
    tension_field : bool
        Iterative membrane properties for wrinkling (False: compression-carrying fabric).
    slack_stiffness_ratio : float
        Final :math:`\\kappa`, residual stiffness of released directions, dimensionless.
    kappa_start, kappa_factor : float
        :math:`\\kappa` of the first tension-field pass and its factor per pass.
    tape_slack_ratio : float
        Compression stiffness of a slack tape as a fraction of :math:`EA/L_0` (0: tension
        only, the preview solver's law).
    max_passes : int
        Pass limit.
    position_tolerance : float
        Largest node movement of the last pass, m.
    state_tolerance : float
        Largest fraction of elements changing tension-field state in the last pass.
    stress_tolerance : float
        Largest difference between CalculiX's resultants and the exact rest-to-current
        resultants, relative to the largest resultant.
    residual_target : float
        Relative out-of-balance :math:`\\|f_{ext} - f_{int}\\| / \\|f_{ext}\\|` (free
        degrees of freedom, symmetry-plane reactions excluded) for convergence.
    ramp_steps : int
        Release steps of pass 1 (later passes use one; continuation doubles it).
    max_ramp_steps : int
        Continuation limit for the release steps.
    initial_increment, min_increment : float
        First increment as a fraction of a step, and its continuation limit.
    stabilization_ratio : float
        Spring stiffness of pass 1 as a fraction of the largest fabric stiffness
        :math:`Et` (N/m per N/m).
    stabilization_decay, stabilization_growth : float
        Spring stiffness factor after each completed pass, and extra factor at the start of
        a pass whose out-of-balance grew (the previous pass moved too far).
    min_stabilization_ratio, max_stabilization_ratio : float
        Limits of the spring stiffness (fractions of :math:`Et`).
    newton_tolerance : float
        CalculiX :math:`R_n^\\alpha`: largest residual force / average force of its Newton
        iterations.
    balance_tolerance : float
        Global force-balance limit (AGENTS.md: 0.5 %).
    threads : int
        Solver threads (1 keeps runs bit-reproducible).
    """

    executable: str | None = None
    thickness: float = 1e-3
    tension_field: bool = True
    slack_stiffness_ratio: float = 1e-3
    kappa_start: float = 0.1
    kappa_factor: float = 0.3
    tape_slack_ratio: float = 0.0
    max_passes: int = 60
    position_tolerance: float = 1e-3
    state_tolerance: float = 5e-3
    stress_tolerance: float = 2e-3
    residual_target: float = 1e-5
    ramp_steps: int = 4
    max_ramp_steps: int = 32
    initial_increment: float = 0.25
    min_increment: float = 1e-3
    stabilization_ratio: float = 1e-2
    stabilization_decay: float = 0.5
    stabilization_growth: float = 4.0
    min_stabilization_ratio: float = 1e-8
    max_stabilization_ratio: float = 1.0
    newton_tolerance: float = 1e-6
    balance_tolerance: float = 5e-3
    threads: int = 1

    def as_dict(self) -> dict[str, Any]:
        """Settings as a plain dictionary (for the run manifest)."""
        return asdict(self)


class CalculixRunError(RuntimeError):
    """Raised when CalculiX fails in a way continuation cannot fix (bad deck, crash)."""


def _unit(v: FloatArray) -> FloatArray:
    out: FloatArray = v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-300)
    return out


def _in_plane(stress: FloatArray, x: FloatArray, tri: IntArray) -> FloatArray:
    """Membrane part :math:`P \\sigma P`, :math:`P = I - n n^T`, of resultant tensors."""
    xe = x[tri]
    nrm = _unit(np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0]))
    proj = np.eye(3)[None] - nrm[:, :, None] * nrm[:, None, :]
    out: FloatArray = np.einsum("mij,mjk,mkl->mil", proj, stress, proj)
    return out


class _Problem:
    """Pass-independent data of one verification solve."""

    def __init__(self, model: SolverModel, settings: CalculixSettings) -> None:
        self.model = model
        self.settings = settings
        self.ev = ModelEvaluator(
            model,
            SolverSettings(
                tension_field=settings.tension_field,
                slack_stiffness_ratio=settings.slack_stiffness_ratio,
            ),
        )
        self.X = self.ev.start_positions
        self.tri = model.triangles
        self.n, self.m = model.n_nodes, model.n_triangles
        self.C = self.ev.stiffness
        self.Cinv = self.ev.compliance
        mats = [model.materials[z] for z in model.zone_names]
        zone = model.tri_zone
        self.ew = np.array([m_.stiffness_warp.value for m_ in mats])[zone]
        self.ef = np.array([m_.stiffness_weft.value for m_ in mats])[zone]
        self.gt = np.array([m_.shear_stiffness.value for m_ in mats])[zone]
        self.transverse = np.maximum(self.ew, self.ef)
        self.dead = sum(self.ev.dead_loads().values(), np.zeros((self.n, 3)))
        cables = model.cables
        self.tape_edges = (
            np.concatenate([c.edges for c in cables]) if cables else np.zeros((0, 2), np.int64)
        )
        rest, ea = [], []
        for c in cables:
            rest.append(
                c.rest_lengths
                if c.rest_lengths is not None
                else np.linalg.norm(self.X[c.edges[:, 1]] - self.X[c.edges[:, 0]], axis=1)
            )
            ea.append(np.full(len(c.edges), c.material.axial_stiffness.value))
        self.tape_rest = np.concatenate(rest) if rest else np.zeros(0)
        self.tape_ea = np.concatenate(ea) if ea else np.zeros(0)
        self.fixed: list[tuple[int, int]] = []
        self.fixed_mask = np.zeros((self.n, 3), dtype=bool)
        for con in model.constraints:
            for i in con.nodes:
                for dof, on in enumerate(con.dofs):
                    if on:
                        self.fixed.append((int(i), dof + 1))
                        self.fixed_mask[int(i), dof] = True
        self.equations: list[tuple[int, FloatArray]] = []
        self.plane_nodes: list[tuple[str, IntArray, FloatArray]] = []
        for plane in model.symmetry:
            normal = _unit(np.asarray(plane.normal, dtype=np.float64))
            self.plane_nodes.append((plane.name, plane.nodes, normal))
            for i in plane.nodes:
                if not self.fixed_mask[int(i)].all():
                    self.equations.append((int(i), normal))
        self.plane_mask = np.zeros(self.n, dtype=bool)
        for _, nodes, _ in self.plane_nodes:
            self.plane_mask[nodes] = True

    def classify(self, strain: FloatArray) -> tuple[np.ndarray, FloatArray]:
        """Tension-field state and wrinkle direction (fabric axes) for a rest-to-x strain.

        Elements with (numerically) zero strain are taut: a stress-free element is not a
        wrinkle.
        """
        _, s2, direction, eps_n = trial_principal(strain, self.C)
        state = np.full(self.m, TAUT, dtype=np.int8)
        if self.settings.tension_field:
            strained = np.abs(strain).max(axis=(1, 2)) > 1e-9
            released = (s2 <= 0.0) & strained
            state[released & (eps_n > 0.0)] = WRINKLED
            state[released & (eps_n <= 0.0)] = SLACK
        return state, direction

    def materials(self, state: np.ndarray, direction: FloatArray, kappa: float) -> FloatArray:
        r"""Plane stiffness (fabric axes, Voigt, N/m) of every element for a pass.

        The preview solver's tension-field law with the wrinkle direction :math:`n` frozen
        (iterative membrane properties): taut :math:`\mathbb{C}`; wrinkled
        :math:`(1 - \kappa) E_n v v^\mathsf{T} + \kappa \mathbb{C}` with
        :math:`v = (n_1^2, n_2^2, n_1 n_2)` and :math:`E_n` the uniaxial stiffness along
        :math:`n`; slack :math:`\kappa \mathbb{C}`. At a fixed point of the passes (states
        and directions unchanged) the stress is exactly the preview solver's.
        """
        d = self.C.copy()
        d[state == SLACK] *= kappa
        wr = state == WRINKLED
        if np.any(wr):
            c, sn = direction[wr, 0], direction[wr, 1]
            v = np.stack([c * c, sn * sn, c * sn], axis=1)
            e_n = uniaxial_stiffness(direction[wr], self.Cinv[wr])
            d[wr] = (1.0 - kappa) * e_n[:, None, None] * v[:, :, None] * v[:, None, :]
            d[wr] += kappa * self.C[wr]
        return d

    def exact_stress(self, x: FloatArray, material: FloatArray) -> FloatArray:
        r"""Cauchy resultant (global, N/m) of the pass material for the rest-to-``x`` strain.

        :math:`\sigma = J^{-1} F S F^\mathsf{T}` with :math:`S = D : E` in fabric axes
        (St. Venant-Kirchhoff, as the preview solver).
        """
        f0, e0 = self.ev.deformation(x)
        j0 = np.linalg.norm(np.cross(f0[:, :, 0], f0[:, :, 1]), axis=1)
        e = np.stack([e0[:, 0, 0], e0[:, 1, 1], 2.0 * e0[:, 0, 1]], axis=1)
        s = np.einsum("mij,mj->mi", material, e)
        s_fab = np.stack([np.stack([s[:, 0], s[:, 2]], 1), np.stack([s[:, 2], s[:, 1]], 1)], 1)
        out: FloatArray = np.einsum("mij,mjk,mlk->mil", f0, s_fab, f0) / j0[:, None, None]
        return out

    def axes(self, x: FloatArray) -> FloatArray:
        """Local axes (rows a, b, n) of every element at reference ``x``: a is the warp
        direction mapped to ``x`` and projected into the element plane."""
        f0, _ = self.ev.deformation(x)
        xe = x[self.tri]
        normal = _unit(np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0]))
        a = _unit(f0[:, :, 0])
        a = _unit(a - np.einsum("mi,mi->m", a, normal)[:, None] * normal)
        b = np.cross(normal, a)
        return np.stack([a, b, normal], axis=1)

    def external(self, x: FloatArray) -> FloatArray:
        """Nodal external force at ``x`` (pressure, closures, dead loads), N."""
        xe = x[self.tri]
        p = self.model.triangle_pressure(xe[:, :, 2])
        area_normal = 0.5 * np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0])
        weights = (p + p.sum(axis=1, keepdims=True)) / 12.0  # (2 p_a + p_b + p_c) / 12
        out = np.zeros((self.n, 3))
        for k in range(3):
            np.add.at(out, self.tri[:, k], weights[:, k, None] * area_normal)
        for vec in self.ev.closure_forces(x).values():
            out += vec
        out += self.dead
        return out

    def split_planes(self, force: FloatArray) -> tuple[FloatArray, dict[str, FloatArray]]:
        """Split :math:`f_{int} - f_{ext}` at the free nodes into the part normal to each
        symmetry plane at its nodes (the plane's reaction) and the rest (out-of-balance).

        Returns the out-of-balance force (N, shape (n, 3)) and, per plane, the total
        reaction on the structure (N, shape (3,)).
        """
        rest = force.copy()
        removed: dict[str, FloatArray] = {}
        for name, nodes, normal in self.plane_nodes:
            free = nodes[~self.fixed_mask[nodes].all(axis=1)]
            part = (rest[free] @ normal)[:, None] * normal
            rest[free] -= part
            removed[name] = part.sum(axis=0)
        return rest, removed

    def tape_forces(self, x: FloatArray) -> FloatArray:
        r"""Nodal internal force of the tapes at ``x`` (N), with the deck's SPRINGA law.

        CalculiX's printed nodal forces (``RF``) leave out spring elements, so the adapter
        adds the tape forces itself: :math:`T = (EA/L_0)(l - L_0)` for :math:`l \ge L_0`,
        else ``tape_slack_ratio`` times that.
        """
        e = self.tape_edges
        out = np.zeros((self.n, 3))
        if len(e) == 0:
            return out
        d = x[e[:, 1]] - x[e[:, 0]]
        length = np.linalg.norm(d, axis=1)
        k = self.tape_ea / self.tape_rest
        stretch = length - self.tape_rest
        tension = np.where(stretch >= 0.0, 1.0, self.settings.tape_slack_ratio) * k * stretch
        vec = (tension / length)[:, None] * d
        np.add.at(out, e[:, 1], vec)
        np.add.at(out, e[:, 0], -vec)
        return out

    def deck(
        self,
        x: FloatArray,
        axes: FloatArray,
        material: FloatArray,
        sig0: FloatArray,
        steps: list[LoadStep],
        hold_all: bool,
        stabilization: float,
        increment: float,
    ) -> DeckInput:
        e = self.tape_edges
        s = self.settings
        return DeckInput(
            reference=x,
            triangles=self.tri,
            axes=axes,
            material=material,
            transverse=self.transverse,
            initial_stress=sig0,
            steps=steps,
            tape_edges=e,
            tape_rest=self.tape_rest,
            tape_ref=np.linalg.norm(x[e[:, 1]] - x[e[:, 0]], axis=1),
            tape_ea=self.tape_ea,
            fixed=self.fixed,
            equations=self.equations,
            hold_all=hold_all,
            stabilization=stabilization,
            thickness=s.thickness,
            tape_slack_ratio=s.tape_slack_ratio,
            initial_increment=increment,
            residual_tolerance=s.newton_tolerance,
        )


def _run_job(inst: CalculixInstallation, deck: DeckInput, workdir: Path, threads: int) -> bool:
    write_deck(deck, workdir / f"{JOB}.inp")
    for suffix in (".dat", ".sta", ".cvg", ".frd"):
        (workdir / f"{JOB}{suffix}").unlink(missing_ok=True)
    env = dict(os.environ)
    env.update(
        OMP_NUM_THREADS=str(threads),
        CCX_NPROC_STIFFNESS=str(threads),
        CCX_NPROC_EQUATION_SOLVER=str(threads),
    )
    proc = subprocess.run(
        [str(inst.executable), "-i", JOB],
        cwd=workdir,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    log = proc.stdout + proc.stderr
    (workdir / f"{JOB}.log").write_text(log, encoding="utf-8")
    if "*ERROR reading" in log or "*ERROR in calinput" in log:
        raise CalculixRunError(f"CalculiX rejected the input deck:\n{log[-2000:]}")
    if proc.returncode < 0:
        raise CalculixRunError(f"CalculiX crashed (signal {-proc.returncode}):\n{log[-2000:]}")
    return proc.returncode == 0 and steps_completed(workdir / f"{JOB}.sta", deck.n_steps)


def run_calculix(
    model: SolverModel,
    settings: CalculixSettings | None = None,
    workdir: str | Path | None = None,
    mesh_options: dict[str, Any] | None = None,
    start_positions: FloatArray | None = None,
) -> SimulationResult:
    """Verification solve of ``model`` with CalculiX (see module docstring).

    Parameters
    ----------
    model : SolverModel
        Same model as the preview solver uses (rest triangles, grain, zones, tapes,
        constraints, loads, operating conditions).
    settings : CalculixSettings, optional
        Solver settings.
    workdir : str or Path, optional
        Directory for the CalculiX files of the last job (kept); default a temporary
        directory that is removed.
    mesh_options : dict, optional
        Mesh settings recorded in the run manifest.
    start_positions : ndarray, shape (n, 3), optional
        Reference geometry of the first pass, m (default: the model's initial shape). A
        start close to equilibrium, such as the preview solver's result, shortens the
        form-finding stage; it does not enter the equilibrium equations, and the result is
        accepted only on CalculiX's own convergence criteria. Displacements are still
        measured from the model's initial shape.

    Returns
    -------
    SimulationResult
        Positions (m), stress resultants (N/m), tape tensions (N), reactions (N), residual
        and iteration history, CalculiX version, mesh size, elapsed time and manifest.
        ``converged`` is False (with an error finding) when any criterion failed.

    Raises
    ------
    calculix_adapter.CalculixNotFoundError
        When ``ccx`` is not installed (the message explains how to install it).
    CalculixRunError
        When CalculiX rejects the input deck or crashes.
    """
    settings = settings or CalculixSettings()
    inst = require_calculix(settings.executable)
    start = time.perf_counter()
    temp = None
    if workdir is None:
        temp = tempfile.mkdtemp(prefix="envelopelab-ccx-")
        work = Path(temp)
    else:
        work = Path(workdir)
        work.mkdir(parents=True, exist_ok=True)
    try:
        return _solve(model, settings, inst, work, start, mesh_options, start_positions)
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)


@dataclass
class _PassState:
    """Mutable state of the pass loop."""

    x: FloatArray
    state: np.ndarray
    direction: FloatArray
    stress: FloatArray
    reactions: FloatArray
    f_ext: FloatArray
    plane_reactions: dict[str, FloatArray] = field(default_factory=dict)
    moved: float = np.inf
    changed: float = 1.0
    mismatch: float = np.inf
    residual: float = np.inf


def _solve(
    model: SolverModel,
    settings: CalculixSettings,
    inst: CalculixInstallation,
    work: Path,
    start: float,
    mesh_options: dict[str, Any] | None,
    start_positions: FloatArray | None = None,
) -> SimulationResult:
    s = settings
    prob = _Problem(model, s)
    x_start = prob.X.copy() if start_positions is None else np.array(start_positions, float)
    if x_start.shape != prob.X.shape:
        raise ValueError(f"start_positions must have shape {prob.X.shape}, got {x_start.shape}")
    findings: list[Finding] = []
    history: list[IterationRecord] = []
    residuals: list[tuple[int, float]] = []
    _, strain0 = prob.ev.deformation(x_start)
    state0, direction0 = prob.classify(strain0)
    ps = _PassState(
        x_start,
        state0,
        direction0,
        np.zeros((prob.m, 3, 3)),
        np.zeros((prob.n, 3)),
        prob.external(x_start),
    )
    e_max = float(max(prob.ew.max(), prob.ef.max()))
    k_stab = s.stabilization_ratio * e_max
    k_min, k_max = s.min_stabilization_ratio * e_max, s.max_stabilization_ratio * e_max
    jobs_ok, passes_ok, settled = True, False, False
    prev_start: float | None = None
    total_iterations = tf_pass = pass_no = 0
    while pass_no < s.max_passes:
        pass_no += 1
        if s.tension_field and np.any(ps.state != TAUT):
            tf_pass += 1
            kappa = max(s.slack_stiffness_ratio, s.kappa_start * s.kappa_factor ** (tf_pass - 1))
        else:
            kappa = s.slack_stiffness_ratio
        x = ps.x
        mats = prob.materials(ps.state, ps.direction, kappa)
        axes = prob.axes(x)
        sig0 = prob.exact_stress(x, mats)
        f_ext = prob.external(x)
        held = prob.deck(x, axes, mats, sig0, [LoadStep("held", f_ext)], True, 0.0, 1.0)
        if not _run_job(inst, held, work, s.threads):
            raise CalculixRunError("CalculiX failed on a held (fully fixed) job")
        f_int = read_reactions(work / f"{JOB}.dat", prob.n) + prob.tape_forces(x)
        balance = f_int - f_ext
        start_residual, _ = prob.split_planes(np.where(prob.fixed_mask, 0.0, balance))
        b_rel = float(np.linalg.norm(start_residual)) / (float(np.linalg.norm(f_ext)) or 1.0)
        history.append(
            IterationRecord("pass: start out-of-balance (exact law)", pass_no, 0, 0, b_rel)
        )
        log.info("pass %d: start out-of-balance %.3e of the load", pass_no, b_rel)
        final_kappa = kappa <= s.slack_stiffness_ratio * (1.0 + 1e-9)
        if settled and final_kappa and b_rel <= s.residual_target:
            # The held job evaluated CalculiX's internal force for the exact material law
            # at the settled geometry: the final equilibrium check.
            ps.residual = b_rel
            passes_ok = True
            break
        if prev_start is not None and b_rel > prev_start:
            k_stab = min(k_max, k_stab * s.stabilization_growth)
        prev_start = b_rel
        ramp = s.ramp_steps if pass_no == 1 else 1
        stab, inc = k_stab, s.initial_increment
        first = "prestress establishment" if pass_no == 1 else f"pass {pass_no}: balanced start"
        label = "inflation" if pass_no == 1 else f"pass {pass_no}: release"
        while True:
            steps = [LoadStep(first, f_ext + balance, instant=True)]
            steps += [
                LoadStep(f"{label} {r}/{ramp}", f_ext + (1.0 - r / ramp) * balance)
                for r in range(1, ramp + 1)
            ]
            deck = prob.deck(x, axes, mats, sig0, steps, False, stab, inc)
            ok = _run_job(inst, deck, work, s.threads)
            if ok:
                break
            if ramp * 2 <= s.max_ramp_steps:
                ramp *= 2
                what = f"{ramp} release steps"
            elif stab * 4.0 <= k_max:
                stab *= 4.0
                what = f"stabilisation {stab:.3g} N/m"
            elif inc / 2.0 >= s.min_increment:
                inc /= 2.0
                what = f"initial increment {inc:g}"
            else:
                break
            findings.append(
                Finding(
                    "continuation",
                    f"pass {pass_no}: CalculiX did not complete; retrying with {what}",
                    "info",
                )
            )
        for row in read_cvg(work / f"{JOB}.cvg"):
            total_iterations += 1
            name = steps[row.step - 1].name if row.step <= len(steps) else str(row.step)
            residual = row.residual_force / 100.0
            history.append(IterationRecord(name, row.step, row.increment, row.iteration, residual))
            residuals.append((total_iterations, residual))
        if not ok:
            jobs_ok = False
            findings.append(
                Finding(
                    "calculix_failed",
                    f"pass {pass_no}: CalculiX did not complete even at the continuation "
                    f"limits ({ramp} release steps, stabilisation {stab:.3g} N/m, first "
                    f"increment {inc:g}); see {JOB}.log",
                    "error",
                )
            )
            break
        _update(prob, ps, work, axes, f_ext, mats)
        history.append(IterationRecord("pass: largest node movement (m)", pass_no, 0, 0, ps.moved))
        history.append(IterationRecord("pass: relative out-of-balance", pass_no, 0, 0, ps.residual))
        log.info(
            "pass %d: kappa %.3g, stabilisation %.3g N/m, %d release steps, moved %.3g mm, "
            "state changes %.2f%%, stress mismatch %.2e, out-of-balance %.2e",
            pass_no,
            kappa,
            stab,
            ramp,
            ps.moved * 1000,
            ps.changed * 100,
            ps.mismatch,
            ps.residual,
        )
        k_stab = min(k_max, max(k_min, stab * s.stabilization_decay))
        settled = (
            final_kappa
            and ps.moved < s.position_tolerance
            and ps.changed <= s.state_tolerance
            and ps.mismatch <= s.stress_tolerance
            and ps.residual <= s.residual_target
        )
    elapsed = time.perf_counter() - start
    return _result(
        model,
        s,
        inst,
        prob,
        ps,
        history,
        residuals,
        findings,
        jobs_ok,
        passes_ok,
        elapsed,
        mesh_options,
        start_positions is not None,
    )


def _update(
    prob: _Problem,
    ps: _PassState,
    work: Path,
    axes: FloatArray,
    f_ext: FloatArray,
    material: FloatArray,
) -> None:
    """Read a completed release job and advance the pass state."""
    u = read_displacements(work / f"{JOB}.dat", prob.n)
    if not np.all(np.isfinite(u)):
        raise CalculixRunError("CalculiX output is missing node displacements")
    x_new = ps.x + u
    # RF is the fabric's internal force only (no SPRINGA tapes, no SPRING1 springs).
    f_int = read_reactions(work / f"{JOB}.dat", prob.n) + prob.tape_forces(x_new)
    stress_loc = read_element_stress(work / f"{JOB}.dat", prob.m)
    rot = np.transpose(axes, (0, 2, 1))  # columns a, b, n
    ps.stress = _in_plane(
        prob.settings.thickness * np.einsum("mij,mjk,mlk->mil", rot, stress_loc, rot),
        x_new,
        prob.tri,
    )
    ps.reactions = np.where(prob.fixed_mask, f_int - f_ext, 0.0)
    # The springs' force is the out-of-balance force of the real problem at x_new; it is
    # computed from the forces rather than as k u, so that it also checks the tape law.
    # Force normal to a symmetry plane at its nodes is the plane's reaction.
    spring, ps.plane_reactions = prob.split_planes(np.where(prob.fixed_mask, 0.0, f_int - f_ext))
    ps.residual = float(np.linalg.norm(spring)) / (float(np.linalg.norm(f_ext)) or 1.0)
    ps.moved = float(np.max(np.linalg.norm(u, axis=1)))
    _, strain = prob.ev.deformation(x_new)
    new_state, new_direction = prob.classify(strain)
    ps.changed = float(np.mean(new_state != ps.state))
    exact = prob.exact_stress(x_new, material)
    scale = float(np.max(np.linalg.norm(exact, axis=(1, 2)))) or 1.0
    ps.mismatch = float(np.max(np.linalg.norm(ps.stress - exact, axis=(1, 2)))) / scale
    ps.f_ext = f_ext
    ps.x, ps.state, ps.direction = x_new, new_state, new_direction


def _result(
    model: SolverModel,
    s: CalculixSettings,
    inst: CalculixInstallation,
    prob: _Problem,
    ps: _PassState,
    history: list[IterationRecord],
    residuals: list[tuple[int, float]],
    findings: list[Finding],
    jobs_ok: bool,
    passes_ok: bool,
    elapsed: float,
    mesh_options: dict[str, Any] | None,
    supplied_start: bool,
) -> SimulationResult:
    groups: dict[str, FloatArray] = {}
    remaining = ps.reactions.copy()
    for con in model.constraints:
        groups[con.name] = remaining[con.nodes].sum(axis=0)
        remaining[con.nodes] = 0.0
    applied = ps.f_ext.sum(axis=0)
    total_reaction = sum(groups.values(), np.zeros(3))
    pressure_part = (ps.f_ext - prob.dead).sum(axis=0)
    scale = float(np.linalg.norm(pressure_part)) or float(np.linalg.norm(applied)) or 1.0
    for name, force in ps.plane_reactions.items():
        groups[name] = force
    total_reaction = sum(groups.values(), np.zeros(3))
    imbalance = float(np.linalg.norm(applied + total_reaction)) / scale
    balance_ok = imbalance <= s.balance_tolerance and ps.residual <= 10 * s.balance_tolerance
    converged = jobs_ok and passes_ok and balance_ok
    if jobs_ok and not passes_ok:
        findings.append(
            Finding(
                "not_converged",
                f"passes did not converge within {s.max_passes} (last pass: largest movement "
                f"{ps.moved * 1000:.3g} mm vs {s.position_tolerance * 1000:g} mm, state "
                f"changes {ps.changed:.2%} vs {s.state_tolerance:.2%}, stress consistency "
                f"{ps.mismatch:.2e} vs {s.stress_tolerance:g}, relative out-of-balance "
                f"{ps.residual:.2e} vs {s.residual_target:g}); result is NOT final",
                "error",
            )
        )
    if not jobs_ok:
        findings.append(Finding("not_converged", "CalculiX solve failed; NOT final", "error"))
    if not balance_ok:
        findings.append(
            Finding(
                "force_imbalance",
                f"global force imbalance {imbalance:.2e} (relative out-of-balance "
                f"{ps.residual:.2e}) exceeds {s.balance_tolerance}",
                "error",
            )
        )
    if s.tension_field:
        findings.append(
            Finding(
                "wrinkles",
                f"{int(np.sum(ps.state == WRINKLED))} wrinkled and "
                f"{int(np.sum(ps.state == SLACK))} slack elements of {prob.m}",
                "info",
            )
        )
    solver_settings = s.as_dict()
    solver_settings["executable"] = str(inst.executable)
    solver_settings["start"] = "supplied positions" if supplied_start else "model initial shape"
    manifest = manifest_for(
        model,
        "calculix",
        solver_version=inst.version,
        solver_settings=solver_settings,
        mesh_options=mesh_options,
    )
    manifest.dependencies["calculix"] = inst.version
    tensions, _ = prob.ev.tapes(ps.x)
    volume = prob.ev.volume(ps.x)
    status = "converged" if converged else ("failed" if not jobs_ok else "not converged")
    return SimulationResult(
        solver="calculix",
        solver_version=inst.version,
        status=status,
        converged=converged,
        positions=ps.x,
        initial_positions=prob.X,
        triangles=prob.tri,
        stress=ps.stress,
        principal=principal_resultants(ps.stress, prob.tri, ps.x),
        tape_tensions=tensions,
        tape_edges={c.name: c.edges for c in model.cables},
        reactions=groups,
        nodal_reactions=ps.reactions,
        volume=volume,
        lift=prob.ev.lift(ps.x),
        chamber_volumes=prob.ev.chamber_volumes(ps.x),
        residual_history=residuals,
        iteration_history=history,
        residual_measure=(
            "CalculiX Newton residual (largest residual force / average force, fraction) "
            "per iteration; per pass: largest node movement (m), relative out-of-balance "
            "||f_ext - f_int|| / ||f_ext|| at the end of the release job and, from the next "
            "held job, for the exact material law (symmetry-plane reactions excluded)"
        ),
        elapsed=elapsed,
        mouth_nodes=mouth_nodes(model),
        manifest=manifest,
        wrinkle_state=ps.state,
        findings=findings,
    )
