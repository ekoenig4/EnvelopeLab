from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from conftest import PackFactory, default_import, panel_entities, ring_assembly, ring_pack_entities

from envelopelab.assembly.mesh import RestMesh, sew, triangle_quality, validate_mesh
from envelopelab.assembly.pieces import build_finished_pieces
from envelopelab.assembly.seam_graph import Assembly, build_assembly
from envelopelab.assembly.spec import load_assembly_spec
from envelopelab.io.pattern_import import import_patterns, load_mapping


def _assemble(path: Path) -> Assembly:
    pieces, _ = build_finished_pieces(import_patterns(load_mapping(path)))
    return build_assembly(load_assembly_spec(path), pieces)


@pytest.fixture
def tagged(make_pack: PackFactory) -> tuple[Assembly, RestMesh]:
    """3 gores x 2 rows; row B of gore 2 has a feed hole, a tape line and a zone override."""
    entities = ring_pack_entities([("A", 1000, 800), ("B", 900, 700)], gores=3)
    # Row B piece starts at x = 1100 (see ring_pack_entities spacing).
    entities += [
        ("FEAT", "circle", ((1550, 350), 150)),
        ("TAPE", "open", [(1250, 600), (1850, 600)]),
        ("GRAIN", "line", ((1550, 100), (1550, 500))),
    ]
    cfg = default_import()
    cfg["layers"].update({"tape": ["TAPE"], "grain": ["GRAIN"]})
    cfg["pieces"] = {"A": {"material_zone": "nomex"}}
    assembly_cfg = ring_assembly(
        ["A", "B"],
        3,
        instances=[
            {
                "select": {"ring": "body", "rows": ["B"], "gores": [2]},
                "material_zone": "doubled",
                "openings": [
                    {"name": "feed", "kind": "feed_hole", "feature": {"circle_radius_mm": 150}}
                ],
            }
        ],
    )
    assembly = _assemble(make_pack(entities, cfg, assembly_cfg))
    return assembly, sew(assembly)


def test_every_triangle_is_tagged(tagged: tuple[Assembly, RestMesh]) -> None:
    _, mesh = tagged
    assert len(mesh.tri_instance) == len(mesh.triangles)
    tags = [mesh.tags(t) for t in range(len(mesh.triangles))]
    panels = {t["panel_id"] for t in tags}
    assert panels == {f"body/{r}@{g}" for r in "AB" for g in (1, 2, 3)}
    zones = {(t["panel_id"], t["material_zone"]) for t in tags}
    assert ("body/A@1", "nomex") in zones
    assert ("body/B@2", "doubled") in zones
    assert ("body/B@1", "default") in zones
    grain = {t["panel_id"]: t["grain"] for t in tags}
    assert grain["body/A@1"] == pytest.approx((1.0, 0.0))  # mapping default
    assert grain["body/B@1"] == pytest.approx((0.0, 1.0))  # grain layer
    source = {t["panel_id"]: t["source_pattern_id"] for t in tags}
    assert source["body/B@3"].startswith("pack.dxf:CUT:")


def test_seams_and_tapes_are_tagged_for_cables(tagged: tuple[Assembly, RestMesh]) -> None:
    assembly, mesh = tagged
    edges = {
        tuple(sorted(e))
        for e in np.concatenate(
            [mesh.triangles[:, [0, 1]], mesh.triangles[:, [1, 2]], mesh.triangles[:, [2, 0]]]
        ).tolist()
    }
    sewn = [s for s in assembly.graph.seams if s.seam_type in {"horizontal_panel", "vertical_gore"}]
    assert set(mesh.seam_edges) >= {s.seam_id for s in sewn}
    for seam in sewn:
        seam_edges = mesh.seam_edges[seam.seam_id]
        assert len(seam_edges) >= 2
        assert all(tuple(sorted(e)) in edges for e in seam_edges.tolist())
    tapes = [k for k in mesh.tape_edges if k.endswith(":tape0")]
    assert len(tapes) == 3  # the tape line of piece B in every gore
    assert all(tuple(sorted(e)) in edges for e in mesh.tape_edges[tapes[0]].tolist())


def test_openings_stay_open_and_seams_are_closed(tagged: tuple[Assembly, RestMesh]) -> None:
    assembly, mesh = tagged
    report = validate_mesh(mesh, assembly)
    names = sorted(loop.opening or "?" for loop in report.boundary_loops)
    assert names == ["body/B@2:feed", "crown", "mouth"]
    assert report.passed, report.checks
    assert report.components == 1
    assert report.euler_characteristic == 2 - 3  # sphere with three holes
    assert report.area_relative_error == pytest.approx(0.0, abs=1e-3)


def test_rest_coordinates_keep_flat_panel_geometry(tagged: tuple[Assembly, RestMesh]) -> None:
    assembly, mesh = tagged
    by_inst: dict[str, float] = {}
    for k, iid in enumerate(mesh.instance_ids):
        by_inst[iid] = float(np.abs(mesh.rest_areas[mesh.tri_instance == k]).sum())
    assert by_inst["body/A@1"] == pytest.approx(0.8, rel=1e-9)
    # The hole rim is a chord polygon (about 19 segments here), so the meshed hole is
    # slightly smaller than the true circle: an O((h/r)^2) discretisation error.
    assert by_inst["body/B@2"] == pytest.approx(0.63 - math.pi * 0.15**2, rel=5e-3)
    assert np.all(mesh.rest_areas > 0)


def test_unmeshed_part_is_excluded(make_pack: PackFactory) -> None:
    entities = ring_pack_entities([("A", 1000, 800)], gores=3) + panel_entities(
        5000, 300, 300, "PANEL X x1"
    )
    cfg = ring_assembly(["A"], 3, parts=[{"name": "x", "piece": "X", "mesh": False}])
    assembly = _assemble(make_pack(entities, assembly=cfg))
    mesh = sew(assembly)
    assert "x" not in mesh.instance_ids
    assert validate_mesh(mesh, assembly).passed


def test_mesh_size_follows_options(make_pack: PackFactory) -> None:
    entities = ring_pack_entities([("A", 1000, 800)], gores=3)
    coarse = _assemble(make_pack(entities, assembly=ring_assembly(["A"], 3), name="a"))
    fine_cfg = ring_assembly(["A"], 3)
    fine_cfg["mesh"] = {"target_edge_length_mm": 100}
    fine = _assemble(make_pack(entities, assembly=fine_cfg, name="b"))
    assert len(sew(fine).triangles) > 2 * len(sew(coarse).triangles)


def test_triangle_quality_of_equilateral_is_one() -> None:
    tri = np.array([[[0.0, 0.0], [1.0, 0.0], [0.5, math.sqrt(3) / 2]]])
    assert triangle_quality(tri)[0] == pytest.approx(1.0)
    flat = np.array([[[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]])
    assert triangle_quality(flat)[0] == pytest.approx(0.0)


def test_tape_reaching_the_panel_edge_is_clipped(make_pack: PackFactory) -> None:
    entities = ring_pack_entities([("A", 1000, 800)], gores=3)
    entities.append(("TAPE", "open", [(0, 400), (1000, 400)]))  # edge to edge
    cfg = default_import()
    cfg["layers"]["tape"] = ["TAPE"]
    assembly = _assemble(make_pack(entities, cfg, ring_assembly(["A"], 3)))
    loop = assembly.instances["body/A@1"].loops["tape0"]
    assert loop.note is not None
    assert loop.points[:, 0].min() == pytest.approx(-0.49, abs=2e-3)
    assert loop.points[:, 0].max() == pytest.approx(0.49, abs=2e-3)
    assert any("tape line clipped" in w.message for w in assembly.warnings)
    mesh = sew(assembly)
    assert validate_mesh(mesh, assembly).passed
    assert len(mesh.tape_edges["body/A@1:tape0"]) >= 2
