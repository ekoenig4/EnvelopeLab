"""An open project: the current design state, its command history and artifact staleness.

:class:`ProjectSession` is the model behind the desktop application (and usable from
scripts). Every change of the design state goes through the
:class:`~envelopelab.commands.CommandStack` as a :class:`StateCommand`, which stores the
state before and after the edit, so undo and redo restore exact states and the history
can be replayed to any point. Artifact staleness is decided by fingerprints
(:mod:`envelopelab.project.dependencies`), never by the order of edits.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from envelopelab.commands import Command, CommandStack
from envelopelab.design.model import DesignDocument
from envelopelab.project.dependencies import (
    ArtifactStatus,
    ArtifactTracker,
    changed_groups,
    fingerprints,
    group_hashes,
    input_groups,
)
from envelopelab.project.model import (
    DesignState,
    DesignVersion,
    PatternSet,
    Project,
    ProvenanceEntry,
    RunRecord,
    Snapshot,
    load_project,
    load_result_arrays,
    runs_dir,
    save_project,
    save_result_arrays,
    utc_now,
)

#: Session events passed to listeners.
EVENT_STATE = "state"  # design state changed (edit, undo, redo)
EVENT_ARTIFACTS = "artifacts"  # an artifact was built or forgotten
EVENT_RUNS = "runs"  # a run was added or removed
EVENT_SNAPSHOTS = "snapshots"  # snapshots or versions changed
EVENT_FILE = "file"  # saved, opened or path changed
EVENT_PROVENANCE = "provenance"

Listener = Callable[[str], None]
Mutator = Callable[[dict[str, Any], dict[str, Any]], None]


class StateCommand(Command):
    """Replace the design state; undo restores the previous one.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    before, after : DesignState
        States before and after the edit.
    description : str
        History text.
    provenance : (str, str, str), optional
        ``(action, target, detail)`` logged on execute (and as ``undo <action>`` on undo).
    """

    def __init__(
        self,
        session: ProjectSession,
        before: DesignState,
        after: DesignState,
        description: str,
        provenance: tuple[str, str, str] | None = None,
    ) -> None:
        self._session = session
        self._before = before
        self._after = after
        self._description = description
        self._provenance = provenance

    @property
    def description(self) -> str:
        return self._description

    def execute(self) -> None:
        self._session._set_state(self._after)
        if self._provenance is not None:
            self._session.log(*self._provenance)

    def undo(self) -> None:
        self._session._set_state(self._before)
        if self._provenance is not None:
            action, target, detail = self._provenance
            self._session.log(f"undo {action}", target, detail)


def _state_data(state: DesignState) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        state.design.model_dump(by_alias=True, mode="json"),
        state.patterns.model_dump(mode="json"),
    )


def _state_from(design: dict[str, Any], patterns: dict[str, Any]) -> DesignState:
    doc = DesignDocument.model_validate(design)
    return DesignState(design=doc, patterns=PatternSet.model_validate(patterns))


def _set_path(data: Any, path: Sequence[str | int], value: Any) -> None:
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _get_path(data: Any, path: Sequence[str | int]) -> Any:
    for key in path:
        data = data[key]
    return data


class ProjectSession:
    """An open project (see module docstring).

    Parameters
    ----------
    project : Project
        Project to edit.
    path : str or Path, optional
        Where it was loaded from / will be saved to.
    """

    def __init__(self, project: Project, path: str | Path | None = None) -> None:
        self.project = project
        self.path: Path | None = Path(path) if path is not None else None
        self.stack = CommandStack()
        self._listeners: list[Listener] = []
        self._hashes: dict[str, str] = {}
        self._fingerprints: dict[str, str] = {}
        self._refresh_hashes()
        self.tracker = ArtifactTracker(lambda: self._fingerprints)
        self._saved_hashes = dict(self._hashes)
        self._aux_dirty = False
        self._saved_runs = {r.run_id for r in project.runs}
        self._arrays: dict[str, dict[str, np.ndarray]] = {}
        self._pending_arrays: dict[str, dict[str, np.ndarray]] = {}
        # Listeners hear about a state change only after the stack is updated, so that
        # the history they read includes the command that changed the state.
        self.stack.add_listener(lambda: self._emit(EVENT_STATE))

    # -- construction -------------------------------------------------------------------

    @classmethod
    def new(cls, design: DesignDocument) -> ProjectSession:
        """Session for a new, unsaved project around ``design``."""
        return cls(Project(state=DesignState(design=design)))

    @classmethod
    def open(cls, path: str | Path) -> ProjectSession:
        """Open a project file."""
        return cls(load_project(path), path)

    # -- listeners ----------------------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        """Call ``listener(event)`` after every change (see the ``EVENT_*`` constants)."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        """Stop notifying ``listener``."""
        self._listeners.remove(listener)

    def _emit(self, event: str) -> None:
        for listener in list(self._listeners):
            listener(event)

    # -- state --------------------------------------------------------------------------

    @property
    def state(self) -> DesignState:
        """Current design state."""
        return self.project.state

    @property
    def design(self) -> DesignDocument:
        """Current design document."""
        return self.project.state.design

    @property
    def patterns(self) -> PatternSet:
        """Current pattern annotations."""
        return self.project.state.patterns

    def _refresh_hashes(self) -> None:
        design, patterns = _state_data(self.project.state)
        self._hashes = group_hashes(input_groups(design, patterns))
        self._fingerprints = fingerprints(self._hashes)

    def _set_state(self, state: DesignState) -> None:
        self.project.state = state
        self._refresh_hashes()

    def content_hash(self) -> str:
        """Content hash of the current design document."""
        return self.design.compute_content_hash()

    def group_hashes(self) -> dict[str, str]:
        """Hash of every input group of the current state."""
        return dict(self._hashes)

    def fingerprints(self) -> dict[str, str]:
        """Fingerprint of every artifact for the current state."""
        return dict(self._fingerprints)

    # -- editing ------------------------------------------------------------------------

    def apply_state(
        self,
        state: DesignState,
        description: str,
        provenance: tuple[str, str, str] | None = None,
        stamp: bool = True,
    ) -> bool:
        """Replace the design state as one undoable command.

        Parameters
        ----------
        state : DesignState
            New state.
        description : str
            History text.
        provenance : (str, str, str), optional
            Provenance entry for flagged edits.
        stamp : bool
            Set ``meta.modified`` to now (an edit). False keeps the state's own metadata,
            so that restoring a snapshot or version reproduces its content hash exactly.

        Returns
        -------
        bool
            False (and no history entry) when the new state equals the current one.
        """
        before = self.project.state
        design_b, patterns_b = _state_data(before)
        design_a, patterns_a = _state_data(state)
        if stamp:
            design_b["meta"]["modified"] = design_a["meta"]["modified"] = None
        if design_b == design_a and patterns_b == patterns_a:
            return False
        after = state.model_copy(deep=True)
        if stamp:
            after.design.meta.modified = utc_now()
        after.design.meta.content_hash = after.design.compute_content_hash()
        self.stack.do(StateCommand(self, before, after, description, provenance))
        return True

    def edit(
        self,
        description: str,
        mutate: Mutator,
        provenance: tuple[str, str, str] | None = None,
    ) -> bool:
        """Edit JSON copies of the design and pattern data, validate and apply.

        Parameters
        ----------
        description : str
            History text.
        mutate : callable
            ``mutate(design_data, patterns_data)`` changes the dictionaries in place.
        provenance : (str, str, str), optional
            Provenance entry for flagged edits.

        Returns
        -------
        bool
            Whether the state changed.

        Raises
        ------
        ValueError
            When the edited data is not a valid design (nothing is changed).
        """
        design, patterns = _state_data(self.project.state)
        design, patterns = copy.deepcopy(design), copy.deepcopy(patterns)
        mutate(design, patterns)
        return self.apply_state(_state_from(design, patterns), description, provenance)

    def set_design_value(
        self, path: Sequence[str | int], value: Any, description: str | None = None
    ) -> bool:
        """Set one design field (``path`` into the JSON data, e.g. ``("operating",
        "internal_temperature")``) as an undoable command."""

        def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
            _set_path(design, path, value)

        label = ".".join(str(p) for p in path)
        return self.edit(description or f"Set {label}", mutate)

    def design_value(self, path: Sequence[str | int]) -> Any:
        """Read one design field from the JSON data."""
        return _get_path(self.design.model_dump(by_alias=True, mode="json"), path)

    def set_row_pattern(
        self,
        letter: str,
        values: Mapping[str, Any],
        description: str | None = None,
        provenance: tuple[str, str, str] | None = None,
    ) -> bool:
        """Update pattern annotations of row ``letter`` as an undoable command."""

        def mutate(_design: dict[str, Any], patterns: dict[str, Any]) -> None:
            row = patterns["rows"].setdefault(letter, {})
            row.update(values)

        keys = ", ".join(values)
        return self.edit(description or f"Row {letter}: set {keys}", mutate, provenance)

    def undo(self) -> bool:
        """Undo the last edit."""
        return self.stack.undo()

    def redo(self) -> bool:
        """Redo the last undone edit."""
        return self.stack.redo()

    # -- dirty state --------------------------------------------------------------------

    @property
    def is_dirty(self) -> bool:
        """Unsaved changes (edits, runs, snapshots or versions)."""
        return self._aux_dirty or self._hashes != self._saved_hashes or not self.stack.is_clean

    def unsaved_runs(self) -> list[str]:
        """Ids of runs added or removed since the last save."""
        ids = {r.run_id for r in self.project.runs}
        return sorted(ids ^ self._saved_runs)

    def mark_aux_dirty(self) -> None:
        """Record an unsaved change outside the design state (locks, settings)."""
        self._aux_dirty = True
        self._emit(EVENT_FILE)

    def unsaved_groups(self) -> set[str]:
        """Input groups that differ from the saved file."""
        return changed_groups(self._saved_hashes, self._hashes)

    # -- artifacts ----------------------------------------------------------------------

    def artifact_status(self, name: str) -> ArtifactStatus:
        """``current``, ``stale`` or ``not built``."""
        return self.tracker.status(name)

    def mark_built(self, name: str, fingerprint: str | None = None) -> None:
        """Record that ``name`` was built from the current state (or ``fingerprint``)."""
        self.tracker.mark_built(name, fingerprint)
        self._emit(EVENT_ARTIFACTS)

    # -- provenance ---------------------------------------------------------------------

    def log(self, action: str, target: str, detail: str) -> None:
        """Append to the provenance log."""
        self.project.provenance.append(
            ProvenanceEntry(timestamp=utc_now(), action=action, target=target, detail=detail)
        )
        self._aux_dirty = True
        self._emit(EVENT_PROVENANCE)

    # -- snapshots and versions ---------------------------------------------------------

    def create_snapshot(self, name: str) -> Snapshot:
        """Save the current state under ``name`` (replacing a snapshot of that name)."""
        snap = Snapshot(
            name=name,
            created=utc_now(),
            state=self.state.model_copy(deep=True),
            content_hash=self.content_hash(),
        )
        self.project.snapshots = [s for s in self.project.snapshots if s.name != name]
        self.project.snapshots.append(snap)
        self._aux_dirty = True
        self._emit(EVENT_SNAPSHOTS)
        return snap

    def restore_snapshot(self, name: str) -> bool:
        """Make snapshot ``name`` the current state (undoable)."""
        snap = next((s for s in self.project.snapshots if s.name == name), None)
        if snap is None:
            raise KeyError(f"no snapshot {name!r}")
        return self.apply_state(
            snap.state.model_copy(deep=True), f"Restore snapshot {name}", stamp=False
        )

    def delete_snapshot(self, name: str) -> None:
        """Remove snapshot ``name``."""
        self.project.snapshots = [s for s in self.project.snapshots if s.name != name]
        self._aux_dirty = True
        self._emit(EVENT_SNAPSHOTS)

    def commit_version(self, message: str) -> DesignVersion:
        """Start a new design version: ``meta.version_id`` gets a new id whose parent is
        the current one, and a copy of the state is recorded."""
        parent = self.design.meta.version_id
        new_id = f"v{len(self.project.versions) + 2}-{uuid.uuid4().hex[:8]}"

        def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
            design["meta"]["version_id"] = new_id
            design["meta"]["parent_id"] = parent

        self.edit(f"Commit version {new_id}", mutate)
        version = DesignVersion(
            version_id=new_id,
            parent_id=parent,
            created=utc_now(),
            message=message,
            content_hash=self.content_hash(),
            state=self.state.model_copy(deep=True),
        )
        self.project.versions.append(version)
        self._aux_dirty = True
        self._emit(EVENT_SNAPSHOTS)
        return version

    def checkout_version(self, version_id: str) -> bool:
        """Make a recorded version the current state (undoable)."""
        version = next((v for v in self.project.versions if v.version_id == version_id), None)
        if version is None:
            raise KeyError(f"no version {version_id!r}")
        return self.apply_state(
            version.state.model_copy(deep=True), f"Check out {version_id}", stamp=False
        )

    # -- runs ---------------------------------------------------------------------------

    def add_run(self, record: RunRecord, arrays: dict[str, np.ndarray] | None = None) -> None:
        """Keep a run record (and its result arrays, written with the project)."""
        self.project.runs.append(record)
        if arrays is not None:
            self._arrays[record.run_id] = arrays
            self._pending_arrays[record.run_id] = arrays
        self._aux_dirty = True
        self._emit(EVENT_RUNS)

    def remove_run(self, run_id: str) -> None:
        """Forget a run."""
        self.project.runs = [r for r in self.project.runs if r.run_id != run_id]
        self._arrays.pop(run_id, None)
        self._pending_arrays.pop(run_id, None)
        self._aux_dirty = True
        self._emit(EVENT_RUNS)

    def run_status(self, record: RunRecord) -> ArtifactStatus:
        """``current`` when the run's inputs equal the current design's, else ``stale``."""
        return (
            "current" if record.input_fingerprint == self._fingerprints["simulation"] else ("stale")
        )

    def run_arrays(self, run_id: str) -> dict[str, np.ndarray] | None:
        """Result arrays of a run (loaded from the project's run directory on demand)."""
        if run_id in self._arrays:
            return self._arrays[run_id]
        record = next((r for r in self.project.runs if r.run_id == run_id), None)
        if record is None or record.result_file is None or self.path is None:
            return None
        file = self.path.parent / record.result_file
        if not file.is_file():
            return None
        self._arrays[run_id] = load_result_arrays(file)
        return self._arrays[run_id]

    # -- files --------------------------------------------------------------------------

    def save(self, path: str | Path | None = None) -> Path:
        """Write the project (and new result arrays) and mark it clean."""
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("no file name: use save(path)")
        folder = runs_dir(target)
        moved = self.path is not None and target != self.path
        for record in self.project.runs:
            arrays = self._pending_arrays.get(record.run_id)
            if arrays is None and moved:
                arrays = self.run_arrays(record.run_id)
            if arrays is None:
                continue
            file = folder / f"{record.run_id}.npz"
            save_result_arrays(file, arrays)
            record.result_file = str(file.relative_to(target.parent))
        self._pending_arrays.clear()
        save_project(self.project, target)
        self.path = target
        self._saved_hashes = dict(self._hashes)
        self._saved_runs = {r.run_id for r in self.project.runs}
        self._aux_dirty = False
        self.stack.set_clean()
        self._emit(EVENT_FILE)
        return target
