"""Project file: a design document with its pattern annotations, history and run records.

An EnvelopeLab *project* (``*.elproj``, format ``envelopelab.project`` version 2) is a
JSON file that wraps one design document (unchanged, in the design schema) with

* **pattern annotations** per panel row (printed label, grain direction, fabric zone,
  seam allowance override, notches, tape paths, feature locations, and an optional
  *manual override* of the finished outline);
* **named snapshots** and **design versions** (full copies of the design state);
* a **provenance log** (append-only record of flagged edits such as manual overrides);
* **run records** of preview and CalculiX solves (solver, convergence, residual, run time,
  mesh size, material sources, load case, design hash and the input fingerprint that
  decides whether the result is still current). Result arrays are kept next to the
  project in ``<name>.elproj.runs/<run_id>.npz``.
* **constraint locks** of the standard-gore editor;
* the **special shapes** placed on the envelope (domes, tubes, revolved and mesh shapes,
  :mod:`envelopelab.project.shapes`), part of the design state since version 2.

Version 1 files (no shapes) are read as version 2 files with no shapes (ADR-0020).

All lengths are in m, angles in degrees (pattern annotations only; a boundary format
for builders), temperatures in K and pressures in Pa.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from envelopelab.design.model import DesignDocument, load_design_document
from envelopelab.project.shapes import ShapeSpec

PROJECT_FORMAT: Literal["envelopelab.project"] = "envelopelab.project"
PROJECT_FORMAT_VERSION: Literal[2] = 2
#: Older versions :func:`load_project_text` still reads (see :func:`migrate_project_data`).
READABLE_FORMAT_VERSIONS: tuple[int, ...] = (1, 2)
PROJECT_SUFFIX = ".elproj"

NotchEdge = Literal["left", "right", "bottom", "top"]
SolverName = Literal["envelopelab-preview", "calculix"]

#: Display label per solver. The GUI shows these on every result.
SOLVER_LABELS: dict[str, str] = {
    "envelopelab-preview": "Preview (dynamic relaxation)",
    "calculix": "CalculiX verification",
}


def utc_now() -> datetime:
    """Current UTC time, rounded to the second."""
    return datetime.now(UTC).replace(microsecond=0)


class Notch(BaseModel):
    """A notch (match mark) on a panel edge.

    Attributes
    ----------
    edge : {"left", "right", "bottom", "top"}
        Finished edge that carries the notch.
    position : float
        Position along the edge from its lower or left end, fraction in [0, 1].
    """

    model_config = ConfigDict(extra="forbid")

    edge: NotchEdge
    position: float = Field(ge=0.0, le=1.0)


class TapePath(BaseModel):
    """A tape sewn onto a panel (not along a seam).

    Attributes
    ----------
    name : str
        Tape name.
    points : list of (float, float)
        Polyline in panel coordinates (x across, y up from the finished bottom seam), m.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    points: list[tuple[float, float]] = Field(min_length=2)


class FeatureLocation(BaseModel):
    """Where a design feature (vent, appendage hole, appliqué) sits on a panel.

    Attributes
    ----------
    feature : int
        Index into ``DesignDocument.features``.
    x, y : float
        Centre in panel coordinates, m.
    radius : float
        Finished radius of the opening or appliqué, m.
    """

    model_config = ConfigDict(extra="forbid")

    feature: int = Field(ge=0)
    x: float
    y: float
    radius: float = Field(gt=0.0)


class ManualOutline(BaseModel):
    """A finished panel outline edited by hand (a flagged manual override).

    Attributes
    ----------
    points : list of (float, float)
        Finished outline in panel coordinates, m, counter-clockwise.
    created : datetime
        When the override was made (UTC).
    reason : str
        Free text entered by the user or the editor that made the change.
    base_hash : str
        SHA-256 of the design geometry the override was drawn over.
    """

    model_config = ConfigDict(extra="forbid")

    points: list[tuple[float, float]] = Field(min_length=3)
    created: datetime
    reason: str = "manual edit in the 2D pattern editor"
    base_hash: str = ""


class RowPattern(BaseModel):
    """Pattern annotations of one panel row (every gore uses the same piece).

    Attributes
    ----------
    label_text : str, optional
        Printed label; default ``PANEL <letter> x<N>``.
    grain_angle_deg : float
        Warp direction, degrees counter-clockwise from the panel x axis (across the gore).
    zone : str, optional
        Material zone (key of ``DesignDocument.zones``); default the first zone.
    seam_allowance : float, optional
        Seam allowance of this row, m; default the first seam type's allowance.
    notches, tape_paths, feature_locations : list
        See :class:`Notch`, :class:`TapePath`, :class:`FeatureLocation`.
    manual_outline : ManualOutline, optional
        Manual override of the finished outline.
    """

    model_config = ConfigDict(extra="forbid")

    label_text: str | None = None
    grain_angle_deg: float = 0.0
    zone: str | None = None
    seam_allowance: float | None = Field(default=None, ge=0.0)
    notches: list[Notch] = Field(default_factory=list)
    tape_paths: list[TapePath] = Field(default_factory=list)
    feature_locations: list[FeatureLocation] = Field(default_factory=list)
    manual_outline: ManualOutline | None = None


class PatternSet(BaseModel):
    """Pattern annotations keyed by panel-row letter."""

    model_config = ConfigDict(extra="forbid")

    rows: dict[str, RowPattern] = Field(default_factory=dict)

    def row(self, letter: str) -> RowPattern:
        """Annotations of row ``letter`` (defaults when none were made)."""
        return self.rows.get(letter, RowPattern())


class ConstraintLocks(BaseModel):
    """Constraint locks of the standard-gore editor.

    A lock holds its value (m, m^3 or a count) from the moment it was switched on; edits
    of the profile are corrected to keep every locked quantity (see
    :func:`envelopelab.project.gore_design.apply_locks`).
    """

    model_config = ConfigDict(extra="forbid")

    height: float | None = Field(default=None, gt=0.0)
    volume: float | None = Field(default=None, gt=0.0)
    max_diameter: float | None = Field(default=None, gt=0.0)
    gore_count: int | None = Field(default=None, ge=3)


class DesignState(BaseModel):
    """Everything that is edited: the design document, its pattern annotations and the
    special shapes placed on it."""

    model_config = ConfigDict(extra="forbid")

    design: DesignDocument
    patterns: PatternSet = Field(default_factory=PatternSet)
    shapes: list[ShapeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_shape_names(self) -> DesignState:
        names = [s.name for s in self.shapes]
        if len(set(names)) != len(names):
            raise ValueError("special shape names must be unique")
        return self


class Snapshot(BaseModel):
    """A named copy of the design state."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    created: datetime
    state: DesignState
    content_hash: str


class DesignVersion(BaseModel):
    """A committed design version (``meta.version_id`` with its parent)."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    parent_id: str | None
    created: datetime
    message: str
    content_hash: str
    state: DesignState


class ProvenanceEntry(BaseModel):
    """One entry of the append-only provenance log."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    action: str
    target: str
    detail: str


class RunFinding(BaseModel):
    """A solver warning or error kept with a run record."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    message: str


class RunRecord(BaseModel):
    """Summary and provenance of one structural solve.

    Attributes
    ----------
    run_id : str
        Unique id (also the result file name).
    solver : {"envelopelab-preview", "calculix"}
        Solver identifier.
    solver_version : str
        Solver version.
    status : str
        ``converged`` or why the solve stopped.
    converged : bool
        True only when every convergence criterion was met.
    residual : float
        Final residual (see ``residual_measure``), dimensionless.
    residual_measure : str
        What the residual means for this solver.
    iterations : int
        Iterations (preview) or recorded CalculiX iterations.
    run_time : float
        Wall time, s.
    n_nodes, n_elements, n_tape_elements : int
        Mesh size.
    mesh_target_mm : float
        Target edge length of the mesh, mm (a boundary format).
    load_case : str
        Operating-condition label.
    material_sources : list of str
        Distinct source tags of the materials used.
    design_content_hash : str
        Design document hash at solve time.
    input_fingerprint : str
        Fingerprint of the ``simulation`` artifact at solve time.
    volume, lift, height, max_width : float
        m^3, N, m, m.
    findings : list of RunFinding
        Warnings and errors.
    manifest : dict
        Run manifest (git commit, dependency versions, seed, ...).
    result_file : str, optional
        Result arrays, relative to the project directory.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created: datetime
    solver: SolverName
    solver_version: str
    status: str
    converged: bool
    residual: float
    residual_measure: str
    iterations: int
    run_time: float
    n_nodes: int
    n_elements: int
    n_tape_elements: int
    mesh_target_mm: float
    load_case: str
    material_sources: list[str]
    design_content_hash: str
    input_fingerprint: str
    volume: float
    lift: float
    height: float
    max_width: float
    findings: list[RunFinding] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    result_file: str | None = None

    @property
    def solver_label(self) -> str:
        """Human-readable solver name."""
        return SOLVER_LABELS[self.solver]

    @property
    def error_count(self) -> int:
        """Number of error-level findings."""
        return sum(f.severity == "error" for f in self.findings)


class Project(BaseModel):
    """An EnvelopeLab project file (``envelopelab.project`` v2)."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["envelopelab.project"] = PROJECT_FORMAT
    format_version: Literal[2] = PROJECT_FORMAT_VERSION
    state: DesignState
    locks: ConstraintLocks = Field(default_factory=ConstraintLocks)
    snapshots: list[Snapshot] = Field(default_factory=list)
    versions: list[DesignVersion] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    runs: list[RunRecord] = Field(default_factory=list)


def state_to_data(state: DesignState) -> dict[str, Any]:
    """JSON data of a design state (design with its content hash)."""
    return {
        "design": state.design.with_updated_hash().model_dump(by_alias=True, mode="json"),
        "patterns": state.patterns.model_dump(mode="json"),
        "shapes": [s.model_dump(mode="json") for s in state.shapes],
    }


def state_from_data(data: dict[str, Any]) -> DesignState:
    """Design state from JSON data; the design content hash is checked."""
    design = load_design_document(json.dumps(data["design"]))
    return DesignState.model_validate(
        {
            "design": design,
            "patterns": PatternSet.model_validate(data["patterns"]),
            "shapes": data.get("shapes", []),
        }
    )


def migrate_project_data(raw: dict[str, Any]) -> dict[str, Any]:
    """Bring project file data of any readable version to the current version.

    Version 1 states have no ``shapes``; they read as states without special shapes.

    Raises
    ------
    ValueError
        For a version this release cannot read.
    """
    version = raw.get("format_version")
    if version not in READABLE_FORMAT_VERSIONS:
        raise ValueError(f"unsupported project format version {version!r}")
    if version == 1:
        states = [raw["state"]] + [
            i["state"] for k in ("snapshots", "versions") for i in raw.get(k, [])
        ]
        for state in states:
            state.setdefault("shapes", [])
    raw["format_version"] = PROJECT_FORMAT_VERSION
    return raw


def _project_to_data(project: Project) -> dict[str, Any]:
    data = project.model_dump(mode="json", by_alias=True)
    data["state"] = state_to_data(project.state)
    for snap, raw in zip(project.snapshots, data["snapshots"], strict=True):
        raw["state"] = state_to_data(snap.state)
    for version, raw in zip(project.versions, data["versions"], strict=True):
        raw["state"] = state_to_data(version.state)
    return data


def dump_project(project: Project) -> str:
    """Project file text (sorted, indented JSON)."""
    return json.dumps(_project_to_data(project), indent=2, sort_keys=True, ensure_ascii=False)


def load_project_text(text: str) -> Project:
    """Parse project file text.

    Raises
    ------
    ValueError
        For another format, an unsupported version or a design content-hash mismatch.
        Older readable versions are migrated (:func:`migrate_project_data`).
    """
    raw = json.loads(text)
    if raw.get("format") != PROJECT_FORMAT:
        raise ValueError(f"not an EnvelopeLab project (format {raw.get('format')!r})")
    raw = migrate_project_data(raw)
    raw["state"] = state_from_data(raw["state"])
    for key in ("snapshots", "versions"):
        for item in raw.get(key, []):
            item["state"] = state_from_data(item["state"])
    return Project.model_validate(raw)


def runs_dir(path: str | Path) -> Path:
    """Directory holding the result arrays of the project at ``path``."""
    p = Path(path)
    return p.with_name(p.name + ".runs")


def save_project(project: Project, path: str | Path) -> Path:
    """Write a project file atomically (write to a temporary file, then rename)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(dump_project(project), encoding="utf-8")
    tmp.replace(target)
    return target


def load_project(path: str | Path) -> Project:
    """Read a project file."""
    return load_project_text(Path(path).read_text(encoding="utf-8"))


def save_result_arrays(path: Path, arrays: dict[str, np.ndarray]) -> Path:
    """Write run result arrays (``.npz``, no pickles)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.savez_compressed(handle, **arrays)  # type: ignore[arg-type]
    return path


def load_result_arrays(path: Path) -> dict[str, np.ndarray]:
    """Read run result arrays written by :func:`save_result_arrays`."""
    with np.load(path, allow_pickle=False) as data:
        return {k: np.asarray(data[k]) for k in data.files}
