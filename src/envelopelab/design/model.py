from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CURRENT_SCHEMA_VERSION = 2


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
    model_config = ConfigDict(extra="forbid")

    letter: str = Field(min_length=1, max_length=4)
    finished_height: float = Field(gt=0)


class ParachuteSpec(BaseModel):
    """Flat parachute closing the crown hole (theory: docs/theory/parachute-geometry.md).

    Attributes
    ----------
    gore_count : int
        Number of parachute gores (>= 3), usually the envelope gore count.
    diameter : float
        Finished flat diameter, m; normally the hole diameter plus twice the seal overlap.
    centre_diameter : float
        Finished diameter of the centre disc the gores are sewn to, m.
    """

    model_config = ConfigDict(extra="forbid")

    gore_count: int = Field(ge=3)
    diameter: float = Field(gt=0)
    centre_diameter: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_centre(self) -> ParachuteSpec:
        if self.centre_diameter >= self.diameter:
            raise ValueError("parachute centre disc must be smaller than the parachute")
        return self


class GoreSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=3)
    meridian_profile_control_points: list[MeridianControlPoint]
    panel_rows: list[PanelRow]
    mouth_diameter: float = Field(gt=0)
    crown_ring: float = Field(gt=0)
    parachute_hole_diameter: float = Field(gt=0)
    seal_overlap: float = Field(ge=0)
    parachute: ParachuteSpec | None = None

    @model_validator(mode="after")
    def validate_overlap(self) -> GoreSpec:
        if self.seal_overlap >= self.parachute_hole_diameter / 2:
            raise ValueError("seal overlap must be less than hole radius")
        if self.parachute is not None and self.parachute.diameter <= self.parachute_hole_diameter:
            raise ValueError("the parachute must be larger than the parachute hole it closes")
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


class RiggingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crown_line: str
    red_line: str
    flying_wires: list[str]
    parachute_confluence_centering: str


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

    @model_validator(mode="after")
    def validate_shape(self) -> DesignDocument:
        if self.envelope_type == "gore" and self.gores is None:
            raise ValueError("gore envelope_type requires gores")
        if self.envelope_type == "special" and self.special is None:
            raise ValueError("special envelope_type requires special")
        return self

    def model_dump_for_hash(self) -> dict[str, Any]:
        dumped = self.model_dump(by_alias=True, mode="json")
        dumped["meta"]["content_hash"] = None
        return dumped

    def compute_content_hash(self) -> str:
        return _canonical_hash(self.model_dump_for_hash())

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
    upgraded.setdefault("schema_version", 1)
    return upgraded


def _canonical_hash(dumped: dict[str, Any]) -> str:
    canonical_json = json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def _upgrade_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """v2 adds the optional ``gores.parachute``; the content hash is recomputed.

    The stored v1 hash is checked first against the v1 canonical form (no ``parachute``
    key), so a v1 file that was changed by hand is still refused.
    """
    stored = (raw.get("meta") or {}).get("content_hash")
    if stored is not None:
        v1 = DesignDocument.model_validate({**raw, "schema_version": 1}).model_dump_for_hash()
        if isinstance(v1.get("gores"), dict):
            v1["gores"].pop("parachute", None)
        if _canonical_hash(v1) != stored:
            raise ValueError("content hash mismatch")
    upgraded = dict(raw)
    upgraded["meta"] = {**raw["meta"], "content_hash": None}
    upgraded["schema_version"] = 2
    return upgraded


def migrate_document(raw: dict[str, Any]) -> dict[str, Any]:
    version = int(raw.get("schema_version", 0))
    upgraded = dict(raw)
    while version < CURRENT_SCHEMA_VERSION:
        if version == 0:
            upgraded = _upgrade_v0_to_v1(upgraded)
        elif version == 1:
            upgraded = _upgrade_v1_to_v2(upgraded)
        else:
            raise ValueError(f"unsupported schema version: {version}")
        version += 1
    return upgraded


def load_design_document(json_payload: str) -> DesignDocument:
    raw = json.loads(json_payload)
    migrated = migrate_document(raw)
    document = DesignDocument.model_validate(migrated)
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
