"""Build-pack export (DXF, PDF, index) and its output QA (AGENTS.md §6.6)."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

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
    # Every skin seam, the tip seam and every envelope seam is listed as a sewn pair.
    assert len(index["seam_pairs"]) == 16 + 4 + 1 + 6 + 5
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
    assert sorted(set(texts) | set(marks), key=int) == [str(k) for k in range(1, 33)]


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
