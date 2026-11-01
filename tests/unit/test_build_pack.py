"""Build-pack export (DXF, PDF, index) and its output QA (AGENTS.md §6.6)."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.filemanagement import readfile

from envelopelab.export.build_pack import (
    PT_PER_M,
    BuildPackError,
    calibration,
    calibration_label,
    export_build_pack,
    write_pack,
)
from envelopelab.export.qa import check_pack
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    Tube,
    design_primitive,
)
from envelopelab.project.gore_design import standard_gore_design

DESIGN = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
SURFACE = EnvelopeSurface.from_design(DESIGN)
SHAPES = [
    design_primitive(
        Dome("ear", Placement(3, 12.0, across=0.5), 1.0, 1.2, gores=16), SURFACE, 0.0125, 0.3
    ),
    design_primitive(Tube("horn", Placement(7, 10.0, lean_deg=20), 0.8, 0.3, 2.0), SURFACE),
]


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pack")
    export_build_pack(DESIGN, SHAPES, out, skin_fabric={"ear": "ripstop red"})
    return out


def _copy(pack: Path, tmp_path: Path) -> Path:
    target = tmp_path / "pack"
    shutil.copytree(pack, target)
    return target


def test_exported_pack_passes_the_output_qa(pack: Path) -> None:
    assert check_pack(pack) == []
    index = json.loads((pack / "index.json").read_text(encoding="utf-8"))
    files = [s["file"] for s in index["sheets"]]
    assert "envelope-row-A.dxf" in files and "ear-G16.dxf" in files and "horn-TIP.dxf" in files
    assert {"ear-mark-G3-D.dxf", "ear-mark-G4-D.dxf"} <= set(files)
    rows = [s for s in index["sheets"] if s["kind"] == "envelope panel"]
    assert all(s["cut_count"] == 12 for s in rows)
    ear = next(s for s in index["sheets"] if s["file"] == "ear-G1.dxf")
    assert ear["fabric"] == "ripstop red"
    piece = SHAPES[0].pieces[0]
    assert ear["finished_width_mm"] == pytest.approx(piece.size[0] * 1000, abs=1e-3)
    # Every skin seam, the tip seam, every envelope seam, the parachute's radial seams and
    # centre seam, and each shape's rim to its marked footprint lines is a sewn pair.
    assert len(index["seam_pairs"]) == 16 + 4 + 1 + 6 + 5 + 2 + 2
    assert index["roll_width_mm"] == pytest.approx(60 * 25.4)


def test_dxf_is_in_millimetres_and_carries_the_marks(pack: Path) -> None:
    hole = SHAPES[0].feed_hole
    assert hole is not None
    doc = readfile(pack / f"ear-mark-G{hole.gore}-{hole.row}.dxf")
    assert doc.header["$INSUNITS"] == 4
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"SEW", "CUT", "ATTACH", "MARKS", "HOLE", "LABEL", "CAL"} <= layers
    texts = [
        e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT" and e.dxf.layer == "MARKS"
    ]
    assert texts  # the numbered marks of this half of the footprint
    top = readfile(pack / "ear-mark-G3-D.dxf")
    marks = [
        e.dxf.text for e in top.modelspace() if e.dxftype() == "TEXT" and e.dxf.layer == "MARKS"
    ]
    # Each number names the skin piece that carries it: "12 (G6)".
    numbers = {x.split()[0] for x in [*texts, *marks]}
    assert sorted(numbers, key=int) == [str(k) for k in range(1, 33)]
    assert all(x.split()[1].startswith("(G") for x in [*texts, *marks])


def test_calibration_label_comes_from_the_drawn_length() -> None:
    assert calibration(2.0) == (0.5, 0.1)
    assert calibration(0.3) == (0.2, 0.1)
    assert calibration(0.05) == (0.1, 0.05)
    assert calibration_label(0.5, 0.1) == "must measure 500 mm at 1:1, ticks every 100 mm"


def test_pdf_pages_are_roll_wide_and_wide_sheets_are_split(pack: Path) -> None:
    data = (pack / "pattern.pdf").read_bytes()
    index = json.loads((pack / "index.json").read_text(encoding="utf-8"))
    roll = f"/MediaBox [0 0 {60 * 0.0254 * PT_PER_M:.2f} ".encode()
    assert data.count(roll) == sum(s["pdf_pages"] for s in index["sheets"])
    widest = max(index["sheets"], key=lambda s: s["finished_width_mm"])
    assert widest["pdf_pages"] == math.ceil((widest["finished_width_mm"] + 90) / 1524.0)


def test_qa_catches_missing_and_unlisted_files(pack: Path, tmp_path: Path) -> None:
    p = _copy(pack, tmp_path)
    (p / "horn-P1.dxf").unlink()
    (p / "notes.txt").write_text("x", encoding="utf-8")
    found = {(f.file, f.check) for f in check_pack(p)}
    assert ("horn-P1.dxf", "index") in found and ("notes.txt", "index") in found


def test_qa_catches_wrong_units_and_calibration(pack: Path, tmp_path: Path) -> None:
    p = _copy(pack, tmp_path)
    doc = readfile(p / "ear-G1.dxf")
    doc.header["$INSUNITS"] = 1
    for e in doc.modelspace():
        if e.dxf.layer == "CAL" and e.dxftype() == "LINE" and e.dxf.end.x - e.dxf.start.x > 100:
            e.dxf.end = (e.dxf.end.x + 5.0, e.dxf.end.y)
    doc.saveas(p / "ear-G1.dxf")
    checks = {f.check for f in check_pack(p)}
    assert {"units", "calibration"} <= checks


def test_qa_catches_unequal_sewn_edges_and_wrong_headers(pack: Path, tmp_path: Path) -> None:
    p = _copy(pack, tmp_path)
    doc = readfile(p / "horn-P2.dxf")
    for e in doc.modelspace():
        if e.dxf.layer == "EDGE_LEFT" and isinstance(e, LWPolyline):
            e.set_points([(x * 1.01, y * 1.01) for x, y, *_ in e.get_points()])
    doc.saveas(p / "horn-P2.dxf")
    index = json.loads((p / "index.json").read_text(encoding="utf-8"))
    index["sheets"][7]["cut_count"] = 2
    index["roll_width_mm"] = 1000.0
    (p / "index.json").write_text(json.dumps(index), encoding="utf-8")
    checks = {f.check for f in check_pack(p)}
    assert {"seam", "header", "page size"} <= checks


def test_sheet_names_must_be_unique(tmp_path: Path) -> None:
    from envelopelab.export.build_pack import primitive_sheets

    sheets = primitive_sheets(SHAPES[1])
    with pytest.raises(BuildPackError):
        write_pack(sheets + sheets[:1], tmp_path)


def test_rim_is_paired_with_the_marked_lines_and_their_ease(pack: Path) -> None:
    index = json.loads((pack / "index.json").read_text(encoding="utf-8"))
    rims = [p for p in index["seam_pairs"] if p["a"][0]["edge"] == "rim"]
    assert len(rims) == 2
    ear = next(p for p in rims if p["a"][0]["file"].startswith("ear-"))
    assert len(ear["a"]) == 16
    assert {r["file"] for r in ear["b"]} == {"ear-mark-G3-D.dxf", "ear-mark-G4-D.dxf"}
    assert all(r["edge"].startswith("attach") for r in ear["b"])
    design = SHAPES[0]
    rim = sum(
        float(np.linalg.norm(np.diff(c.rim, axis=0), axis=1).sum())
        for c in design.pieces
        if c.rim is not None
    )
    marked = sum(a.length for a in design.attachment)
    assert ear["ease_mm"] == pytest.approx((rim - marked) * 1000, abs=1e-3)


def test_qa_catches_a_moved_footprint_line(pack: Path, tmp_path: Path) -> None:
    p = _copy(pack, tmp_path)
    doc = readfile(p / "ear-mark-G3-D.dxf")
    for e in doc.modelspace():
        if e.dxf.layer == "ATTACH" and isinstance(e, LWPolyline):
            e.set_points([(x * 1.02, y * 1.02) for x, y, *_ in e.get_points()])
    doc.saveas(p / "ear-mark-G3-D.dxf")
    findings = [f for f in check_pack(p) if f.check == "seam"]
    assert len(findings) == 1 and "ear-G1.dxf:rim" in findings[0].file
    assert "planned ease" in findings[0].message


def test_parachute_panels_and_centre_panel_are_in_the_pack(pack: Path) -> None:
    from envelopelab.rigging import rigging_outputs

    index = json.loads((pack / "index.json").read_text(encoding="utf-8"))
    sheets = {s["file"]: s for s in index["sheets"]}
    pr = rigging_outputs(DESIGN).parachute
    assert pr is not None and pr.panel is not None and pr.centre_panel is not None
    radial = sheets["parachute-panel.dxf"]
    assert radial["kind"] == "parachute panel" and radial["cut_count"] == pr.panel_count
    assert radial["finished_width_mm"] == pytest.approx(pr.panel.bottom_width * 1000, abs=1e-3)
    centre = sheets["parachute-centre.dxf"]
    assert centre["cut_count"] == 1
    assert centre["finished_width_mm"] == pytest.approx(pr.centre_panel.diameter * 1000, abs=0.5)
    # All radial tops are sewn to the centre panel's edge, and the QA measured it.
    pair = next(p for p in index["seam_pairs"] if p["b"][0]["file"] == "parachute-centre.dxf")
    assert len(pair["a"]) == pr.panel_count and pair["ease_mm"] == 0.0
    assert {r["edge"] for r in pair["a"]} == {"top"} and pair["b"][0]["edge"] == "rim"


def test_qa_catches_a_parachute_centre_panel_of_the_wrong_size(pack: Path, tmp_path: Path) -> None:
    p = _copy(pack, tmp_path)
    doc = readfile(p / "parachute-centre.dxf")
    for e in doc.modelspace():
        if e.dxf.layer == "EDGE_RIM" and isinstance(e, LWPolyline):
            e.set_points([(x * 1.01, y * 1.01) for x, y, *_ in e.get_points()])
    doc.saveas(p / "parachute-centre.dxf")
    assert any(f.check == "seam" and "parachute-centre.dxf" in f.message for f in check_pack(p))


def test_wedge_parachute_and_no_parachute(tmp_path: Path) -> None:
    wedges = DESIGN.model_copy(deep=True)
    assert wedges.parachute is not None
    wedges.parachute.centre_panel_diameter = None
    export_build_pack(wedges, [], tmp_path / "wedges")
    files = {
        s["file"] for s in json.loads((tmp_path / "wedges" / "index.json").read_text())["sheets"]
    }
    assert "parachute-panel.dxf" in files and "parachute-centre.dxf" not in files
    assert check_pack(tmp_path / "wedges") == []
    bare = DESIGN.model_copy(update={"parachute": None})
    export_build_pack(bare, [], tmp_path / "bare")
    files = {
        s["file"] for s in json.loads((tmp_path / "bare" / "index.json").read_text())["sheets"]
    }
    assert not {f for f in files if f.startswith("parachute")}


def test_a_parachute_that_cannot_be_cut_stops_the_export(tmp_path: Path) -> None:
    broken = DESIGN.model_copy(deep=True)
    assert broken.parachute is not None and broken.gores is not None
    broken.parachute.centre_panel_diameter = 2.0 * broken.gores.parachute_hole_diameter
    with pytest.raises(BuildPackError, match="parachute pattern cannot be made"):
        export_build_pack(broken, [], tmp_path / "broken")


def _texts(path: Path, layer: str) -> list[str]:
    return [
        e.dxf.text
        for e in readfile(path).modelspace()
        if e.dxftype() == "TEXT" and e.dxf.layer == layer
    ]


def _inside(point: tuple[float, float], poly: np.ndarray) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, np.roll(poly, -1, axis=0), strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def test_marking_sheets_say_where_and_how_the_shape_is_sewn(pack: Path) -> None:
    """Feed holes at cut and finished size, ticks on the side the shape covers, and the
    instructions; panels under a shape say so."""
    from envelopelab.export.build_pack import TICK_LENGTH, primitive_sheets

    ear = SHAPES[0]
    hem = 2.0 * DESIGN.tapes.hole.width
    hole = ear.feed_hole
    assert hole is not None
    sheets = {s.name: s for s in primitive_sheets(ear, "skin", None, hem, "hole tape")}
    marking = sheets[f"ear-mark-G{hole.gore}-{hole.row}"]
    assert marking.hole_cuts[0][2] == pytest.approx(hole.radius - hem)
    text = next(t for _, _, t in marking.texts if t.startswith("FEED HOLE"))
    assert f"cut diameter {2000 * (hole.radius - hem):.0f} mm" in text
    assert f"{2000 * hole.radius:.0f} mm finished" in text and "hole tape" in text
    # Every tick ends inside the footprint (the ear lies on that side of the line). The
    # generic design has lobe gores: x = 2 tau w(s), y = s - s_row.
    surface = ear.surface
    n = surface.gore_count
    g_centre = ear.primitive.placement.gore - 0.5 + ear.primitive.placement.across
    g = surface.gore_position(ear.footprint_theta)
    g = g_centre + np.mod(g - g_centre + 0.5 * n, n) - 0.5 * n
    loop = np.column_stack([g, ear.footprint_s])
    bottoms = {b.label: b.s_bottom for b in surface.rows}
    ticked = 0
    for sheet in sheets.values():
        if sheet.kind != "marking":
            continue
        gore = int(sheet.piece.split()[1])
        row = sheet.piece.split()[3]
        cell = g_centre + np.mod(gore - 0.5 - g_centre + 0.5 * n, n) - 0.5 * n - 0.5
        if not sheet.lines:
            assert any("lies under ear" in note for note in sheet.notes)
            continue
        assert any("ticks point into ear" in note for note in sheet.notes)
        for tick in sheet.ticks:
            assert np.linalg.norm(tick[1] - tick[0]) == pytest.approx(TICK_LENGTH)
            x, y = tick[1]
            s = y + bottoms[row]
            across = x / (2.0 * float(surface.half_width(np.array([s]))[0]))
            assert _inside((cell + 0.5 + across, s), loop)
            ticked += 1
    assert ticked > 20
    assert {"ATTACH_SIDE", "HOLE_CUT", "NOTES"} <= {
        e.dxf.layer for e in readfile(pack / f"{marking.name}.dxf").modelspace()
    }


def test_skin_pieces_say_what_each_edge_is_sewn_to(pack: Path) -> None:
    ear = _texts(pack / "ear-G5.dxf", "NOTES")
    assert "sew to G6 (its left side)" in ear and "sew to G4 (its right side)" in ear
    assert any(t.startswith("RIM: sew to the envelope, marks") for t in ear)
    assert "APEX of ear" in ear
    first = _texts(pack / "ear-G1.dxf", "NOTES")
    assert "sew to G16 (its right side)" in first  # round the shape
    horn = _texts(pack / "horn-P1.dxf", "NOTES")
    assert "TOP: sew to the tip disc" in horn
    assert "TIP DISC" in _texts(pack / "horn-TIP.dxf", "NOTES")
    tip = _texts(pack / "horn-TIP.dxf", "LABEL")
    assert any(t.startswith("TIP DISC: sew round the tops") for t in tip)
    label = _texts(pack / "ear-G5.dxf", "LABEL")
    assert any(t.startswith("rim marks") and "lie on the envelope at gore" in t for t in label)


def test_row_sheets_list_the_gores_to_mark(pack: Path) -> None:
    ear = SHAPES[0]
    rows = {a.row for a in ear.attachment}
    for row in rows:
        gores = sorted(
            {a.gore for a in ear.attachment if a.row == row}
            | {h.gore for h in ear.feed_holes if h.row == row}
        )
        label = _texts(pack / f"envelope-row-{row}.dxf", "LABEL")
        assert any(
            t.startswith(f"ear: mark gores {', '.join(str(g) for g in gores)} of this row")
            for t in label
        ), label
    assert check_pack(pack) == []


def test_the_tip_disc_shows_where_every_seam_meets_it() -> None:
    """A tick on the tip disc's edge (pointing in) and the two panels' names at every seam,
    so the panel tops are sewn round it in place."""
    from envelopelab.export.build_pack import TICK_LENGTH, primitive_sheets

    horn = SHAPES[1]
    sheets = {s.name: s for s in primitive_sheets(horn)}
    tip = sheets["horn-TIP"]
    m = horn.primitive.pieces
    assert len(tip.ticks) == m
    radius = horn.primitive.tip_radius
    for tick in tip.ticks:
        assert np.linalg.norm(tick[0]) == pytest.approx(radius, abs=1e-9)
        assert np.linalg.norm(tick[1]) == pytest.approx(radius - TICK_LENGTH, abs=1e-9)
    names = [t[2] for t in tip.texts]
    assert names == ["TIP DISC", *(f"P{k}" for k in range(1, m + 1))]
    # Each panel's name sits inside its stretch of edge, between the ticks of its seams.
    for k, (x, y, _) in enumerate(tip.texts[1:]):
        a = 2.0 * math.pi * k / m - math.pi / m
        turn = (math.atan2(y, x) - (a + math.pi / m) + math.pi) % (2.0 * math.pi) - math.pi
        assert turn == pytest.approx(0.0, abs=1e-6)
        assert math.hypot(x, y) < radius
    assert any("sew each panel's top between the ticks" in n for n in tip.notes)
    assert any(n.startswith("TIP DISC: sew round the tops of all horn") for n in tip.notes)


def test_a_capped_dome_is_sewn_round_its_cap() -> None:
    from envelopelab.export.build_pack import primitive_seam_pairs, primitive_sheets

    ear = design_primitive(
        Dome("ear", Placement(3, 12.0, across=0.5), 1.0, 1.2, gores=16, cap_radius=0.25),
        SURFACE,
    )
    assert ear.pieces[-1].label == "ear-TIP"
    sheets = {s.name: s for s in primitive_sheets(ear)}
    assert any(t[2] == "TOP: sew to the tip disc" for t in sheets["ear-G5"].texts)
    assert len(sheets["ear-TIP"].ticks) == 16
    # The gore tops add up to the cap's edge (3 mm sewing tolerance of the QA).
    pair = next(p for p in primitive_seam_pairs(ear) if p.b == (("ear-TIP", "top"),))
    tops = sum(_polyline_length(ear.pieces[k].edges["top"]) for k in range(16))
    cap = _polyline_length(ear.pieces[-1].edges["top"])
    assert len(pair.a) == 16 and abs(tops - cap) < 3e-3


def _polyline_length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
