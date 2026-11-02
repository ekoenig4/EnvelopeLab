"""Special shapes of the open project, computed off the GUI thread.

Placing a shape on the envelope and flattening its skin takes from a fraction of a second
to a few seconds, far too long to do on every edit in the GUI thread. The
:class:`ShapeService` keeps, for every shape of the project, the result for its current
specification and envelope (a key from both), recomputes only the shapes whose key
changed, in a worker thread, and announces new results with ``updated``. A result
computed for an older key is dropped when it arrives.

Shape simulations (the shape's sub-model, its skin sewn from the cut pieces, solved by the
preview solver) run in their own worker, one at a time. Each result is a run record and
the skin as solved (:mod:`envelopelab.project.shape_runs`), kept with the project; it is
marked stale when the shape or the envelope changes. Nothing here does engineering math:
every number comes from :mod:`envelopelab`.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal

from envelopelab.design.model import DesignDocument
from envelopelab.features.primitives import PrimitiveDesign, PrimitiveError
from envelopelab.features.scene import ShapeDisplay
from envelopelab.project.model import PatternSet, ShapeRunRecord
from envelopelab.project.shapes import (
    ShapeSpec,
    envelope_surface,
    feed_hole_clearance,
    shape_design,
)

if TYPE_CHECKING:
    from envelopelab.project.session import ProjectSession


def shape_key(spec: ShapeSpec, host_hash: str) -> str:
    """Key of a shape result: its specification and the envelope it sits on.

    ``host_hash`` identifies everything of the envelope a shape reads (geometry, rows and
    their fabrics); see ``WorkspaceController.shape_host_hash``.
    """
    text = json.dumps(spec.model_dump(mode="json"), sort_keys=True) + host_hash
    return sha256(text.encode("utf-8")).hexdigest()


def simulation_key(key: str, simulation_fingerprint: str) -> str:
    """Key of a shape simulation: the shape key and the envelope's simulation inputs
    (load case, materials, tapes)."""
    return sha256((key + simulation_fingerprint).encode("utf-8")).hexdigest()


@dataclass
class ShapeResult:
    """A shape's placed design (or why it could not be placed) for one key."""

    key: str
    design: PrimitiveDesign | None
    error: str | None = None


@dataclass
class ShapeSimulation:
    """A shape simulation: its record and the skin as solved, as sewn.

    Attributes
    ----------
    name : str
        Shape name.
    key : str
        Simulation key of the solve (stale when it differs from the current one, see
        :func:`simulation_key`).
    record : ShapeRunRecord
        Summary, metrics and provenance.
    display : ShapeDisplay
        The solved skin split into its pieces, with its seams and rim (envelope frame, m).
    arrays : dict of str to ndarray, optional
        Display arrays of a new solve, to be kept with the project (None once kept or for
        a simulation read from the project).
    """

    name: str
    key: str
    record: ShapeRunRecord
    display: ShapeDisplay
    arrays: dict[str, np.ndarray] | None = None


class _DesignWorker(QThread):
    """Places a batch of shapes on the envelope (pure functions of copies of the data).

    Each shape's result is announced as soon as it is placed, so the first shapes show
    while the others are still being placed. Setting ``stop`` (a newer request is waiting)
    ends the batch after the shape being placed.
    """

    done = Signal(object)  # list[tuple[str, ShapeResult]]

    def __init__(
        self,
        design: DesignDocument,
        patterns: PatternSet,
        jobs: list[tuple[str, str, ShapeSpec]],
    ) -> None:
        super().__init__()
        self.design = design
        self.patterns = patterns
        self.jobs = jobs
        #: Set from the GUI thread when the batch is out of date (a plain flag is enough:
        #: it is only read between shapes).
        self.stop = False

    def run(self) -> None:  # noqa: D102 (QThread entry point)
        try:
            surface = envelope_surface(self.design, self.patterns)
        except Exception as exc:  # the envelope itself cannot be built
            message = f"the envelope cannot be built: {exc}"
            self.done.emit([(n, ShapeResult(k, None, message)) for n, k, _ in self.jobs])
            return
        clearance = feed_hole_clearance(self.design, self.patterns)
        for name, key, spec in self.jobs:
            if self.stop:
                return
            try:
                result = ShapeResult(key, shape_design(spec, surface, clearance))
            except (PrimitiveError, ValueError) as exc:
                result = ShapeResult(key, None, str(exc))
            except Exception as exc:  # report everything to the GUI, never crash it
                detail = traceback.format_exception_only(type(exc), exc)[-1].strip()
                result = ShapeResult(key, None, f"internal error: {detail}")
            self.done.emit([(name, result)])


class ShapeService(QObject):
    """See module docstring."""

    updated = Signal()
    busyChanged = Signal(bool)  # noqa: N815 (Qt naming)

    def __init__(self) -> None:
        super().__init__()
        self.results: dict[str, ShapeResult] = {}
        self.keys: dict[str, str] = {}
        self.simulations: dict[str, ShapeSimulation] = {}
        self.simulation_fingerprint = ""
        self._worker: _DesignWorker | None = None
        self._queued: tuple[DesignDocument, PatternSet, list[tuple[str, str, ShapeSpec]]] | None = (
            None
        )

    @property
    def busy(self) -> bool:
        """A worker is placing shapes."""
        return self._worker is not None

    def reset(self) -> None:
        """Forget every result and simulation (another project was opened)."""
        self.keys, self.results, self.simulations = {}, {}, {}
        self._queued = None

    def restore(self, session: ProjectSession) -> None:
        """Take the shape simulations kept with ``session``'s project (those whose result
        file can be read); their status follows from their keys as usual."""
        from envelopelab.project.shape_runs import display_from_arrays

        for record in session.project.shape_runs:
            arrays = session.run_arrays(record.run_id)
            if arrays is None:
                continue
            self.simulations[record.shape] = ShapeSimulation(
                record.shape, record.simulation_key, record, display_from_arrays(arrays)
            )

    def sync(
        self,
        design: DesignDocument | None,
        patterns: PatternSet | None,
        shapes: list[ShapeSpec],
        host_hash: str,
        simulation_fingerprint: str = "",
    ) -> None:
        """Bring the results in line with the project's shapes (recompute what changed).

        Parameters
        ----------
        design, patterns : DesignDocument, PatternSet or None
            Current design state (None: no project).
        shapes : list of ShapeSpec
            The project's special shapes.
        host_hash : str
            Hash of the envelope inputs a shape reads (:func:`shape_key`).
        simulation_fingerprint : str
            Fingerprint of the envelope's simulation inputs (:func:`simulation_key`).
        """
        changed = simulation_fingerprint != self.simulation_fingerprint
        self.simulation_fingerprint = simulation_fingerprint
        if design is None or patterns is None or design.gores is None:
            if self.keys or self.results or changed:
                self.keys, self.results = {}, {}
                self.updated.emit()
            return
        keys = {s.name: shape_key(s, host_hash) for s in shapes}
        # Announce only real changes: every listener redraws on ``updated``.
        changed = changed or keys != self.keys
        self.keys = keys
        for name in list(self.results):
            if name not in self.keys:
                del self.results[name]
        jobs = [
            (s.name, self.keys[s.name], s)
            for s in shapes
            if self.results.get(s.name) is None or self.results[s.name].key != self.keys[s.name]
        ]
        if jobs:
            self._start(design, patterns, jobs)
        if changed:
            self.updated.emit()

    def _start(
        self, design: DesignDocument, patterns: PatternSet, jobs: list[tuple[str, str, ShapeSpec]]
    ) -> None:
        if self._worker is not None:
            # One worker at a time: the newest request runs when the current one ends,
            # which it does after its current shape (the rest of its batch is out of date).
            self._queued = (design, patterns, jobs)
            self._worker.stop = True
            return
        self._worker = _DesignWorker(design, patterns, jobs)
        self._worker.done.connect(self._finished)
        self._worker.finished.connect(self._worker_ended)
        self.busyChanged.emit(True)
        self._worker.start()

    def _finished(self, out: list[tuple[str, ShapeResult]]) -> None:
        for name, result in out:
            if self.keys.get(name) == result.key:
                self.results[name] = result
        self.updated.emit()

    def _worker_ended(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        if self._queued is not None:
            design, patterns, jobs = self._queued
            self._queued = None
            # Still wanted, and not placed meanwhile by the batch that just ended.
            jobs = [
                (name, key, spec)
                for name, key, spec in jobs
                if self.keys.get(name) == key
                and (name not in self.results or self.results[name].key != key)
            ]
            if jobs:
                self._start(design, patterns, jobs)
                return
        self.busyChanged.emit(False)

    def wait(self, timeout_ms: int = 120_000) -> bool:
        """Block until no worker runs (tests, closing the window)."""
        while self._worker is not None:
            if not self._worker.wait(timeout_ms):
                return False
            # Deliver the finished signals queued for this thread.
            QCoreApplication.processEvents()
        return True

    def result(self, name: str) -> ShapeResult | None:
        """Current result of shape ``name`` (None while it is being computed)."""
        r = self.results.get(name)
        return r if r is not None and r.key == self.keys.get(name) else None

    def simulation_status(self, name: str) -> str:
        """``none``, ``current`` or ``stale`` for the shape's last simulation."""
        sim = self.simulations.get(name)
        if sim is None:
            return "none"
        return "current" if sim.key == self.current_simulation_key(name) else "stale"

    def current_simulation_key(self, name: str) -> str | None:
        """Simulation key shape ``name`` would be solved with now (None: unknown shape)."""
        key = self.keys.get(name)
        return None if key is None else simulation_key(key, self.simulation_fingerprint)

    @property
    def pending(self) -> bool:
        """Some shape has no result for its current key yet."""
        return any(self.result(name) is None for name in self.keys)


@dataclass
class ShapeSolveRequest:
    """Everything a shape simulation needs (copied for the worker thread).

    Attributes
    ----------
    name, key : str
        Shape name and simulation key (:func:`simulation_key`).
    design : PrimitiveDesign
        The placed shape.
    document : DesignDocument
        The envelope's design (load case, tapes).
    host_fabric, skin_fabric : str
        Fabric ids of the envelope patch and of the skin.
    fabrics : FabricCatalog
        Immutable copy of the fabric library (safe in the worker thread).
    mesh_mm : float
        Target element size, mm.
    """

    name: str
    key: str
    design: PrimitiveDesign
    document: DesignDocument
    host_fabric: str
    skin_fabric: str
    fabrics: Any
    mesh_mm: float


class ShapeSolveError(Exception):
    """A shape simulation did not produce a result (the message says why)."""


#: Solver identifiers (as in envelope run records).
PREVIEW = "envelopelab-preview"
CALCULIX = "calculix"


def solve_shape(
    req: ShapeSolveRequest,
    solver: str = PREVIEW,
    progress: Callable[[str, float], None] | None = None,
    cancel: Any = None,
    ccx_path: str | None = None,
    workdir: str | None = None,
    envelope_run_id: str | None = None,
) -> ShapeSimulation:
    """Build and solve one shape sub-model (worker thread; no Qt).

    The skin is sewn from the shape's cut pieces
    (:func:`envelopelab.features.primitives.primitive_appendage`) and loaded with the
    envelope's load case. ``solver`` is the preview solver, or CalculiX started from a
    converged preview of the same sub-model (when that preview does not converge, it is
    returned as the result, with the reason in its findings).

    Raises
    ------
    ShapeSolveError
        When the sub-model cannot be built, or the solve is cancelled.
    """
    from envelopelab.features.builder import FeatureBuildError, build_appendage
    from envelopelab.features.metrics import appendage_metrics
    from envelopelab.features.primitives import primitive_appendage
    from envelopelab.project.model import RunFinding
    from envelopelab.project.shape_runs import display_from_arrays, shape_run_record
    from envelopelab.project.simulation import (
        membrane_for_fabric,
        operating_conditions,
        tape_material,
    )
    from envelopelab.solvers.dynamic_relaxation import SolverProgress, solve
    from envelopelab.solvers.simulation import from_preview

    label = f"Shape {req.name}"
    say = progress or (lambda _m, _f: None)
    try:
        doc = req.document
        tapes = doc.tapes
        design = req.design
        conditions = operating_conditions(doc, float(design.surface.profile.z[0]))
        spec = primitive_appendage(
            design,
            mesh_size=req.mesh_mm / 1000.0,
            load_tape=tape_material(tapes.vertical.tape_class, tapes.vertical.strength),
            row_tape=tape_material(tapes.horizontal.tape_class, tapes.horizontal.strength),
            rim_tape=tape_material(tapes.rim.tape_class, tapes.rim.strength),
            hem_tape=tape_material(tapes.hole.tape_class, tapes.hole.strength),
        )
        materials = {
            "host": membrane_for_fabric(req.host_fabric, req.fabrics),
            "skin": membrane_for_fabric(req.skin_fabric, req.fabrics),
        }
        say(f"{label}: building the sub-model ({req.mesh_mm:g} mm)", 0.0)
        appendage = build_appendage(spec, conditions, materials)
    except (FeatureBuildError, PrimitiveError, ValueError) as exc:
        raise ShapeSolveError(f"{label}: not simulated: {exc}") from exc

    def report(p: SolverProgress) -> None:
        say(
            f"{label}: preview iteration {p.iteration}, residual {p.residual:.2e} "
            f"(target {p.tolerance:.0e}), {p.elapsed:.0f} s",
            p.fraction,
        )

    raw = solve(appendage.model, progress=report, cancel=cancel)
    if raw.convergence.status == "cancelled":
        raise ShapeSolveError(f"{label}: simulation cancelled")
    result = from_preview(appendage.model, raw)
    note: str | None = None
    if solver == CALCULIX:
        if not result.converged:
            note = (
                "CalculiX not started: the preview that finds its starting shape did not "
                f"converge ({result.status})"
            )
        else:
            from calculix_adapter import CalculixCancelledError, CalculixSettings, run_calculix

            say(f"{label}: CalculiX from the preview equilibrium", 0.5)
            try:
                result = run_calculix(
                    appendage.model,
                    CalculixSettings(executable=ccx_path),
                    workdir=workdir,
                    start_positions=result.positions,
                    cancel=cancel,
                )
            except CalculixCancelledError as exc:
                raise ShapeSolveError(f"{label}: CalculiX cancelled (no result)") from exc
    metrics = appendage_metrics(appendage, result)
    record, arrays = shape_run_record(
        req.name,
        req.key,
        design,
        appendage,
        result,
        metrics,
        req.mesh_mm / 1000.0,
        doc.compute_content_hash(),
        envelope_run_id,
    )
    if note is not None:
        record.findings.append(
            RunFinding(code="calculix_not_started", severity="error", message=note)
        )
    return ShapeSimulation(req.name, req.key, record, display_from_arrays(arrays), arrays)


class _SolveWorker(QThread):
    """Solves one shape sub-model with the preview solver (Simulate shape)."""

    progress = Signal(str, float)
    solved = Signal(object)  # ShapeSimulation
    failed = Signal(str)

    def __init__(self, request: ShapeSolveRequest) -> None:
        super().__init__()
        self.request = request
        from envelopelab.solvers.dynamic_relaxation import CancellationToken

        self.token = CancellationToken()

    def run(self) -> None:  # noqa: D102 (QThread entry point)
        req = self.request
        try:
            self.solved.emit(solve_shape(req, PREVIEW, self.progress.emit, self.token))
        except ShapeSolveError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # the thread must report every failure to the GUI
            self.failed.emit(f"Shape {req.name}: simulation failed: {type(exc).__name__}: {exc}")


class ShapeSimulator(QObject):
    """Runs one shape simulation at a time (see :class:`ShapeService`)."""

    started = Signal(str)
    progress = Signal(str, float)
    finished = Signal(str)  # shape name; the result is in ``service.simulations``
    failed = Signal(str)
    idle = Signal()  # the worker thread has ended (after ``finished`` or ``failed``)

    def __init__(self, service: ShapeService) -> None:
        super().__init__()
        self.service = service
        self._worker: _SolveWorker | None = None
        self._solved_sim: ShapeSimulation | None = None
        self._next: ShapeSolveRequest | None = None
        #: The request being solved (None when idle).
        self.request: ShapeSolveRequest | None = None

    @property
    def running(self) -> bool:
        """A shape simulation is running (or one waits for the running one to stop)."""
        return self._worker is not None or self._next is not None

    def start(self, request: ShapeSolveRequest, replace: bool = False) -> bool:
        """Start a simulation.

        With ``replace`` a running simulation is cancelled and ``request`` starts as soon
        as it has stopped; otherwise nothing starts while one runs (returns False).
        """
        if self._worker is not None:
            if not replace:
                return False
            self._next = request
            self.cancel()
            return True
        self._next = None
        self.request = request
        worker = _SolveWorker(request)
        worker.progress.connect(self._progress)
        worker.failed.connect(self._failed)
        # Bound methods of this object: the slots run in the GUI thread (queued).
        worker.solved.connect(self._solved)
        worker.finished.connect(self._ended)
        self._worker = worker
        self.started.emit(request.name)
        worker.start()
        return True

    def cancel(self) -> None:
        """Ask the running simulation to stop."""
        if self._worker is not None:
            self._worker.token.cancel()

    def wait(self, timeout_ms: int = 600_000) -> bool:
        """Block until no simulation runs (a queued one included)."""
        while self._worker is not None:
            if not self._worker.wait(timeout_ms):
                return False
            QCoreApplication.processEvents()
        return True

    def _solved(self, sim: ShapeSimulation) -> None:
        # Announced once the thread has ended, so ``running`` is already False then.
        self._solved_sim = sim

    def _progress(self, message: str, fraction: float) -> None:
        self.progress.emit(message, fraction)

    def _failed(self, message: str) -> None:
        self.failed.emit(message)

    def _ended(self) -> None:
        worker, self._worker = self._worker, None
        self.request = None
        if worker is not None:
            worker.deleteLater()
        sim, self._solved_sim = self._solved_sim, None
        if sim is not None and sim.name in self.service.keys:  # not removed meanwhile
            self.service.simulations[sim.name] = sim
            self.finished.emit(sim.name)
            self.service.updated.emit()
        if self._next is not None:
            self.start(self._next)
            return
        self.idle.emit()
