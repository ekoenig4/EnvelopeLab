"""Configurable DXF pattern import.

Flat patterns are read from DXF files with ezdxf and sorted into *pieces* using a
per-build-pack YAML mapping file (format documented in
``docs/formats/pattern-import-mapping.md``). The mapping says which DXF layers carry cut
lines, sew lines, dimensions, feature marks, tape lines, match marks, notches, grain
arrows and labels, and how panel labels are parsed (regular expressions). Nothing about a
particular build pack is encoded here.

Units: DXF coordinates are converted to m on read; mapping lengths are given in mm (the
unit patterns are drawn in) and converted to m by the model properties.

Every imported entity keeps its provenance: source file name, DXF layer, entity handle
and the mapping version, so that any assembled mesh element can be traced back to the
line that will be cut or sewn.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args

import numpy as np
import yaml
from ezdxf import path as ezpath
from ezdxf.document import Drawing
from ezdxf.entities.dxfentity import DXFEntity
from ezdxf.entities.dxfgfx import DXFGraphic
from ezdxf.filemanagement import readfile
from ezdxf.lldxf.const import DXFError
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from envelopelab.geometry.polygon import (
    FloatArray,
    clean_polyline,
    interior_point,
    points_in_polygon,
    polygon_contains,
    signed_area,
)

MAPPING_FORMAT_VERSION = 1

LayerRole = Literal[
    "cut", "sew", "dimension", "feature", "tape", "match_mark", "notch", "grain", "label"
]
LAYER_ROLES: tuple[LayerRole, ...] = get_args(LayerRole)
PieceKind = Literal["panel", "appendage", "mark"]
Units = Literal["auto", "mm", "cm", "m", "in", "ft"]
WarningCode = Literal[
    "missing_label",
    "ambiguous_label",
    "unknown_layer",
    "invalid_geometry",
    "unassigned_entity",
    "duplicate_piece_id",
    "unsupported_entity",
    "units",
    "assumption",
    "ambiguous_seam",
    "quantity",
    "orientation",
]

#: Scale from a drawing unit to m.
UNIT_SCALE: dict[str, float] = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "in": 0.0254, "ft": 0.3048}
#: DXF ``$INSUNITS`` codes for the supported units.
INSUNITS_CODES: dict[int, str] = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
MM = 1e-3  # m per mm


class PatternImportError(ValueError):
    """Raised when a build pack cannot be imported (bad mapping, unreadable DXF)."""


# --------------------------------------------------------------------------------------
# Mapping file model
# --------------------------------------------------------------------------------------


class LayerMap(BaseModel):
    """DXF layer names for each pattern role (case-insensitive)."""

    model_config = ConfigDict(extra="forbid")

    cut: list[str] = Field(default_factory=list, description="Cut lines (outer cut outline).")
    sew: list[str] = Field(default_factory=list, description="Sew (finished) lines.")
    dimension: list[str] = Field(default_factory=list, description="Dimension annotations.")
    feature: list[str] = Field(
        default_factory=list, description="Feature marks: holes, appendage footprints, etc."
    )
    tape: list[str] = Field(default_factory=list, description="Load-tape paths.")
    match_mark: list[str] = Field(default_factory=list, description="Match marks.")
    notch: list[str] = Field(default_factory=list, description="Notches.")
    grain: list[str] = Field(
        default_factory=list, description="Grain arrows (line from tail to head)."
    )
    label: list[str] = Field(default_factory=list, description="Text labels.")
    ignore: list[str] = Field(
        default_factory=list,
        description="Layers that are known but deliberately not imported (no warning).",
    )

    @model_validator(mode="after")
    def _no_layer_in_two_roles(self) -> LayerMap:
        seen: dict[str, str] = {}
        for role in (*LAYER_ROLES, "ignore"):
            for name in getattr(self, role):
                key = name.casefold()
                if key in seen and seen[key] != role:
                    raise ValueError(f"layer {name!r} is mapped to both {seen[key]} and {role}")
                seen[key] = role
        return self

    def role_of(self, layer: str) -> LayerRole | Literal["ignore"] | None:
        """Role mapped to a DXF layer name, ``"ignore"``, or None for an unknown layer."""
        key = layer.casefold()
        for role in (*LAYER_ROLES, "ignore"):
            if key in (name.casefold() for name in getattr(self, role)):
                return role  # type: ignore[return-value]
        return None


class LabelRule(BaseModel):
    """A regular expression that recognises a piece label.

    Named groups: ``panel`` (piece identifier), ``quantity`` (cut count) and ``mirror``
    (any match marks the piece as also cut mirrored). ``piece_id`` may instead give a
    template filled from the named groups, e.g. ``"MOUTH-{gore}"``.
    """

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(description="Python regular expression matched against label text.")
    piece_id: str = Field(
        default="{panel}", description="Piece id template filled from named groups."
    )
    kind: PieceKind = Field(
        default="panel",
        description="panel (envelope panel), appendage (separate skin) or mark (not cut).",
    )
    quantity: int | None = Field(
        default=None, ge=0, description="Fixed cut count; overrides a `quantity` group."
    )
    ignore_case: bool = Field(default=False, description="Match the pattern case-insensitively.")

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid label pattern {value!r}: {exc}") from exc
        return value

    def compiled(self) -> re.Pattern[str]:
        """The compiled expression."""
        return re.compile(self.pattern, re.IGNORECASE if self.ignore_case else 0)


class PieceOptions(BaseModel):
    """Per-piece overrides keyed by piece id."""

    model_config = ConfigDict(extra="forbid")

    quantity: int | None = Field(
        default=None, ge=0, description="Cut count (overrides the label; reported as info)."
    )
    kind: PieceKind | None = Field(
        default=None, description="Piece category (overrides the label rule)."
    )
    material_zone: str | None = Field(default=None, description="Material zone of the piece.")
    grain: tuple[float, float] | None = Field(
        default=None, description="Grain (warp) direction in the pattern frame."
    )
    seam_allowance_mm: float | None = Field(
        default=None, ge=0, description="Seam allowance of the piece."
    )
    corner_angle_deg: float | None = Field(
        default=None, gt=0, lt=180, description="Corner detection threshold for the piece."
    )
    notes: str | None = Field(
        default=None, description="Free text shown in reports and quantity warnings."
    )


class SourceSpec(BaseModel):
    """One DXF file of the build pack, with optional per-file overrides."""

    model_config = ConfigDict(extra="forbid")

    file: str = Field(description="Path relative to the mapping file.")
    layers: LayerMap | None = Field(default=None, description="Replaces the global layer map.")
    units: Units | None = Field(
        default=None, description="Drawing unit of this file (overrides the global units)."
    )
    seam_allowance_mm: float | None = Field(
        default=None, ge=0, description="Seam allowance for pieces in this file."
    )
    labels: list[LabelRule] | None = Field(
        default=None, description="Replaces the global label rules for this file."
    )


class ImportMapping(BaseModel):
    """Per-build-pack pattern import mapping (the ``import`` section of the YAML file)."""

    model_config = ConfigDict(extra="forbid")

    format_version: Literal[1] = Field(
        default=1, description="Mapping file format version (currently 1)."
    )
    mapping_version: str = Field(
        min_length=1, description="Version of this mapping; recorded in every provenance."
    )
    units: Units = Field(default="auto", description="Drawing unit; auto reads $INSUNITS.")
    seam_allowance_mm: float = Field(ge=0, description="Default seam allowance.")
    flatten_tolerance_mm: float = Field(
        default=0.05,
        gt=0,
        description="Max chord error when flattening circles, arcs and splines; a closed "
        "curve comes out about 2.1 x this value short.",
    )
    join_tolerance_mm: float = Field(
        default=0.5, gt=0, description="Gap closed when chaining line segments into outlines."
    )
    duplicate_vertex_tolerance_mm: float = Field(
        default=0.2, gt=0, description="Consecutive vertices closer than this are merged."
    )
    pattern_face: Literal["outside", "inside"] = Field(
        default="outside",
        description="Side of the fabric the patterns are drawn from; inside mirrors them.",
    )
    up_axis: Literal["+y", "-y", "+x", "-x"] = Field(
        default="+y", description="Drawing direction that points up the envelope."
    )
    layers: LayerMap = Field(
        description="Layer names per role (applies to every source unless overridden)."
    )
    labels: list[LabelRule] = Field(
        default_factory=list,
        description="Label rules, tried in order; the first match names the piece.",
    )
    sources: list[SourceSpec] = Field(min_length=1, description="DXF files of the build pack.")
    pieces: dict[str, PieceOptions] = Field(
        default_factory=dict, description="Per-piece overrides keyed by piece id."
    )
    default_material_zone: str = Field(
        default="default", description="Material zone of pieces without an override."
    )
    default_grain: tuple[float, float] | None = Field(
        default=None, description="Grain direction used when a piece has none."
    )
    corner_angle_deg: float = Field(
        default=30.0,
        gt=0,
        lt=180,
        description="Turning angle above which an outline vertex is a corner.",
    )

    _base_dir: Path = PrivateAttr(default_factory=Path.cwd)
    _content_hash: str = PrivateAttr(default="")

    @property
    def base_dir(self) -> Path:
        """Directory that source paths are relative to."""
        return self._base_dir

    @property
    def content_hash(self) -> str:
        """SHA-256 of the mapping file text (empty when built in code)."""
        return self._content_hash

    @property
    def seam_allowance(self) -> float:
        """Default seam allowance, m."""
        return self.seam_allowance_mm * MM

    def piece_options(self, piece_id: str) -> PieceOptions:
        """Overrides for a piece (empty options if none)."""
        return self.pieces.get(piece_id, PieceOptions())


def read_config_file(path: str | Path) -> tuple[dict[str, Any], str]:
    """Read a build-pack YAML file.

    Parameters
    ----------
    path : str or Path
        YAML file.

    Returns
    -------
    (dict, str)
        Parsed document and the SHA-256 of its text.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise PatternImportError(f"cannot read mapping file {file}: {exc}") from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise PatternImportError(f"{file}: expected a YAML mapping at the top level")
    return data, hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_mapping(path: str | Path) -> ImportMapping:
    """Load the ``import`` section of a build-pack YAML file.

    Parameters
    ----------
    path : str or Path
        Build-pack YAML file. Source DXF paths are resolved relative to its directory.

    Returns
    -------
    ImportMapping
        Validated mapping.
    """
    data, digest = read_config_file(path)
    if "import" not in data:
        raise PatternImportError(f"{path}: missing top-level 'import' section")
    mapping = ImportMapping.model_validate(data["import"])
    mapping._base_dir = Path(path).resolve().parent
    mapping._content_hash = digest
    return mapping


# --------------------------------------------------------------------------------------
# Imported data
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """Where an imported entity came from.

    Attributes
    ----------
    source_file : str
        DXF file name (relative to the mapping file).
    layer : str
        DXF layer name.
    entity_id : str
        DXF entity handle; ``a+b`` for outlines chained from several entities and
        ``insert/n`` for entities exploded from a block reference.
    entity_type : str
        DXF entity type (``LWPOLYLINE``, ``CIRCLE``, ...).
    mapping_version : str
        ``mapping_version`` of the import mapping used.
    """

    source_file: str
    layer: str
    entity_id: str
    entity_type: str
    mapping_version: str

    def as_dict(self) -> dict[str, str]:
        """Plain dictionary for JSON/CSV export."""
        return {
            "source_file": self.source_file,
            "layer": self.layer,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "mapping_version": self.mapping_version,
        }

    @property
    def pattern_id(self) -> str:
        """Compact source pattern identifier ``file:layer:handle``."""
        return f"{self.source_file}:{self.layer}:{self.entity_id}"


@dataclass(frozen=True, eq=False)
class PatternEntity:
    """A geometric or text entity after unit conversion.

    Attributes
    ----------
    role : str
        Layer role from the mapping.
    points : ndarray, shape (n, 2)
        Vertices in m (pattern frame); a text insertion point for labels.
    closed : bool
        Closed outline (first vertex not repeated).
    provenance : Provenance
        Source of the entity.
    text : str, optional
        Text content (TEXT/MTEXT).
    circle : (float, float, float), optional
        Centre x, y and radius in m for circles.
    """

    role: str
    points: FloatArray
    closed: bool
    provenance: Provenance
    text: str | None = None
    circle: tuple[float, float, float] | None = None

    @property
    def anchor(self) -> FloatArray:
        """Representative point used to assign the entity to a piece, m."""
        if self.circle is not None:
            return np.array(self.circle[:2])
        if self.text is not None or len(self.points) == 1:
            return np.asarray(self.points[0], dtype=np.float64)
        if self.closed:
            return np.asarray(self.points.mean(axis=0), dtype=np.float64)
        return np.asarray(self.points[len(self.points) // 2], dtype=np.float64)


@dataclass(frozen=True)
class ImportWarning:
    """A problem or assumption noted during import or assembly.

    Attributes
    ----------
    code : str
        Category (``missing_label``, ``unknown_layer``, ``invalid_geometry``, ...).
    message : str
        Human-readable explanation.
    severity : {"info", "warning", "error"}
        How serious it is; errors block a result from being treated as final.
    piece_id : str, optional
        Affected piece.
    provenance : Provenance, optional
        Affected entity.
    """

    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    piece_id: str | None = None
    provenance: Provenance | None = None

    def as_dict(self) -> dict[str, Any]:
        """Plain dictionary for JSON/CSV export."""
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "piece_id": self.piece_id,
            **({"provenance": self.provenance.as_dict()} if self.provenance else {}),
        }


@dataclass(frozen=True, eq=False)
class HoleLines:
    """Cut and (optional) sew line of a hole inside a piece."""

    cut: PatternEntity
    sew: PatternEntity | None


@dataclass(eq=False)
class RawPiece:
    """One cut piece as found in a DXF file, before finished-geometry construction.

    Attributes
    ----------
    piece_id : str
        Identifier parsed from the label (or generated when the label is missing).
    kind : {"panel", "appendage", "mark"}
        Piece category from the label rule or piece overrides.
    quantity : int
        Cut count from the label (1 when not stated).
    mirrored : bool
        The label says the piece is also cut mirrored.
    label : PatternEntity, optional
        Label text entity that identified the piece.
    cut : PatternEntity
        Closed cut outline.
    sew : PatternEntity, optional
        Closed sew (finished) outline.
    holes : list of HoleLines
        Holes cut inside the piece (inner cut loops without a label).
    entities : dict of str to list of PatternEntity
        Other entities inside the piece, keyed by role (feature, tape, match_mark, notch,
        grain, dimension, label).
    seam_allowance : float
        Seam allowance used when the piece has no sew line, m.
    source_file : str
        DXF file name.
    """

    piece_id: str
    kind: PieceKind
    quantity: int
    mirrored: bool
    label: PatternEntity | None
    cut: PatternEntity
    sew: PatternEntity | None
    holes: list[HoleLines]
    entities: dict[str, list[PatternEntity]]
    seam_allowance: float
    source_file: str
    material_zone: str = "default"
    grain: tuple[float, float] | None = None
    grain_source: str = "none"
    corner_angle_deg: float = 30.0


@dataclass(frozen=True)
class SourceInfo:
    """Metadata for one imported DXF file."""

    file: str
    sha256: str
    dxf_version: str
    insunits: int
    units: str
    scale_to_m: float
    entity_count: int

    def as_dict(self) -> dict[str, Any]:
        """Plain dictionary for JSON export."""
        return dict(self.__dict__)


@dataclass
class PatternImport:
    """Result of importing every DXF file of a build pack.

    Attributes
    ----------
    pieces : list of RawPiece
        Pieces in file order.
    entities : list of PatternEntity
        Every imported entity (assigned or not).
    unassigned : list of PatternEntity
        Entities that are not inside any piece.
    warnings : list of ImportWarning
        Problems and assumptions.
    sources : list of SourceInfo
        Imported files.
    mapping_version : str
        Mapping version used.
    mapping_hash : str
        SHA-256 of the mapping file.
    """

    pieces: list[RawPiece]
    entities: list[PatternEntity]
    unassigned: list[PatternEntity]
    warnings: list[ImportWarning]
    sources: list[SourceInfo]
    mapping_version: str
    mapping_hash: str

    def piece(self, piece_id: str) -> RawPiece:
        """Look up a piece by id."""
        for piece in self.pieces:
            if piece.piece_id == piece_id:
                return piece
        raise KeyError(f"no piece {piece_id!r}; known: {', '.join(self.piece_ids)}")

    @property
    def piece_ids(self) -> list[str]:
        """All piece ids in import order."""
        return [piece.piece_id for piece in self.pieces]

    @property
    def content_hash(self) -> str:
        """SHA-256 over the mapping and every source file (design content hash)."""
        digest = hashlib.sha256(self.mapping_hash.encode())
        for source in self.sources:
            digest.update(source.sha256.encode())
        return digest.hexdigest()


# --------------------------------------------------------------------------------------
# DXF reading
# --------------------------------------------------------------------------------------


def _frame_transform(mapping: ImportMapping) -> np.ndarray:
    """2x2 matrix taking drawing axes to the pattern frame (+y up, seen from outside)."""
    rotations = {
        "+y": np.eye(2),
        "-y": np.array([[-1.0, 0.0], [0.0, -1.0]]),
        "+x": np.array([[0.0, -1.0], [1.0, 0.0]]),  # drawing +x becomes +y
        "-x": np.array([[0.0, 1.0], [-1.0, 0.0]]),
    }
    matrix = rotations[mapping.up_axis]
    if mapping.pattern_face == "inside":
        matrix = np.array([[-1.0, 0.0], [0.0, 1.0]]) @ matrix
    return matrix


def _resolve_units(
    doc: Drawing, requested: Units, file: str, warnings: list[ImportWarning]
) -> tuple[str, int]:
    insunits = int(doc.header.get("$INSUNITS", 0))
    header_unit = INSUNITS_CODES.get(insunits)
    if requested == "auto":
        if header_unit is None:
            raise PatternImportError(
                f"{file}: $INSUNITS={insunits} is not a supported length unit; set 'units' "
                "in the mapping file instead of guessing the drawing scale"
            )
        return header_unit, insunits
    if header_unit is not None and header_unit != requested:
        warnings.append(
            ImportWarning(
                "units",
                f"{file}: mapping units '{requested}' override $INSUNITS ({header_unit})",
                severity="warning",
            )
        )
    return requested, insunits


def _iter_graphics(entities: Iterable[DXFEntity], prefix: str = "") -> Iterator[tuple[str, Any]]:
    for index, entity in enumerate(entities):
        if not isinstance(entity, DXFGraphic):
            continue
        handle = f"{prefix}{entity.dxf.handle}" if not prefix else f"{prefix}{index}"
        if entity.dxftype() == "INSERT":
            yield from _iter_graphics(entity.virtual_entities(), prefix=f"{handle}/")  # type: ignore[attr-defined]
        else:
            yield handle, entity


def _entity_geometry(
    entity: Any, flatten: float
) -> tuple[FloatArray, bool, tuple[float, float, float] | None] | None:
    """Vertices (drawing units), closed flag and circle data for a curve entity."""
    kind = entity.dxftype()
    if kind == "CIRCLE":
        center = entity.dxf.center
        radius = float(entity.dxf.radius)
        n = max(24, math.ceil(2 * math.pi / (2 * math.acos(max(-1.0, 1 - flatten / radius)))))
        angle = np.linspace(0.0, 2 * math.pi, n, endpoint=False)
        pts = np.column_stack(
            [center.x + radius * np.cos(angle), center.y + radius * np.sin(angle)]
        )
        return pts, True, (float(center.x), float(center.y), radius)
    if kind == "POINT":
        loc = entity.dxf.location
        return np.array([[loc.x, loc.y]]), False, None
    if kind in {"LWPOLYLINE", "POLYLINE", "LINE", "ARC", "ELLIPSE", "SPLINE"}:
        closed = bool(getattr(entity, "closed", False) or getattr(entity, "is_closed", False))
        if kind == "ELLIPSE":
            closed = abs(abs(entity.dxf.end_param - entity.dxf.start_param) - 2 * math.pi) < 1e-9
        p = ezpath.make_path(entity)
        verts = np.array([[v.x, v.y] for v in p.flattening(flatten)], dtype=np.float64)
        if len(verts) >= 2 and np.hypot(*(verts[-1] - verts[0])) <= 1e-9 * max(
            1.0, float(np.abs(verts).max())
        ):
            closed = True
        return verts, closed, None
    return None


def _chain_open_paths(
    items: list[tuple[FloatArray, str]], tolerance: float
) -> list[tuple[FloatArray, bool, str]]:
    """Join open polylines whose end points meet into longer (possibly closed) paths."""
    remaining = [(pts.copy(), ident) for pts, ident in items]
    result: list[tuple[FloatArray, bool, str]] = []
    while remaining:
        path, ident = remaining.pop(0)
        grown = True
        while grown:
            grown = False
            for k, (other, other_id) in enumerate(remaining):
                if np.hypot(*(path[-1] - other[0])) <= tolerance:
                    path = np.vstack([path, other[1:]])
                elif np.hypot(*(path[-1] - other[-1])) <= tolerance:
                    path = np.vstack([path, other[::-1][1:]])
                elif np.hypot(*(path[0] - other[-1])) <= tolerance:
                    path = np.vstack([other, path[1:]])
                elif np.hypot(*(path[0] - other[0])) <= tolerance:
                    path = np.vstack([other[::-1], path[1:]])
                else:
                    continue
                ident = f"{ident}+{other_id}"
                remaining.pop(k)
                grown = True
                break
        closed = len(path) > 2 and np.hypot(*(path[-1] - path[0])) <= tolerance
        result.append((path, bool(closed), ident))
    return result


def read_dxf_entities(
    path: Path,
    source: SourceSpec,
    mapping: ImportMapping,
    warnings: list[ImportWarning],
) -> tuple[list[PatternEntity], SourceInfo]:
    """Read the mapped entities of one DXF file.

    Parameters
    ----------
    path : Path
        DXF file.
    source : SourceSpec
        Source entry from the mapping (per-file overrides).
    mapping : ImportMapping
        Import mapping.
    warnings : list of ImportWarning
        Appended with unknown layers, unsupported entities and unit notes.

    Returns
    -------
    (list of PatternEntity, SourceInfo)
        Entities in m in the pattern frame, and file metadata.
    """
    try:
        raw = path.read_bytes()
        doc = readfile(str(path))
    except (OSError, DXFError) as exc:
        raise PatternImportError(f"cannot read DXF {path}: {exc}") from exc
    file = source.file
    unit, insunits = _resolve_units(doc, source.units or mapping.units, file, warnings)
    scale = UNIT_SCALE[unit]
    layers = source.layers or mapping.layers
    frame = _frame_transform(mapping)
    flatten = mapping.flatten_tolerance_mm * MM / scale
    dedupe = mapping.duplicate_vertex_tolerance_mm * MM

    entities: list[PatternEntity] = []
    unknown: dict[str, int] = {}
    unsupported: dict[str, int] = {}
    open_by_layer: dict[tuple[str, str], list[tuple[FloatArray, str, str]]] = {}
    count = 0
    for handle, entity in _iter_graphics(doc.modelspace()):
        count += 1
        layer = entity.dxf.layer
        role = layers.role_of(layer)
        if role is None:
            unknown[layer] = unknown.get(layer, 0) + 1
            continue
        if role == "ignore":
            continue
        kind = entity.dxftype()

        def prov(ident: str, kind: str = kind, layer: str = layer) -> Provenance:
            return Provenance(file, layer, ident, kind, mapping.mapping_version)

        if kind in {"TEXT", "MTEXT", "ATTRIB"}:
            text = entity.plain_text() if kind == "MTEXT" else entity.dxf.text
            insert = entity.dxf.insert
            pts = (np.array([[insert.x, insert.y]]) * scale) @ frame.T
            entities.append(PatternEntity(role, pts, False, prov(handle), text=str(text)))
            continue
        if kind == "DIMENSION":
            try:
                measurement = float(entity.get_measurement())
            except Exception:  # noqa: BLE001 - ezdxf raises various errors for odd dimensions
                measurement = float("nan")
            base = entity.dxf.defpoint
            pts = (np.array([[base.x, base.y]]) * scale) @ frame.T
            text = f"{measurement * scale:.6g} m"
            entities.append(PatternEntity(role, pts, False, prov(handle), text=text))
            continue
        geometry = _entity_geometry(entity, flatten)
        if geometry is None:
            unsupported[kind] = unsupported.get(kind, 0) + 1
            continue
        verts, closed, circle = geometry
        pts = (verts * scale) @ frame.T
        if circle is not None:
            cxy = (np.array(circle[:2]) * scale) @ frame.T
            circle = (float(cxy[0]), float(cxy[1]), circle[2] * scale)
        if not closed and len(pts) > 1 and role in {"cut", "sew", "feature"}:
            open_by_layer.setdefault((role, layer), []).append((pts, handle, kind))
            continue
        pts = clean_polyline(pts, dedupe, closed)
        entities.append(PatternEntity(role, pts, closed, prov(handle), circle=circle))

    join = mapping.join_tolerance_mm * MM
    for (open_role, layer), items in open_by_layer.items():
        kinds = {handle: kind for _, handle, kind in items}
        for pts, closed, ident in _chain_open_paths([(p, h) for p, h, _ in items], join):
            kind = "+".join(sorted({kinds[h] for h in ident.split("+")}))
            entities.append(
                PatternEntity(
                    open_role,
                    clean_polyline(pts, dedupe, closed),
                    closed,
                    Provenance(file, layer, ident, kind, mapping.mapping_version),
                )
            )
    for layer, n in sorted(unknown.items()):
        warnings.append(
            ImportWarning(
                "unknown_layer",
                f"{file}: layer {layer!r} ({n} entities) is not in the mapping and was skipped",
            )
        )
    for kind, n in sorted(unsupported.items()):
        warnings.append(
            ImportWarning(
                "unsupported_entity", f"{file}: {n} {kind} entities are not supported; skipped"
            )
        )
    info = SourceInfo(
        file=file,
        sha256=hashlib.sha256(raw).hexdigest(),
        dxf_version=str(doc.dxfversion),
        insunits=insunits,
        units=unit,
        scale_to_m=scale,
        entity_count=count,
    )
    return entities, info


# --------------------------------------------------------------------------------------
# Piece grouping
# --------------------------------------------------------------------------------------


@dataclass
class _Loop:
    entity: PatternEntity
    area: float
    parent: _Loop | None = None
    children: list[_Loop] = field(default_factory=list)
    label: tuple[str, LabelRule, re.Match[str], PatternEntity] | None = None


def _parse_label(text: str, rules: list[LabelRule]) -> tuple[str, LabelRule, re.Match[str]] | None:
    for rule in rules:
        match = rule.compiled().search(text)
        if match is None:
            continue
        groups = {k: (v or "").strip() for k, v in match.groupdict().items()}
        try:
            piece_id = rule.piece_id.format(**groups).strip()
        except (KeyError, IndexError) as exc:
            raise PatternImportError(
                f"label rule {rule.pattern!r}: piece_id template {rule.piece_id!r} uses an "
                f"unknown group ({exc})"
            ) from exc
        if piece_id:
            return piece_id, rule, match
    return None


def _innermost(loops: list[_Loop], point: FloatArray) -> _Loop | None:
    best: _Loop | None = None
    for loop in loops:
        if points_in_polygon(point, loop.entity.points)[0] and (
            best is None or loop.area < best.area
        ):
            best = loop
    return best


def _grain_from_entities(entities: list[PatternEntity]) -> tuple[float, float] | None:
    for entity in entities:
        if len(entity.points) >= 2 and not entity.closed:
            vec = entity.points[-1] - entity.points[0]
            norm = float(np.hypot(*vec))
            if norm > 0:
                return float(vec[0] / norm), float(vec[1] / norm)
    return None


def group_pieces(
    entities: list[PatternEntity],
    source: SourceSpec,
    mapping: ImportMapping,
    warnings: list[ImportWarning],
) -> tuple[list[RawPiece], list[PatternEntity]]:
    """Group the entities of one file into pieces.

    Closed cut outlines define pieces; a cut outline inside another piece without a label
    of its own is a hole of that piece. Sew lines, labels and marks are assigned to the
    innermost cut outline that contains them.

    Parameters
    ----------
    entities : list of PatternEntity
        Entities of one DXF file.
    source : SourceSpec
        Source entry (per-file label rules and allowance).
    mapping : ImportMapping
        Import mapping.
    warnings : list of ImportWarning
        Appended with missing/ambiguous labels, invalid geometry and unassigned entities.

    Returns
    -------
    (list of RawPiece, list of PatternEntity)
        Pieces and the entities not inside any piece.
    """
    rules = source.labels if source.labels is not None else mapping.labels
    file = source.file
    loops: list[_Loop] = []
    unassigned: list[PatternEntity] = []
    for entity in entities:
        if entity.role != "cut":
            continue
        if not entity.closed or len(entity.points) < 3:
            warnings.append(
                ImportWarning(
                    "invalid_geometry",
                    f"{file}: cut line {entity.provenance.entity_id} is not a closed outline "
                    "and cannot define a piece",
                    severity="error",
                    provenance=entity.provenance,
                )
            )
            unassigned.append(entity)
            continue
        loops.append(_Loop(entity, abs(signed_area(entity.points))))
    loops.sort(key=lambda loop: -loop.area)
    for k, loop in enumerate(loops):
        for candidate in reversed(loops[:k]):
            if polygon_contains(candidate.entity.points, loop.entity.points, 0.99) and (
                loop.parent is None or candidate.area < loop.parent.area
            ):
                loop.parent = candidate
        if loop.parent is not None:
            loop.parent.children.append(loop)

    labels = [e for e in entities if e.role == "label" and e.text is not None]
    label_hits: dict[int, list[tuple[str, LabelRule, re.Match[str], PatternEntity]]] = {}
    free_labels: list[PatternEntity] = []
    for text_entity in labels:
        owner = _innermost(loops, text_entity.anchor)
        parsed = _parse_label(text_entity.text or "", rules)
        if owner is None:
            free_labels.append(text_entity)
            continue
        if parsed is not None:
            label_hits.setdefault(id(owner), []).append((*parsed, text_entity))
    for loop in loops:
        hits = label_hits.get(id(loop), [])
        if hits:
            ids = {h[0] for h in hits}
            loop.label = hits[0]
            if len(ids) > 1:
                warnings.append(
                    ImportWarning(
                        "ambiguous_label",
                        f"{file}: cut outline {loop.entity.provenance.entity_id} contains "
                        f"labels for {sorted(ids)}; using {hits[0][0]!r}",
                        provenance=loop.entity.provenance,
                    )
                )
    # Unlabelled loops nested in a piece are holes; labelled ones are separate pieces.
    piece_loops = [lp for lp in loops if lp.parent is None or lp.label is not None]
    hole_loops = [lp for lp in loops if lp not in piece_loops]

    def owner_piece(loop: _Loop | None) -> _Loop | None:
        while loop is not None and loop not in piece_loops:
            loop = loop.parent
        return loop

    sew_for: dict[int, list[PatternEntity]] = {}
    for entity in entities:
        if entity.role != "sew":
            continue
        if not entity.closed:
            warnings.append(
                ImportWarning(
                    "invalid_geometry",
                    f"{file}: sew line {entity.provenance.entity_id} is not closed; ignored "
                    "(partial sew lines are not supported)",
                    provenance=entity.provenance,
                )
            )
            unassigned.append(entity)
            continue
        sew_area = abs(signed_area(entity.points))
        # A hole's finished line encloses its cut loop; a piece's lies inside its cut line
        # (or on it, for pieces with exact edges). A piece's sew line also encloses its
        # holes, so the candidate whose cut area is closest to the sew area wins.
        candidates: list[_Loop] = [
            h
            for h in hole_loops
            if sew_area > h.area
            and points_in_polygon(interior_point(h.entity.points), entity.points)[0]
            and polygon_contains(entity.points, h.entity.points, 0.99)
        ]
        inner = interior_point(entity.points)
        candidates += [
            lp
            for lp in piece_loops
            if sew_area <= lp.area * (1.0 + 1e-6) and points_in_polygon(inner, lp.entity.points)[0]
        ]
        if not candidates:
            unassigned.append(entity)
            continue
        owner = min(candidates, key=lambda lp: abs(lp.area - sew_area))
        sew_for.setdefault(id(owner), []).append(entity)

    others: dict[int, dict[str, list[PatternEntity]]] = {}
    for entity in entities:
        if entity.role in {"cut", "sew"}:
            continue
        if entity.role == "label" and entity in free_labels:
            unassigned.append(entity)
            continue
        owner = owner_piece(_innermost(loops, entity.anchor))
        if owner is None:
            unassigned.append(entity)
            continue
        others.setdefault(id(owner), {}).setdefault(entity.role, []).append(entity)

    pieces: list[RawPiece] = []
    for loop in piece_loops:
        prov = loop.entity.provenance
        label: PatternEntity | None
        if loop.label is not None:
            piece_id, rule, match, label_entity = loop.label
            kind: PieceKind = rule.kind
            groups = match.groupdict()
            if rule.quantity is not None:
                quantity = rule.quantity
            elif groups.get("quantity"):
                quantity = int(groups["quantity"])
            else:
                quantity = 1
            mirrored = bool(groups.get("mirror"))
            label = label_entity
        else:
            piece_id = f"{Path(file).stem}#{prov.entity_id}"
            kind, quantity, mirrored, label = "panel", 1, False, None
            warnings.append(
                ImportWarning(
                    "missing_label",
                    f"{file}: cut outline {prov.entity_id} has no label matching the mapping; "
                    f"named {piece_id!r}",
                    piece_id=piece_id,
                    provenance=prov,
                )
            )
        options = mapping.piece_options(piece_id)
        if options.kind is not None:
            kind = options.kind
        if options.quantity is not None and options.quantity != quantity:
            warnings.append(
                ImportWarning(
                    "quantity",
                    f"{piece_id}: mapping quantity {options.quantity} overrides label "
                    f"quantity {quantity}",
                    severity="info",
                    piece_id=piece_id,
                )
            )
            quantity = options.quantity
        sews = sew_for.get(id(loop), [])
        sew = max(sews, key=lambda e: abs(signed_area(e.points))) if sews else None
        if len(sews) > 1:
            warnings.append(
                ImportWarning(
                    "ambiguous_seam",
                    f"{piece_id}: {len(sews)} sew outlines inside the cut line; using the largest",
                    piece_id=piece_id,
                    provenance=prov,
                )
            )
        holes = [
            HoleLines(h.entity, next(iter(sew_for.get(id(h), [])), None))
            for h in hole_loops
            if owner_piece(h) is loop
        ]
        entity_map = others.get(id(loop), {})
        allowance_mm = (
            options.seam_allowance_mm
            if options.seam_allowance_mm is not None
            else source.seam_allowance_mm
            if source.seam_allowance_mm is not None
            else mapping.seam_allowance_mm
        )
        grain = _grain_from_entities(entity_map.get("grain", []))
        grain_source = "grain layer"
        if grain is None and options.grain is not None:
            grain, grain_source = options.grain, "mapping (piece)"
        elif grain is None and mapping.default_grain is not None:
            grain, grain_source = mapping.default_grain, "mapping (default)"
        elif grain is None:
            grain_source = "none"
        if grain is not None:
            norm = math.hypot(*grain)
            if norm == 0:
                raise PatternImportError(f"{piece_id}: grain direction must be nonzero")
            grain = (grain[0] / norm, grain[1] / norm)
        pieces.append(
            RawPiece(
                piece_id=piece_id,
                kind=kind,
                quantity=quantity,
                mirrored=mirrored,
                label=label,
                cut=loop.entity,
                sew=sew,
                holes=holes,
                entities=entity_map,
                seam_allowance=allowance_mm * MM,
                source_file=file,
                material_zone=options.material_zone or mapping.default_material_zone,
                grain=grain,
                grain_source=grain_source,
                corner_angle_deg=options.corner_angle_deg or mapping.corner_angle_deg,
            )
        )
    for entity in unassigned:
        if entity.role == "label":
            continue  # title blocks and sheet notes
        warnings.append(
            ImportWarning(
                "unassigned_entity",
                f"{file}: {entity.role} entity {entity.provenance.entity_id} is not inside any "
                "cut outline",
                severity="info",
                provenance=entity.provenance,
            )
        )
    return pieces, unassigned


def import_patterns(mapping: ImportMapping) -> PatternImport:
    """Import every source DXF file listed in a mapping.

    Parameters
    ----------
    mapping : ImportMapping
        Import mapping (``load_mapping``); source paths are relative to its directory.

    Returns
    -------
    PatternImport
        Pieces, entities, warnings and file metadata.
    """
    warnings: list[ImportWarning] = []
    pieces: list[RawPiece] = []
    all_entities: list[PatternEntity] = []
    unassigned: list[PatternEntity] = []
    sources: list[SourceInfo] = []
    for source in mapping.sources:
        path = (mapping.base_dir / source.file).resolve()
        entities, info = read_dxf_entities(path, source, mapping, warnings)
        file_pieces, file_unassigned = group_pieces(entities, source, mapping, warnings)
        sources.append(info)
        all_entities.extend(entities)
        unassigned.extend(file_unassigned)
        pieces.extend(file_pieces)
    seen: dict[str, int] = {}
    for piece in pieces:
        if piece.piece_id in seen:
            seen[piece.piece_id] += 1
            new_id = f"{piece.piece_id}~{seen[piece.piece_id]}"
            warnings.append(
                ImportWarning(
                    "duplicate_piece_id",
                    f"piece id {piece.piece_id!r} appears more than once; renamed to {new_id!r}",
                    piece_id=new_id,
                    provenance=piece.cut.provenance,
                )
            )
            piece.piece_id = new_id
        else:
            seen[piece.piece_id] = 1
    for piece in pieces:
        if piece.grain is None:
            warnings.append(
                ImportWarning(
                    "assumption",
                    f"{piece.piece_id}: no grain direction (grain layer, piece option or "
                    "default_grain); grain is left unset",
                    piece_id=piece.piece_id,
                )
            )
    return PatternImport(
        pieces=pieces,
        entities=all_entities,
        unassigned=unassigned,
        warnings=warnings,
        sources=sources,
        mapping_version=mapping.mapping_version,
        mapping_hash=mapping.content_hash,
    )
