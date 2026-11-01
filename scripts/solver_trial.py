"""Solver trial: speed and accuracy of candidate inflation solvers on ever finer meshes.

Benchmark: the Smalley 90K shape-file fixture (tests/fixtures/smalley_90k), built into a
20-gore design with 12 rows and meshed at each target edge length. This is a development
study, not part of the application: the energy and Newton solvers here are prototypes.

Solvers
-------
dr              The app's preview solver (dynamic relaxation), cold start.
dr-ml           dr on every coarser mesh first, carried to the next mesh through the flat
                pattern (envelopelab.solvers.multilevel); time includes the coarse solves.
newton-ml       App law. Multilevel; per mesh dynamic relaxation to 1e-3, then Newton with
                pseudo-transient continuation (finite-difference Jacobian by graph
                colouring); dynamic relaxation finishes when Newton stalls.
energy-newton-ml  Total-potential-energy model (scripts/solver_trial_energy.py: relaxed
                wrinkling energy). Multilevel from the design shape on the coarsest mesh;
                modified Newton with Armijo line search on the energy.
energy-lbfgs-ml Same energy, scipy L-BFGS (off the shelf), multilevel.
calculix        CalculiX equilibrium check of the dr result (ADR-0027 warm start).

Usage::

    python scripts/solver_trial.py run --meshes 3200 1600 800 400 --out trial.json
    python scripts/solver_trial.py report trial.json --md docs/dev/solver-trial.md
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp
from scipy.optimize import minimize
from scipy.sparse.linalg import splu

sys.path.insert(0, str(Path(__file__).resolve().parent))

from solver_trial_energy import EnergyModel, free_basis  # noqa: E402

from envelopelab.assembly.rest_model import git_commit  # noqa: E402
from envelopelab.io.shape_file import load_shape_file  # noqa: E402
from envelopelab.project.session import ProjectSession  # noqa: E402
from envelopelab.project.shape_family import shape_design  # noqa: E402
from envelopelab.project.simulation import build_solver_model, final_residual  # noqa: E402
from envelopelab.solvers.dynamic_relaxation import (  # noqa: E402
    Convergence,
    _finish,
    _relative,
    _System,
    solve,
)
from envelopelab.solvers.kernels import compiled_forces_and_masses  # noqa: E402
from envelopelab.solvers.model import SolverModel, SolverSettings  # noqa: E402
from envelopelab.solvers.multilevel import prolongate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "smalley_90k" / "shape.yaml"
TOL = 1e-6  # AGENTS.md: residual norm < 1e-6 relative
SOLVERS = ("dr", "dr-ml", "newton-ml", "energy-newton-ml", "energy-lbfgs-ml", "calculix")


# --------------------------------------------------------------------------------------
# Benchmark meshes


@dataclass
class Level:
    """One mesh of the benchmark design."""

    mesh_mm: float
    model: SolverModel
    tri_panel: np.ndarray
    build_time: float


def build_levels(meshes: list[float], rows: int = 12) -> list[Level]:
    """Smalley 90K meshed at each target edge length (coarse to fine)."""
    shape_file = load_shape_file(FIXTURE)
    design = shape_design(shape_file.name, shape_file.shape, shape_file.solve(), row_count=rows)
    patterns = ProjectSession.new(design).patterns
    levels: list[Level] = []
    ids: list[str] | None = None
    for mm in sorted(meshes, reverse=True):
        t0 = time.perf_counter()
        built = build_solver_model(design, patterns, tempfile.mkdtemp(), mm)
        mesh = built.build.rest_model.mesh  # type: ignore[union-attr]
        if ids is None:
            ids = list(mesh.instance_ids)
        index = {name: k for k, name in enumerate(ids)}
        tri_panel = np.array([index[mesh.instance_ids[i]] for i in mesh.tri_instance])
        levels.append(Level(mm, built.model, tri_panel, time.perf_counter() - t0))
        print(f"  mesh {mm:g} mm: {built.model.n_nodes} nodes", flush=True)
    return levels


def carry(coarse: Level, x: np.ndarray, fine: Level) -> np.ndarray:
    """Coarse solution as a fine start (flat-pattern prolongation)."""
    return prolongate(
        x,
        coarse.model.triangles,
        coarse.model.rest_uv,
        coarse.tri_panel,
        fine.model.triangles,
        fine.model.rest_uv,
        fine.tri_panel,
        fine.model.n_nodes,
    )


# --------------------------------------------------------------------------------------
# Finite-difference Jacobians by graph colouring


class Colouring:
    """Distance-2 colouring of the node graph (triangles and tapes).

    Ring-to-ring coupling through a closure cap is left out of the pattern (it would make
    every ring a clique); those small entries are missing from the Jacobian, so Newton is
    slightly inexact at closure rings.
    """

    def __init__(self, system: _System) -> None:
        n = system.n
        rows, cols = [], []
        for a in range(3):
            for b in range(3):
                rows.append(system.tri[:, a])
                cols.append(system.tri[:, b])
        ce = system.cable_edges
        for a in range(2):
            for b in range(2):
                rows.append(ce[:, a])
                cols.append(ce[:, b])
        r = np.concatenate(rows)
        c = np.concatenate(cols)
        adj = sp.csr_matrix((np.ones(len(r)), (r, c)), shape=(n, n))
        adj.data[:] = 1.0
        adj.sum_duplicates()
        adj.data[:] = 1.0
        two = (adj @ adj).tocsr()
        colour = -np.ones(n, dtype=np.int64)
        for i in np.argsort(-np.diff(two.indptr), kind="stable"):
            used = set(colour[two.indices[two.indptr[i] : two.indptr[i + 1]]].tolist())
            k = 0
            while k in used:
                k += 1
            colour[i] = k
        self.colour = colour
        self.count = int(colour.max()) + 1
        coo = adj.tocoo()
        self.pair_i = coo.row.astype(np.int64)
        self.pair_j = coo.col.astype(np.int64)
        self.n = n

    def jacobian(
        self, func: Callable[[np.ndarray], np.ndarray], x: np.ndarray, f0: np.ndarray, h: float
    ) -> sp.csr_matrix:
        """Sparse d func / d x (3n x 3n) by forward differences, 3 evaluations per colour."""
        rows, cols, vals = [], [], []
        for c in range(self.count):
            nodes = np.flatnonzero(self.colour == c)
            sel = self.colour[self.pair_j] == c
            pi, pj = self.pair_i[sel], self.pair_j[sel]
            for d in range(3):
                xp = x.copy()
                xp[nodes, d] += h
                diff = (func(xp) - f0) / h
                for k in range(3):
                    rows.append(3 * pi + k)
                    cols.append(3 * pj + d)
                    vals.append(diff[pi, k])
        n3 = 3 * self.n
        return sp.csr_matrix(
            (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n3, n3)
        )


# --------------------------------------------------------------------------------------
# Results


@dataclass
class Run:
    """One solver on one mesh."""

    solver: str
    mesh_mm: float
    nodes: int
    status: str
    converged: bool
    wall_time: float
    residual: float  # the solver's own relative residual
    app_residual: float  # relative residual of the app's law at the result
    counts: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    positions: np.ndarray | None = None


def metrics(level: Level, x: np.ndarray) -> tuple[float, dict[str, float]]:
    """App residual and engineering quantities at positions ``x`` (app's law)."""
    system = _System(level.model, SolverSettings())
    r, ext, data = system.forces(x)
    res = _relative(system.project(r), ext)
    conv = Convergence("converged", 0, res, TOL, 0, 0.0, [])
    out = _finish(system, x, system.x_start, r, data, conv)
    tapes = [t.max() for t in out.tape_tensions.values() if len(t)]
    z_mouth = float(level.model.conditions.mouth_height)
    return res, {
        "volume_m3": float(out.volume),
        "crown_height_m": float(x[:, 2].max() - z_mouth),
        "max_diameter_m": float(2.0 * np.hypot(x[:, 0], x[:, 1]).max()),
        "max_tape_tension_n": float(max(tapes)) if tapes else 0.0,
        "max_fabric_n1_n_m": float(out.principal[:, 0].max()),
        "wrinkled_fraction": float((out.state != 0).mean()),
    }


def finish_run(
    solver: str, level: Level, x: np.ndarray, status: str, wall: float, residual: float,
    counts: dict[str, float], notes: list[str],
) -> Run:  # fmt: skip
    app_res, m = metrics(level, x)
    run = Run(
        solver, level.mesh_mm, level.model.n_nodes, status, status == "converged", wall,
        residual, app_res, counts, m, notes, x,
    )  # fmt: skip
    print(
        f"    {solver:17s} {level.mesh_mm:6g} mm  {status:13s} {wall:8.1f} s  "
        f"res {residual:.2e}  app {app_res:.2e}  V {m['volume_m3']:.2f}",
        flush=True,
    )
    return run


# --------------------------------------------------------------------------------------
# Solvers


def run_dr(level: Level, start: np.ndarray | None, tol: float, limit: float) -> tuple:
    settings = SolverSettings(tolerance=tol, max_iterations=10_000_000, time_limit=limit)
    t0 = time.perf_counter()
    res = solve(level.model, settings, initial_positions=start)
    wall = time.perf_counter() - t0
    c = res.convergence
    return res.positions, c.status, wall, c.residual, {"iterations": c.iterations}


def run_newton(level: Level, start: np.ndarray | None, limit: float) -> tuple:
    """Dynamic relaxation to 1e-3, then pseudo-transient Newton; DR finishes on a stall."""
    t0 = time.perf_counter()
    x, status, _, res, counts = run_dr(level, start, 1e-3, limit)
    counts = {"dr_iterations": counts["iterations"]}
    settings = SolverSettings()
    system = _System(level.model, settings)
    inputs = system.compiled_inputs()

    def forces(xx: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return compiled_forces_and_masses(
            xx, system.tri, system.rest, system.c, system.c_inv,
            settings.slack_stiffness_ratio, settings.tension_field, inputs, settings.mass_factor,
        )  # fmt: skip

    colouring = Colouring(system)
    basis = free_basis(system)
    x = x.copy()
    x[system.constrained] = system.x_start[system.constrained]
    r, ext, mass = forces(x)
    res = _relative(system.project(r), ext)
    res0, mu0, evals, its, best = res, 1e-2, 0, 0, res
    h = 1e-6
    while res >= TOL and its < 60 and time.perf_counter() - t0 < limit:
        its += 1
        jac = colouring.jacobian(lambda xx: forces(xx)[0], x, r, h)
        evals += 3 * colouring.count
        k_red = -(basis.T @ jac @ basis)
        d_red = sp.diags(basis.T @ np.repeat(mass, 3))
        mu = mu0 * res / res0
        try:
            dq = splu((k_red + mu * d_red).tocsc()).solve(basis.T @ r.ravel())
        except RuntimeError:
            mu0 *= 10.0
            continue
        xn = x + (basis @ dq).reshape(-1, 3)
        rn, en, mn = forces(xn)
        evals += 1
        resn = _relative(system.project(rn), en)
        if np.isfinite(resn) and resn < 10.0 * best:
            x, r, mass, res = xn, rn, mn, resn
            best = min(best, res)
            mu0 *= 0.5
        else:
            mu0 *= 4.0
    counts.update({"newton_iterations": its, "residual_evaluations": evals,
                   "newton_reached": res})  # fmt: skip
    notes = []
    status = "converged" if res < TOL else "stalled"
    if res >= TOL:
        notes.append(f"Newton stalled at {res:.1e}; dynamic relaxation finished")
        left = max(1.0, limit - (time.perf_counter() - t0))
        x, status, _, res, c2 = run_dr(level, x, TOL, left)
        counts["dr_finish_iterations"] = c2["iterations"]
    return x, status, time.perf_counter() - t0, res, counts, notes


def energy_residual(em: EnergyModel, x: np.ndarray, grad: np.ndarray) -> float:
    return float(np.linalg.norm(em.system.project(-grad))) / em.external_scale(x)


def run_energy_newton(level: Level, start: np.ndarray | None, limit: float) -> tuple:
    """Modified Newton on the total energy with Armijo backtracking."""
    t0 = time.perf_counter()
    em = EnergyModel(level.model)
    system = em.system
    colouring = Colouring(system)
    basis = free_basis(system)
    x = (system.x_start if start is None else start).copy()
    x[system.constrained] = system.x_start[system.constrained]
    terms = em.evaluate(x)
    evals, its, factorisations, lam = 1, 0, 0, 1e-6
    res = energy_residual(em, x, terms.gradient)
    status = "max_iterations"
    while its < 500:
        if res < TOL:
            status = "converged"
            break
        if time.perf_counter() - t0 > limit:
            status = "time_limit"
            break
        its += 1
        hess = colouring.jacobian(lambda xx: em.evaluate(xx).gradient, x, terms.gradient, 1e-6)
        evals += 3 * colouring.count
        hess = 0.5 * (hess + hess.T)
        h_red = (basis.T @ hess @ basis).tocsc()
        g_red = basis.T @ terms.gradient.ravel()
        diag = np.abs(h_red.diagonal()) + 1e-12 * np.abs(h_red.diagonal()).max()
        while True:
            factorisations += 1
            try:
                d_red = -splu((h_red + lam * sp.diags(diag)).tocsc()).solve(g_red)
                slope = float(g_red @ d_red)
                if slope < 0.0:
                    break
            except RuntimeError:
                pass
            lam = max(10.0 * lam, 1e-6)
        step = (basis @ d_red).reshape(-1, 3)
        alpha, accepted = 1.0, False
        while alpha > 1e-6:
            trial = em.evaluate(x + alpha * step)
            evals += 1
            if trial.energy <= terms.energy + 1e-4 * alpha * slope:
                accepted = True
                break
            # Near convergence the energy change is below round-off; accept a step that
            # lowers the residual instead.
            if abs(alpha * slope) < 1e-13 * abs(terms.energy):
                if energy_residual(em, x + alpha * step, trial.gradient) < res:
                    accepted = True
                    break
            alpha *= 0.5
        if not accepted:
            lam = max(100.0 * lam, 1e-4)
            continue
        x = x + alpha * step
        terms = trial
        res = energy_residual(em, x, terms.gradient)
        lam = lam / 10.0 if alpha == 1.0 else lam * 2.0
    counts = {"newton_iterations": its, "gradient_evaluations": evals,
              "factorisations": factorisations, "colours": colouring.count}  # fmt: skip
    return x, status, time.perf_counter() - t0, res, counts, []


def run_energy_lbfgs(level: Level, start: np.ndarray | None, limit: float) -> tuple:
    """scipy L-BFGS on the total energy (stops at the trial tolerance or time limit)."""
    t0 = time.perf_counter()
    em = EnergyModel(level.model)
    system = em.system
    basis = free_basis(system)
    x0 = (system.x_start if start is None else start).copy()
    x0[system.constrained] = system.x_start[system.constrained]
    scale = em.external_scale(x0)
    state: dict[str, Any] = {"evals": 0, "res": math.inf, "status": "max_iterations"}

    def fun(q: np.ndarray) -> tuple[float, np.ndarray]:
        x = x0 + (basis @ q).reshape(-1, 3)
        t = em.evaluate(x)
        state["evals"] += 1
        return t.energy, basis.T @ t.gradient.ravel()

    def callback(intermediate_result: Any) -> None:
        q = intermediate_result.x
        x = x0 + (basis @ q).reshape(-1, 3)
        g = em.evaluate(x).gradient
        state["res"] = float(np.linalg.norm(system.project(-g))) / scale
        if state["res"] < TOL:
            state["status"] = "converged"
            raise StopIteration
        if time.perf_counter() - t0 > limit:
            state["status"] = "time_limit"
            raise StopIteration

    out = minimize(
        fun, np.zeros(basis.shape[1]), jac=True, method="L-BFGS-B", callback=callback,
        options={"maxiter": 10_000_000, "maxfun": 10_000_000, "maxcor": 30,
                 "ftol": 0.0, "gtol": 0.0},
    )  # fmt: skip
    x = x0 + (basis @ out.x).reshape(-1, 3)
    counts = {"iterations": int(out.nit), "gradient_evaluations": state["evals"]}
    notes = [] if state["status"] != "max_iterations" else [f"scipy: {out.message}"]
    return x, state["status"], time.perf_counter() - t0, state["res"], counts, notes


def run_calculix(level: Level, start: np.ndarray) -> tuple:
    from calculix_adapter.analysis import run_calculix as ccx

    t0 = time.perf_counter()
    result = ccx(level.model, start_positions=start)
    wall = time.perf_counter() - t0
    res, _ = final_residual(result)
    status = "converged" if result.converged else result.status
    return result.positions, status, wall, res, {"passes": len(result.residual_history)}, []


# --------------------------------------------------------------------------------------
# Driver


def multilevel(
    solver: str,
    levels: list[Level],
    step: Callable[[Level, np.ndarray | None], tuple],
) -> list[Run]:
    """Solve every level in turn, each started from the previous one's result; a level's
    reported time includes all coarser solves."""
    runs: list[Run] = []
    previous: tuple[Level, np.ndarray] | None = None
    elapsed = 0.0
    for level in levels:
        start = None if previous is None else carry(previous[0], previous[1], level)
        t0 = time.perf_counter()
        out = step(level, start)
        x, status, _, res, counts = out[:5]
        notes = list(out[5]) if len(out) > 5 else []
        own = time.perf_counter() - t0
        elapsed += own
        counts = dict(counts, level_time_s=own)
        runs.append(finish_run(solver, level, x, status, elapsed, res, counts, notes))
        previous = (level, x)
    return runs


def run_trial(meshes: list[float], solvers: list[str], limit: float) -> dict[str, Any]:
    print("building meshes", flush=True)
    levels = build_levels(meshes)
    runs: list[Run] = []
    dr_runs: dict[float, Run] = {}
    for solver in solvers:
        print(f"solver {solver}", flush=True)
        if solver == "dr":
            for level in levels:
                x, status, wall, res, counts = run_dr(level, None, TOL, limit)
                run = finish_run(solver, level, x, status, wall, res, counts, [])
                runs.append(run)
                dr_runs[level.mesh_mm] = run
        elif solver == "dr-ml":
            runs += multilevel(solver, levels, lambda lv, s: run_dr(lv, s, TOL, limit))
        elif solver == "newton-ml":
            runs += multilevel(solver, levels, lambda lv, s: run_newton(lv, s, limit))
        elif solver == "energy-newton-ml":
            runs += multilevel(solver, levels, lambda lv, s: run_energy_newton(lv, s, limit))
        elif solver == "energy-lbfgs-ml":
            runs += multilevel(solver, levels, lambda lv, s: run_energy_lbfgs(lv, s, limit))
        elif solver == "calculix":
            for level in levels:
                base = dr_runs.get(level.mesh_mm)
                if base is None or base.positions is None or not base.converged:
                    continue
                out = run_calculix(level, base.positions)
                runs.append(finish_run(solver, level, *out))
    # Agreement with dr at the same mesh.
    for run in runs:
        base = dr_runs.get(run.mesh_mm)
        if base is None or base.positions is None or run.positions is None:
            continue
        run.metrics["max_node_distance_to_dr_mm"] = float(
            1e3 * np.linalg.norm(run.positions - base.positions, axis=1).max()
        )
    import importlib.metadata as md

    versions = {"python": platform.python_version()}
    for name in ("numpy", "scipy", "numba"):
        try:
            versions[name] = md.version(name)
        except md.PackageNotFoundError:
            versions[name] = "not installed"
    return {
        "benchmark": "Smalley 90K (tests/fixtures/smalley_90k/shape.yaml), 12 rows",
        "tolerance": TOL,
        "time_limit_s": limit,
        "git_commit": git_commit(),
        "versions": versions,
        "machine": f"{platform.machine()}, {platform.system()}",
        "levels": [
            {
                "mesh_mm": lv.mesh_mm,
                "nodes": lv.model.n_nodes,
                "triangles": len(lv.model.triangles),
                "build_time_s": lv.build_time,
            }
            for lv in levels
        ],  # fmt: skip
        "runs": [{k: v for k, v in asdict(r).items() if k != "positions"} for r in runs],
    }


# --------------------------------------------------------------------------------------
# Report


def richardson(h: list[float], q: list[float]) -> tuple[float, float] | None:
    """Extrapolated value and observed order from the three finest meshes (ratio 2)."""
    if len(q) < 3:
        return None
    q1, q2, q3 = q[-3], q[-2], q[-1]  # coarse -> fine
    d1, d2 = q2 - q1, q3 - q2
    if d1 == 0.0 or d2 == 0.0 or d1 / d2 <= 0.0:
        return None
    ratio = h[-2] / h[-1]
    p = math.log(d1 / d2) / math.log(ratio)
    return q3 + d2 / (ratio**p - 1.0), p


def report(data: dict[str, Any]) -> str:
    runs = data["runs"]
    solvers = list(dict.fromkeys(r["solver"] for r in runs))
    meshes = [lv["mesh_mm"] for lv in data["levels"]]
    lines = [
        "# Solver trial: Smalley 90K",
        "",
        "<!-- Generated by scripts/solver_trial.py report; do not edit by hand. -->",
        "",
        f"Benchmark: {data['benchmark']}. Convergence: relative residual below "
        f"{data['tolerance']:g}. Time limit per mesh: {data['time_limit_s']:g} s. "
        f"Commit `{data['git_commit'][:10]}`, {data['machine']}, "
        + ", ".join(f"{k} {v}" for k, v in data["versions"].items())
        + ".",
        "",
        "A development study, not a validation page: the energy and Newton solvers are "
        "prototypes in `scripts/`. The energy solvers use the relaxed (Pipkin) wrinkling "
        "energy, which equals the app's law for isotropic fabric and differs slightly for "
        "this orthotropic ripstop, so their *app residual* is not expected to reach the "
        "tolerance; compare their geometry with `dr` instead.",
        "",
        "## Meshes",
        "",
        "| mesh (mm) | nodes | triangles | build (s) |",
        "|---|---|---|---|",
    ]
    for lv in data["levels"]:
        lines.append(
            f"| {lv['mesh_mm']:g} | {lv['nodes']} | {lv['triangles']} | {lv['build_time_s']:.1f} |"
        )
    lines += ["", "## Time to a converged solution (s)", ""]
    lines.append("| solver | " + " | ".join(f"{m:g} mm" for m in meshes) + " |")
    lines.append("|---|" + "---|" * len(meshes))
    for s in solvers:
        cells = []
        for m in meshes:
            r = next((r for r in runs if r["solver"] == s and r["mesh_mm"] == m), None)
            if r is None:
                cells.append("-")
            else:
                mark = "" if r["converged"] else f" ({r['status']})"
                cells.append(f"{r['wall_time']:.1f}{mark}")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Multilevel (`-ml`) times include every coarser mesh. `calculix` times exclude the "
        "`dr` solve it starts from.",
        "",
        "## Every run",
        "",
        "| solver | mesh (mm) | status | time (s) | own residual | app residual | "
        "volume (m^3) | crown height (m) | max tape (N) | max N1 (N/m) | wrinkled | "
        "max distance to dr (mm) | counts |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        m = r["metrics"]
        counts = ", ".join(
            f"{k} {v:.3g}" if isinstance(v, float) else f"{k} {v}" for k, v in r["counts"].items()
        )
        notes = ("; " + "; ".join(r["notes"])) if r["notes"] else ""
        lines.append(
            f"| {r['solver']} | {r['mesh_mm']:g} | {r['status']} | {r['wall_time']:.1f} | "
            f"{r['residual']:.1e} | {r['app_residual']:.1e} | {m['volume_m3']:.3f} | "
            f"{m['crown_height_m']:.4f} | {m['max_tape_tension_n']:.1f} | "
            f"{m['max_fabric_n1_n_m']:.1f} | {m['wrinkled_fraction']:.2f} | "
            f"{m.get('max_node_distance_to_dr_mm', float('nan')):.2f} | {counts}{notes} |"
        )
    lines += ["", "## Mesh convergence", ""]
    lines.append(
        "Richardson extrapolation from the three finest meshes of each solver's converged "
        "results (ratio 2); error of each mesh against the extrapolated value."
    )
    lines.append("")
    for key, label in (
        ("volume_m3", "volume (m^3)"),
        ("crown_height_m", "crown height (m)"),
        ("max_tape_tension_n", "max tape tension (N)"),
        ("max_fabric_n1_n_m", "max fabric N1 (N/m)"),
    ):
        lines += [f"### {label}", ""]
        lines.append(
            "| solver | " + " | ".join(f"{m:g} mm" for m in meshes) + " | extrapolated | order |"
        )
        lines.append("|---|" + "---|" * (len(meshes) + 2))
        for s in solvers:
            series = [
                (r["mesh_mm"], r["metrics"][key])
                for r in runs
                if r["solver"] == s and r["converged"]
            ]
            if not series:
                continue
            ext = richardson([h for h, _ in series], [q for _, q in series])
            cells = []
            for m in meshes:
                q = next((v for h, v in series if h == m), None)
                if q is None:
                    cells.append("-")
                elif ext is None:
                    cells.append(f"{q:.4g}")
                else:
                    err = 100.0 * (q - ext[0]) / ext[0]
                    cells.append(f"{q:.4g} ({err:+.2f} %)")
            tail = f"{ext[0]:.4g} | {ext[1]:.2f}" if ext else "- | -"
            lines.append(f"| {s} | " + " | ".join(cells) + f" | {tail} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run the trial and write JSON")
    run_p.add_argument("--meshes", type=float, nargs="+", default=[3200, 1600, 800, 400])
    run_p.add_argument("--solvers", nargs="+", default=list(SOLVERS), choices=SOLVERS)
    run_p.add_argument("--time-limit", type=float, default=1800.0, help="per mesh, s")
    run_p.add_argument("--out", type=Path, required=True)
    rep_p = sub.add_parser("report", help="write the Markdown report from JSON files")
    rep_p.add_argument("json", type=Path, nargs="+")
    rep_p.add_argument("--md", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        data = run_trial(args.meshes, args.solvers, args.time_limit)
        args.out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    else:
        merged: dict[str, Any] | None = None
        for path in args.json:
            part = json.loads(path.read_text(encoding="utf-8"))
            if merged is None:
                merged = part
            else:
                known = {lv["mesh_mm"] for lv in merged["levels"]}
                merged["levels"] += [lv for lv in part["levels"] if lv["mesh_mm"] not in known]
                merged["levels"].sort(key=lambda lv: -lv["mesh_mm"])
                merged["runs"] += part["runs"]
        assert merged is not None
        args.md.write_text(report(merged), encoding="utf-8")


if __name__ == "__main__":
    main()
