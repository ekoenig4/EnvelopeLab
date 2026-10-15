"""Synthetic flat-chord pattern set and its special shapes (tests/fixtures/flat_chord_pattern/)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from envelopelab.export.build_pack import primitive_sheets
from envelopelab.features.primitives import PrimitiveDesign
from envelopelab.io.shape_file import load_shape_file
from envelopelab.project.gore_design import gore_outputs, panel_rows, panel_zone, seam_mismatches
from envelopelab.project.model import PatternSet
from envelopelab.project.shapes import (
    DomeShape,
    MeshShape,
    TubeShape,
    envelope_surface,
    shape_design,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "flat_chord_pattern"
SHAPE = load_shape_file(FIXTURE / "shape.yaml")
SPECIAL = load_shape_file(FIXTURE / "special.yaml")
DESIGN = SHAPE.design()
ROWS = panel_rows(DESIGN, PatternSet())


def test_generated_files_are_current() -> None:
    done = subprocess.run(
        [sys.executable, str(FIXTURE / "make_fixture.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_blister_mesh_is_the_same_on_every_platform() -> None:
    """Faces come from integer arithmetic; vertices are compared to a tolerance."""
    sys.path.insert(0, str(FIXTURE))
    try:
        import make_fixture
    finally:
        sys.path.remove(str(FIXTURE))
    uv, tri = make_fixture.footprint(0.9, 0.7)
    p, q, w = uv[tri[:, 0]], uv[tri[:, 1]], uv[tri[:, 2]]
    ccw = (q[:, 0] - p[:, 0]) * (w[:, 1] - p[:, 1]) - (q[:, 1] - p[:, 1]) * (w[:, 0] - p[:, 0])
    assert np.all(ccw > 0)
    text = (FIXTURE / "shapes" / "blister.obj").read_text(encoding="utf-8")
    nudged = text.replace("v 0.000000 -0.000000 0.500000", "v 0.000001 0.000000 0.500000", 1)
    assert nudged != text and make_fixture.same_mesh(text, nudged)
    first_face = next(line for line in text.splitlines() if line.startswith("f "))
    assert not make_fixture.same_mesh(text, text.replace(first_face, "f 1 3 2", 1))


def test_the_design_is_the_whole_pattern_set() -> None:
    gores = DESIGN.gores
    assert gores is not None
    assert gores.count == 16
    assert gores.construction == "flat_chord" and gores.profile_interpolation == "linear"
    assert [r.letter for r in gores.panel_rows] == [r.name for r in SHAPE.rows]
    assert gores.panel_rows[0].zone == "mouth" and DESIGN.zones["mouth"] == "nomex"
    assert gores.seal_overlap == pytest.approx(0.3)
    assert DESIGN.parachute is not None and DESIGN.parachute.panel_count == 16
    assert [(v.seam, v.rows) for v in DESIGN.turning_vents] == [(4, ["E", "F"]), (12, ["E", "F"])]
    assert DESIGN.meta.content_hash == DESIGN.compute_content_hash()


def test_measured_bows_are_reproduced_and_the_rows_sew_together() -> None:
    for row, spec in zip(ROWS, SHAPE.rows, strict=True):
        assert spec.bows is not None
        assert (row.bottom_bow, row.top_bow) == pytest.approx(spec.bows, abs=1e-12)
        assert row.side_length == pytest.approx(row.s_top - row.s_bottom, rel=1e-12)
    assert seam_mismatches(ROWS, PatternSet()) == []
    total = sum(r.s_top - r.s_bottom for r in ROWS)
    assert total == pytest.approx(SHAPE.hold["tape_length"], abs=1e-6)


def test_crest_seams_are_symmetric_and_differ_from_the_measured_ones() -> None:
    crest = panel_rows(SHAPE.design(seams="crest"), PatternSet())
    for low, high in zip(crest, crest[1:], strict=False):
        assert low.top_bow == pytest.approx(high.bottom_bow, abs=1e-12)
    # The measured bows come from a 2.5 % crest, the file's loft is 2 %.
    measured = np.array([r.bottom_bow + r.top_bow for r in ROWS])
    generated = np.array([r.bottom_bow + r.top_bow for r in crest])
    assert np.max(np.abs(measured - generated)) > 1e-3
    assert generated.sum() == pytest.approx(0.8 * measured.sum(), rel=0.15)


def test_a_scaled_variant_scales_the_bows() -> None:
    variant = SHAPE.design(
        SHAPE.solve({**SHAPE.hold, "tape_length": 1.5 * SHAPE.hold["tape_length"]})
    )
    assert variant.gores is not None and DESIGN.gores is not None
    for big, small in zip(variant.gores.panel_rows, DESIGN.gores.panel_rows, strict=True):
        assert big.finished_height == pytest.approx(1.5 * small.finished_height)
        assert big.bow_top == pytest.approx(1.5 * (small.bow_top or 0.0))


@pytest.fixture(scope="module")
def placed() -> dict[str, PrimitiveDesign]:
    design = SPECIAL.design()
    surface = envelope_surface(design, PatternSet())
    return {spec.name: shape_design(spec, surface) for spec in SPECIAL.shapes(design)}


def test_extends_adds_zones_and_shapes() -> None:
    design = SPECIAL.design()
    assert design.gores is not None and DESIGN.gores is not None
    assert design.gores.model_dump(exclude={"panel_zones"}) == DESIGN.gores.model_dump(
        exclude={"panel_zones"}
    )
    assert panel_zone(design, PatternSet(), "C", 16) == "accent"
    assert panel_zone(design, PatternSet(), "G", 5) == "doubled"
    outputs = gore_outputs(design, PatternSet())
    assert outputs.mass is not None
    assert {"body", "mouth", "accent", "doubled"} <= set(outputs.mass.zones)
    dome, horn, blister = SPECIAL.shapes(design)
    assert isinstance(dome, DomeShape) and isinstance(horn, TubeShape)
    assert isinstance(blister, MeshShape) and len(blister.feed_holes) == 2


def test_shapes_are_placed_with_their_feed_holes(placed: dict[str, PrimitiveDesign]) -> None:
    assert placed["dome"].designed_height == pytest.approx(0.6, abs=1e-3)
    assert placed["blister"].designed_height == pytest.approx(0.5, abs=1e-3)
    assert [(h.gore, h.row) for h in placed["blister"].feed_holes] == [(13, "D"), (13, "D")]
    for design in placed.values():
        holes = [c for c in design.checks if c.name == "feed hole inside footprint"]
        assert holes and all(c.severity == "info" for c in holes)
    sheets = primitive_sheets(placed["blister"], "accent")
    marking = [s for s in sheets if s.kind == "marking"]
    assert sum(len(s.holes) for s in marking) == 2


def test_known_findings_are_reported(placed: dict[str, PrimitiveDesign]) -> None:
    # The flat-panel attachment ease of these shapes is above the 3 mm default (README.md).
    for design in placed.values():
        ease = [c for c in design.checks if c.name == "attachment ease"]
        assert ease and ease[0].severity == "error"
