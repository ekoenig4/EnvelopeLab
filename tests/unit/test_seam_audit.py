from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import (
    PackFactory,
    default_import,
    panel_entities,
    ring_assembly,
    ring_pack_entities,
)

from envelopelab.assembly.audit import audit_assembly
from envelopelab.assembly.mesh import MeshingError, sew
from envelopelab.assembly.pieces import build_finished_pieces
from envelopelab.assembly.seam_graph import Assembly, AssemblyError, build_assembly
from envelopelab.assembly.spec import load_assembly_spec
from envelopelab.io.pattern_import import import_patterns, load_mapping


def _assemble(path: Path) -> Assembly:
    pieces, _ = build_finished_pieces(import_patterns(load_mapping(path)))
    return build_assembly(load_assembly_spec(path), pieces)


def _ring(make_pack: PackFactory, **extra: Any) -> Assembly:
    entities = ring_pack_entities([("A", 1000, 800), ("B", 1000, 800)], gores=3)
    return _assemble(make_pack(entities, assembly=ring_assembly(["A", "B"], 3, **extra)))


def test_ring_seam_pairing(make_pack: PackFactory) -> None:
    assembly = _ring(make_pack)
    graph = assembly.graph
    types = [s.seam_type for s in graph.seams]
    assert types.count("horizontal_panel") == 3
    assert types.count("vertical_gore") == 6
    seam = next(s for s in graph.seams if s.seam_id == "body:v:3/1:A")
    assert [u.node_id for u in seam.side_a] == ["body/A@3:right"]
    assert [u.node_id for u in seam.side_b] == ["body/A@1:left"]
    assert all(s.orientation_check == "ok" for s in graph.seams if s.seam_type != "rim")
    audit = audit_assembly(assembly)
    assert audit.summary()["error"] == 0
    assert all(r.abs_mismatch < 1e-9 for r in audit.rows)
    assert {o.name for o in graph.openings} == {"mouth", "crown"}


def test_mismatch_beyond_tolerance_is_an_error(make_pack: PackFactory) -> None:
    # Row B is 10 mm wider than row A: the horizontal seams mismatch by 10 mm.
    entities = ring_pack_entities([("A", 1000, 800), ("B", 1010, 800)], gores=3)
    assembly = _assemble(make_pack(entities, assembly=ring_assembly(["A", "B"], 3)))
    rows = [r for r in audit_assembly(assembly).rows if r.seam_type == "horizontal_panel"]
    assert all(r.severity == "error" for r in rows)
    assert rows[0].mismatch == pytest.approx(0.010)
    assert rows[0].rel_mismatch == pytest.approx(0.010 / 1.010)
    assert rows[0].panels_a == ["body/A@1"]


def test_per_seam_tolerance(make_pack: PackFactory) -> None:
    entities = ring_pack_entities([("A", 1000, 800), ("B", 1010, 800)], gores=3)
    cfg = ring_assembly(["A", "B"], 3)
    cfg["rings"][0]["horizontal_seam"] = {"tolerance_mm": 12}
    assembly = _assemble(make_pack(entities, assembly=cfg))
    assert all(r.severity == "ok" for r in audit_assembly(assembly).rows)


def _two_panel_pack(make_pack: PackFactory, ease_mm: float | None, width_b: float) -> Path:
    entities = panel_entities(0, 1000, 800, "PANEL A x1") + panel_entities(
        2000, width_b, 800, "PANEL B x1"
    )
    seam: dict[str, Any] = {
        "name": "join",
        "type": "appendage",
        "a": [{"instance": "a", "edge": "top"}],
        "b": [{"instance": "b", "edge": "bottom"}],
    }
    if ease_mm is not None:
        seam["designed_ease_mm"] = ease_mm
    edges = ("bottom", "left", "right")
    openings = [{"name": f"open_a_{e}", "edges": [{"instance": "a", "edge": e}]} for e in edges] + [
        {"name": f"open_b_{e}", "edges": [{"instance": "b", "edge": e}]}
        for e in ("top", "left", "right")
    ]
    assembly = {
        "kind": "special_shape",
        "parts": [{"name": "a", "piece": "A"}, {"name": "b", "piece": "B"}],
        "seams": [seam],
        "openings": openings,
        "mesh": {"target_edge_length_mm": 200},
    }
    return make_pack(entities, assembly=assembly)


def test_designed_ease_is_not_an_error(make_pack: PackFactory) -> None:
    without = audit_assembly(_assemble(_two_panel_pack(make_pack, None, 1040))).rows[0]
    assert without.severity == "error"
    assert without.mismatch == pytest.approx(0.040)
    row = audit_assembly(_assemble(_two_panel_pack(make_pack, 40, 1040))).rows[0]
    assert row.severity == "info"
    assert row.designed_ease == pytest.approx(0.040)
    assert row.abs_mismatch == pytest.approx(0.0, abs=1e-9)
    assert any("designed ease" in f for f in row.findings)


def test_designed_ease_reaches_the_mesh_seam_data(make_pack: PackFactory) -> None:
    assembly = _assemble(_two_panel_pack(make_pack, 40, 1040))
    mesh = sew(assembly)
    pairs = mesh.seam_pairs["join"]
    assert pairs[0, 2] == pytest.approx(1.0)  # side A length
    assert pairs[0, 3] == pytest.approx(1.04)  # side B length
    seam = next(s for s in assembly.graph.seams if s.seam_id == "join")
    assert seam.props.designed_ease_m == pytest.approx(0.040)


def test_unmatched_edge(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 1000, 800, "PANEL A x1")
    assembly = _assemble(
        make_pack(
            entities, assembly={"kind": "special_shape", "parts": [{"name": "a", "piece": "A"}]}
        )
    )
    findings = audit_assembly(assembly).edge_findings
    assert {f.node_id for f in findings if f.kind == "unmatched_edge"} == {
        "a:bottom",
        "a:right",
        "a:top",
        "a:left",
    }
    assert all(f.severity == "error" for f in findings)


def test_duplicate_assignment(make_pack: PackFactory) -> None:
    entities = ring_pack_entities([("A", 1000, 800)], gores=3)
    cfg = ring_assembly(["A"], 3)
    cfg["seams"] = [
        {
            "name": "extra",
            "type": "reinforcement",
            "a": [{"instance": "body/A@1", "edge": "right"}],
            "b": [{"instance": "body/A@3", "edge": "left"}],
        }
    ]
    assembly = _assemble(make_pack(entities, assembly=cfg))
    findings = [
        f for f in audit_assembly(assembly).edge_findings if f.kind == "duplicate_assignment"
    ]
    assert {f.node_id for f in findings} == {"body/A@1:right", "body/A@3:left"}
    with pytest.raises(MeshingError, match="already sewn"):
        sew(assembly)


def test_reversed_orientation_error(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 1000, 800, "PANEL T x1")
    cfg = {
        "kind": "special_shape",
        "parts": [{"name": "tube", "piece": "T"}],
        "seams": [
            {
                "name": "close",
                "type": "closing",
                "orientation": "same",
                "a": [{"instance": "tube", "edge": "right"}],
                "b": [{"instance": "tube", "edge": "left"}],
            }
        ],
    }
    assembly = _assemble(make_pack(entities, assembly=cfg))
    seam = next(s for s in assembly.graph.seams if s.seam_id == "close")
    assert seam.orientation_check == "error"
    row = next(r for r in audit_assembly(assembly).rows if r.seam_id == "close")
    assert row.severity == "error"
    assert any("reversed orientation" in f for f in row.findings)


def test_incompatible_seam_allowances(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 1000, 800, "PANEL A x1", allowance=25) + panel_entities(
        3000, 1000, 800, "PANEL B x1", allowance=50
    )
    cfg = {
        "kind": "special_shape",
        "parts": [{"name": "a", "piece": "A"}, {"name": "b", "piece": "B"}],
        "seams": [
            {
                "name": "join",
                "type": "appendage",
                "a": [{"instance": "a", "edge": "top"}],
                "b": [{"instance": "b", "edge": "bottom"}],
            },
            {
                "name": "join_declared",
                "type": "appendage",
                "allowance_mm": 25,
                "a": [{"instance": "a", "edge": "right"}],
                "b": [{"instance": "b", "edge": "left"}],
            },
            {
                "name": "join_per_side",
                "type": "appendage",
                "allowance_a_mm": 25,
                "allowance_b_mm": 50,
                "a": [{"instance": "a", "edge": "left"}],
                "b": [{"instance": "b", "edge": "right"}],
            },
        ],
    }
    rows = {r.seam_id: r for r in audit_assembly(_assemble(make_pack(entities, assembly=cfg))).rows}
    assert rows["join"].severity == "warning"
    assert any("incompatible seam allowances" in f for f in rows["join"].findings)
    assert rows["join_declared"].severity == "warning"
    assert any("side B measures 50.0 mm" in f for f in rows["join_declared"].findings)
    assert rows["join_per_side"].severity == "ok"
    assert rows["join"].allowance_a == pytest.approx(0.025)
    assert rows["join"].allowance_b == pytest.approx(0.050)


def test_unknown_edge_name_is_explained(make_pack: PackFactory) -> None:
    entities = panel_entities(0, 1000, 800, "PANEL A x1")
    cfg = {
        "kind": "special_shape",
        "parts": [{"name": "a", "piece": "A"}],
        "seams": [
            {
                "name": "bad",
                "type": "closing",
                "a": [{"instance": "a", "edge": "e7"}],
                "b": [{"instance": "a", "edge": "left"}],
            }
        ],
    }
    with pytest.raises(AssemblyError, match="no edge 'e7'"):
        _assemble(make_pack(entities, assembly=cfg))


def test_seam_graph_exports(make_pack: PackFactory) -> None:
    graph = _ring(make_pack).graph
    csv_text = graph.to_csv()
    assert csv_text.splitlines()[0].startswith("seam_id,type,side_a,side_b")
    assert "body:v:1/2:A,vertical_gore,body/A@1:right,body/A@2:left" in csv_text
    import json

    data = json.loads(graph.to_json())
    kinds = {n["kind"] for n in data["nodes"]}
    assert {"panel_edge", "mouth_boundary", "parachute_boundary"} <= kinds
    assert len(data["seams"]) == len(graph.seams)
    assert data["seams"][0]["construction_order"] == 0


def test_cut_only_and_sew_packs_give_the_same_seams(make_pack: PackFactory) -> None:
    with_sew = _ring(make_pack)
    entities = [
        e for e in ring_pack_entities([("A", 1000, 800), ("B", 1000, 800)], 3) if e[0] != "SEW"
    ]
    cut_only = _assemble(
        make_pack(entities, default_import(), ring_assembly(["A", "B"], 3), name="c")
    )
    for seam in with_sew.graph.seams:
        other = next(s for s in cut_only.graph.seams if s.seam_id == seam.seam_id)
        assert with_sew.graph.chain_length(seam.side_a) == pytest.approx(
            cut_only.graph.chain_length(other.side_a), abs=1e-9
        )
