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
    return dict(json.loads((pack / "cad" / "index.json").read_text(encoding="utf-8")))


def test_every_document_is_written_listed_and_passes_the_qa(pack: Path) -> None:
    assert check_pack(pack) == []
    index = _index(pack)
    assert index["format"] == PACK_FORMAT == "envelopelab-build-pack/3"
    files = {d["file"] for d in index["documents"]}
    expected = {f"documents-sample-{f}" for spec in DOCUMENTS.values() for f, _what in spec.files}
    assert files == expected
    assert index["documents"][0]["file"] == "documents-sample-00-BUILD-PACK-INDEX.pdf"
    prov = index["provenance"]
    assert prov["design_hash"] == DESIGN.compute_content_hash()
    assert prov["app_version"] and prov["created"]


def test_sheets_only_by_default_and_unknown_documents_are_refused(tmp_path: Path) -> None:
    export_build_pack(DESIGN, [], tmp_path / "plain")
    index = _index(tmp_path / "plain")
    assert index["documents"] == [] and check_pack(tmp_path / "plain") == []
    with pytest.raises(BuildPackError):
        export_build_pack(DESIGN, [], tmp_path / "bad", extras=PackExtras(frozenset({"x"})))


def test_panel_dimensions_match_every_row_header(pack: Path) -> None:
    index = _index(pack)
    text = (pack / "documents-sample-panel-dimensions.csv").read_text(encoding="utf-8")
    rows = list(csv.reader(text.splitlines()))
    header, body = rows[0], {r[0]: r for r in rows[1:]}
    for entry in index["sheets"]:
        if entry["kind"] != "envelope panel":
            continue
        row = body[entry["piece"].removeprefix("row ")]
        assert row[header.index("cut")] == str(entry["cut_count"])
        assert row[header.index("fabric")] == entry["fabric"]
        assert int(row[header.index("height_mm")]) == round(entry["finished_height_mm"])
    # Top row first, as on the builder's sheets; the across-bolt side is the shorter one.
    assert [r[0] for r in rows[1:]] == ["F", "E", "D", "C", "B", "A"]
    for r in rows[1:]:
        assert int(r[header.index("across_bolt_mm")]) <= int(r[header.index("along_table_mm")])
    loft = list(csv.reader((pack / "documents-sample-panel-loft.csv").read_text().splitlines()))
    assert loft[0][1:] == [f"width@{p}%_mm" for p in (0, 25, 50, 75, 100)]
    # The loft's end widths are the dimension sheet's bottom and top widths.
    first = loft[1]
    assert int(first[1]) == int(body[first[0]][1]) and int(first[5]) == int(body[first[0]][2])


def test_qa_catches_dimensions_that_disagree_and_a_page_that_loads_a_file(
    pack: Path, tmp_path: Path
) -> None:
    bad = _copy(pack, tmp_path)
    name = "documents-sample-panel-dimensions.csv"
    lines = (bad / name).read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace(",12,", ",11,")
    (bad / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    page = (bad / "documents-sample-3d.html").read_text(encoding="utf-8")
    (bad / "documents-sample-3d.html").write_text(
        page.replace("<head>", '<head><script src="https://example.com/x.js"></script>'),
        encoding="utf-8",
    )
    checks = {(f.file, f.check) for f in check_pack(bad)}
    assert (name, "dimensions") in checks
    assert ("documents-sample-3d.html", "html") in checks
    (bad / "documents-sample-spec-summary.pdf").unlink()
    assert ("documents-sample-spec-summary.pdf", "index") in {
        (f.file, f.check) for f in check_pack(bad)
    }


def test_sewing_schedule_lists_every_seam_in_assembly_order(pack: Path) -> None:
    index = _index(pack)
    page = (pack / "documents-sample-sewing-schedule.html").read_text(encoding="utf-8")
    for heading in ("Seam specifications", "Webbing / tape schedule", "Assembly sequence"):
        assert heading in page
    sheets = envelope_sheets(DESIGN)
    table = sewing_schedule(sheets, envelope_seam_pairs(sheets), 12)
    assert len(table.rows) == 6 + 5
    order = [
        "Gore seams (load tapes)",
        "Row seams (horizontal tapes)",
        "Parachute",
        "Shape skin seams",
        "Shape rim to the envelope",
    ]
    ranks = [order.index(r[1]) for r in table.rows]
    assert ranks == sorted(ranks)
    gore = table.rows[0]
    assert gore[4] == "12" and gore[5] == gore[6]  # sewn once per gore, equal lengths
    assert all(r[-1] == "[  ]" for r in table.rows)
    # Every seam pair of the pack is on the schedule page.
    assert page.count("[  ]") == len(index["seam_pairs"])


def test_panel_map_and_layout_locate_every_feature(pack: Path) -> None:
    text = (pack / "documents-sample-panel-map.csv").read_text(encoding="utf-8")
    grid = {r[0]: r[1:] for r in csv.reader(text.splitlines()[1:])}
    for a in SHAPES[0].attachment:
        assert grid[a.row][a.gore - 1].startswith("EAR")
    diagram = (pack / "documents-sample-layout-diagram.html").read_text(encoding="utf-8")
    assert "<svg" in diagram and "EAR" in diagram
    from envelopelab.export.qa import _page_boxes

    gores = _page_boxes(pack / "documents-sample-gore-layout.pdf")
    assert len(gores) == 1 + 12  # all gores, then one page per gore


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
    scene = read_scene(pack / "documents-sample-3d.html")
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
