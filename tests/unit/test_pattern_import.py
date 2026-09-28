from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import Entity, PackFactory, default_import, panel_entities, rect
from pydantic import ValidationError

from envelopelab.assembly.pieces import build_finished_piece
from envelopelab.geometry.polygon import signed_area
from envelopelab.io.pattern_import import (
    ImportMapping,
    ImportWarning,
    LayerMap,
    PatternImportError,
    import_patterns,
    load_mapping,
)


def _import(path: Path):  # type: ignore[no-untyped-def]
    return import_patterns(load_mapping(path))


def test_layer_roles_are_mapped_case_insensitively() -> None:
    layers = LayerMap(cut=["Cut"], sew=["SEW"], label=["txt"], ignore=["0"])
    assert layers.role_of("CUT") == "cut"
    assert layers.role_of("sew") == "sew"
    assert layers.role_of("TXT") == "label"
    assert layers.role_of("0") == "ignore"
    assert layers.role_of("OTHER") is None


def test_layer_in_two_roles_is_rejected() -> None:
    with pytest.raises(ValidationError, match="both cut and sew"):
        LayerMap(cut=["A"], sew=["a"])


def test_invalid_label_regex_is_rejected() -> None:
    with pytest.raises(ValidationError, match="invalid label pattern"):
        ImportMapping.model_validate(default_import(labels=[{"pattern": "PANEL (?P<panel>"}]))


def test_entities_sorted_by_layer_role_and_unknown_layers_warned(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 1000, 800, "PANEL A x4")
    entities += [
        ("JUNK", "poly", rect(0, 0, 10, 10)),
        ("0", "poly", rect(0, 0, 10, 10)),
        ("FEAT", "circle", ((500, 400), 100)),
    ]
    cfg = default_import()
    cfg["layers"]["ignore"] = ["0"]
    result = _import(make_pack(entities, cfg))
    (piece,) = result.pieces
    assert piece.piece_id == "A"
    assert piece.quantity == 4
    assert piece.sew is not None
    assert len(piece.entities["feature"]) == 1
    codes = [(w.code, w.message) for w in result.warnings]
    assert any(code == "unknown_layer" and "'JUNK'" in msg for code, msg in codes)
    assert not any("'0'" in msg for _, msg in codes)


def test_units_are_converted_to_metres(make_pack: PackFactory) -> None:
    result = _import(make_pack(panel_entities(0, 1000, 800, "PANEL A x1")))
    piece = result.pieces[0]
    assert piece.sew is not None
    assert abs(signed_area(piece.sew.points)) == pytest.approx(0.8)
    assert result.sources[0].units == "mm"


def test_inch_drawing(make_pack: PackFactory) -> None:
    entities = [("CUT", "poly", rect(0, 0, 10, 10)), ("TEXT", "text", ("PANEL A x1", (5, 5)))]
    result = _import(make_pack(entities, insunits=1))
    assert abs(signed_area(result.pieces[0].cut.points)) == pytest.approx(0.254**2)


def test_unitless_drawing_requires_explicit_units(make_pack: PackFactory) -> None:
    path = make_pack(panel_entities(0, 1000, 800, "PANEL A x1"), insunits=0)
    with pytest.raises(PatternImportError, match="set 'units'"):
        _import(path)
    cfg = default_import(units="mm")
    result = _import(make_pack(panel_entities(0, 1000, 800, "PANEL A x1"), cfg, insunits=0))
    assert result.sources[0].units == "mm"


def test_mapping_units_override_header_with_warning(make_pack: PackFactory) -> None:
    cfg = default_import(units="cm")
    result = _import(make_pack(panel_entities(0, 100, 80, "PANEL A x1"), cfg))
    assert result.sources[0].scale_to_m == pytest.approx(0.01)
    assert any(w.code == "units" for w in result.warnings)


def test_label_regex_groups_and_template(make_pack: PackFactory) -> None:
    cfg = default_import(
        labels=[
            {
                "pattern": r"^SKIN (?P<side>[LR]) x(?P<quantity>\d+)(?P<mirror> MIRROR)?$",
                "piece_id": "skin_{side}",
                "kind": "appendage",
            }
        ]
    )
    entities = panel_entities(0, 500, 500, "SKIN L x2 MIRROR") + panel_entities(
        1000, 500, 500, "SKIN R x3"
    )
    result = _import(make_pack(entities, cfg))
    by_id = {p.piece_id: p for p in result.pieces}
    assert set(by_id) == {"skin_L", "skin_R"}
    assert by_id["skin_L"].mirrored and by_id["skin_L"].quantity == 2
    assert not by_id["skin_R"].mirrored and by_id["skin_R"].quantity == 3
    assert by_id["skin_L"].kind == "appendage"


def test_missing_label_generates_id_and_warning(make_pack: PackFactory) -> None:
    result = _import(make_pack(panel_entities(0, 500, 500, "not a label")))
    (piece,) = result.pieces
    assert piece.piece_id.startswith("pack#")
    assert any(w.code == "missing_label" for w in result.warnings)


def test_ambiguous_labels_warn(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 500, 500, "PANEL A x1") + [
        ("TEXT", "text", ("PANEL B x1", (100, 100)))
    ]
    result = _import(make_pack(entities))
    assert any(w.code == "ambiguous_label" for w in result.warnings)


def test_sew_line_extraction_and_provenance(make_pack: PackFactory) -> None:
    path = make_pack(panel_entities(0, 1000, 800, "PANEL A x1"))
    result = _import(path)
    piece = result.pieces[0]
    assert piece.sew is not None
    prov = piece.sew.provenance
    assert prov.source_file == "pack.dxf"
    assert prov.layer == "SEW"
    assert prov.entity_type == "LWPOLYLINE"
    assert prov.entity_id  # DXF handle
    assert prov.mapping_version == "test/1"
    assert piece.cut.provenance.layer == "CUT"


def test_exact_edge_piece_gets_its_sew_line(make_pack: PackFactory) -> None:
    outline = rect(0, 0, 400, 300)
    entities = [
        ("CUT", "poly", outline),
        ("SEW", "poly", outline),
        ("TEXT", "text", ("PANEL X x1", (200, 150))),
    ]
    piece = _import(make_pack(entities)).pieces[0]
    assert piece.sew is not None


def test_cut_only_pack_insets_by_allowance(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 1000, 800, "PANEL A x1", sew=False)
    result = _import(make_pack(entities))
    raw = result.pieces[0]
    assert raw.sew is None
    warnings: list[ImportWarning] = []
    piece = build_finished_piece(raw, warnings)
    assert piece.outline_source == "inset"
    lo, hi = piece.outline.min(axis=0), piece.outline.max(axis=0)
    assert (hi - lo) == pytest.approx([1.0, 0.8], abs=1e-9)
    assert piece.finished_area == pytest.approx(0.8)
    assert piece.cut_area == pytest.approx(1.05 * 0.85)


def test_measured_allowance_from_sew_line(make_pack: PackFactory) -> None:
    raw = _import(make_pack(panel_entities(0, 1000, 800, "PANEL A x1", allowance=30))).pieces[0]
    piece = build_finished_piece(raw, [])
    assert piece.measured_allowance == pytest.approx(0.030)


def test_line_segments_are_chained_into_an_outline(make_pack: PackFactory) -> None:
    pts = rect(0, 0, 600, 400)
    entities: list[Entity] = [("CUT", "line", (pts[k], pts[(k + 1) % 4])) for k in (0, 2, 1, 3)]
    entities.append(("TEXT", "text", ("PANEL L x1", (300, 200))))
    result = _import(make_pack(entities))
    (piece,) = result.pieces
    assert piece.cut.closed
    assert abs(signed_area(piece.cut.points)) == pytest.approx(0.24)
    assert piece.cut.provenance.entity_id.count("+") == 3


def test_open_cut_line_is_reported(make_pack: PackFactory) -> None:
    entities = [("CUT", "open", [(0, 0), (100, 0), (100, 100)])]
    result = _import(make_pack(entities))
    assert not result.pieces
    assert any(w.code == "invalid_geometry" and w.severity == "error" for w in result.warnings)


def test_inner_cut_loop_is_a_hole(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 1000, 800, None)
    entities.append(("TEXT", "text", ("PANEL H x1", (200, 200))))
    entities.append(("CUT", "circle", ((500, 400), 100)))
    entities.append(("SEW", "circle", ((500, 400), 125)))
    raw = _import(make_pack(entities)).pieces[0]
    assert len(raw.holes) == 1
    assert raw.holes[0].sew is not None
    piece = build_finished_piece(raw, [])
    assert piece.finished_area == pytest.approx(0.8 - np.pi * 0.125**2, rel=1e-4)


def test_circle_feature_keeps_radius(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 1000, 800, "PANEL C x1") + [("FEAT", "circle", ((500, 400), 250))]
    feature = _import(make_pack(entities)).pieces[0].entities["feature"][0]
    assert feature.circle is not None
    assert feature.circle[2] == pytest.approx(0.25)
    # Flattening with chord error f shortens a circle by about 2 pi f / 3 (0.1 mm for the
    # default f = 0.05 mm), whatever its radius.
    closed = np.vstack([feature.points, feature.points[:1]])
    perimeter = float(np.sum(np.hypot(*np.diff(closed, axis=0).T)))
    assert perimeter == pytest.approx(2 * np.pi * 0.25, abs=1.5e-4)
    assert perimeter < 2 * np.pi * 0.25


def test_grain_from_grain_layer(make_pack: PackFactory) -> None:
    cfg = default_import()
    cfg["layers"]["grain"] = ["GRAIN"]
    entities = panel_entities(0, 1000, 800, "PANEL G x1") + [
        ("GRAIN", "line", ((500, 100), (500, 700)))
    ]
    piece = _import(make_pack(entities, cfg)).pieces[0]
    assert piece.grain == pytest.approx((0.0, 1.0))
    assert piece.grain_source == "grain layer"


def test_missing_grain_is_an_explicit_assumption(make_pack: PackFactory) -> None:
    cfg = default_import()
    del cfg["default_grain"]
    result = _import(make_pack(panel_entities(0, 100, 100, "PANEL A x1"), cfg))
    assert result.pieces[0].grain is None
    assert any(w.code == "assumption" and "grain" in w.message for w in result.warnings)


def test_per_file_layer_override(make_pack: PackFactory) -> None:
    entities = [
        ("OUTLINE", "poly", rect(-25, -25, 550, 550)),
        ("TEXT", "text", ("PANEL Z x1", (250, 250))),
    ]
    cfg = default_import(
        sources=[{"file": "pack.dxf", "layers": {"cut": ["OUTLINE"], "label": ["TEXT"]}}]
    )
    result = _import(make_pack(entities, cfg))
    assert result.piece_ids == ["Z"]


def test_up_axis_rotation(make_pack: PackFactory) -> None:
    # Drawn sideways: the envelope "up" direction is the drawing +x axis.
    entities = [
        ("CUT", "poly", rect(0, 0, 1000, 400)),
        ("TEXT", "text", ("PANEL R x1", (500, 200))),
    ]
    cfg = default_import(up_axis="+x")
    cut = _import(make_pack(entities, cfg)).pieces[0].cut.points
    extent = cut.max(axis=0) - cut.min(axis=0)
    assert extent == pytest.approx([0.4, 1.0])


def test_duplicate_piece_ids_are_renamed(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 500, 500, "PANEL A x1") + panel_entities(
        1000, 500, 500, "PANEL A x1"
    )
    result = _import(make_pack(entities))
    assert sorted(result.piece_ids) == ["A", "A~2"]
    assert any(w.code == "duplicate_piece_id" for w in result.warnings)


def test_mapping_file_requires_import_section(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    path.write_text("assembly: {}\n", encoding="utf-8")
    with pytest.raises(PatternImportError, match="import"):
        load_mapping(path)


def test_content_hash_changes_with_the_dxf(make_pack: PackFactory) -> None:
    first = _import(make_pack(panel_entities(0, 500, 500, "PANEL A x1"))).content_hash
    second = _import(make_pack(panel_entities(0, 600, 500, "PANEL A x1"))).content_hash
    assert first != second
