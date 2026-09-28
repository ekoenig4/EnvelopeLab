from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from envelopelab.design import (
    DesignDocument,
    dump_design_document,
    load_design_document,
    migrate_document,
    validate_design_fabrics,
)
from envelopelab.materials import FabricLibraryRepository


@st.composite
def gore_documents(draw: st.DrawFn) -> DesignDocument:
    hole_diameter = draw(
        st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False)
    )
    overlap = draw(
        st.floats(
            min_value=0.0,
            max_value=float(hole_diameter / 2.0 - 0.01),
            allow_nan=False,
            allow_infinity=False,
        )
    )
    payload = {
        "schema_version": 1,
        "meta": {
            "name": "property-test",
            "version_id": "v1",
            "parent_id": None,
            "content_hash": None,
            "created": "2026-01-01T00:00:00Z",
            "modified": "2026-01-01T00:00:00Z",
        },
        "envelope_type": "gore",
        "gores": {
            "count": draw(st.integers(min_value=3, max_value=40)),
            "meridian_profile_control_points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 2.0}],
            "panel_rows": [{"letter": "A", "finished_height": 10.0}],
            "mouth_diameter": 25.0,
            "crown_ring": 5.0,
            "parachute_hole_diameter": hole_diameter,
            "seal_overlap": overlap,
        },
        "zones": {"zone-A": "ripstop_nylon"},
        "tapes": {
            "vertical": {"class": "V", "width": 2.0, "strength": 100.0},
            "horizontal": {"class": "H", "width": 2.0, "strength": 100.0},
            "rim": {"class": "R", "width": 3.0, "strength": 120.0},
            "hole": {"class": "O", "width": 1.0, "strength": 80.0},
        },
        "seam_types": [
            {"name": "flat", "allowance": 1.5, "rows_of_stitching": 2, "efficiency": 0.8}
        ],
        "features": [],
        "operating": {
            "ambient_temperature": 20.0,
            "ambient_pressure": 101325.0,
            "altitude": 0.0,
            "internal_temperature": 95.0,
            "payload_mass": 30.0,
        },
        "scale_variants": [],
        "rigging": {
            "crown_line": "crown",
            "red_line": "red",
            "flying_wires": ["wire-1"],
            "parachute_confluence_centering": "centered",
        },
    }
    return DesignDocument.model_validate(payload)


@given(gore_documents())
def test_round_trip_is_lossless_and_hash_stable(document: DesignDocument) -> None:
    serialized = dump_design_document(document)
    loaded = load_design_document(serialized)
    reserialized = dump_design_document(loaded)

    assert json.loads(serialized) == json.loads(reserialized)
    assert loaded.meta.content_hash == loaded.compute_content_hash()


def test_validation_rejects_negative_sizes() -> None:
    payload = {
        "schema_version": 1,
        "meta": {
            "name": "invalid",
            "version_id": "v1",
            "parent_id": None,
            "content_hash": None,
            "created": "2026-01-01T00:00:00Z",
            "modified": "2026-01-01T00:00:00Z",
        },
        "envelope_type": "gore",
        "gores": {
            "count": 6,
            "meridian_profile_control_points": [{"x": 0.0, "y": 0.0}],
            "panel_rows": [{"letter": "A", "finished_height": -1.0}],
            "mouth_diameter": 10.0,
            "crown_ring": 4.0,
            "parachute_hole_diameter": 2.0,
            "seal_overlap": 0.5,
        },
        "zones": {"zone-A": "ripstop_nylon"},
        "tapes": {
            "vertical": {"class": "V", "width": 2.0, "strength": 100.0},
            "horizontal": {"class": "H", "width": 2.0, "strength": 100.0},
            "rim": {"class": "R", "width": 3.0, "strength": 120.0},
            "hole": {"class": "O", "width": 1.0, "strength": 80.0},
        },
        "seam_types": [
            {"name": "flat", "allowance": 1.5, "rows_of_stitching": 2, "efficiency": 0.8}
        ],
        "features": [],
        "operating": {
            "ambient_temperature": 20.0,
            "ambient_pressure": 101325.0,
            "altitude": 0.0,
            "internal_temperature": 95.0,
            "payload_mass": 30.0,
        },
        "scale_variants": [],
        "rigging": {
            "crown_line": "crown",
            "red_line": "red",
            "flying_wires": ["wire-1"],
            "parachute_confluence_centering": "centered",
        },
    }
    with pytest.raises(ValidationError):
        DesignDocument.model_validate(payload)


def test_validation_rejects_overlap_and_low_gore_count() -> None:
    payload = {
        "schema_version": 1,
        "meta": {
            "name": "invalid",
            "version_id": "v1",
            "parent_id": None,
            "content_hash": None,
            "created": "2026-01-01T00:00:00Z",
            "modified": "2026-01-01T00:00:00Z",
        },
        "envelope_type": "gore",
        "gores": {
            "count": 2,
            "meridian_profile_control_points": [{"x": 0.0, "y": 0.0}],
            "panel_rows": [{"letter": "A", "finished_height": 1.0}],
            "mouth_diameter": 10.0,
            "crown_ring": 4.0,
            "parachute_hole_diameter": 2.0,
            "seal_overlap": 1.0,
        },
        "zones": {"zone-A": "ripstop_nylon"},
        "tapes": {
            "vertical": {"class": "V", "width": 2.0, "strength": 100.0},
            "horizontal": {"class": "H", "width": 2.0, "strength": 100.0},
            "rim": {"class": "R", "width": 3.0, "strength": 120.0},
            "hole": {"class": "O", "width": 1.0, "strength": 80.0},
        },
        "seam_types": [
            {"name": "flat", "allowance": 1.5, "rows_of_stitching": 2, "efficiency": 0.8}
        ],
        "features": [],
        "operating": {
            "ambient_temperature": 20.0,
            "ambient_pressure": 101325.0,
            "altitude": 0.0,
            "internal_temperature": 95.0,
            "payload_mass": 30.0,
        },
        "scale_variants": [],
        "rigging": {
            "crown_line": "crown",
            "red_line": "red",
            "flying_wires": ["wire-1"],
            "parachute_confluence_centering": "centered",
        },
    }
    with pytest.raises(ValidationError):
        DesignDocument.model_validate(payload)


def test_validation_rejects_unknown_fabric_id() -> None:
    repo = FabricLibraryRepository()
    repo.seed_example_data()
    payload = {
        "schema_version": 1,
        "meta": {
            "name": "unknown-fabric",
            "version_id": "v1",
            "parent_id": None,
            "content_hash": None,
            "created": "2026-01-01T00:00:00Z",
            "modified": "2026-01-01T00:00:00Z",
        },
        "envelope_type": "gore",
        "gores": {
            "count": 8,
            "meridian_profile_control_points": [{"x": 0.0, "y": 0.0}],
            "panel_rows": [{"letter": "A", "finished_height": 1.0}],
            "mouth_diameter": 10.0,
            "crown_ring": 4.0,
            "parachute_hole_diameter": 2.0,
            "seal_overlap": 0.5,
        },
        "zones": {"zone-A": "not_real"},
        "tapes": {
            "vertical": {"class": "V", "width": 2.0, "strength": 100.0},
            "horizontal": {"class": "H", "width": 2.0, "strength": 100.0},
            "rim": {"class": "R", "width": 3.0, "strength": 120.0},
            "hole": {"class": "O", "width": 1.0, "strength": 80.0},
        },
        "seam_types": [
            {"name": "flat", "allowance": 1.5, "rows_of_stitching": 2, "efficiency": 0.8}
        ],
        "features": [],
        "operating": {
            "ambient_temperature": 20.0,
            "ambient_pressure": 101325.0,
            "altitude": 0.0,
            "internal_temperature": 95.0,
            "payload_mass": 30.0,
        },
        "scale_variants": [],
        "rigging": {
            "crown_line": "crown",
            "red_line": "red",
            "flying_wires": ["wire-1"],
            "parachute_confluence_centering": "centered",
        },
    }
    document = DesignDocument.model_validate(payload)

    with pytest.raises(ValueError, match="unknown fabric"):
        validate_design_fabrics(document, repo.known_fabric_ids())


def test_migration_upgrades_v0_fixture() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "design_v0.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    migrated = migrate_document(fixture)
    loaded = load_design_document(json.dumps(migrated))

    assert loaded.schema_version == 1
    assert loaded.meta.content_hash is not None
