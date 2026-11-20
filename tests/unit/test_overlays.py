"""Overlays (appliqués sewn on the envelope, ADR-0056): outlines, the layout on the
envelope and its analytic cases, sessions and files, findings, and the build pack."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from envelopelab.export.build_pack import PackExtras, export_build_pack
from envelopelab.export.qa import check_pack
from envelopelab.project import edits
from envelopelab.project.colours import PanelRef
from envelopelab.project.model import dump_project, load_project_text
from envelopelab.project.overlays import (
    OverlaySpec,
    cloth_half_width,
    outline_points,
    overlay_findings,
    overlay_layout,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import ShapePlacement, default_shape, envelope_surface

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
STAR = [
    (0, 0.6),
    (0.15, 0.15),
    (0.6, 0),
    (0.15, -0.15),
    (0, -0.6),
    (-0.15, -0.15),
    (-0.6, 0),
    (-0.15, 0.15),
]


@pytest.fixture
def session() -> ProjectSession:
    return ProjectSession.open(FIXTURE)


def _spec(
    name: str = "sun", gore: int = 2, s: float = 3.5, across: float = 0.0, **kw: Any
) -> OverlaySpec:
    return OverlaySpec(
        name=name, placement=ShapePlacement(gore=gore, tape_position=s, across=across), **kw
    )


def _rows_mid(session: ProjectSession, i: int) -> float:
    surface = envelope_surface(session.design, session.patterns)
    band = surface.rows[i]
    return 0.5 * (band.s_bottom + band.s_top)


# -- outlines ----------------------------------------------------------------------------


def test_outline_sizes_turn_and_orientation() -> None:
    circle = outline_points(_spec(width=0.8))
    assert np.allclose(np.hypot(circle[:, 0], circle[:, 1]), 0.4)
    rect = outline_points(_spec(outline="rectangle", width=0.6, height=0.2, turn_deg=90))
    assert np.ptp(rect[:, 0]) == pytest.approx(0.2) and np.ptp(rect[:, 1]) == pytest.approx(0.6)
    for p in (circle, rect):  # anticlockwise
        assert np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(np.roll(p[:, 0], -1), p[:, 1]) > 0
    imported = outline_points(
        _spec(outline="outline", width=1.0, height=1.0, points=[(0, 0), (40, 0), (40, 10), (0, 10)])
    )
    assert np.ptp(imported[:, 0]) == pytest.approx(1.0) and np.ptp(imported[:, 1]) == pytest.approx(
        0.25
    )
    with pytest.raises(ValueError, match="crosses itself"):
        outline_points(_spec(outline="polygon", points=[(0, 0), (1, 1), (1, 0), (0, 1)]))
    with pytest.raises(ValueError, match="at least 3"):
        _spec(outline="polygon", points=[(0, 0), (1, 1)])


# -- layout --------------------------------------------------------------------------------


def test_centred_in_one_lobe_panel_the_marked_line_is_the_outline(session: ProjectSession) -> None:
    """Analytic case: centred on the gore centreline, inside one row, the mapping is a
    pure translation (x = a, y = s0 + b - s_bottom), so the marked line is the outline."""
    surface = envelope_surface(session.design, session.patterns)
    s0 = _rows_mid(session, 1)
    layout = overlay_layout(_spec(s=s0, width=0.5), surface)
    (run,) = layout.runs
    assert layout.crossings == [] and (run.gore, run.row) == (2, surface.rows[1].label)
    shift = np.array([0.0, s0 - surface.rows[1].s_bottom])
    assert np.allclose(run.panel[:-1], layout.outline + shift, atol=1e-9)
    assert layout.marked == pytest.approx(layout.perimeter, abs=1e-9)
    assert layout.ease == pytest.approx(0.0, abs=1e-9) and layout.warnings() == []


def test_crossing_a_gore_seam_splits_the_line_at_the_seam(session: ProjectSession) -> None:
    surface = envelope_surface(session.design, session.patterns)
    s0 = _rows_mid(session, 1)
    layout = overlay_layout(_spec(across=0.5, s=s0, width=0.6), surface)
    assert {r.gore for r in layout.runs} == {2, 3} and len(layout.crossings) == 2
    for run in layout.runs:
        # Each run ends on its panel's gore seam: |x| = h(s) at both ends.
        for end, s in ((run.panel[0], run.gs[0, 1]), (run.panel[-1], run.gs[-1, 1])):
            assert abs(end[0]) == pytest.approx(float(cloth_half_width(surface, s)[0]), abs=1e-9)
    assert layout.marked == pytest.approx(layout.perimeter, rel=0.01)
    assert sorted(layout.covered) == [(2, surface.rows[1].label), (3, surface.rows[1].label)]


def test_wrap_round_from_the_last_gore_to_the_first(session: ProjectSession) -> None:
    """Regression: a polygon whose corners lie exactly on the seam between the last gore
    and the first is still split there."""
    surface = envelope_surface(session.design, session.patterns)
    n = surface.gore_count
    layout = overlay_layout(
        _spec(gore=n, across=0.5, s=_rows_mid(session, 2), outline="polygon", points=STAR),
        surface,
    )
    assert {r.gore for r in layout.runs} == {1, n} and len(layout.crossings) == 2
    left = next(r for r in layout.runs if r.gore == 1)
    assert left.panel[:, 0].max() < 0.0  # in gore 1 it lies on the left of the centreline


def test_crossing_a_row_seam(session: ProjectSession) -> None:
    surface = envelope_surface(session.design, session.patterns)
    seam = surface.rows[1].s_top
    layout = overlay_layout(_spec(s=seam, width=0.4), surface)
    assert {r.row for r in layout.runs} == {surface.rows[1].label, surface.rows[2].label}
    for run in layout.runs:
        ends = run.gs[[0, -1], 1]
        assert np.allclose(ends, seam)


def test_overlays_that_cannot_be_laid(session: ProjectSession) -> None:
    surface = envelope_surface(session.design, session.patterns)
    with pytest.raises(ValueError, match="mouth"):
        overlay_layout(_spec(s=0.2, width=1.0), surface)
    with pytest.raises(ValueError, match="wider than the whole envelope"):
        overlay_layout(_spec(outline="rectangle", width=40.0, height=0.2, s=4.0), surface)
    findings = overlay_findings([_spec(s=0.2, width=1.0)], surface)
    assert [f.severity for f in findings] == ["error"] and findings[0].target == "shape:sun"


def test_a_large_patch_on_a_curved_envelope_is_warned(session: ProjectSession) -> None:
    surface = envelope_surface(session.design, session.patterns)
    layout = overlay_layout(_spec(across=0.5, s=4.8, width=2.5), surface)
    assert abs(layout.ease) > 0.01 * layout.perimeter
    (finding,) = overlay_findings([layout.spec], surface)
    assert finding.severity == "warning" and "work the ease in" in finding.message


# -- sessions and files ----------------------------------------------------------------------


def test_add_edit_duplicate_remove_and_undo(session: ProjectSession) -> None:
    fingerprints = session.fingerprints()
    assert edits.add_overlay(session, _spec())
    changed = {k for k, v in session.fingerprints().items() if fingerprints[k] != v}
    assert changed == {"export"}  # only the build pack reads overlays
    assert edits.update_overlay(session, "sun", {"width": 0.5, "placement": {"across": 0.2}})
    (spec,) = session.state.overlays
    assert spec.width == 0.5 and spec.placement.across == 0.2 and spec.placement.gore == 2
    with pytest.raises(ValueError, match="mouth"):
        edits.update_overlay(session, "sun", {"placement": {"tape_position": 0.1}})
    copy = edits.duplicate_overlay(session, "sun")
    assert copy == "sun 2" and session.state.overlays[1].placement.gore == 3
    edits.remove_overlay(session, "sun")
    assert [o.name for o in session.state.overlays] == ["sun 2"]
    session.undo()
    session.undo()
    assert [o.name for o in session.state.overlays] == ["sun"]
    with pytest.raises(KeyError):
        edits.remove_overlay(session, "nope")


def test_names_are_shared_with_special_shapes(session: ProjectSession) -> None:
    shape = default_shape("dome", session.design, "Nose")
    edits.add_shape(session, shape)
    with pytest.raises(ValueError, match="must be unique"):
        edits.add_overlay(session, _spec(name="Nose"))
    assert edits.unique_name(session, "Nose") == "Nose 2"


def test_a_renamed_overlay_keeps_its_colour_and_files_round_trip(
    session: ProjectSession, tmp_path: Path
) -> None:
    assert "overlays" not in json.loads(dump_project(session.project))["state"]
    edits.add_overlay(session, _spec())
    edits.paint_panels(session, [PanelRef("sun", "A", 1)], "#ffc000")
    edits.update_overlay(session, "sun", {"name": "Sol"})
    assert session.state.colours.colour_of(PanelRef("Sol", "A", 1)) == "#ffc000"
    path = session.save(tmp_path / "o.elproj")
    again = ProjectSession.open(path)
    assert again.state.overlays == session.state.overlays
    assert load_project_text(path.read_text("utf-8")).state.overlays[0].name == "Sol"
    # Other edits keep the overlays.
    edits.add_shape(again, default_shape("dome", again.design, "Nose"))
    assert [o.name for o in again.state.overlays] == ["Sol"]


# -- build pack ----------------------------------------------------------------------------


def test_build_pack_cuts_and_marks_every_overlay(session: ProjectSession, tmp_path: Path) -> None:
    overlays = [
        _spec(across=0.5, s=4.8, width=1.6),
        _spec(name="star", gore=8, across=0.5, s=6.0, outline="polygon", points=STAR),
    ]
    for o in overlays:
        edits.add_overlay(session, o)
    edits.paint_panels(session, [PanelRef("sun", "A", 1)], "#ffc000")
    export_build_pack(
        session.design,
        [],
        tmp_path,
        session.patterns,
        extras=PackExtras(frozenset({"planning"})),
        colours=session.state.colours,
        overlays=session.state.overlays,
    )
    assert check_pack(tmp_path) == []
    index = json.loads((tmp_path / "cad" / "index.json").read_text("utf-8"))
    sheets = {s["file"]: s for s in index["sheets"]}
    sun = sheets["cad/sun-overlay.dxf"]
    assert sun["kind"] == "overlay" and sun["cut_count"] == 1
    assert sun["colours"] == [{"colour": "#ffc000", "count": 1, "numbers": [1]}]
    surface = envelope_surface(session.design, session.patterns)
    layout = overlay_layout(session.state.overlays[0], surface)
    marks = {f"cad/sun-mark-G{g}-{r}.dxf" for g, r in {(x.gore, x.row) for x in layout.runs}}
    assert marks <= set(sheets) and all(sheets[m]["kind"] == "marking" for m in marks)
    pair = next(p for p in index["seam_pairs"] if p["a"][0]["file"] == "cad/sun-overlay.dxf")
    assert pair["ease_mm"] == pytest.approx(layout.ease * 1000.0, abs=1e-3)
    assert any(t["file"].endswith("-sun-overlay.pdf") for t in index["templates"])
    assert any(t["file"].endswith("-star-overlay.pdf") for t in index["templates"])
    with (tmp_path / "generic-standard-gore-fixture-colour-cloth.csv").open(encoding="utf-8") as f:
        assert "#ffc000,1," in f.read()


def test_overlay_fabric_defaults_to_the_row_under_it(
    session: ProjectSession, tmp_path: Path
) -> None:
    edits.add_overlay(session, _spec(s=3.5))
    edits.add_overlay(session, _spec(name="tag", gore=5, s=3.5, width=0.3, fabric="red ripstop"))
    export_build_pack(
        session.design, [], tmp_path, session.patterns, overlays=session.state.overlays
    )
    index = json.loads((tmp_path / "cad" / "index.json").read_text("utf-8"))
    by = {s["piece"]: s["fabric"] for s in index["sheets"]}
    row_fabric = next(s["fabric"] for s in index["sheets"] if s["kind"] == "envelope panel")
    assert by["sun overlay"] == row_fabric and by["tag overlay"] == "red ripstop"
    assert math.isfinite(len(index["seam_pairs"]))
