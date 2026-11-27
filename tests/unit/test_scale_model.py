"""Scale-model build packs: scaling the design and sheets, fitting the paper, the paper
pages and the documents at model size."""

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
    Sheet,
    export_build_pack,
    pack_sheets,
)
from envelopelab.export.documents import DOCUMENTS
from envelopelab.export.qa import _page_boxes, check_pack
from envelopelab.export.scale_model import (
    INCH,
    NOT_APPLICABLE,
    PAPER_SIZES,
    PaperSize,
    ScaleModel,
    fit_scale,
    oversize_pieces,
    paper_fit,
    piece_scale_limit,
    scale_design,
    scale_inputs,
    scale_overlay,
    scale_patterns,
    scale_primitive,
    scale_sheet,
)
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    Revolved,
    Tube,
    design_primitive,
)
from envelopelab.geometry.polygon import offset_polygon, signed_area
from envelopelab.project.gore_design import gore_outputs, standard_gore_design
from envelopelab.project.model import PatternSet, RowPattern
from envelopelab.project.overlays import OverlaySpec
from envelopelab.project.shapes import ShapePlacement

DESIGN = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
LETTER = PAPER_SIZES["letter"]
LETTER_H = 11.0 * 0.0254  # m


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
        PaperSize("no width", 0.0, 0.2)
    with pytest.raises(BuildPackError):
        PaperSize("no height", 0.2, -1.0)
    assert PaperSize.custom(0.3, 0.45).name == "custom 300 x 450 mm"
    strip = PaperSize.custom(0.6)
    assert strip.unbounded and strip.height is None
    assert strip.name == "max width 600 mm, any length"
    pw, ph = ScaleModel(10.0, strip, 0.01).printable
    assert pw == pytest.approx(0.58) and ph == math.inf


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
    paper = {(round(LETTER.width * PT_PER_M), round(LETTER_H * PT_PER_M))}
    paper |= {(h, w) for w, h in paper}
    for t in index["templates"]:
        assert t["file"].startswith("print/generic-model-")
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


def test_scale_design_scales_every_length_and_keeps_the_rest() -> None:
    model = ScaleModel(20.0)
    small = scale_design(DESIGN, model)
    g, sg = DESIGN.gores, small.gores
    assert g is not None and sg is not None
    assert small.meta.name == "generic model 1-20"
    for a, b in zip(
        g.meridian_profile_control_points, sg.meridian_profile_control_points, strict=True
    ):
        assert (b.x, b.y) == pytest.approx((a.x / 20, a.y / 20))
    for ra, rb in zip(g.panel_rows, sg.panel_rows, strict=True):
        assert rb.finished_height == pytest.approx(ra.finished_height / 20)
    for key in ("mouth_diameter", "crown_ring", "parachute_hole_diameter", "seal_overlap"):
        assert getattr(sg, key) == pytest.approx(getattr(g, key) / 20)
    assert small.tapes.vertical.width == pytest.approx(DESIGN.tapes.vertical.width / 20)
    assert small.seam_types[0].allowance == pytest.approx(DESIGN.seam_types[0].allowance / 20)
    assert DESIGN.parachute is not None and small.parachute is not None
    assert small.parachute.shroud_attachment == pytest.approx(
        DESIGN.parachute.shroud_attachment / 20
    )
    # Not geometric: kept, and never printed for the model.
    assert small.tapes.vertical.strength == DESIGN.tapes.vertical.strength
    assert small.operating == DESIGN.operating
    assert (sg.count, sg.loft) == (g.count, g.loft)
    # Volume k^3, height and area as lengths.
    full = gore_outputs(DESIGN, PatternSet())
    out = gore_outputs(small, PatternSet())
    assert out.volume == pytest.approx(full.volume / 20**3, rel=1e-9)
    assert out.height == pytest.approx(full.height / 20, rel=1e-9)
    assert out.area == pytest.approx(full.area / 20**2, rel=1e-9)
    fixed = scale_design(DESIGN, ScaleModel(20.0, seam_allowance=0.004))
    assert {s.allowance for s in fixed.seam_types} == {0.004}


def test_scaled_design_cuts_the_scaled_sheets() -> None:
    model = ScaleModel(25.0)
    full = pack_sheets(DESIGN)[0]
    small = pack_sheets(scale_design(DESIGN, model))[0]
    assert [s.name for s in small] == [s.name for s in full]
    for a, b in zip(full, small, strict=True):
        ref = scale_sheet(a, model.factor)
        assert b.finished == pytest.approx(ref.finished, abs=1e-9)
        assert b.cut == pytest.approx(ref.cut, abs=1e-9)
        for name, edge in ref.edges.items():
            assert b.edges[name] == pytest.approx(edge, abs=1e-9)


def test_patterns_and_overlays_scale() -> None:
    model = ScaleModel(10.0)
    rows = PatternSet(rows={"A": RowPattern(seam_allowance=0.02)})
    assert scale_patterns(rows, model).rows["A"].seam_allowance == pytest.approx(0.002)
    blank = PatternSet(rows={"B": RowPattern()})
    fixed = scale_patterns(blank, ScaleModel(10.0, seam_allowance=0.003))
    assert fixed.rows["B"].seam_allowance == 0.003
    spec = OverlaySpec(
        name="sun",
        placement=ShapePlacement(gore=2, tape_position=8.0, across=0.25),
        width=1.5,
        height=0.5,
        outline="polygon",
        points=[(0.0, 0.5), (0.5, 0.0), (0.0, -0.5)],
        hem=0.02,
    )
    small = scale_overlay(spec, model)
    assert small.placement.tape_position == pytest.approx(0.8)
    assert small.placement.across == 0.25
    assert (small.width, small.height, small.hem) == pytest.approx((0.15, 0.05, 0.002))
    want = np.array([[0.0, 0.05], [0.05, 0.0], [0.0, -0.05]])
    assert np.array(small.points) == pytest.approx(want)


def test_scale_primitive_scales_lengths_only() -> None:
    dome = Dome("d", Placement(3, 12.0, across=0.5, lean_deg=10.0), 1.0, 1.2, 16, cap_radius=0.2)
    small = scale_primitive(dome, 0.1)
    assert isinstance(small, Dome)
    pl = small.placement
    assert (pl.gore, pl.tape_position, pl.across, pl.lean_deg) == pytest.approx((3, 1.2, 0.5, 10.0))
    assert (small.base_radius, small.height, small.cap_radius) == pytest.approx((0.1, 0.12, 0.02))
    assert small.gores == 16
    tube = scale_primitive(Tube("t", Placement(1, 10.0), 0.8, 0.3, 2.0), 0.5)
    assert isinstance(tube, Tube)
    assert (tube.base_radius, tube.tip_radius, tube.length) == pytest.approx((0.4, 0.15, 1.0))
    rev = scale_primitive(Revolved("r", Placement(1, 9.0), ((0.4, 0.0), (0.0, 1.2))), 0.5)
    assert isinstance(rev, Revolved)
    assert rev.profile == ((0.2, 0.0), (0.0, 0.6))


SURFACE = EnvelopeSurface.from_design(DESIGN)
SHAPES = [
    design_primitive(
        Dome("ear", Placement(3, 12.0, across=0.5), 1.0, 1.2, gores=12), SURFACE, 0.0125
    ),
    design_primitive(Tube("horn", Placement(7, 10.0, lean_deg=20), 0.8, 0.3, 2.0), SURFACE),
]


def test_shapes_designed_again_at_model_size_match_the_scaled_pieces() -> None:
    model = ScaleModel(20.0)
    scaled = scale_inputs(DESIGN, SHAPES, None, [], model)
    for full, small in zip(SHAPES, scaled.primitives, strict=True):
        assert small.inputs is not None and full.inputs is not None
        assert small.inputs.seam_allowance == pytest.approx(full.inputs.seam_allowance / 20)
        assert small.footprint_length == pytest.approx(full.footprint_length / 20, rel=1e-6)
        assert len(small.pieces) == len(full.pieces) and len(small.marks) == len(full.marks)
        for a, b in zip(full.pieces, small.pieces, strict=True):
            # The skin is flattened again at model size: the same piece within 0.1 % in
            # area and in the length of every sewn edge.
            assert abs(signed_area(b.finished)) == pytest.approx(
                abs(signed_area(a.finished)) / 400, rel=1e-3
            )
            for name, edge in a.edges.items():
                la = float(np.linalg.norm(np.diff(edge, axis=0), axis=1).sum())
                lb = float(np.linalg.norm(np.diff(b.edges[name], axis=0), axis=1).sum())
                assert lb == pytest.approx(la / 20, rel=1e-3)


@pytest.mark.slow
def test_model_pack_writes_every_document_at_model_size(tmp_path: Path) -> None:
    out = tmp_path / "model"
    model = ScaleModel(20.0, LETTER, seam_allowance=0.005)
    include = frozenset(DOCUMENTS) - {"lift_chart"}
    export_build_pack(DESIGN, SHAPES, out, extras=PackExtras(include), scale_model=model)
    assert check_pack(out) == []
    index = json.loads((out / "cad" / "index.json").read_text())
    files = {d["file"] for d in index["documents"]}
    stem = "generic-model-1-20"
    for name in (
        "00-BUILD-PACK-INDEX.pdf",
        "spec-summary.pdf",
        "sewing-schedule.html",
        "build-log.pdf",
        "assembly-envelope.pdf",
        "assembly-ear.pdf",
        "ear-build.pdf",
        "parachute.pdf",
        "scoop.pdf",
        "3d.html",
        "ear-3d.html",
        "panel-dimensions.csv",
    ):
        assert f"{stem}-{name}" in files
    assert not any("lift-chart" in f for f in files)
    # Dimensions at model size: every panel's finished height in the CSV is the sheet's.
    rows = (out / f"{stem}-panel-dimensions.csv").read_text().splitlines()
    heights = {r.split(",")[0]: int(r.split(",")[3]) for r in rows[1:]}
    for s in index["sheets"]:
        if s["kind"] == "envelope panel" and "half" not in s["file"]:
            letter = s["piece"].removeprefix("row ")
            assert abs(heights[letter] - s["finished_height_mm"]) <= 1
    # Physics: never printed for a model, said to be n/a.
    from envelopelab.export.shop import PackContext, spec_rows
    from envelopelab.export.templates import template_files

    small = scale_design(DESIGN, model)
    sheets = pack_sheets(small)[0]
    ctx = PackContext(
        small,
        gore_outputs(small, PatternSet()),
        sheets,
        [],
        [],
        template_files(small.meta.name, sheets),
        model.printable[0],
        scale=model,
    )
    spec = {name: (metric, english) for name, metric, english, _note in spec_rows(ctx)}
    assert spec["Gross lift"] == (NOT_APPLICABLE, NOT_APPLICABLE)
    assert spec["Lift margin"] == (NOT_APPLICABLE, NOT_APPLICABLE)
    assert spec["Total volume"][0] == "0.25 m3"
    html = (out / f"{stem}-sewing-schedule.html").read_text()
    assert "5 mm" in html


def test_model_documents_mark_physics_not_applicable() -> None:
    from envelopelab.export.documents import rigging_table

    out = gore_outputs(scale_design(DESIGN, ScaleModel(20.0)), PatternSet())
    table = rigging_table(out.rigging, model=True)
    assert table.rows and not table.fails
    for row in table.rows:
        assert row[5] == row[6] == row[8] == row[10] == row[11] == NOT_APPLICABLE
        assert float(row[4]) > 0.0  # lengths are given


def test_scale_model_pack_has_no_lift_charts(tmp_path: Path) -> None:
    with pytest.raises(BuildPackError, match="no lift charts"):
        export_build_pack(
            DESIGN,
            [],
            tmp_path,
            extras=PackExtras(include=frozenset({"planning", "lift_chart"})),
            scale_model=ScaleModel(20.0),
        )


def test_width_only_print_gives_pages_of_that_width(tmp_path: Path) -> None:
    strip = PaperSize.custom(0.20)
    model = ScaleModel(1.0, strip, 0.005)
    sheets = pack_sheets(DESIGN)[0]
    n = fit_scale(sheets, model)
    # A strip as wide as Letter but of any length never needs a smaller model.
    wide = fit_scale(sheets, ScaleModel(1.0, PaperSize.custom(LETTER.width), 0.005))
    assert wide <= fit_scale(sheets, ScaleModel(1.0, LETTER, 0.005))
    out = tmp_path / "strip"
    export_build_pack(DESIGN, [], out, scale_model=ScaleModel(n, strip, 0.005))
    assert check_pack(out) == []
    index = json.loads((out / "cad" / "index.json").read_text())
    assert index["scale_model"]["paper_height_mm"] is None
    for t in index["templates"]:
        for (w, _h, _c), page in zip(_page_boxes(out / t["file"]), t["pages"], strict=True):
            assert w == pytest.approx(0.20 * PT_PER_M, abs=1.0)
            assert page["fits_paper"] is True


def test_model_summary_is_geometrically_similar() -> None:
    from envelopelab.export.scale_model import model_summary

    s = model_summary(2000.0, 17.0, 16.0, ScaleModel(20.0))
    assert (s.volume, s.height, s.max_diameter) == pytest.approx((0.25, 0.85, 0.8))
