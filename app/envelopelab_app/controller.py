"""Qt-facing wrapper around a :class:`~envelopelab.project.session.ProjectSession`.

The controller owns the open session, turns session events into Qt signals, keeps the
derived data the panels show (live gore outputs, the last generated patterns, the last
built solver model) and reports refused edits. It contains no engineering math: every
number comes from :mod:`envelopelab`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from PySide6.QtCore import QObject, Signal

from envelopelab.design.model import DesignDocument
from envelopelab.geometry.gore import PanelRow
from envelopelab.geometry.parachute import ParachutePieces
from envelopelab.materials.repository import FabricLibraryRepository
from envelopelab.project import edits
from envelopelab.project.dependencies import ARTIFACTS, ArtifactStatus
from envelopelab.project.gore_design import (
    DesignFinding,
    GoreOutputs,
    check_locks,
    design_findings,
    design_parachute,
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
from envelopelab.project.simulation import BuiltModel
from envelopelab_app.settings import Preferences

T = TypeVar("T")


@dataclass
class PatternCache:
    """Patterns as last generated, with the fingerprint they were generated from."""

    rows: list[PanelRow]
    fingerprint: str
    parachute: ParachutePieces | None = None


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
    message = Signal(str)

    def __init__(self, prefs: Preferences, fabrics: FabricLibraryRepository | None = None) -> None:
        super().__init__()
        self.prefs = prefs
        if fabrics is None:
            fabrics = FabricLibraryRepository()
            fabrics.seed_example_data()
        self.fabrics = fabrics
        self.session: ProjectSession | None = None
        self.patterns_cache: PatternCache | None = None
        self.model_cache: ModelCache | None = None
        self.selection = ""
        self._outputs: GoreOutputs | None = None
        self._outputs_error: str | None = None

    # -- session ------------------------------------------------------------------------

    def set_session(self, session: ProjectSession | None) -> None:
        """Show another session (None: no project open)."""
        if self.session is not None:
            self.session.remove_listener(self._on_event)
        self.session = session
        self.patterns_cache = None
        self.model_cache = None
        self._refresh_outputs()
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
        if event == EVENT_STATE:
            self._refresh_outputs()
            if self.prefs.auto_regenerate_patterns:
                self.regenerate_patterns(emit=False)
            self.stateChanged.emit()
            self.artifactsChanged.emit()
            self.fileChanged.emit()
        elif event == EVENT_ARTIFACTS:
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
        ):
            kwargs.setdefault("keep_rows_fitted", self.prefs.keep_rows_fitted)
        result = self.attempt(func, self.session, *args, **kwargs)
        if name == "set_lock":
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
        self.selectionChanged.emit(target)

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

    def regenerate_patterns(self, emit: bool = True) -> bool:
        """Generate the flat patterns from the current design; False when it cannot."""
        if self.session is None or self.session.design.gores is None:
            return False
        try:
            rows = panel_rows(self.session.design, self.session.patterns)
        except ValueError as exc:
            if emit:
                self.editRejected.emit(f"patterns not generated: {exc}")
            return False
        try:
            parachute = design_parachute(self.session.design, self.session.patterns)
        except ValueError as exc:  # an invalid override: the rows are still drawn
            parachute = None
            if emit:
                self.editRejected.emit(f"parachute not generated: {exc}")
        fingerprint = self.session.fingerprints()["patterns"]
        self.patterns_cache = PatternCache(rows, fingerprint, parachute)
        self.session.tracker.mark_built("patterns", fingerprint)
        if emit:
            self.artifactsChanged.emit()
        return True

    def store_model(self, built: BuiltModel, fingerprints: dict[str, str]) -> None:
        """Keep a solver model built from the state with ``fingerprints``."""
        if self.session is None:
            return
        self.model_cache = ModelCache(built, fingerprints["rest_mesh"])
        self.session.tracker.mark_built("assembly", fingerprints["assembly"])
        self.session.tracker.mark_built("rest_mesh", fingerprints["rest_mesh"])
        self.artifactsChanged.emit()

    def run_status(self, record: RunRecord) -> ArtifactStatus:
        """``current`` or ``stale`` for a run."""
        if self.session is None:
            return "stale"
        return self.session.run_status(record)

    def findings(self) -> list[DesignFinding]:
        """Everything the Validation panel shows, errors first."""
        if self.session is None:
            return []
        s = self.session
        out = list(design_findings(s.design, s.patterns))
        if self._outputs is not None:
            out += [f for f in self._outputs.findings if f.code != "rows"]
        if s.design.gores is not None:
            try:
                rows = panel_rows(s.design, s.patterns)
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
        order = {"error": 0, "warning": 1, "info": 2}
        return sorted(out, key=lambda f: order[f.severity])
