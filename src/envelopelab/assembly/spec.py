"""Assembly specification: the ``assembly`` section of a build-pack YAML file.

The assembly spec says how the imported pieces are sewn together. It is data, written per
build pack; the assembler has no knowledge of any particular design.

* **Rings** describe standard gore construction: ``gore_count`` gores, each made of the
  listed rows from the bottom (mouth) to the top (crown), joined by horizontal panel seams
  and vertical gore seams. Ring instances are named ``<ring>/<row>@<gore>``.
* **Instance overrides** change material zones, cut declared feature openings (feed holes,
  vents) and embed feature marks (attachment lines for appendages) in selected ring
  instances.
* **Parts** are single piece instances (appendages, mirrored pieces).
* **Seams** join edge chains explicitly (appendage, reinforcement, closing seams). Each
  seam carries metadata: type, allowance, stitch rows, load tape, designed ease,
  construction order, orientation and mismatch tolerance.
* **Openings** declare boundaries that are meant to stay open.

Lengths are in mm in the file and converted to m by the ``*_m`` properties.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from envelopelab.io.pattern_import import PatternImportError, read_config_file

MM = 1e-3  # m per mm

SeamType = Literal[
    "horizontal_panel", "vertical_gore", "reinforcement", "appendage", "rim", "closing"
]
OpeningKind = Literal[
    "mouth", "parachute_opening", "vent", "feed_hole", "feature_opening", "parachute_rim"
]
Orientation = Literal["reversed", "same"]
RingSide = Literal["bottom", "top", "left", "right"]


def _default_ring_edges() -> dict[RingSide, str]:
    return {"bottom": "bottom", "top": "top", "left": "left", "right": "right"}


class SeamProperties(BaseModel):
    """Seam metadata shared by ring seams, explicit seams and hems."""

    model_config = ConfigDict(extra="forbid")

    allowance_mm: float | None = Field(
        default=None, ge=0, description="Expected allowance on both sides (None: not checked)."
    )
    allowance_a_mm: float | None = Field(default=None, ge=0, description="Side A allowance.")
    allowance_b_mm: float | None = Field(default=None, ge=0, description="Side B allowance.")
    stitch_rows: int = Field(default=2, ge=0, description="Number of stitch rows.")
    stitch: str | None = Field(default=None, description="Stitch/seam construction name.")
    load_tape: str | None = Field(default=None, description="Load tape type sewn in the seam.")
    designed_ease_mm: float = Field(
        default=0.0,
        description="Intended length excess of side B over side A (not an error).",
    )
    construction_order: int = Field(default=0, description="Assembly step number.")
    orientation: Orientation = Field(
        default="reversed",
        description="reversed: side A start meets side B end (normal for panels that lie "
        "side by side); same: starts meet (appendage sewn onto a marked line).",
    )
    tolerance_mm: float = Field(default=3.0, gt=0, description="Allowed length mismatch.")
    notes: str | None = Field(default=None, description="Free text.")

    @property
    def designed_ease_m(self) -> float:
        """Designed ease, m."""
        return self.designed_ease_mm * MM

    @property
    def tolerance_m(self) -> float:
        """Mismatch tolerance, m."""
        return self.tolerance_mm * MM

    def side_allowance_m(self, side: Literal["a", "b"]) -> float | None:
        """Expected allowance of one side, m (None when not specified)."""
        value = self.allowance_a_mm if side == "a" else self.allowance_b_mm
        value = self.allowance_mm if value is None else value
        return None if value is None else value * MM


class BoundarySpec(BaseModel):
    """An open ring boundary (mouth or crown) and its hem."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Opening name.")
    kind: OpeningKind = Field(description="Opening kind.")
    hem: SeamProperties | None = Field(default=None, description="Hem (rim seam) metadata.")


class OpenSeamSpec(BaseModel):
    """A vertical ring seam left unsewn over some rows (e.g. a turning vent)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Opening name.")
    gores: tuple[int, int] = Field(description="The two neighbouring gores, e.g. [15, 16].")
    rows: list[str] = Field(min_length=1, description="Rows over which the seam stays open.")
    kind: OpeningKind = Field(default="vent", description="Opening kind.")
    hem: SeamProperties | None = Field(default=None, description="Hem (rim seam) metadata.")


class RingSpec(BaseModel):
    """Standard gore construction: rows stacked into gores, gores joined into a ring."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        pattern=r"^[A-Za-z0-9_\-]+$",
        description="Ring name, used in instance ids <ring>/<row>@<gore>.",
    )
    gore_count: int = Field(ge=3, description="Number of gores.")
    rows: list[str] = Field(min_length=1, description="Piece ids from bottom to top.")
    first_gore: int = Field(default=1, description="Number of the first gore.")
    bottom: BoundarySpec = Field(
        description="Open boundary along the bottom edges of the first row."
    )
    top: BoundarySpec = Field(description="Open boundary along the top edges of the last row.")
    edges: dict[RingSide, str] = Field(
        default_factory=_default_ring_edges,
        description="Edge names used for each side of a row piece.",
    )
    horizontal_seam: SeamProperties = Field(
        default_factory=SeamProperties, description="Metadata of the seams between rows."
    )
    vertical_seam: SeamProperties = Field(
        default_factory=SeamProperties, description="Metadata of the seams between gores."
    )
    open_seams: list[OpenSeamSpec] = Field(
        default_factory=list, description="Vertical seams left unsewn (e.g. turning vents)."
    )
    material_zone: str | None = Field(default=None, description="Overrides piece zones.")

    @property
    def gores(self) -> list[int]:
        """Gore numbers in order around the ring."""
        return list(range(self.first_gore, self.first_gore + self.gore_count))

    def instance_id(self, row: str, gore: int) -> str:
        """Instance id of one ring panel."""
        return f"{self.name}/{row}@{gore}"


class FeatureSelector(BaseModel):
    """Selects one feature entity (circle or closed polyline) inside a piece.

    Coordinates are in the piece's local frame: origin at the bottom-centre of the
    finished outline's bounding box, +y up, in mm.
    """

    model_config = ConfigDict(extra="forbid")

    circle_radius_mm: float | None = Field(
        default=None, gt=0, description="Select circles of this radius."
    )
    near_mm: tuple[float, float] | None = Field(
        default=None, description="Feature centre closest to this point."
    )
    entity_id: str | None = Field(default=None, description="DXF handle.")
    tolerance_mm: float = Field(default=2.0, gt=0, description="Radius match tolerance.")


class InstanceFeature(BaseModel):
    """A feature opening or embedded mark in selected instances."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Name of the opening or mark within the instance.")
    feature: FeatureSelector = Field(description="Selects the feature entity in the piece.")
    kind: OpeningKind = Field(
        default="feature_opening", description="Opening kind (ignored for marks)."
    )
    hem: SeamProperties | None = Field(
        default=None, description="Hem (rim seam) metadata for openings."
    )


class InstanceSelect(BaseModel):
    """Selects ring instances by ring, rows and gores (empty = all)."""

    model_config = ConfigDict(extra="forbid")

    ring: str = Field(description="Ring name.")
    rows: list[str] = Field(default_factory=list, description="Row piece ids (empty = all rows).")
    gores: list[int] = Field(default_factory=list, description="Gore numbers (empty = all gores).")


class InstanceOverride(BaseModel):
    """Changes applied to the selected ring instances."""

    model_config = ConfigDict(extra="forbid")

    select: InstanceSelect = Field(description="Which ring instances to change.")
    material_zone: str | None = Field(default=None, description="New material zone.")
    openings: list[InstanceFeature] = Field(
        default_factory=list, description="Feature openings cut in the instances."
    )
    marks: list[InstanceFeature] = Field(
        default_factory=list, description="Feature marks embedded in the mesh."
    )
    notes: str | None = Field(default=None, description="Free text.")


class PartSpec(BaseModel):
    """A single piece instance outside the rings (appendage, mirrored copy, ...)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_\-/@.]+$", description="Instance id of the part.")
    piece: str = Field(description="Piece id.")
    mirror: bool = Field(default=False, description="Use the mirror image of the piece.")
    material_zone: str | None = Field(default=None, description="Overrides the piece zone.")
    mesh: bool = Field(default=True, description="False: seam graph and audit only.")
    reason: str | None = Field(default=None, description="Why the part is not meshed.")


class EdgeRef(BaseModel):
    """One edge of an instance: a named outline edge, an embedded mark or an opening."""

    model_config = ConfigDict(extra="forbid")

    instance: str = Field(description="Instance id.")
    edge: str | None = Field(
        default=None, description="Outline edge name (bottom, right, top, left, e0.., loop)."
    )
    mark: str | None = Field(default=None, description="Embedded mark or instance opening name.")
    reverse: bool = Field(default=False, description="Traverse the edge backwards.")

    @model_validator(mode="after")
    def _one_target(self) -> EdgeRef:
        if (self.edge is None) == (self.mark is None):
            raise ValueError("an edge reference needs exactly one of 'edge' or 'mark'")
        return self


class RingBoundaryRef(BaseModel):
    """All bottom or top edges of a ring, in gore order."""

    model_config = ConfigDict(extra="forbid")

    ring: str = Field(description="Ring name.")
    boundary: Literal["bottom", "top"] = Field(
        description="bottom or top edges of the ring, in gore order."
    )


class SeamSpec(SeamProperties):
    """An explicit seam between two edge chains."""

    name: str = Field(description="Unique seam id.")
    type: SeamType = Field(description="Seam type.")
    a: list[EdgeRef | RingBoundaryRef] = Field(
        min_length=1,
        description="Side A: chain of edge or ring-boundary references in sewing order.",
    )
    b: list[EdgeRef | RingBoundaryRef] = Field(
        min_length=1,
        description="Side B: chain of edge or ring-boundary references in sewing order.",
    )
    attachment: bool = Field(
        default=False,
        description="Side A is a line marked on a panel surface (T-junction seam).",
    )


class OpeningSpec(BaseModel):
    """An explicitly declared opening made of instance edges."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Opening name.")
    kind: OpeningKind = Field(default="feature_opening", description="Opening kind.")
    edges: list[EdgeRef] = Field(min_length=1, description="Edges forming the opening.")
    hem: SeamProperties | None = Field(default=None, description="Hem (rim seam) metadata.")
    reason: str | None = Field(
        default=None, description="Why the boundary is left open (shown in reports)."
    )


class MeshOptions(BaseModel):
    """Triangulation settings (all lengths in mm)."""

    model_config = ConfigDict(extra="forbid")

    target_edge_length_mm: float = Field(
        default=300.0, gt=0, description="Interior target edge length."
    )
    seam_edge_length_mm: float | None = Field(
        default=None, gt=0, description="Edge length along seams (default 0.5 x target)."
    )
    corner_edge_length_mm: float | None = Field(
        default=None, gt=0, description="Edge length at corners (default 0.5 x seam)."
    )
    hole_edge_length_mm: float | None = Field(
        default=None, gt=0, description="Edge length on holes and marks (default 0.5 x seam)."
    )
    appendage_edge_length_mm: float | None = Field(
        default=None, gt=0, description="Edge length on appendage seams (default = hole)."
    )
    refinement_distance_mm: float | None = Field(
        default=None,
        gt=0,
        description="Distance over which sizes grow to the target (default 1.5 x target).",
    )
    growth: float = Field(
        default=1.3, gt=1.0, description="Growth ratio of boundary spacing away from corners."
    )
    min_quality: float = Field(
        default=0.3, gt=0, le=1, description="Triangle quality below which the mesh check fails."
    )
    algorithm: Literal["frontal_delaunay", "delaunay", "meshadapt"] = Field(
        default="frontal_delaunay", description="Gmsh 2D algorithm."
    )

    @property
    def target(self) -> float:
        """Interior target edge length, m."""
        return self.target_edge_length_mm * MM

    @property
    def seam(self) -> float:
        """Edge length along seams, m (default 0.5 x target)."""
        return (self.seam_edge_length_mm or 0.5 * self.target_edge_length_mm) * MM

    @property
    def corner(self) -> float:
        """Edge length at corners, m (default 0.5 x seam)."""
        return (self.corner_edge_length_mm or 0.5 * self.seam * 1e3) * MM

    @property
    def hole(self) -> float:
        """Edge length on holes and marks, m (default 0.5 x seam)."""
        return (self.hole_edge_length_mm or 0.5 * self.seam * 1e3) * MM

    @property
    def appendage(self) -> float:
        """Edge length on appendage seams, m (default = hole size)."""
        return (self.appendage_edge_length_mm or self.hole * 1e3) * MM

    @property
    def refinement_distance(self) -> float:
        """Distance over which sizes grow to the target, m (default 1.5 x target)."""
        return (self.refinement_distance_mm or 1.5 * self.target_edge_length_mm) * MM


class InitialShapeSpec(BaseModel):
    """Initial 3D guess for the as-sewn rest model (never the inflated shape)."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["gore_revolution", "reference_mesh"] = Field(
        default="gore_revolution",
        description="gore_revolution, or reference_mesh (project onto an OBJ).",
    )
    reference_mesh: str | None = Field(
        default=None, description="OBJ file (m), relative to the YAML file."
    )
    appendage_lift: float = Field(
        default=0.5, ge=0, description="Outward offset of unplaced nodes per m of distance."
    )


class AssemblySpec(BaseModel):
    """The ``assembly`` section of a build-pack YAML file."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["standard_gore", "special_shape"] = Field(
        description="standard_gore (rings only) or special_shape (rings plus appendages)."
    )
    rings: list[RingSpec] = Field(default_factory=list, description="Gore rings.")
    instances: list[InstanceOverride] = Field(
        default_factory=list, description="Changes applied to selected ring instances."
    )
    parts: list[PartSpec] = Field(
        default_factory=list, description="Single piece instances outside the rings."
    )
    seams: list[SeamSpec] = Field(
        default_factory=list, description="Explicit seams between edge chains."
    )
    openings: list[OpeningSpec] = Field(
        default_factory=list, description="Declared openings made of instance edges."
    )
    mesh: MeshOptions = Field(default_factory=MeshOptions, description="Triangulation settings.")
    initial_shape: InitialShapeSpec = Field(
        default_factory=InitialShapeSpec, description="Initial 3D guess settings."
    )

    _base_dir: Path = PrivateAttr(default_factory=Path.cwd)

    @property
    def base_dir(self) -> Path:
        """Directory that relative paths are resolved against."""
        return self._base_dir

    @model_validator(mode="after")
    def _unique_names(self) -> AssemblySpec:
        names = [r.name for r in self.rings] + [p.name for p in self.parts]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate ring/part names: {sorted(duplicates)}")
        seams = [s.name for s in self.seams]
        if len(set(seams)) != len(seams):
            raise ValueError("seam names must be unique")
        return self


def load_assembly_spec(path: str | Path) -> AssemblySpec:
    """Load the ``assembly`` section of a build-pack YAML file.

    Parameters
    ----------
    path : str or Path
        Build-pack YAML file.

    Returns
    -------
    AssemblySpec
        Validated specification.
    """
    data, _ = read_config_file(path)
    if "assembly" not in data:
        raise PatternImportError(f"{path}: missing top-level 'assembly' section")
    spec = AssemblySpec.model_validate(data["assembly"])
    spec._base_dir = Path(path).resolve().parent
    return spec
