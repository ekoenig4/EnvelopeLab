"""Qt-facing wrapper around a :class:`~envelopelab.project.session.ProjectSession`.

The controller owns the open session, turns session events into Qt signals, keeps the
derived data the panels show (live gore outputs, the last generated patterns, the last
built solver model, the placed special shapes, computed in a worker thread by
:class:`~envelopelab_app.shapes_service.ShapeService`) and reports refused edits. It
contains no engineering math: every number comes from :mod:`envelopelab`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from PySide6.QtCore import QObject, Signal

from envelopelab.design.model import DesignDocument
from envelopelab.features.metrics import REQUIRED_FOS
from envelopelab.features.primitives import EnvelopeSurface
from envelopelab.geometry.gore import PanelRow
from envelopelab.materials.repository import (
    Fabric,
    FabricLibraryError,
    FabricLibraryRepository,
    FabricValidationError,
    fabric_data,
    open_user_library,
)
from envelopelab.project import edits
from envelopelab.project.dependencies import ARTIFACTS, ArtifactStatus, canonical_hash
from envelopelab.project.gore_design import (
    DesignFinding,
    GoreOutputs,
    check_locks,
    design_findings,
    gore_outputs,
    panel_rows,
    seam_mismatches,
)
from envelopelab.project.model import RunRecord
from envelopelab.project.session import (
    EVENT_ARTIFACTS,
    EVENT_FILE,
    EVENT_PROVENANCE,
    EVENT_RUNS,
    EVENT_SNAPSHOTS,
    EVENT_STATE,
    ProjectSession,
)
from envelopelab.project.shapes import envelope_surface
from envelopelab.project.simulation import BuiltModel
from envelopelab.rigging import RiggingOutputs, rigging_polylines
from envelopelab_app.settings import Preferences
from envelopelab_app.shapes_service import ShapeService, ShapeSimulator

#: Input groups of the envelope a special shape reads (its key, see ``shape_host_hash``).
SHAPE_HOST_GROUPS = ("geometry", "row_zones", "materials")

T = TypeVar("T")


@dataclass
class PatternCache:
    """Patterns as last generated, with the fingerprint they were generated from."""

    rows: list[PanelRow]
    fingerprint: str


@dataclass
class ModelCache:
    """Solver model as last built (rest mesh), with its fingerprint."""

    built: BuiltModel
    fingerprint: str


class WorkspaceController(QObject):
    """See module docstring."""

    sessionChanged = Signal()  # noqa: N815 (Qt naming)
    stateChanged = Signal()  # noqa: N815
    artifactsChanged = Signal()  # noqa: N815
    runsChanged = Signal()  # noqa: N815
    fileChanged = Signal()  # noqa: N815
    snapshotsChanged = Signal()  # noqa: N815
    provenanceChanged = Signal()  # noqa: N815
    selectionChanged = Signal(str)  # noqa: N815
    editRejected = Signal(str)  # noqa: N815
    libraryChanged = Signal()  # noqa: N815
    shapesChanged = Signal()  # noqa: N815 (placed shapes or shape simulations changed)
    message = Signal(str)

    def __init__(self, prefs: Preferences, fabrics: FabricLibraryRepository | None = None) -> None:
        super().__init__()
        self.prefs = prefs
        #: Why the shared library file could not be opened (None: it is in use).
        self.library_error: str | None = None
        if fabrics is None:
            fabrics = self._open_library()
        self.fabrics = fabrics
        self.session: ProjectSession | None = None
        self.patterns_cache: PatternCache | None = None
        self.model_cache: ModelCache | None = None
        self.selection = ""
        self._outputs: GoreOutputs | None = None
        self._outputs_error: str | None = None
        #: Change number: bumped once per burst of signals, so a panel connected to
        #: several of them refreshes once per change (``envelopelab_app.refresh``).
        self.revision = 0
        #: Hidden panels wait until they are shown before refreshing. On in the
        #: interactive application; off for scripted windows that read hidden panels.
        self.defer_hidden = False
        self._derived: dict[str, tuple[int, Any]] = {}
        self.shapes = ShapeService()
        self.shapes.updated.connect(self._shapes_updated)
        self.shape_simulator = ShapeSimulator(self.shapes)

    def bump(self) -> None:
        """Start a new change (call before emitting the signals that announce it)."""
        self.revision += 1

    def _cached(self, key: str, compute: Callable[[], T]) -> T:
        """``compute()`` once per revision."""
        hit = self._derived.get(key)
        if hit is not None and hit[0] == self.revision:
            return hit[1]  # type: ignore[no-any-return]
        value = compute()
        self._derived[key] = (self.revision, value)
        return value

    def notify_artifacts(self) -> None:
        """Announce that built artifacts (patterns, models, runs) changed."""
        self.bump()
        self.artifactsChanged.emit()

    def _open_library(self) -> FabricLibraryRepository:
        path = self.prefs.resolved_material_library()
        try:
            return open_user_library(path)
        except (sqlite3.Error, FabricLibraryError, OSError) as exc:
            # Keep the application usable, but say plainly that nothing will be kept.
            self.library_error = (
                f"The fabric library {path} could not be opened ({exc}). A temporary library "
                "with the example fabrics is used; fabrics created now are not saved."
            )
            fallback = FabricLibraryRepository()
            fallback.seed_example_data()
            return fallback

    # -- fabric library -----------------------------------------------------------------

    def fabric_lookup(self, fabric_id: str) -> Mapping[str, Any] | None:
        """Library values of ``fabric_id`` for the session's fingerprints (None: missing)."""
        fabric = self.fabrics.fabric(fabric_id)
        return None if fabric is None else fabric_data(fabric)

    def add_fabric(self, fabric: Fabric) -> bool:
        """Create a fabric in the shared library; a refusal is reported (``editRejected``)."""
        return self._library_edit(self.fabrics.add_fabric, fabric)

    def update_fabric(self, fabric: Fabric) -> bool:
        """Change a user fabric in the shared library."""
        return self._library_edit(self.fabrics.update_fabric, fabric)

    def delete_fabric(self, fabric_id: str) -> bool:
        """Remove a user fabric from the shared library."""
        return self._library_edit(self.fabrics.delete_fabric, fabric_id)

    def zones_using(self, fabric_id: str) -> list[str]:
        """Zones of the open design that use ``fabric_id``."""
        design = self.design
        if design is None:
            return []
        return [zone for zone, fid in design.zones.items() if fid == fabric_id]

    def _library_edit(self, action: Callable[[Any], None], argument: Any) -> bool:
        try:
            action(argument)
        except (FabricValidationError, FabricLibraryError, sqlite3.Error) as exc:
            self.editRejected.emit(str(exc))
            return False
        if self.session is not None:
            # Results built from the old values become stale (fabric_properties group).
            self.session.refresh_fabrics()
        self.bump()
        self._refresh_outputs()
        self.libraryChanged.emit()
        self.stateChanged.emit()
        self.artifactsChanged.emit()
        return True

    # -- session ------------------------------------------------------------------------

    def set_session(self, session: ProjectSession | None) -> None:
        """Show another session (None: no project open)."""
        if self.session is not None:
            self.session.remove_listener(self._on_event)
        self.bump()
        self.session = session
        self.patterns_cache = None
        self.model_cache = None
        self.shapes.reset()
        if session is not None:
            session.set_fabric_lookup(self.fabric_lookup)
        self._refresh_outputs()
        self.sync_shapes()
        if session is not None:
            session.add_listener(self._on_event)
            if self.prefs.auto_regenerate_patterns:
                self.regenerate_patterns()
        self.sessionChanged.emit()
        self.stateChanged.emit()
        self.artifactsChanged.emit()
        self.runsChanged.emit()
        self.fileChanged.emit()
        self.snapshotsChanged.emit()

    def _on_event(self, event: str) -> None:
        self.bump()
        if event == EVENT_STATE:
            self._refresh_outputs()
            self.sync_shapes()
            if self.prefs.auto_regenerate_patterns:
                self.regenerate_patterns(emit=False)
            self.stateChanged.emit()
            self.artifactsChanged.emit()
            self.fileChanged.emit()
        elif event == EVENT_ARTIFACTS:
            self.sync_shapes()
            self.artifactsChanged.emit()
        elif event == EVENT_RUNS:
            self.runsChanged.emit()
            self.fileChanged.emit()
        elif event == EVENT_SNAPSHOTS:
            self.snapshotsChanged.emit()
            self.fileChanged.emit()
        elif event == EVENT_FILE:
            self.fileChanged.emit()
        elif event == EVENT_PROVENANCE:
            self.provenanceChanged.emit()
            self.fileChanged.emit()

    @property
    def design(self) -> DesignDocument | None:
        """Current design (None without a session)."""
        return None if self.session is None else self.session.design

    @property
    def is_gore(self) -> bool:
        """The open design is a standard-gore design."""
        return self.design is not None and self.design.gores is not None

    # -- edits --------------------------------------------------------------------------

    def attempt(self, action: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
        """Run an edit; a refused edit is reported (``editRejected``) and returns None."""
        try:
            return action(*args, **kwargs)
        except (ValueError, KeyError, IndexError) as exc:  # includes LockError, ValidationError
            text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            self.editRejected.emit(text)
            return None

    def edit(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Call ``envelopelab.project.edits.<name>(session, *args)`` via :meth:`attempt`."""
        if self.session is None:
            return None
        func = getattr(edits, name)
        if name in (
            "set_control_points",
            "move_control_point",
            "insert_control_point",
            "delete_control_point",
            "set_loft",
        ):
            kwargs.setdefault("keep_rows_fitted", self.prefs.keep_rows_fitted)
        result = self.attempt(func, self.session, *args, **kwargs)
        if name == "set_lock":
            self.bump()
            self.stateChanged.emit()
        return result

    def set_value(self, path: tuple[str | int, ...], value: Any) -> Any:
        """Set one design field (undoable)."""
        if self.session is None:
            return None
        return self.attempt(self.session.set_design_value, path, value)

    def set_row_pattern(self, letter: str, values: dict[str, Any], description: str) -> Any:
        """Update a row's pattern annotations (undoable)."""
        if self.session is None:
            return None
        return self.attempt(self.session.set_row_pattern, letter, values, description)

    def select(self, target: str) -> None:
        """Select a design element (e.g. ``row:B``, ``operating``, ``point:2``)."""
        self.selection = target
        self.bump()
        self.selectionChanged.emit(target)

    # -- special shapes -----------------------------------------------------------------

    def shape_host_hash(self) -> str:
        """Hash of the envelope inputs the special shapes are placed from."""
        if self.session is None:
            return ""
        hashes = self.session.group_hashes()
        return canonical_hash({g: hashes[g] for g in SHAPE_HOST_GROUPS})

    def envelope_surface(self) -> EnvelopeSurface | None:
        """Surface the special shapes are placed on (None: no gore design or not buildable),
        built once per change."""
        s = self.session
        if s is None or s.design.gores is None:
            return None

        def build() -> EnvelopeSurface | None:
            try:
                return envelope_surface(s.design, s.patterns)
            except ValueError:  # includes PrimitiveError
                return None

        return self._cached("envelope_surface", build)

    def sync_shapes(self) -> None:
        """Start placing the shapes whose specification or envelope changed (worker)."""
        s = self.session
        if s is None:
            self.shapes.sync(None, None, [], "")
            return
        self.shapes.sync(
            s.design,
            s.patterns,
            list(s.state.shapes),
            self.shape_host_hash(),
            s.fingerprints()["simulation"],
        )

    def _shapes_updated(self) -> None:
        s = self.session
        if s is not None and not s.state.shapes:
            s.tracker.forget("shapes")  # nothing to build, so never stale
        elif s is not None and not self.shapes.pending:
            s.tracker.mark_built("shapes", s.fingerprints()["shapes"])
        self.bump()
        self.shapesChanged.emit()

    def shape_findings(self) -> list[DesignFinding]:
        """Findings of the special shapes: placement errors, pattern checks, simulations."""
        s = self.session
        if s is None:
            return []
        out: list[DesignFinding] = []
        for spec in s.state.shapes:
            target = f"shape:{spec.name}"
            label = f"shape {spec.name}"
            result = self.shapes.result(spec.name)
            if result is None:
                out.append(DesignFinding("shape_pending", "info", f"{label}: being placed", target))
            elif result.design is None:
                out.append(
                    DesignFinding(
                        "shape_error", "error", f"{label} cannot be placed: {result.error}", target
                    )
                )
            else:
                for check in result.design.checks:
                    if check.severity != "info":
                        out.append(
                            DesignFinding(
                                f"shape_{check.name}",
                                check.severity,
                                f"{label}: {check.message}",
                                target,
                            )
                        )
            sim = self.shapes.simulations.get(spec.name)
            if sim is None:
                continue
            if self.shapes.simulation_status(spec.name) == "stale":
                out.append(
                    DesignFinding(
                        "shape_simulation_stale",
                        "warning",
                        f"{label}: simulation is STALE: the shape or the envelope changed",
                        target,
                    )
                )
            m = sim.metrics
            if not m.converged:
                out.append(
                    DesignFinding(
                        "shape_not_converged",
                        "error",
                        f"{label}: simulation did NOT converge ({m.status}); its results are "
                        "not final",
                        target,
                    )
                )
            for region, fos in sorted(m.fos.items()):
                if fos < REQUIRED_FOS:
                    out.append(
                        DesignFinding(
                            "shape_fos",
                            "error",
                            f"{label}: factor of safety of {region} is {fos:.2f}, below the "
                            f"required {REQUIRED_FOS:g}",
                            target,
                        )
                    )
        return out

    # -- derived data -------------------------------------------------------------------

    def _refresh_outputs(self) -> None:
        self._outputs = None
        self._outputs_error = None
        if self.session is None or self.session.design.gores is None:
            return
        try:
            self._outputs = gore_outputs(self.session.design, self.session.patterns, self.fabrics)
        except ValueError as exc:
            self._outputs_error = str(exc)

    @property
    def outputs(self) -> GoreOutputs | None:
        """Live outputs of the current gore design (None when they cannot be computed)."""
        return self._outputs

    @property
    def rigging(self) -> RiggingOutputs | None:
        """Parachute, red line, flying wires and turning vents of the current gore design."""
        return None if self._outputs is None else self._outputs.rigging

    def rigging_polylines(self) -> dict[str, list[Any]]:
        """3-D polylines of the rigging (m) for the 3D view; empty when unavailable."""
        design, out = self.design, self.rigging
        if design is None or out is None:
            return {}
        return rigging_polylines(design, out)

    @property
    def outputs_error(self) -> str | None:
        """Why the live outputs are missing."""
        return self._outputs_error

    def artifact_status(self, name: str) -> ArtifactStatus:
        """Staleness of an artifact of the current design."""
        if self.session is None:
            return "not built"
        return self.session.artifact_status(name)

    def artifact_statuses(self) -> dict[str, ArtifactStatus]:
        """Staleness of every artifact."""
        return {a.name: self.artifact_status(a.name) for a in ARTIFACTS}

    def rows(self) -> list[PanelRow]:
        """Panel rows of the current gore design, computed once per change.

        Raises
        ------
        ValueError
            When the rows cannot be generated (the message says why).
        """
        session = self.session
        if session is None or session.design.gores is None:
            return []

        def compute() -> tuple[list[PanelRow] | None, str]:
            try:
                return panel_rows(session.design, session.patterns), ""
            except ValueError as exc:
                return None, str(exc)

        rows, error = self._cached("rows", compute)
        if rows is None:
            raise ValueError(error)
        return rows

    def regenerate_patterns(self, emit: bool = True) -> bool:
        """Generate the flat patterns from the current design; False when it cannot."""
        if self.session is None or self.session.design.gores is None:
            return False
        try:
            rows = self.rows()
        except ValueError as exc:
            if emit:
                self.editRejected.emit(f"patterns not generated: {exc}")
            return False
        fingerprint = self.session.fingerprints()["patterns"]
        self.patterns_cache = PatternCache(rows, fingerprint)
        self.session.tracker.mark_built("patterns", fingerprint)
        if emit:
            self.notify_artifacts()
        return True

    def store_model(self, built: BuiltModel, fingerprints: dict[str, str]) -> None:
        """Keep a solver model built from the state with ``fingerprints``."""
        if self.session is None:
            return
        self.model_cache = ModelCache(built, fingerprints["rest_mesh"])
        self.session.tracker.mark_built("assembly", fingerprints["assembly"])
        self.session.tracker.mark_built("rest_mesh", fingerprints["rest_mesh"])
        self.notify_artifacts()

    def run_status(self, record: RunRecord) -> ArtifactStatus:
        """``current`` or ``stale`` for a run."""
        if self.session is None:
            return "stale"
        return self.session.run_status(record)

    def findings(self) -> list[DesignFinding]:
        """Everything the Validation panel shows, errors first (once per change)."""
        return list(self._cached("findings", self._findings))

    def _findings(self) -> list[DesignFinding]:
        if self.session is None:
            return []
        s = self.session
        out = list(design_findings(s.design, s.patterns))
        if self._outputs is not None:
            out += [f for f in self._outputs.findings if f.code != "rows"]
        if s.design.gores is not None:
            try:
                rows = self.rows()
            except ValueError:
                rows = []
            if rows:
                out += seam_mismatches(rows, s.patterns)
            try:
                for text in check_locks(s.design, s.project.locks):
                    out.append(DesignFinding("lock", "error", f"lock not met: {text}", "locks"))
            except ValueError:
                pass
            for letter, row in s.patterns.rows.items():
                if row.manual_outline is None:
                    continue
                out.append(
                    DesignFinding(
                        "manual_override",
                        "warning",
                        f"row {letter}: finished outline is a MANUAL OVERRIDE "
                        f"({row.manual_outline.reason}); it is not the generated geometry",
                        f"row:{letter}",
                    )
                )
                if edits.manual_override_is_outdated(s, letter):
                    out.append(
                        DesignFinding(
                            "manual_override_outdated",
                            "error",
                            f"row {letter}: the design geometry changed after the manual "
                            "override was drawn; review or remove the override",
                            f"row:{letter}",
                        )
                    )
        for name, status in self.artifact_statuses().items():
            if status == "stale":
                out.append(
                    DesignFinding(
                        "stale",
                        "warning",
                        f"{name.replace('_', ' ')} is stale: the design changed since it was built",
                        f"artifact:{name}",
                    )
                )
        for record in s.project.runs:
            label = f"{record.solver_label} run {record.run_id}"
            if self.run_status(record) == "stale":
                out.append(
                    DesignFinding(
                        "stale_run",
                        "warning",
                        f"{label} is STALE: its inputs differ from the current design",
                        f"run:{record.run_id}",
                    )
                )
            if not record.converged:
                out.append(
                    DesignFinding(
                        "not_converged",
                        "error",
                        f"{label} did NOT converge ({record.status}); its results are not final",
                        f"run:{record.run_id}",
                    )
                )
            for f in record.findings:
                if f.severity == "error" and f.code != "not_converged":
                    out.append(
                        DesignFinding(
                            f.code, "error", f"{label}: {f.message}", f"run:{record.run_id}"
                        )
                    )
        out += self.shape_findings()
        order = {"error": 0, "warning": 1, "info": 2}
        return sorted(out, key=lambda f: order[f.severity])
