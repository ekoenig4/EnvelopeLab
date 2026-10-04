"""Special shapes of the open project, computed off the GUI thread.

Placing a shape on the envelope and flattening its skin takes from a fraction of a second
to a few seconds, far too long to do on every edit in the GUI thread. The
:class:`ShapeService` keeps, for every shape of the project, the result for its current
specification and envelope (a key from both), recomputes only the shapes whose key
changed, in a worker thread, and announces new results with ``updated``. A result
computed for an older key is dropped when it arrives.

Shape simulations (the shape's sub-model solved by the preview solver) run in their own
worker; their results are kept in memory for this session and are marked stale when the
shape or the envelope changes. Nothing here does engineering math: every number comes
from :mod:`envelopelab`.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal

from envelopelab.design.model import DesignDocument
from envelopelab.features.primitives import PrimitiveDesign, PrimitiveError
from envelopelab.project.model import PatternSet
from envelopelab.project.shapes import ShapeSpec, envelope_surface, shape_design


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
    """A solved shape sub-model (kept in memory for this session).

    Attributes
    ----------
    name : str
        Shape name.
    key : str
        Simulation key of the solve (stale when it differs from the current one, see
        :func:`simulation_key`).
    appendage : AppendageModel
        Sub-model.
    result : SimulationResult
        Preview-solver result.
    metrics : AppendageMetrics
        Heights (m), FoS (-), wrinkled fraction (-), chamber pressure (Pa).
    design : PrimitiveDesign
        The placed shape that was solved.
    """

    name: str
    key: str
    appendage: Any
    result: Any
    metrics: Any
    design: PrimitiveDesign


class _DesignWorker(QThread):
    """Places a batch of shapes on the envelope (pure functions of copies of the data)."""

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

    def run(self) -> None:  # noqa: D102 (QThread entry point)
        out: list[tuple[str, ShapeResult]] = []
        try:
            surface = envelope_surface(self.design, self.patterns)
        except Exception as exc:  # the envelope itself cannot be built
            message = f"the envelope cannot be built: {exc}"
            self.done.emit([(n, ShapeResult(k, None, message)) for n, k, _ in self.jobs])
            return
        for name, key, spec in self.jobs:
            try:
                out.append((name, ShapeResult(key, shape_design(spec, surface))))
            except (PrimitiveError, ValueError) as exc:
                out.append((name, ShapeResult(key, None, str(exc))))
            except Exception as exc:  # report everything to the GUI, never crash it
                detail = traceback.format_exception_only(type(exc), exc)[-1].strip()
                out.append((name, ShapeResult(key, None, f"internal error: {detail}")))
        self.done.emit(out)


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
            # One worker at a time: the newest request runs when the current one ends.
            self._queued = (design, patterns, jobs)
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
            jobs = [j for j in jobs if self.keys.get(j[0]) == j[1]]
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


class _SolveWorker(QThread):
    """Builds and solves one shape sub-model with the preview solver."""

    progress = Signal(str, float)
    solved = Signal(object)  # ShapeSimulation
    failed = Signal(str)

    def __init__(self, request: ShapeSolveRequest) -> None:
        super().__init__()
        self.request = request
        from envelopelab.solvers.dynamic_relaxation import CancellationToken

        self.token = CancellationToken()

    def run(self) -> None:  # noqa: D102 (QThread entry point)
        from envelopelab.features.builder import FeatureBuildError, build_appendage
        from envelopelab.features.metrics import appendage_metrics
        from envelopelab.features.primitives import primitive_appendage
        from envelopelab.project.simulation import (
            membrane_for_fabric,
            operating_conditions,
            tape_material,
        )
        from envelopelab.solvers.dynamic_relaxation import SolverProgress, solve
        from envelopelab.solvers.simulation import from_preview

        req = self.request
        label = f"Shape {req.name}"
        try:
            doc = req.document
            tapes = doc.tapes
            design = req.design
            z_mouth = float(design.surface.profile.z[0])
            conditions = operating_conditions(doc, z_mouth)
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
            self.progress.emit(f"{label}: building the sub-model ({req.mesh_mm:g} mm)", 0.0)
            appendage = build_appendage(spec, conditions, materials)

            def report(p: SolverProgress) -> None:
                self.progress.emit(
                    f"{label}: iteration {p.iteration}, residual {p.residual:.2e} "
                    f"(target {p.tolerance:.0e}), {p.elapsed:.0f} s",
                    p.fraction,
                )

            raw = solve(appendage.model, progress=report, cancel=self.token)
            if raw.convergence.status == "cancelled":
                self.failed.emit(f"{label}: simulation cancelled")
                return
            result = from_preview(appendage.model, raw)
            metrics = appendage_metrics(appendage, result)
            self.solved.emit(ShapeSimulation(req.name, req.key, appendage, result, metrics, design))
        except (FeatureBuildError, PrimitiveError, ValueError) as exc:
            self.failed.emit(f"{label}: not simulated: {exc}")
        except Exception as exc:  # the thread must report every failure to the GUI
            self.failed.emit(f"{label}: simulation failed: {type(exc).__name__}: {exc}")


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

    @property
    def running(self) -> bool:
        """A shape simulation is running."""
        return self._worker is not None

    def start(self, request: ShapeSolveRequest) -> bool:
        """Start a simulation; False when one is already running."""
        if self._worker is not None:
            return False
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
        """Block until no simulation runs."""
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
        if worker is not None:
            worker.deleteLater()
        sim, self._solved_sim = self._solved_sim, None
        if sim is not None and sim.name in self.service.keys:  # not removed meanwhile
            self.service.simulations[sim.name] = sim
            self.finished.emit(sim.name)
            self.service.updated.emit()
        self.idle.emit()
