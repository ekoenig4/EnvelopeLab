"""Panel colours in the build pack (ADR-0055): sheet colour lines, index, templates,
colour plan and cloth table, 3D view, and the output QA of all of them."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from envelopelab.export.build_pack import (
    PackExtras,
    colour_line,
    envelope_sheets,
    export_build_pack,
)
from envelopelab.export.colour_plan import NONE_LABEL, cloth_per_colour
from envelopelab.export.documents import fabric_totals
from envelopelab.export.qa import _page_boxes, _read_dxf, check_pack
from envelopelab.export.viewer import design_scene
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    Tube,
    design_primitive,
)
from envelopelab.project.colours import CAP, PanelColours, PanelRef, painted
from envelopelab.project.gore_design import standard_gore_design

DESIGN = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
SURFACE = EnvelopeSurface.from_design(DESIGN)
ROWS = [r.letter for r in DESIGN.gores.panel_rows]  # type: ignore[union-attr]
SHAPES = [
    design_primitive(
        Dome("ear", Placement(3, 12.0, across=0.5), 1.0, 1.2, gores=6, splits=(0.5,)), SURFACE
    ),
    design_primitive(Tube("horn", Placement(7, 10.0, lean_deg=20), 0.8, 0.3, 2.0), SURFACE),
]


def _colours() -> PanelColours:
    c = painted(PanelColours(), [PanelRef(None, ROWS[0], g) for g in range(1, 13)], "#ffc000")
    c = painted(c, [PanelRef(None, ROWS[-1], g) for g in (1, 5, 9)], "#c00000")
    c = painted(c, [PanelRef(None, ROWS[3], 3)], "#0070c0")  # carries the ear's marking
    c = painted(c, [PanelRef("ear", "B", p) for p in range(1, 7)], "#7030a0")
    return painted(c, [PanelRef("horn", CAP, 1)], "#00b050")


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("colour-pack")
    extras = PackExtras(frozenset({"planning", "viewer"}))
    export_build_pack(DESIGN, SHAPES, out, extras=extras, colours=_colours())
    return out


def _index(pack: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads((pack / "cad" / "index.json").read_text("utf-8"))
    return data


def _sheet(pack: Path, piece: str) -> dict[str, object]:
    sheets = _index(pack)["sheets"]
    assert isinstance(sheets, list)
    found: dict[str, object] = next(s for s in sheets if s["piece"] == piece)
    return found


def test_colour_lines_in_words() -> None:
    assert colour_line([], "envelope panel") == ""
    assert colour_line([("#c00000", [2])], "skin piece") == "colour #c00000"
    assert colour_line([(None, [2])], "skin piece") == "colour: none chosen"
    assert (
        colour_line([("#c00000", [1, 5]), (None, [2])], "envelope panel")
        == "colours: cut 2 in #c00000 (gores 1, 5), 1 with no colour (gore 2)"
    )


def test_coloured_pack_passes_the_output_qa(pack: Path) -> None:
    assert check_pack(pack) == []


def test_index_lists_the_colours_of_every_row_and_skin_piece(pack: Path) -> None:
    top = _sheet(pack, f"row {ROWS[-1]}")
    assert top["colours"] == [
        {"colour": "#c00000", "count": 3, "numbers": [1, 5, 9]},
        {"colour": None, "count": 9, "numbers": [2, 3, 4, 6, 7, 8, 10, 11, 12]},
    ]
    assert _sheet(pack, f"row {ROWS[0]}")["colours"] == [
        {"colour": "#ffc000", "count": 12, "numbers": list(range(1, 13))}
    ]
    # The ear is split: tier B is purple, tier A has no colour.
    assert _sheet(pack, "ear-G2B")["colours"] == [{"colour": "#7030a0", "count": 1, "numbers": [2]}]
    assert _sheet(pack, "ear-G2A")["colours"] == [{"colour": None, "count": 1, "numbers": [2]}]
    assert _sheet(pack, "horn-TIP")["colours"] == [
        {"colour": "#00b050", "count": 1, "numbers": [1]}
    ]
    # Marking sheets and the parachute carry no colours.
    sheets = _index(pack)["sheets"]
    assert isinstance(sheets, list)
    assert all("colours" not in s for s in sheets if s["kind"] in ("marking", "parachute panel"))


def test_dxf_and_template_print_the_colour_line(pack: Path) -> None:
    dxf = _read_dxf(pack / "cad" / f"envelope-row-{ROWS[-1]}.dxf")
    assert dxf["label"][1].startswith("colours: cut 3 in #c00000 (gores 1, 5, 9)")
    page = next(pack.glob(f"print/*-panel-{ROWS[-1]}.pdf"))
    (_w, _h, content) = _page_boxes(page)[0]
    assert "%COLOURS colours: cut 3 in #c00000" in content
    # The marking page of one panel names that panel's colour only.
    marked = next(pack.glob(f"print/*-panel-{ROWS[3]}-gore-3.pdf"))
    assert "%COLOURS colour of this panel (gore 3): #0070c0" in _page_boxes(marked)[0][2]


def test_colour_plan_and_cloth_table(pack: Path) -> None:
    documents = _index(pack)["documents"]
    assert isinstance(documents, list)
    files = {d["file"] for d in documents}
    assert {"generic-colour-plan.pdf", "generic-colour-cloth.csv"} <= files
    with (pack / "generic-colour-cloth.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by = {r["colour"]: r for r in rows}
    assert int(by["#ffc000"]["pieces"]) == 12 and int(by["#7030a0"]["pieces"]) == 6
    assert rows[-1]["colour"] == NONE_LABEL


def test_cloth_per_colour_adds_up_to_the_fabric_totals() -> None:
    from envelopelab.export.build_pack import sheet_colours

    sheets = envelope_sheets(DESIGN)
    sheet_colours(sheets, _colours(), 12)
    rows = cloth_per_colour(sheets)
    totals = fabric_totals(sheets).rows
    assert sum(r[1] for r in rows) == sum(int(t[1]) for t in totals)
    assert sum(r[3] for r in rows) == pytest.approx(sum(float(t[3]) for t in totals), abs=0.02)


def test_uncoloured_pack_is_unchanged(tmp_path: Path) -> None:
    export_build_pack(DESIGN, SHAPES[:1], tmp_path, extras=PackExtras(frozenset({"planning"})))
    index = _index(tmp_path)
    sheets = index["sheets"]
    assert isinstance(sheets, list) and all("colours" not in s for s in sheets)
    assert not list(tmp_path.glob("*colour*"))
    assert check_pack(tmp_path) == []


def test_qa_catches_colours_that_do_not_add_up(pack: Path, tmp_path: Path) -> None:
    target = tmp_path / "pack"
    shutil.copytree(pack, target)
    path = target / "cad" / "index.json"
    index = json.loads(path.read_text("utf-8"))
    entry = next(s for s in index["sheets"] if s["piece"] == f"row {ROWS[-1]}")
    entry["colours"][0]["count"] = 4
    entry["colours"][0]["numbers"] = [1, 5, 9, 2]
    path.write_text(json.dumps(index), encoding="utf-8")
    checks = {(Path(f.file).name, f.check) for f in check_pack(target)}
    assert (f"envelope-row-{ROWS[-1]}.dxf", "colours") in checks


def test_the_3d_view_draws_the_panel_colours() -> None:
    scene = design_scene(DESIGN, colours=_colours())
    rgb = scene.meshes[0].face_rgb
    assert rgb is not None
    assert (rgb == [255, 192, 0]).all(axis=1).any() and (rgb == [192, 0, 0]).all(axis=1).any()
    plain = design_scene(DESIGN).meshes[0].face_rgb
    assert plain is not None and not np.array_equal(plain, rgb)


def test_each_half_of_a_half_gore_row_has_its_own_colours(tmp_path: Path) -> None:
    from envelopelab.export.colour_plan import half_outline

    assert DESIGN.gores is not None
    halved = DESIGN.model_copy(
        update={
            "gores": DESIGN.gores.model_copy(
                update={
                    "panel_rows": [
                        r.model_copy(update={"half_gore": i == 2})
                        for i, r in enumerate(DESIGN.gores.panel_rows)
                    ]
                }
            )
        }
    )
    row = ROWS[2]
    c = painted(PanelColours(), [PanelRef(None, row, g) for g in range(1, 13)], "#c00000")
    c = painted(c, [PanelRef(None, row, g, "left") for g in (1, 2)], "#ffffff")
    export_build_pack(halved, [], tmp_path, extras=PackExtras(frozenset({"planning"})), colours=c)
    assert check_pack(tmp_path) == []
    left = _sheet(tmp_path, f"row {row} left half")["colours"]
    right = _sheet(tmp_path, f"row {row} right half")["colours"]
    assert left == [
        {"colour": "#c00000", "count": 10, "numbers": list(range(3, 13))},
        {"colour": "#ffffff", "count": 2, "numbers": [1, 2]},
    ]
    assert right == [{"colour": "#c00000", "count": 12, "numbers": list(range(1, 13))}]
    # The cloth table counts each half once.
    with (tmp_path / "generic-colour-cloth.csv").open(encoding="utf-8") as f:
        by = {r["colour"]: int(r["pieces"]) for r in csv.DictReader(f)}
    assert by["#ffffff"] == 2 and by["#c00000"] == 22
    square = np.array([[-1.0, 0.0], [1.0, 0.0], [1.0, 2.0], [-1.0, 2.0]])
    assert half_outline(square, "left")[:, 0].max() == pytest.approx(0.0)
    assert half_outline(square, "right")[:, 0].min() == pytest.approx(0.0)
