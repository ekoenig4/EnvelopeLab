"""Background preview and CalculiX solves for the GUI.

A run captures the design state when it starts (so later edits cannot leak into it),
builds the solver model on a worker thread, solves it and hands the result back to the
GUI thread as a run record. The record carries the fingerprint of the state it solved, so
the result becomes *stale* as soon as a relevant input changes.

CalculiX (``ccx``) runs as an external process through ``calculix_adapter``; it is
detected at start and when the preferences change, and *Run CalculiX* is disabled with an
explanation when it is missing. CalculiX starts from a preview equilibrium of the same
model: a current converged preview run of the same mesh when there is one, else a preview
solved first in the same run (and kept as its own run record).

After the envelope, the same run solves every placed special shape that can be fed (it has
a feed hole) with the same solver and load case: each shape's own sub-model, its skin sewn
from the cut pieces on a patch of the envelope round it, at the automatic element size of
:func:`envelopelab.project.shape_runs.auto_mesh_size` (CalculiX from a preview of the same
sub-model). The shapes are solved in parallel threads (:func:`shape_workers`; the
compiled preview solver releases the GIL, and Gmsh is used under
``envelopelab.assembly.mesh.GMSH_LOCK``), and each result is reported as soon as it is
ready. Each result is kept with the project, linked to the envelope run. A shape that
cannot be solved is reported and does not stop the others.
"""

from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from envelopelab.design.model import DesignDocument
from envelopelab.project.model import PatternSet, RunRecord
from envelopelab.project.simulation import (
    BuildError,
    BuiltModel,
    build_solver_model,
    run_record,
    solve_preview,
)
from envelopelab.solvers.dynamic_relaxation import CancellationToken, SolverProgress
from envelopelab.solvers.progress import ConvergenceEstimator, PassProgress, format_duration
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.shapes_service import (
    ShapeSimulation,
    ShapeSolveError,
    ShapeSolveRequest,
    solve_shape,
)

PREVIEW = "envelopelab-preview"
#: Share of the progress bar for building the model, and where a CalculiX run's own
#: preview (form finding) ends. Measured on the generic fixture at 800 mm: build 3 s,
#: preview 18 s, CalculiX 4 s.
BUILD_SHARE = 0.1
FORM_FINDING_END = 0.75
CALCULIX = "calculix"


def shape_workers(count: int, solver: str) -> int:
    """Threads that solve the special shapes of a run in parallel.

    One per shape, at most one fewer than the processor count (one is left for the GUI);
    at most 2 for CalculiX, which runs several threads of its own.
    """
    cpus = os.cpu_count() or 2
    limit = max(1, cpus - 1)
    if solver != PREVIEW:
        limit = min(limit, 2)
    return max(1, min(count, limit))


@dataclass
class RunRequest:
    """Everything a worker needs (copies taken when the run starts)."""

    solver: str
    design: DesignDocument
    patterns: PatternSet
    fingerprints: dict[str, str]
    mesh_mm: float
    ccx_path: str | None
    start_positions: np.ndarray | None = None
    shapes: list[ShapeSolveRequest] = field(default_factory=list)


class SolveWorker(QThread):
    """Worker thread: build the model and run one solver."""

    progress = Signal(str, float)  # message, fraction in [0, 1]
    built = Signal(object)  # BuiltModel
    finished_run = Signal(object, object)  # RunRecord, arrays
    shape_solved = Signal(object)  # ShapeSimulation
    shape_failed = Signal(str)
    failed = Signal(str)

    def __init__(self, request: RunRequest, fabrics: Any) -> None:
        super().__init__()
        self.request = request
        self.fabrics = fabrics
        self.token = CancellationToken()

    def cancel(self) -> None:
        """Ask the solve to stop."""
        self.token.cancel()

    def run(self) -> None:  # noqa: D102 (QThread entry point)
        req = self.request
        label = "Preview" if req.solver == PREVIEW else "CalculiX"
        try:
            with tempfile.TemporaryDirectory(prefix="envelopelab-run-") as tmp:
                self.progress.emit(
                    f"{label}: building the model ({req.mesh_mm:g} mm mesh: import, seam "
                    "audit, meshing, sewing)",
                    0.0,
                )
                built = build_solver_model(
                    req.design, req.patterns, Path(tmp) / "pack", req.mesh_mm, self.fabrics
                )
                self.built.emit(built)
                if self.token.cancelled:
                    self.failed.emit(f"{label} run cancelled")
                    return
                if req.solver == PREVIEW:
                    result = self._preview(built, (BUILD_SHARE, 1.0))
                else:
                    start = req.start_positions
                    if start is None:
                        start = self._form_finding(built)
                        if start is None:
                            return
                        span = (FORM_FINDING_END, 1.0)
                    else:
                        span = (BUILD_SHARE, 1.0)
                    result = self._calculix(built, Path(tmp) / "ccx", start, span)
                if result is None:
                    return
                record, arrays = run_record(result, built, req.fingerprints["simulation"])
                record.findings = [*built.findings, *record.findings]
                self.finished_run.emit(record, arrays)
                self._shapes(record.run_id, Path(tmp))
        except BuildError as exc:
            self.failed.emit(f"{label} run not started: {exc}")
        except Exception as exc:  # the thread must report every failure to the GUI
            self.failed.emit(f"{label} run failed: {type(exc).__name__}: {exc}")

    def _shapes(self, run_id: str, tmp: Path) -> None:
        """Solve the run's special shapes after the envelope (module docstring)."""
        req = self.request
        n = len(req.shapes)
        if not n:
            return

        def one(i: int, shape: ShapeSolveRequest) -> Any:
            head = f"Special shape {i + 1} of {n} ({shape.name})"

            def say(message: str, fraction: float) -> None:
                self.progress.emit(f"{head}: {message}", fraction)

            return solve_shape(
                shape, req.solver, say, self.token, req.ccx_path, str(tmp / f"shape-{i}"), run_id
            )

        with ThreadPoolExecutor(max_workers=shape_workers(n, req.solver)) as pool:
            jobs = {pool.submit(one, i, shape): shape for i, shape in enumerate(req.shapes)}
            for job in as_completed(jobs):
                shape = jobs[job]
                try:
                    sim = job.result()
                except ShapeSolveError as exc:
                    if not self.token.cancelled:
                        self.shape_failed.emit(str(exc))
                    continue
                except Exception as exc:  # report it, go on with the other shapes
                    self.shape_failed.emit(
                        f"Shape {shape.name}: simulation failed: {type(exc).__name__}: {exc}"
                    )
                    continue
                self.shape_solved.emit(sim)
        if self.token.cancelled:
            self.failed.emit("run cancelled before every special shape was solved")

    def _preview(
        self, built: BuiltModel, span: tuple[float, float], prefix: str = "Preview"
    ) -> Any:
        """Preview solve; its progress fills ``span`` of the bar."""
        estimator: ConvergenceEstimator | None = None

        def report(p: SolverProgress) -> None:
            nonlocal estimator
            if estimator is None:
                estimator = ConvergenceEstimator(p.tolerance)
            est = estimator.update(p.elapsed, p.residual, p.iteration, p.max_iterations)
            when = est.describe()
            self.progress.emit(
                f"{prefix}: residual {p.residual:.1e} (target {p.tolerance:.0e}), "
                f"{format_duration(p.elapsed)} elapsed" + (f", {when}" if when else ""),
                span[0] + (span[1] - span[0]) * est.fraction,
            )

        return solve_preview(built, progress=report, cancel=self.token)

    def _form_finding(self, built: BuiltModel) -> np.ndarray | None:
        """Preview solve of the model CalculiX will verify, kept as its own run.

        CalculiX's tension-field passes converge from an equilibrium but not from the
        initial shape (``calculix_adapter.analysis``, *Warm start*), so a CalculiX run
        without a current preview of the same mesh starts with one. Returns its positions
        (m), or None (with the reason reported) when it did not converge.
        """
        result = self._preview(
            built, (BUILD_SHARE, FORM_FINDING_END), "Step 1 of 2, preview for the start"
        )
        record, arrays = run_record(result, built, self.request.fingerprints["simulation"])
        record.findings = [*built.findings, *record.findings]
        self.finished_run.emit(record, arrays)
        if self.token.cancelled:
            self.failed.emit("CalculiX run cancelled during the preview form finding")
            return None
        if not result.converged:
            self.failed.emit(
                "CalculiX run not started: the preview that finds its starting shape did "
                f"not converge ({result.status}); see that run's findings"
            )
            return None
        return np.asarray(result.positions, dtype=np.float64)

    def _calculix(
        self, built: BuiltModel, workdir: Path, start: np.ndarray, span: tuple[float, float]
    ) -> Any:
        from calculix_adapter import (
            CalculixCancelledError,
            CalculixProgress,
            CalculixSettings,
            run_calculix,
        )

        settings = CalculixSettings(executable=self.request.ccx_path)
        estimator = PassProgress(settings.residual_target, settings.max_passes)
        prefix = "Step 2 of 2, CalculiX" if span[0] >= FORM_FINDING_END else "CalculiX"

        def report(p: CalculixProgress) -> None:
            est = estimator.update(
                p.elapsed, p.pass_no, p.job, p.job_fraction, p.residual, p.pass_ended
            )
            residual = "-" if p.residual == float("inf") else f"{p.residual:.1e}"
            job = "done" if p.job == "done" else f"{p.job} job {p.job_fraction:.0%}"
            when = est.describe()
            self.progress.emit(
                f"{prefix} (ccx): pass {p.pass_no}, {job}, out-of-balance {residual} "
                f"(target {settings.residual_target:.0e}), {format_duration(p.elapsed)} "
                "elapsed" + (f", {when}" if when else ""),
                span[0] + (span[1] - span[0]) * est.fraction,
            )

        try:
            return run_calculix(
                built.model,
                settings,
                workdir=workdir,
                mesh_options={"target_edge_length_mm": built.mesh_mm},
                start_positions=start,
                progress=report,
                cancel=self.token,
            )
        except CalculixCancelledError:
            self.failed.emit("CalculiX run cancelled (ccx stopped; no result)")
            return None


class SimulationManager(QObject):
    """Starts runs, tracks the running one and knows whether ``ccx`` is installed."""

    started = Signal(str)
    progress = Signal(str, float)
    finished = Signal(object)  # RunRecord
    failed = Signal(str)
    calculixChanged = Signal()  # noqa: N815
    idle = Signal()  # the worker thread has ended

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.worker: SolveWorker | None = None
        self._session: object | None = None
        self.calculix_version: str | None = None
        self.calculix_message = ""
        self.last_message = ""
        self.last_run_started = 0.0
        #: Why shapes were left out of the last run (still being placed, no feed hole).
        self.skipped_shapes: list[str] = []
        self.detect_calculix()

    # -- CalculiX detection -------------------------------------------------------------

    def detect_calculix(self) -> bool:
        """Look for ``ccx`` (preferences path, ``$ENVELOPELAB_CCX``, then ``PATH``)."""
        try:
            from calculix_adapter import SETUP_MESSAGE, calculix_report, find_calculix
        except ImportError:  # the adapter is part of this project but optional
            self.calculix_version = None
            self.calculix_message = "CalculiX adapter is not installed."
            self.calculixChanged.emit()
            return False
        found = find_calculix(self.controller.prefs.ccx_path or None)
        if found is None:
            self.calculix_version = None
            self.calculix_message = (
                "CalculiX (ccx) was not found, so 'Run CalculiX' is disabled.\n\n"
                + calculix_report(self.controller.prefs.ccx_path or None)
                + "\n\n"
                + SETUP_MESSAGE
            )
        else:
            self.calculix_version = found.version
            self.calculix_message = f"CalculiX {found.version} found at {found.executable}"
        self.calculixChanged.emit()
        return found is not None

    @property
    def calculix_available(self) -> bool:
        """``ccx`` was found."""
        return self.calculix_version is not None

    # -- runs ---------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        """A solve is in progress."""
        return self.worker is not None and self.worker.isRunning()

    def start(self, solver: str) -> bool:
        """Start a preview or CalculiX run of the current design; False if refused."""
        session = self.controller.session
        if session is None or self.running:
            return False
        if solver == CALCULIX and not self.calculix_available:
            self.failed.emit(self.calculix_message)
            return False
        prefs = self.controller.prefs
        mesh = prefs.preview_mesh_mm if solver == PREVIEW else prefs.calculix_mesh_mm
        fingerprints = session.fingerprints()
        shapes, skipped = self._shape_requests()
        request = RunRequest(
            solver=solver,
            design=session.design.model_copy(deep=True),
            patterns=session.patterns.model_copy(deep=True),
            fingerprints=fingerprints,
            mesh_mm=mesh,
            ccx_path=prefs.ccx_path or None,
            start_positions=self._warm_start(solver, fingerprints["simulation"], mesh),
            shapes=shapes,
        )
        self.skipped_shapes = skipped
        # SQLite connections cannot cross threads: the worker gets an immutable copy.
        worker = SolveWorker(request, self.controller.fabrics.catalog())
        worker.progress.connect(self._progress)
        worker.built.connect(lambda built: self.controller.store_model(built, fingerprints))
        worker.finished_run.connect(self._finished)
        worker.shape_solved.connect(self._shape_finished)
        worker.shape_failed.connect(self._shape_failed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self.idle.emit)
        self.worker = worker
        self._session = session
        self.last_run_started = time.perf_counter()
        worker.start()
        self.started.emit(solver)
        if skipped:
            self.controller.message.emit("Special shapes not simulated: " + "; ".join(skipped))
        return True

    def _shape_requests(self) -> tuple[list[ShapeSolveRequest], list[str]]:
        """Solve requests of the shapes this run solves, and why the others are left out."""
        session, c = self.controller.session, self.controller
        requests: list[ShapeSolveRequest] = []
        skipped: list[str] = []
        if session is None:
            return requests, skipped
        for spec in session.state.shapes:
            result = c.shapes.result(spec.name)
            if result is None:
                skipped.append(f"shape {spec.name} is still being placed")
                continue
            if result.design is None:
                skipped.append(f"shape {spec.name} cannot be placed")
                continue
            if result.design.feed_hole is None and not result.design.extra_feed_holes:
                skipped.append(f"shape {spec.name} has no feed hole, so it cannot be fed")
                continue
            request = c.shape_solve_request(spec.name)
            if request is not None:
                requests.append(request)
        return requests, skipped

    def _warm_start(self, solver: str, fingerprint: str, mesh: float) -> np.ndarray | None:
        """CalculiX starts from a current preview result of the same model, when there is
        one (the result is still accepted only on CalculiX's own criteria)."""
        session = self.controller.session
        if solver != CALCULIX or session is None:
            return None
        for record in reversed(session.project.runs):
            if (
                record.solver == PREVIEW
                and record.converged
                and record.input_fingerprint == fingerprint
                and record.mesh_target_mm == mesh
            ):
                arrays = session.run_arrays(record.run_id)
                if arrays is not None:
                    return np.asarray(arrays["positions"])
        return None

    def cancel(self) -> None:
        """Cancel the running solve."""
        if self.worker is not None:
            self.worker.cancel()

    def wait(self, timeout_ms: int = 600_000) -> bool:
        """Block until the worker ends (tests and shutdown)."""
        if self.worker is None:
            return True
        return self.worker.wait(timeout_ms)

    def _progress(self, message: str, fraction: float) -> None:
        self.last_message = message
        self.progress.emit(message, fraction)

    def _finished(self, record: RunRecord, arrays: dict[str, np.ndarray]) -> None:
        session = self.controller.session
        if session is None or session is not self._session:
            self._failed("run finished after its project was closed; result discarded")
            return
        if session is not None:
            session.add_run(record, arrays)
            session.tracker.mark_built("simulation", record.input_fingerprint)
            self.controller.notify_artifacts()
        self.finished.emit(record)

    def _shape_finished(self, sim: ShapeSimulation) -> None:
        """Keep a special shape solved in this run with the project."""
        session, c = self.controller.session, self.controller
        if session is None or session is not self._session or sim.name not in c.shapes.keys:
            return  # the project was closed or the shape removed meanwhile
        c.shapes.simulations[sim.name] = sim
        if sim.arrays is not None:
            session.add_shape_run(sim.record, sim.arrays)
            sim.arrays = None
        c.shapes.updated.emit()

    def _shape_failed(self, message: str) -> None:
        self.last_message = message
        self.controller.message.emit(message)

    def _failed(self, message: str) -> None:
        self.last_message = message
        self.failed.emit(message)
