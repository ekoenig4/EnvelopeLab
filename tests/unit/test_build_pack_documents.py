"""Build pack format 2: the documents (cover, spec, cut list, rigging, sewing, 3D view)."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from envelopelab.export.build_pack import (
    PACK_FORMAT,
    BuildPackError,
    PackExtras,
    envelope_seam_pairs,
    envelope_sheets,
    export_build_pack,
)
from envelopelab.export.documents import (
    DOCUMENTS,
    cut_list,
    pdf_text,
    rigging_table,
    sewing_schedule,
)
from envelopelab.export.qa import check_pack
from envelopelab.export.viewer import (
    Coloring,
    Legend,
    SceneMesh,
    SceneStatus,
    decoded,
    design_scene,
    read_scene,
    render_html,
)
from envelopelab.features.primitives import Dome, EnvelopeSurface, Placement, design_primitive
from envelopelab.project.gore_design import gore_outputs, standard_gore_design
from envelopelab.project.model import PatternSet
from envelopelab.rigging import default_flying_wires, default_red_line

BASE = standard_gore_design("documents sample", 2000.0, 17.0, 16.0, 12, 6)
DESIGN = BASE.model_copy(
    update={
        "rigging": BASE.rigging.model_copy(
            update={
                "red_line": default_red_line(BASE),
                "flying_wires": default_flying_wires(BASE),
            }
        ),
        "operating": BASE.operating.model_copy(update={"payload_mass": 300.0}),
    }
)
SURFACE = EnvelopeSurface.from_design(DESIGN)
SHAPES = [design_primitive(Dome("ear", Placement(3, 12.0, across=0.5), 1.0, 1.2, 16), SURFACE)]


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pack")
    export_build_pack(DESIGN, SHAPES, out, extras=PackExtras(frozenset(DOCUMENTS)))
    return out


def _copy(pack: Path, tmp_path: Path) -> Path:
    target = tmp_path / "pack"
    shutil.copytree(pack, target)
    return target


def _index(pack: Path) -> dict:  # type: ignore[type-arg]
    return dict(json.loads((pack / "index.json").read_text(encoding="utf-8")))


def test_every_document_is_written_listed_and_passes_the_qa(pack: Path) -> None:
    assert check_pack(pack) == []
    index = _index(pack)
    assert index["format"] == PACK_FORMAT == "envelopelab-build-pack/2"
    files = {d["file"] for d in index["documents"]}
    expected = {f for names, _what in DOCUMENTS.values() for f in names}
    assert files == expected
    assert index["documents"][0]["file"] == "00-cover.pdf"
    prov = index["provenance"]
    assert prov["design_hash"] == DESIGN.compute_content_hash()
    assert prov["app_version"] and prov["created"]


def test_sheets_only_by_default_and_unknown_documents_are_refused(tmp_path: Path) -> None:
    export_build_pack(DESIGN, [], tmp_path / "plain")
    index = _index(tmp_path / "plain")
    assert index["documents"] == [] and check_pack(tmp_path / "plain") == []
    with pytest.raises(BuildPackError):
        export_build_pack(DESIGN, [], tmp_path / "bad", extras=PackExtras(frozenset({"x"})))


def test_cut_list_matches_every_sheet_header(pack: Path) -> None:
    index = _index(pack)
    rows = list(csv.reader((pack / "cut-list.csv").read_text(encoding="utf-8").splitlines()))
    header = rows[1]
    pieces = {r[0]: r for r in rows[2 : 2 + len(index["sheets"])]}
    for entry in index["sheets"]:
        row = pieces[entry["file"]]
        assert row[header.index("Cut")] == str(entry["cut_count"])
        assert row[header.index("Fabric")] == entry["fabric"]
    # The totals add up the cut pieces.
    sheets = envelope_sheets(DESIGN)
    table = cut_list(sheets)
    total = sum(float(r[-1]) for r in table.rows)
    assert total == pytest.approx(sum(float(r[-2]) * int(r[3]) for r in table.rows), rel=1e-3)


def test_qa_catches_a_cut_list_that_disagrees_and_a_page_that_loads_a_file(
    pack: Path, tmp_path: Path
) -> None:
    bad = _copy(pack, tmp_path)
    text = (bad / "cut-list.csv").read_text(encoding="utf-8")
    (bad / "cut-list.csv").write_text(
        text.replace(
            "envelope-row-A.dxf,row A,envelope panel,12,",
            "envelope-row-A.dxf,row A,envelope panel,11,",
        ),
        encoding="utf-8",
    )
    page = (bad / "3d-view.html").read_text(encoding="utf-8")
    (bad / "3d-view.html").write_text(
        page.replace("<head>", '<head><script src="https://example.com/x.js"></script>'),
        encoding="utf-8",
    )
    checks = {(f.file, f.check) for f in check_pack(bad)}
    assert ("cut-list.csv", "cut list") in checks
    assert ("3d-view.html", "viewer") in checks
    (bad / "spec-summary.pdf").unlink()
    assert ("spec-summary.pdf", "index") in {(f.file, f.check) for f in check_pack(bad)}


def test_sewing_schedule_lists_every_seam_in_assembly_order(pack: Path) -> None:
    index = _index(pack)
    rows = list(csv.reader((pack / "sewing-schedule.csv").read_text(encoding="utf-8").splitlines()))
    steps = rows[1:]
    assert len(steps) == len(index["seam_pairs"])
    stages = [r[1] for r in steps]
    order = [
        "Gore seams (load tapes)",
        "Row seams (horizontal tapes)",
        "Parachute",
        "Shape skin seams",
        "Shape rim to the envelope",
    ]
    ranks = [order.index(s) for s in stages]
    assert ranks == sorted(ranks)
    gore = next(r for r in steps if r[1] == order[0])
    assert gore[4] == "12" and gore[5] == gore[6]  # sewn once per gore, equal lengths
    assert all(r[-1] == "[  ]" for r in steps)
    sheets = envelope_sheets(DESIGN)
    table = sewing_schedule(sheets, envelope_seam_pairs(sheets), 12)
    assert len(table.rows) == 6 + 5


def test_rigging_sheet_marks_a_failing_factor_of_safety() -> None:
    weak = DESIGN.model_copy(deep=True)
    assert weak.rigging.flying_wires is not None
    weak.rigging.flying_wires.wire.strength.value = 100.0
    out = gore_outputs(weak, PatternSet()).rigging
    table = rigging_table(out)
    wire = next(i for i, r in enumerate(table.rows) if r[1] == "flying wire")
    assert table.rows[wire][10] == "FAILS" and wire in table.fails
    assert "not assessed" in [r[10] for r in table.rows]  # the red line pull
    assert all(r[7] in ("assumed", "datasheet", "measured") for r in table.rows)


def test_pdf_text_is_latin1() -> None:
    text = pdf_text("≥ 10 – ▲ FAILS ✓ ◷ ✕ …")
    text.encode("latin-1")
    assert ">=" in text and "FAILS" in text


def test_design_scene_has_the_surface_seams_gore_numbers_and_rigging(pack: Path) -> None:
    scene = read_scene(pack / "3d-view.html")
    keys = [m["key"] for m in scene["meshes"]]
    assert keys == ["design"]
    assert {ln["key"] for ln in scene["lines"]} == {"seams", "rigging"}
    assert [lb["text"] for lb in scene["labels"]] == [f"G{k}" for k in range(1, 13)]
    assert scene["status"]["kind"] == "info" and "Design only" in scene["status"]["title"]
    positions = decoded(scene["meshes"][0])
    assert len(positions) == 3 * scene["meshes"][0]["triangles"]
    height = gore_outputs(DESIGN, PatternSet()).height
    assert float(np.ptp(positions[:, 2])) == pytest.approx(height, rel=0.02)


def test_colourings_are_embedded_per_vertex_and_status_is_kept() -> None:
    scene = design_scene(DESIGN, None, SceneStatus("fail", "Fails.", "row B FoS 3.1"))
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    mesh = SceneMesh("run", "Run", "Result", pts, np.array([[0, 1, 2]]), role="result")
    mesh.colorings["fos_warp"] = Coloring(
        "fos_warp",
        "FoS warp",
        np.array([[232, 89, 12]], dtype=np.uint8),
        "face",
        Legend("FoS warp", [("#e8590c", "< 5 FAIL")]),
    )
    scene.meshes.append(mesh)
    scene.initial = "fos_warp"
    page = render_html(scene)
    assert "https:" not in page and "http:" not in page
    import base64

    start = page.index('type="application/json">') + len('type="application/json">')
    data = json.loads(page[start : page.index("</script>", start)])
    run = next(m for m in data["meshes"] if m["key"] == "run")
    rgb = np.frombuffer(base64.b64decode(run["colorings"]["fos_warp"]["rgb"]), dtype=np.uint8)
    assert rgb.reshape(-1, 3).tolist() == [[232, 89, 12]] * 3
    assert data["initial"] == "fos_warp" and data["status"]["kind"] == "fail"
    assert data["status"]["symbol"] == "▲"
