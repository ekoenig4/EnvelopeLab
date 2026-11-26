"""Scale-model build packs: scaling the sheets, fitting the paper, the paper pages."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.export.build_pack import (
    PT_PER_M,
    BuildPackError,
    PackExtras,
    SeamPair,
    Sheet,
    export_build_pack,
    pack_sheets,
)
from envelopelab.export.qa import _page_boxes, check_pack
from envelopelab.export.scale_model import (
    INCH,
    PAPER_SIZES,
    PaperSize,
    ScaleModel,
    fit_scale,
    oversize_pieces,
    paper_fit,
    piece_scale_limit,
    scale_pack,
    scale_seam_pair,
    scale_sheet,
)
from envelopelab.geometry.polygon import offset_polygon
from envelopelab.project.gore_design import standard_gore_design

DESIGN = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
LETTER = PAPER_SIZES["letter"]


def _rect(w: float, h: float) -> np.ndarray:
    return np.array([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]])


def _sheet(w: float, h: float, allowance: float = 0.02) -> Sheet:
    finished = _rect(w, h)
    return Sheet(
        name="box",
        piece="box",
        kind="envelope panel",
        cut_count=2,
        fabric="nylon",
        finished=finished,
        cut=offset_polygon(finished, allowance),
        edges={"bottom": finished[:2].copy()},
        marks=[(0.5 * w, 0.5 * h, "1")],
        holes=[(0.5 * w, 0.5 * h, 0.1)],
        hole_cuts=[(0.5 * w, 0.5 * h, 0.08)],
        lines=[finished[1:3].copy()],
        texts=[(0.1, 0.1, "sew")],
        colours=[("#ff0000", [1, 2])],
    )


def test_paper_sizes_are_the_standards() -> None:
    assert (LETTER.width, LETTER.height) == pytest.approx((0.2159, 0.2794))
    assert (PAPER_SIZES["a4"].width, PAPER_SIZES["a4"].height) == (0.210, 0.297)
    assert PAPER_SIZES["tabloid"].height == pytest.approx(17 * INCH)
    with pytest.raises(BuildPackError):
        PaperSize("wrong way", 0.3, 0.2)


def test_scale_model_validates_and_labels() -> None:
    model = ScaleModel(20.0)
    assert model.factor == pytest.approx(0.05)
    assert model.label() == "1:20"
    assert ScaleModel(12.5).label() == "1:12.5"
    assert model.printable == pytest.approx((0.2159 - 0.0254, 0.2794 - 0.0254))
    for bad in (0.0, -2.0, math.inf, math.nan):
        with pytest.raises(BuildPackError):
            ScaleModel(bad)
    with pytest.raises(BuildPackError):
        ScaleModel(10.0, margin=0.11)
    with pytest.raises(BuildPackError):
        ScaleModel(10.0, seam_allowance=-0.001)


def test_scale_sheet_scales_every_length() -> None:
    sheet = _sheet(2.0, 1.0)
    k = 0.1
    out = scale_sheet(sheet, k)
    assert out.finished == pytest.approx(sheet.finished * k)
    assert out.cut == pytest.approx(sheet.cut * k)
    assert out.edges["bottom"] == pytest.approx(sheet.edges["bottom"] * k)
    ((mx, my, mark),) = out.marks
    assert (mx, my) == pytest.approx((0.1, 0.05)) and mark == "1"
    assert out.holes[0] == pytest.approx((0.1, 0.05, 0.01))
    assert out.hole_cuts[0] == pytest.approx((0.1, 0.05, 0.008))
    assert out.lines[0] == pytest.approx(sheet.lines[0] * k)
    assert out.texts[0][:2] == pytest.approx((0.01, 0.01))
    assert out.finished_size == pytest.approx((0.2, 0.1))
    assert (out.name, out.piece, out.cut_count, out.fabric) == ("box", "box", 2, "nylon")
    assert out.colours == sheet.colours and out.colours is not sheet.colours
    # The original is untouched.
    assert sheet.finished_size == pytest.approx((2.0, 1.0))
    with pytest.raises(BuildPackError):
        scale_sheet(sheet, 0.0)


def test_fixed_allowance_offsets_the_scaled_finished_outline() -> None:
    sheet = _sheet(2.0, 1.0, allowance=0.02)
    out = scale_sheet(sheet, 0.1, seam_allowance=0.005)
    lo, hi = out.cut.min(axis=0), out.cut.max(axis=0)
    assert lo == pytest.approx((-0.005, -0.005))
    assert hi == pytest.approx((0.205, 0.105))
    bare = scale_sheet(sheet, 0.1, seam_allowance=0.0)
    assert bare.cut == pytest.approx(bare.finished)


def test_seam_ease_scales() -> None:
    pair = SeamPair((("a", "left"),), (("b", "right"),), ease=0.03)
    assert scale_seam_pair(pair, 0.05).ease == pytest.approx(0.0015)
    assert scale_seam_pair(pair, 0.05).a == pair.a


def test_paper_fit_turns_and_lands_the_piece() -> None:
    printable = ScaleModel(1.0).printable  # 190.5 x 254.0 mm
    upright = paper_fit(_rect(0.15, 0.25), printable)
    assert (upright.angle, upright.landscape, upright.fits) == (0.0, False, True)
    wide = paper_fit(_rect(0.25, 0.15), printable)
    assert wide.fits and (wide.angle == 90.0 or wide.landscape)
    # Too long for either side, short enough for the diagonal (317 mm).
    diagonal = paper_fit(_rect(0.30, 0.01), printable)
    assert diagonal.fits and diagonal.angle not in (0.0, 90.0)
    assert diagonal.width <= printable[0] + 1e-12 or diagonal.landscape
    assert not paper_fit(_rect(0.40, 0.01), printable).fits


def test_scale_limit_of_a_rectangle_is_analytic() -> None:
    # Scaled allowance: the cut box (2.04 x 1.04 m) at its best orientation: landscape,
    # k = min(254.0 / 2040, 190.5 / 1040).
    sheet = _sheet(2.0, 1.0, allowance=0.02)
    model = ScaleModel(1.0)
    pw, ph = model.printable
    assert piece_scale_limit(sheet, model) == pytest.approx(min(ph / 2.04, pw / 1.04), rel=1e-9)
    # Fixed allowance a: the finished box scaled, then a on every side.
    a = 0.005
    fixed = ScaleModel(1.0, seam_allowance=a)
    want = min((ph - 2 * a) / 2.0, (pw - 2 * a) / 1.0)
    assert piece_scale_limit(sheet, fixed) == pytest.approx(want, rel=1e-6)
    with pytest.raises(BuildPackError):
        piece_scale_limit(sheet, ScaleModel(1.0, seam_allowance=0.1))


def test_fit_scale_finds_the_largest_whole_scale_that_fits() -> None:
    sheets = pack_sheets(DESIGN)[0]
    for allowance in (None, 0.005):
        model = ScaleModel(1.0, LETTER, seam_allowance=allowance)
        n = fit_scale(sheets, model)
        exact = fit_scale(sheets, model, whole=False)
        assert n == math.ceil(exact) and n.is_integer()
        assert oversize_pieces(sheets, ScaleModel(n, LETTER, seam_allowance=allowance)) == []
        assert oversize_pieces(sheets, ScaleModel(n - 1, LETTER, seam_allowance=allowance))
    # Bigger paper, larger model.
    tabloid = fit_scale(sheets, ScaleModel(1.0, PAPER_SIZES["tabloid"]))
    assert tabloid < fit_scale(sheets, ScaleModel(1.0, LETTER))
    with pytest.raises(BuildPackError):
        fit_scale([], ScaleModel(1.0))


def test_scale_pack_notes_the_scale_on_every_sheet() -> None:
    sheets, pairs, _ = pack_sheets(DESIGN)
    scaled, scaled_pairs = scale_pack(sheets, pairs, ScaleModel(25.0))
    assert len(scaled) == len(sheets) and len(scaled_pairs) == len(pairs)
    for full, model in zip(sheets, scaled, strict=True):
        assert model.notes[0] == "SCALE MODEL 1:25 - not a full-size pattern"
        assert np.array(model.finished_size) == pytest.approx(np.array(full.finished_size) / 25)


def test_scale_model_pack_passes_qa_on_paper_pages(tmp_path: Path) -> None:
    full = tmp_path / "full"
    export_build_pack(DESIGN, [], full)
    model = ScaleModel(fit_scale(pack_sheets(DESIGN)[0], ScaleModel(1.0)), LETTER)
    out = tmp_path / "model"
    export_build_pack(DESIGN, [], out, scale_model=model)
    assert check_pack(out) == []
    index = json.loads((out / "cad" / "index.json").read_text())
    entry = index["scale_model"]
    assert entry["scale"] == model.label() and entry["factor"] == pytest.approx(model.factor)
    assert (entry["paper_width_mm"], entry["paper_height_mm"]) == (215.9, 279.4)
    assert entry["seam_allowance_mm"] is None
    assert index["title"] == f"generic model 1-{model.denominator:g}"
    assert json.loads((full / "cad" / "index.json").read_text())["scale_model"] is None
    # Finished sizes are the full-size ones divided by n (headers rounded to mm).
    big = {s["file"]: s for s in json.loads((full / "cad" / "index.json").read_text())["sheets"]}
    for s in index["sheets"]:
        for key in ("finished_width_mm", "finished_height_mm"):
            assert s[key] == pytest.approx(big[s["file"]][key] / model.denominator, abs=1e-3)
    # Every page is one Letter sheet, either way up, and says how to print it.
    paper = {(round(LETTER.width * PT_PER_M), round(LETTER.height * PT_PER_M))}
    paper |= {(h, w) for w, h in paper}
    for t in index["templates"]:
        assert t["file"].startswith("generic-model-")
        for (w, h, content), page in zip(_page_boxes(out / t["file"]), t["pages"], strict=True):
            assert (round(w), round(h)) in paper
            assert page["fits_paper"] is True
            assert f"SCALE MODEL {model.label()}" in content and "print at 100 %" in content


def test_oversize_model_pieces_are_flagged_not_hidden(tmp_path: Path) -> None:
    out = tmp_path / "big"
    export_build_pack(DESIGN, [], out, scale_model=ScaleModel(5.0))
    assert check_pack(out) == []
    index = json.loads((out / "cad" / "index.json").read_text())
    pages = [p for t in index["templates"] for p in t["pages"]]
    assert any(not p["fits_paper"] for p in pages)
    flagged = [
        content
        for t in index["templates"]
        for (_w, _h, content), page in zip(_page_boxes(out / t["file"]), t["pages"], strict=True)
        if not page["fits_paper"]
    ]
    assert flagged and all("LARGER THAN THE US LETTER" in c for c in flagged)


def test_qa_catches_a_page_that_is_not_the_paper(tmp_path: Path) -> None:
    out = tmp_path / "model"
    export_build_pack(DESIGN, [], out, scale_model=ScaleModel(30.0, PAPER_SIZES["a4"]))
    assert check_pack(out) == []
    path = out / "cad" / "index.json"
    index = json.loads(path.read_text())
    index["scale_model"]["paper_width_mm"] = 100.0
    index["scale_model"]["scale"] = "1:31"
    path.write_text(json.dumps(index))
    checks = {f.check for f in check_pack(out)}
    assert {"page size", "scale"} <= checks


def test_scale_model_pack_has_no_documents(tmp_path: Path) -> None:
    with pytest.raises(BuildPackError, match="no documents"):
        export_build_pack(
            DESIGN,
            [],
            tmp_path,
            extras=PackExtras(include=frozenset({"planning"})),
            scale_model=ScaleModel(20.0),
        )
