"""Shop documents of a build pack: index, spec summary, build log (metric + English)."""

from __future__ import annotations

from pathlib import Path

import pytest

from envelopelab.export.build_pack import PackExtras, envelope_sheets, export_build_pack
from envelopelab.export.documents import DOCUMENTS
from envelopelab.export.qa import _page_boxes, check_pack
from envelopelab.export.shop import (
    A3_LANDSCAPE,
    A4_LANDSCAPE,
    PackContext,
    both,
    build_log_sheets,
    build_order,
    ft_in,
    key_specs,
    largest_piece,
    volume_both,
)
from envelopelab.export.templates import template_files
from envelopelab.features.primitives import Dome, EnvelopeSurface, Placement, design_primitive
from envelopelab.project.gore_design import gore_outputs, standard_gore_design
from envelopelab.project.model import PatternSet

DESIGN = standard_gore_design("Shop Sample", 2600.0, 18.3, 17.9, 20, 17)
SHAPES = [
    design_primitive(
        Dome("eye", Placement(3, 11.0, across=0.5), 1.2, 1.0, 12),
        EnvelopeSurface.from_design(DESIGN),
    )
]


def test_english_units_are_exact_conversions() -> None:
    assert ft_in(0.3048 * 60 + 0.0254 * 2) == "60 ft 2 in"
    assert both(18.338) == "18,338 mm / 60 ft 2 in"
    assert both(0.36) == "360 mm / 14.2 in"
    assert volume_both(2610.0) == "2,610 m3 / 92,171 cu ft"


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("shop")
    export_build_pack(DESIGN, SHAPES, out, extras=PackExtras(frozenset(DOCUMENTS)))
    return out


def test_index_spec_and_log_are_written_on_their_page_sizes(pack: Path) -> None:
    assert check_pack(pack) == []
    index = _page_boxes(pack / "shop-sample-00-BUILD-PACK-INDEX.pdf")
    assert len(index) == 3
    assert all(abs(w - A3_LANDSCAPE[0]) < 1 and abs(h - A3_LANDSCAPE[1]) < 1 for w, h, _ in index)
    text = "".join(c for _w, _h, c in index)
    for heading in ("BUILD PACK", "FEATURES", "SHOP LIMITS", "FILE INDEX", "BUILD ORDER"):
        assert heading in text
    assert "shop-sample-panel-" in text and "shop-sample-eye-patterns.pdf" in text
    spec = _page_boxes(pack / "shop-sample-spec-summary.pdf")
    assert abs(spec[0][0] - A4_LANDSCAPE[0]) < 1
    assert "METRIC" in spec[0][2] and "ENGLISH" in spec[0][2]
    log = _page_boxes(pack / "shop-sample-build-log.pdf")
    assert "BUILD LOG 1/" in log[0][2] and len(log) >= 3


def _ctx() -> PackContext:
    sheets = envelope_sheets(DESIGN)
    return PackContext(
        DESIGN,
        gore_outputs(DESIGN, PatternSet()),
        sheets,
        [],
        SHAPES,
        template_files(DESIGN.meta.name, sheets),
        60 * 0.0254,
        slug="shop-sample",
    )


def test_key_specs_and_build_order_come_from_the_design() -> None:
    ctx = _ctx()
    specs = dict(key_specs(ctx))
    out = ctx.outputs
    assert out is not None
    assert specs["Volume"] == volume_both(out.volume)
    assert specs["Gores"] == "20 gores x 17 panel rows"
    steps = [name for name, _text in build_order(ctx)]
    assert steps[0] == "PRINT & VERIFY" and steps[-1] == "INSPECT & SIGN OFF"
    assert "EYE SKIN" in steps and "EYE" in steps and "BUILD GORES" in steps
    cut = dict(build_order(ctx))["CUT PANELS"]
    assert "20 x A" in cut


def test_build_log_has_a_sheet_per_shape_and_lists_every_row() -> None:
    sheets = build_log_sheets(_ctx())
    titles = [t for t, _s, _i in sheets]
    assert titles[0] == "PANEL CUTTING" and "EYE" in titles
    rows = [item for item, _spec in sheets[0][2]]
    assert len([r for r in rows if r.startswith("Panel ")]) == 17
    assert all(r.endswith("x20") for r in rows if r.startswith("Panel "))


def test_largest_piece_is_measured_from_the_cut_outlines() -> None:
    short, long, name = largest_piece(envelope_sheets(DESIGN))
    assert name.startswith("envelope-row-") and short < long
    assert short < 1.6  # the rows of this design are about 1.4 m tall


def test_appendage_and_top_bottom_documents(pack: Path) -> None:
    from envelopelab.export.appendages import build_steps

    spec = _page_boxes(pack / "shop-sample-eye.pdf")
    text = "".join(c for _w, _h, c in spec)
    assert "SKIN CUT LIST" in text and "MATCH MARKS" in text
    build = "".join(c for _w, _h, c in _page_boxes(pack / "shop-sample-eye-build.pdf"))
    assert "BUILD PROCEDURE" in build and "notes:" in build
    steps = [s for s, _t in build_steps(_ctx(), SHAPES[0])]
    assert steps[0] == "PRINT & CHECK" and "SEW THE RIM" in steps and steps[-1] == "INSPECT"
    chute = "".join(c for _w, _h, c in _page_boxes(pack / "shop-sample-parachute.pdf"))
    assert "PARACHUTE - PATTERN DATA" in chute and "shroud line" in chute
    scoop = "".join(c for _w, _h, c in _page_boxes(pack / "shop-sample-scoop.pdf"))
    assert "FLYING WIRES" in scoop
    # No vents in this design: no vent sheets.
    assert not (pack / "shop-sample-turning-vents.pdf").exists()
