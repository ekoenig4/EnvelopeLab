"""Background preview and CalculiX solves for the GUI.

A run captures the design state when it starts (so later edits cannot leak into it),
builds the solver model on a worker thread, solves it and hands the result back to the
GUI thread as a run record. The record carries the fingerprint of the state it solved, so
the result becomes *stale* as soon as a relevant input changes.

CalculiX (``ccx``) runs as an external process through ``calculix_adapter``; it is
detected at start and when the preferences change, and *Run CalculiX* is disabled with an
explanation when it is missing.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
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
from envelopelab_app.controller import WorkspaceController

PREVIEW = "envelopelab-preview"
CALCULIX = "calculix"


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


class SolveWorker(QThread):
    """Worker thread: build the model and run one solver."""

    progress = Signal(str, float)  # message, fraction in [0, 1]
    built = Signal(object)  # BuiltModel
    finished_run = Signal(object, object)  # RunRecord, arrays
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
                self.progress.emit(f"{label}: building model ({req.mesh_mm:g} mm mesh)", 0.0)
                built = build_solver_model(
                    req.design, req.patterns, Path(tmp) / "pack", req.mesh_mm, self.fabrics
                )
                self.built.emit(built)
                if self.token.cancelled:
                    self.failed.emit(f"{label} run cancelled")
                    return
                if req.solver == PREVIEW:
                    result = self._preview(built)
                else:
                    result = self._calculix(built, Path(tmp) / "ccx")
                if result is None:
                    return
                record, arrays = run_record(result, built, req.fingerprints["simulation"])
                record.findings = [*built.findings, *record.findings]
                self.finished_run.emit(record, arrays)
        except BuildError as exc:
            self.failed.emit(f"{label} run not started: {exc}")
        except Exception as exc:  # the thread must report every failure to the GUI
            self.failed.emit(f"{label} run failed: {type(exc).__name__}: {exc}")

    def _preview(self, built: BuiltModel) -> Any:
        def report(p: SolverProgress) -> None:
            self.progress.emit(
                f"Preview: iteration {p.iteration}, residual {p.residual:.2e} "
                f"(target {p.tolerance:.0e}), {p.elapsed:.0f} s",
                p.fraction,
            )

        return solve_preview(built, progress=report, cancel=self.token)

    def _calculix(self, built: BuiltModel, workdir: Path) -> Any:
        from calculix_adapter import (
            CalculixCancelledError,
            CalculixProgress,
            CalculixSettings,
            run_calculix,
        )

        def report(p: CalculixProgress) -> None:
            residual = "-" if p.residual == float("inf") else f"{p.residual:.2e}"
            self.progress.emit(
                f"CalculiX (ccx): pass {p.pass_no}/{p.max_passes}, {p.job} job, "
                f"out-of-balance {residual}, {p.elapsed:.0f} s",
                p.fraction,
            )

        try:
            return run_calculix(
                built.model,
                CalculixSettings(executable=self.request.ccx_path),
                workdir=workdir,
                mesh_options={"target_edge_length_mm": built.mesh_mm},
                start_positions=self.request.start_positions,
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
        self.detect_calculix()

    # -- CalculiX detection -------------------------------------------------------------

    def detect_calculix(self) -> bool:
        """Look for ``ccx`` (preferences path, ``$ENVELOPELAB_CCX``, then ``PATH``)."""
        try:
            from calculix_adapter import SETUP_MESSAGE, find_calculix
        except ImportError:  # the adapter is part of this project but optional
            self.calculix_version = None
            self.calculix_message = "CalculiX adapter is not installed."
            self.calculixChanged.emit()
            return False
        found = find_calculix(self.controller.prefs.ccx_path or None)
        if found is None:
            self.calculix_version = None
            self.calculix_message = (
                "CalculiX (ccx) is not installed, so 'Run CalculiX' is disabled.\n" + SETUP_MESSAGE
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
        request = RunRequest(
            solver=solver,
            design=session.design.model_copy(deep=True),
            patterns=session.patterns.model_copy(deep=True),
            fingerprints=fingerprints,
            mesh_mm=mesh,
            ccx_path=prefs.ccx_path or None,
            start_positions=self._warm_start(solver, fingerprints["simulation"], mesh),
        )
        # SQLite connections cannot cross threads: the worker gets an immutable copy.
        worker = SolveWorker(request, self.controller.fabrics.catalog())
        worker.progress.connect(self._progress)
        worker.built.connect(lambda built: self.controller.store_model(built, fingerprints))
        worker.finished_run.connect(self._finished)
        worker.failed.connect(self._failed)
        worker.finished.connect(self.idle.emit)
        self.worker = worker
        self._session = session
        self.last_run_started = time.perf_counter()
        worker.start()
        self.started.emit(solver)
        return True

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

    def _failed(self, message: str) -> None:
        self.last_message = message
        self.failed.emit(message)
