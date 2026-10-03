"""Design document schema (``schema_version`` 3) and its migrations.

A design document holds everything a builder decides: the envelope shape (standard gores
or a special shape), materials, tapes, seams, features, operating conditions, the
parachute (deflation port) that closes the crown opening, the rigging (red line and
flying wires to the basket) and optional turning vents. All values are SI (m, N, kg, K,
Pa) except the few angles marked as degrees. Every material value added in version 2
carries a source tag (:class:`TaggedValue`).

Version history: 0 (no ``meta``), 1 (rigging names only), 2 (parachute, red-line,
flying-wire and turning-vent placement, row zones, crown and centre rings, scoop; see
``docs/adr/ADR-0010-rigging-schema-v2.md`` and ``ADR-0011``), 3 (gore loft, the lobe
bulge of the fabric between load tapes; ``docs/adr/ADR-0014-gore-loft.md``).
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CURRENT_SCHEMA_VERSION = 3

SourceTagName = Literal["datasheet", "measured", "assumed"]


class SourceValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    source: str


class DesignMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version_id: str
    parent_id: str | None = None
    content_hash: str | None = None
    created: datetime
    modified: datetime


class MeridianControlPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class PanelRow(BaseModel):
    """One horizontal panel row of every gore.

    Attributes
    ----------
    letter : str
        Row letter (mouth first).
    finished_height : float
        Finished height along the tape, m.
    zone : str, optional
        Material zone (key of ``zones``), e.g. ``mouth`` for a Nomex row; a pattern
        annotation of the row overrides it; default the first zone.
    """

    model_config = ConfigDict(extra="forbid")

    letter: str = Field(min_length=1, max_length=4)
    finished_height: float = Field(gt=0)
    zone: str | None = None


class LoftPoint(BaseModel):
    r"""One station of a gore loft (lobe bulge between load tapes).

    Attributes
    ----------
    station : float
        Position along the load tape as a fraction of the tape length from the mouth
        (0) to the top opening (1), dimensionless.
    ratio : float
        Lobe-radius ratio :math:`k = \rho / r`: radius of the fabric lobe between two
        adjacent tapes over the tape radius, dimensionless. 1 is the small-bulge gore
        (lobe on the circle through the tapes); larger is flatter, smaller is fuller.
    """

    model_config = ConfigDict(extra="forbid")

    station: float = Field(ge=0, le=1)
    ratio: float = Field(gt=0, allow_inf_nan=False)


class GoreSpec(BaseModel):
    """Standard-gore envelope: meridian, gores, panel rows and openings (m).

    ``loft`` sets the lobe bulge of every gore (:class:`LoftPoint`), interpolated linearly
    between stations and constant beyond the first and last; ``None`` is the small-bulge
    gore (ratio 1 everywhere).
    """

    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=3)
    meridian_profile_control_points: list[MeridianControlPoint]
    panel_rows: list[PanelRow]
    mouth_diameter: float = Field(gt=0)
    crown_ring: float = Field(gt=0)
    parachute_hole_diameter: float = Field(gt=0)
    seal_overlap: float = Field(ge=0)
    loft: list[LoftPoint] | None = None

    @model_validator(mode="after")
    def validate_overlap(self) -> GoreSpec:
        if self.seal_overlap >= self.parachute_hole_diameter / 2:
            raise ValueError("seal overlap must be less than hole radius")
        return self

    @model_validator(mode="after")
    def validate_loft(self) -> GoreSpec:
        if self.loft is None:
            return self
        if not self.loft:
            raise ValueError("a loft needs at least one station (or none for small bulge)")
        stations = [p.station for p in self.loft]
        if any(b <= a for a, b in zip(stations, stations[1:], strict=False)):
            raise ValueError("loft stations must be strictly increasing")
        limit = math.sin(math.pi / self.count)
        low = min(p.ratio for p in self.loft)
        if low < limit:
            raise ValueError(
                f"loft ratio {low:g} is below sin(pi/N) = {limit:.4f} for {self.count} gores "
                "(a lobe cannot be more than a half circle)"
            )
        return self


class SeamCurve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_a: str
    panel_b: str
    points: list[MeridianControlPoint]


class SpecialSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mesh_reference: str
    seam_curves: list[SeamCurve]
    panel_list: list[str]


class TapeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tape_class: str = Field(alias="class")
    width: float = Field(gt=0)
    strength: float = Field(gt=0)


class TapeSet(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    vertical: TapeSpec
    horizontal: TapeSpec
    rim: TapeSpec
    hole: TapeSpec


class SeamType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    allowance: float = Field(ge=0)
    rows_of_stitching: int = Field(ge=1)
    efficiency: float = Field(gt=0, le=1)


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["ram_air_pod", "tubular_appendage", "applique", "vent", "hole"]
    host_panels: list[str]
    feed_holes: list[str] = Field(default_factory=list)
    tapes: list[str] = Field(default_factory=list)
    notes: str | None = None


class OperatingConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ambient_temperature: float
    ambient_pressure: float = Field(gt=0)
    altitude: float
    internal_temperature: float
    payload_mass: float = Field(ge=0)


class ScaleVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_k: float = Field(gt=0)
    model_fabric_override: dict[str, str] = Field(default_factory=dict)
    fixed_size_overrides: dict[str, float] = Field(default_factory=dict)


class TaggedValue(BaseModel):
    """A value with its provenance.

    Attributes
    ----------
    value : float
        Value in the SI unit stated by the field that holds it.
    source : {"datasheet", "measured", "assumed"}
        Provenance tag.
    note : str
        Reference or remark (datasheet name, regulation, "generic value").
    """

    model_config = ConfigDict(extra="forbid")

    value: float
    source: SourceTagName
    note: str = ""


class LineSpec(BaseModel):
    """A line or cable class (shroud, centralising, red line, flying wire, control line).

    Attributes
    ----------
    line_class : str
        Name of the line class (alias ``class``).
    strength : TaggedValue
        Minimum breaking strength, N.
    linear_mass : TaggedValue
        Mass per length, kg/m.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    line_class: str = Field(alias="class")
    strength: TaggedValue
    linear_mass: TaggedValue

    @model_validator(mode="after")
    def validate_values(self) -> LineSpec:
        if self.strength.value <= 0:
            raise ValueError("line strength must be positive")
        if self.linear_mass.value < 0:
            raise ValueError("line linear mass must be non-negative")
        return self


class RingSpec(BaseModel):
    """A load ring (crown ring at the opening rim, centre ring of the parachute).

    Attributes
    ----------
    ring_class : str
        Ring description (alias ``class``), e.g. "aluminium rod ring 8 mm".
    linear_mass : TaggedValue
        Mass per length of the ring, kg/m.
    strength : TaggedValue
        Allowable axial (hoop) force of the ring section, N.
    required_safety_factor : TaggedValue
        Minimum strength-to-limit-load ratio, dimensionless.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ring_class: str = Field(alias="class")
    linear_mass: TaggedValue
    strength: TaggedValue
    required_safety_factor: TaggedValue


class ParachuteSpec(BaseModel):
    """The parachute (deflation port) that closes the crown opening from inside.

    The parachute's diameter follows from the envelope: it covers the parachute hole
    (``gores.parachute_hole_diameter``) and overlaps the envelope by ``gores.seal_overlap``
    measured along the fabric. One shroud line and one centralising line leave each
    radial seam of the parachute.

    Attributes
    ----------
    panel_count : int
        Radial parachute panels (and shroud lines), >= 3.
    billow : float
        Rise of the inflated cap over the hole, as a fraction of the hole diameter
        (0 = flat), dimensionless.
    zone : str, optional
        Material zone of the parachute fabric; default the design's first zone.
    shroud_attachment : float
        Distance along the envelope load tape from the parachute edge down to where each
        shroud line is attached, m.
    centralizing_depth : float
        Depth of the centralising-line confluence (red-line attachment) below the crown
        opening, m.
    shroud_line, centralizing_line : LineSpec
        Line classes.
    crown_ring : RingSpec, optional
        Ring sewn into the rim of the crown opening (its diameter is the opening's).
    centre_ring : RingSpec, optional
        Ring at the parachute apex where the radial tapes meet and the crown line is
        attached; the parachute panels end at it.
    centre_ring_diameter : float, optional
        m; required with ``centre_ring``.
    """

    model_config = ConfigDict(extra="forbid")

    panel_count: int = Field(ge=3)
    billow: float = Field(ge=0.0, le=0.5)
    zone: str | None = None
    shroud_attachment: float = Field(gt=0.0)
    centralizing_depth: float = Field(gt=0.0)
    shroud_line: LineSpec
    centralizing_line: LineSpec
    crown_ring: RingSpec | None = None
    centre_ring: RingSpec | None = None
    centre_ring_diameter: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def validate_centre_ring(self) -> ParachuteSpec:
        if self.centre_ring is not None and self.centre_ring_diameter is None:
            raise ValueError("a centre ring needs centre_ring_diameter")
        return self


class ScoopSpec(BaseModel):
    """A scoop: fabric hanging below the mouth over consecutive gores.

    Attributes
    ----------
    first_gore : int
        First gore (1..N) the scoop hangs from.
    gore_count : int
        Consecutive gores it spans (N: a full skirt).
    height : float
        Vertical depth below the mouth, m.
    flare_deg : float
        Outward angle of the scoop from the vertical, degrees (boundary format).
    zone : str, optional
        Material zone; default the mouth row's zone.
    """

    model_config = ConfigDict(extra="forbid")

    first_gore: int = Field(ge=1)
    gore_count: int = Field(ge=1)
    height: float = Field(gt=0.0)
    flare_deg: float = Field(default=10.0, ge=0.0, lt=60.0)
    zone: str | None = None


class RedLineSpec(BaseModel):
    """The red line (deflation line) from the parachute confluence to the basket.

    Attributes
    ----------
    name : str
        Line name printed on the rigging sheet.
    guide_seam : int
        Vertical load tape (seam number, 1..N) the line is led down; its guide ring sits at
        the mouth on that tape.
    spare_length : float
        Extra length below the basket attachment for handling and tie-off, m.
    line : LineSpec
        Line class.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = "red line"
    guide_seam: int = Field(ge=1)
    spare_length: float = Field(ge=0.0)
    line: LineSpec


class FlyingWireSpec(BaseModel):
    """Flying wires from the mouth load tapes to the basket's burner frame.

    The load tapes are gathered in equal groups; each group meets at a carabiner (crow's
    foot) ``crows_foot_drop`` below the mouth, and one flying wire runs from each
    carabiner to the nearest frame attachment point.

    Attributes
    ----------
    count : int
        Flying wires, >= 3; the gore count must be a multiple.
    frame_points : int
        Attachment points on the burner frame (4 for a square frame).
    frame_radius : float
        Horizontal distance of the frame attachment points from the envelope axis, m.
    frame_drop : float
        Height of the mouth above the frame attachment points, m.
    frame_azimuth_deg : float
        Azimuth of the first frame point from seam N (degrees, boundary format).
    crows_foot_drop : float
        Height of the mouth above the carabiners, m (0: tapes end at the mouth).
    wire : LineSpec
        Cable class.
    """

    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=3)
    frame_points: int = Field(default=4, ge=1)
    frame_radius: float = Field(ge=0.0)
    frame_drop: float = Field(gt=0.0)
    frame_azimuth_deg: float = 45.0
    crows_foot_drop: float = Field(ge=0.0)
    wire: LineSpec


class TurningVentSpec(BaseModel):
    """A turning (rotation) vent: a vertical seam left open over some rows.

    Attributes
    ----------
    name : str
        Vent name.
    seam : int
        Vertical seam number (1..N); seam k joins gore k and gore k+1.
    rows : list of str
        Consecutive panel rows over which the seam is open.
    direction : {"clockwise", "counterclockwise"}
        Rotation the vent's jet gives the balloon, seen from above.
    opening_width : float
        Gap width when the vent is pulled fully open, m.
    discharge_coefficient : TaggedValue
        Orifice discharge coefficient, dimensionless.
    control_line : LineSpec
        Line from the vent to the basket.
    simulate_open : bool
        Leave the seam open in the structural model (vent open); default closed.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    seam: int = Field(ge=1)
    rows: list[str] = Field(min_length=1)
    direction: Literal["clockwise", "counterclockwise"]
    opening_width: float = Field(gt=0.0)
    discharge_coefficient: TaggedValue
    control_line: LineSpec
    simulate_open: bool = False


class RiggingSpec(BaseModel):
    """Rigging: crown line, red line, flying wires and the rigging load case.

    Attributes
    ----------
    crown_line : str
        Crown line name.
    load_factor : TaggedValue
        Limit flight load factor applied to rigging loads, dimensionless.
    required_safety_factor : TaggedValue
        Minimum breaking-strength-to-limit-load ratio of lines, wires and load tapes,
        dimensionless.
    red_line : RedLineSpec, optional
    flying_wires : FlyingWireSpec, optional
    """

    model_config = ConfigDict(extra="forbid")

    crown_line: str
    load_factor: TaggedValue
    required_safety_factor: TaggedValue
    red_line: RedLineSpec | None = None
    flying_wires: FlyingWireSpec | None = None


#: Default rigging load case (14 CFR 31.23 limit load factor, 31.25(b) rigging FoS).
DEFAULT_LOAD_FACTOR = {
    "value": 1.4,
    "source": "assumed",
    "note": "minimum limit flight load factor, 14 CFR 31.23(b)",
}
DEFAULT_SAFETY_FACTOR = {
    "value": 5.0,
    "source": "assumed",
    "note": "fibrous rigging factor of safety, 14 CFR 31.25(b)",
}


class DesignDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION)
    meta: DesignMeta
    envelope_type: Literal["gore", "special"]
    gores: GoreSpec | None = None
    special: SpecialSpec | None = None
    zones: dict[str, str]
    tapes: TapeSet
    seam_types: list[SeamType]
    features: list[Feature] = Field(default_factory=list)
    operating: OperatingConditions
    scale_variants: list[ScaleVariant] = Field(default_factory=list)
    rigging: RiggingSpec
    parachute: ParachuteSpec | None = None
    turning_vents: list[TurningVentSpec] = Field(default_factory=list)
    scoop: ScoopSpec | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_older(cls, data: Any) -> Any:
        # Older documents validate through the migrations, so code and tests that build a
        # version-1 payload keep working (the content hash is checked before this step in
        # load_design_document).
        if isinstance(data, dict) and int(data.get("schema_version", 0)) < CURRENT_SCHEMA_VERSION:
            return migrate_document(data)
        return data

    @model_validator(mode="after")
    def validate_shape(self) -> DesignDocument:
        if self.envelope_type == "gore" and self.gores is None:
            raise ValueError("gore envelope_type requires gores")
        if self.envelope_type == "special" and self.special is None:
            raise ValueError("special envelope_type requires special")
        if self.schema_version != CURRENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version: {self.schema_version}")
        names = [v.name for v in self.turning_vents]
        if len(set(names)) != len(names):
            raise ValueError("turning vent names must be unique")
        return self

    def model_dump_for_hash(self) -> dict[str, Any]:
        dumped = self.model_dump(by_alias=True, mode="json")
        dumped["meta"]["content_hash"] = None
        return dumped

    def compute_content_hash(self) -> str:
        canonical_json = json.dumps(
            self.model_dump_for_hash(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return sha256(canonical_json.encode("utf-8")).hexdigest()

    def with_updated_hash(self) -> DesignDocument:
        updated = self.model_copy(deep=True)
        updated.meta.content_hash = updated.compute_content_hash()
        return updated


def _upgrade_v0_to_v1(raw: dict[str, Any]) -> dict[str, Any]:
    upgraded = dict(raw)
    now = datetime.now(UTC).isoformat()
    upgraded.setdefault(
        "meta",
        {
            "name": upgraded.get("name", "migrated-document"),
            "version_id": "v1",
            "parent_id": None,
            "content_hash": None,
            "created": now,
            "modified": now,
        },
    )
    upgraded.pop("name", None)
    upgraded["schema_version"] = 1
    return upgraded


def _upgrade_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Version 1 held rigging names only; version 2 holds placements.

    The crown-line name is kept. The red-line and flying-wire names and the
    ``parachute_confluence_centering`` text cannot become placements, so they are dropped
    and the parachute, red line and flying wires are left undefined (the editor reports
    them as missing). The rigging load case gets the documented defaults.
    """
    upgraded = dict(raw)
    rigging = dict(upgraded.get("rigging") or {})
    upgraded["rigging"] = {
        "crown_line": str(rigging.get("crown_line", "crown line")),
        "load_factor": dict(DEFAULT_LOAD_FACTOR),
        "required_safety_factor": dict(DEFAULT_SAFETY_FACTOR),
        "red_line": None,
        "flying_wires": None,
    }
    upgraded.setdefault("parachute", None)
    upgraded.setdefault("turning_vents", [])
    upgraded.setdefault("scoop", None)
    upgraded["schema_version"] = 2
    return upgraded


def _upgrade_v2_to_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """Version 3 adds the gore loft; version-2 gores are small-bulge gores (no loft)."""
    upgraded = dict(raw)
    if isinstance(upgraded.get("gores"), dict):
        upgraded["gores"] = {**upgraded["gores"], "loft": None}
    upgraded["schema_version"] = 3
    return upgraded


def migrate_document(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade raw design data to :data:`CURRENT_SCHEMA_VERSION`, one version at a time."""
    version = int(raw.get("schema_version", 0))
    upgraded = dict(raw)
    while version < CURRENT_SCHEMA_VERSION:
        if version == 0:
            upgraded = _upgrade_v0_to_v1(upgraded)
        elif version == 1:
            upgraded = _upgrade_v1_to_v2(upgraded)
        elif version == 2:
            upgraded = _upgrade_v2_to_v3(upgraded)
        else:
            raise ValueError(f"unsupported schema version: {version}")
        version += 1
    return upgraded


def _raw_hash(raw: dict[str, Any]) -> str:
    """Content hash of raw design data as written (canonical JSON, hash field cleared)."""
    data = json.loads(json.dumps(raw))
    data["meta"]["content_hash"] = None
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(text.encode("utf-8")).hexdigest()


def load_design_document(json_payload: str) -> DesignDocument:
    """Parse, migrate and validate a design document; its content hash is checked.

    A document of an older schema version is checked against the hash it was written
    with (before migration) and gets a new hash for the migrated content.

    Raises
    ------
    ValueError
        For a content-hash mismatch or an unsupported schema version.
    """
    raw = json.loads(json_payload)
    version = int(raw.get("schema_version", 0))
    if version < CURRENT_SCHEMA_VERSION:
        stored = (raw.get("meta") or {}).get("content_hash")
        if stored is not None and stored != _raw_hash(raw):
            raise ValueError("content hash mismatch")
        migrated = migrate_document(raw)
        migrated["meta"] = {**migrated["meta"], "content_hash": None}
        return DesignDocument.model_validate(migrated).with_updated_hash()
    document = DesignDocument.model_validate(raw)
    computed_hash = document.compute_content_hash()
    if document.meta.content_hash is None:
        document.meta.content_hash = computed_hash
    elif document.meta.content_hash != computed_hash:
        raise ValueError("content hash mismatch")
    return document


def dump_design_document(document: DesignDocument) -> str:
    with_hash = document.with_updated_hash()
    return json.dumps(with_hash.model_dump(by_alias=True, mode="json"), indent=2, sort_keys=True)


def validate_design_fabrics(document: DesignDocument, known_fabric_ids: set[str]) -> None:
    unknown = sorted(
        {fabric_id for fabric_id in document.zones.values() if fabric_id not in known_fabric_ids}
    )
    if unknown:
        raise ValueError(f"unknown fabric id(s): {', '.join(unknown)}")
