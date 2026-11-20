"""Half gores: rows cut as two halves sewn down the gore centre, and the print-roll advice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from envelopelab.design.model import DesignDocument, _raw_hash, load_design_document
from envelopelab.export.build_pack import envelope_seam_pairs, envelope_sheets, row_sheets
from envelopelab.geometry.gore import (
    MeridianProfile,
    PanelRow,
    SeamAllowance,
    flat_chord_rows,
    half_panel,
)
from envelopelab.mass_estimate import MassEstimate
from envelopelab.project import edits
from envelopelab.project.dependencies import ARTIFACTS
from envelopelab.project.gore_design import (
    gore_outputs,
    panel_rows,
    row_allowance,
    row_pieces,
)
from envelopelab.project.roll_advice import piece_fits, roll_advice
from envelopelab.project.session import ProjectSession

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


def _session() -> ProjectSession:
    return ProjectSession.open(FIXTURE)


def _halved(design: DesignDocument, letters: set[str]) -> DesignDocument:
    assert design.gores is not None
    rows = [
        r.model_copy(update={"half_gore": r.letter in letters}) for r in design.gores.panel_rows
    ]
    return design.model_copy(update={"gores": design.gores.model_copy(update={"panel_rows": rows})})


def _length(points: np.ndarray) -> float:
    return float(np.sum(np.linalg.norm(np.diff(points, axis=0), axis=1)))


def _rows(flat: bool) -> list[tuple[PanelRow, float]]:
    if not flat:
        s = _session()
        return [
            (r, row_allowance(s.design, s.patterns, r.label))
            for r in panel_rows(s.design, s.patterns)
        ]
    profile = MeridianProfile.from_control_points(
        [1.0, 3.0, 3.5, 2.0], [0.0, 2.0, 5.0, 7.0], interpolation="linear"
    )
    third = profile.meridian_length / 3
    a = 0.02
    rows = flat_chord_rows(
        profile,
        16,
        [third] * 3,
        bows=[(0.0, 0.03), (0.02, 0.04), (0.01, 0.0)],
        allowance=SeamAllowance(a, a, a),
    )
    return [(r, a) for r in rows]


@pytest.mark.parametrize("flat", [False, True])
def test_the_halves_sew_back_into_the_panel(flat: bool) -> None:
    for row, a in _rows(flat):
        left, right = half_panel(row, a)
        # Together the halves are the finished panel, exactly.
        assert left.finished_area + right.finished_area == pytest.approx(row.finished_area)
        assert left.finished_area == pytest.approx(right.finished_area)
        assert left.finished == pytest.approx(right.finished[::-1] * [-1.0, 1.0])
        # The centre seams match each other and run the panel's centreline height.
        assert _length(left.edges["centre"]) == pytest.approx(_length(right.edges["centre"]))
        assert _length(right.edges["centre"]) == pytest.approx(row.centre_height, abs=1e-9)
        # The gore side is the panel's: its cut edge reaches as far as the whole panel's.
        assert right.edges["side"] == pytest.approx(row.right_edge)
        assert float(right.cut[:, 0].max()) == pytest.approx(
            float(row.cut_outline[:, 0].max()), abs=1e-9
        )
        # Seam edges split the panel's seams in two.
        assert _length(right.edges["bottom"]) == pytest.approx(row.bottom_seam_length / 2, rel=1e-3)
        assert _length(right.edges["top"]) == pytest.approx(row.top_seam_length / 2, rel=1e-3)
        # Extra cloth: a strip a wide down each side of the centre seam (+ corner squares).
        extra = left.cut_area + right.cut_area - row.cut_area
        assert extra == pytest.approx(2 * a * row.centre_height + 4 * a * a, rel=2e-3)


def test_row_pieces_follow_the_rows_half_gore_flag() -> None:
    s = _session()
    design = _halved(s.design, {"B"})
    pieces = row_pieces(design, s.patterns)
    names = [p.name for p in pieces]
    assert names == ["row A", "row B left half", "row B right half", "row C", "row D"]
    assert [p.centre_seam > 0 for p in pieces] == [False, True, True, False, False]


def test_the_mass_counts_the_halves_cloth_and_centre_seam() -> None:
    s = _session()
    before = gore_outputs(s.design, s.patterns)
    after = gore_outputs(_halved(s.design, {"B", "C"}), s.patterns)
    assert before.mass is not None and after.mass is not None
    rows = panel_rows(s.design, s.patterns)
    n = s.design.gores.count  # type: ignore[union-attr]
    pieces = row_pieces(_halved(s.design, {"B", "C"}), s.patterns, rows)
    halves = sum(abs(_area(p.cut)) for p in pieces if p.side != "whole")
    whole = sum(r.cut_area for r in rows if r.label in ("B", "C"))
    extra = n * (halves - whole)
    assert _cut(after.mass) - _cut(before.mass) == pytest.approx(extra)
    assert sum(z.finished_area for z in after.mass.zones.values()) == pytest.approx(
        sum(z.finished_area for z in before.mass.zones.values())
    )
    centre = n * sum(r.centre_height for r in rows if r.label in ("B", "C"))
    assert after.mass.centre_seam_length == pytest.approx(centre)
    assert before.mass.centre_seam_length == 0.0
    assert after.mass.thread_length > before.mass.thread_length
    assert after.mass.total_mass > before.mass.total_mass
    # The sewn shape is the same.
    assert after.volume == before.volume


def _cut(mass: MassEstimate) -> float:
    return sum(z.cut_area for z in mass.zones.values())


def _area(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def test_half_gores_are_an_undoable_edit_that_leaves_simulations_current() -> None:
    s = _session()
    before = dict(s.fingerprints())
    assert edits.set_half_gores(s, ["B"], True)
    assert [r.half_gore for r in s.design.gores.panel_rows] == [False, True, False, False]  # type: ignore[union-attr]
    after = s.fingerprints()
    changed = {a.name for a in ARTIFACTS if before[a.name] != after[a.name]}
    assert changed == {"patterns", "nesting", "export"}
    assert not edits.set_half_gores(s, ["B"], True)  # no change
    assert edits.set_half_gores(s, None, True)
    assert all(r.half_gore for r in s.design.gores.panel_rows)  # type: ignore[union-attr]
    # Splitting a half-gore row keeps both parts as half gores.
    assert edits.split_row(s, 1)
    assert all(r.half_gore for r in s.design.gores.panel_rows)  # type: ignore[union-attr]
    s.undo()
    s.undo()
    s.undo()
    assert s.fingerprints() == before
    with pytest.raises(KeyError):
        edits.set_half_gores(s, ["Q"], True)


def test_designs_without_half_gores_keep_their_fingerprints() -> None:
    s = _session()
    groups = s.group_hashes()
    assert "piece_split" not in groups  # empty: left out of every fingerprint


def test_version_8_designs_load_as_whole_panels() -> None:
    s = _session()
    raw = json.loads(s.design.model_dump_json(by_alias=True))
    raw["schema_version"] = 8
    for row in raw["gores"]["panel_rows"]:
        del row["half_gore"]
    raw["meta"]["content_hash"] = None
    raw["meta"]["content_hash"] = _raw_hash(raw)  # written by a version-8 EnvelopeLab
    loaded = load_design_document(json.dumps(raw))
    assert loaded.schema_version == 9
    assert not any(r.half_gore for r in loaded.gores.panel_rows)  # type: ignore[union-attr]


def test_build_pack_sheets_and_seams_of_half_gores() -> None:
    s = _session()
    design = _halved(s.design, {"B"})
    sheets = envelope_sheets(design, s.patterns)
    assert [x.piece for x in sheets] == [
        "row A",
        "row B left half",
        "row B right half",
        "row C",
        "row D",
    ]
    assert [x.piece for x in row_sheets(sheets)] == ["row A", "row B", "row C", "row D"]
    left, right = sheets[1], sheets[2]
    assert left.whole is right.whole and left.letter == "B"
    assert left.cut_count == design.gores.count  # type: ignore[union-attr]
    pairs = envelope_seam_pairs(sheets)
    as_names = [(p.a, p.b) for p in pairs]
    assert as_names[0] == (((left.name, "centre"),), ((right.name, "centre"),))
    assert (((left.name, "left"),), ((right.name, "right"),)) in as_names
    assert (((sheets[0].name, "top"),), ((left.name, "bottom"), (right.name, "bottom"))) in as_names
    assert (((left.name, "top"), (right.name, "top")), ((sheets[3].name, "bottom"),)) in as_names
    # Sewn edges agree in length (the build-pack rule), the halves' row seams summed.
    by = {x.name: x for x in sheets}
    for pair in pairs:
        la = sum(_length(by[n].edges[e]) for n, e in pair.a)
        lb = sum(_length(by[n].edges[e]) for n, e in pair.b)
        assert la == pytest.approx(lb, abs=3e-3)


def test_roll_advice_finds_the_fewest_gores_and_the_half_gores_that_fit() -> None:
    s = _session()
    advice = roll_advice(s.design, s.patterns, 1.524)
    assert not advice.fits
    n = advice.gores_needed
    assert n is not None and n > s.design.gores.count  # type: ignore[union-attr]

    def with_count(k: int) -> DesignDocument:
        g = s.design.gores
        assert g is not None
        return s.design.model_copy(update={"gores": g.model_copy(update={"count": k})})

    assert all(p.fits for p in piece_fits(with_count(n), s.patterns, 1.524))
    assert not all(p.fits for p in piece_fits(with_count(n - 1), s.patterns, 1.524))
    assert advice.half_gores_rows == ["A", "B", "C", "D"]
    halved = _halved(s.design, set(advice.half_gores_rows))
    assert all(p.fits for p in piece_fits(halved, s.patterns, 1.524))
    assert "14 gores or more" in advice.summary() or f"{n} gores or more" in advice.summary()
    wide = roll_advice(s.design, s.patterns, 3.7)
    assert wide.fits and "fits" in wide.summary()
    # On a very narrow roll even the halves are too wide: shorter rows are advised.
    narrow = roll_advice(s.design, s.patterns, 0.9)
    assert narrow.too_wide_halved and narrow.rows_needed is not None
    assert f"{narrow.rows_needed} equal panel rows or more" in narrow.summary()


def test_equal_rows_divide_the_tape_and_carry_what_belonged_to_the_old_rows() -> None:
    from envelopelab.project.gore_design import design_profile
    from envelopelab.rigging.defaults import turning_vent_pair

    s = _session()
    assert s.design.gores is not None
    vents = [v.model_dump(mode="json", by_alias=True) for v in turning_vent_pair(s.design)]

    def setup(data: dict[str, Any], patterns: dict[str, Any]) -> None:
        g = data["gores"]
        g["panel_rows"][0]["zone"] = data_zone = next(iter(data["zones"]))
        g["panel_rows"][3]["half_gore"] = True
        g["panel_zones"] = [{"name": "patch", "row": "B", "gores": [2], "zone": data_zone}]
        data["turning_vents"] = [dict(v, rows=["C", "D"]) for v in vents]
        patterns.setdefault("rows", {})["B"] = {
            "grain_angle_deg": 5.0,
            "notches": [{"edge": "left", "position": 0.5}],
        }

    assert s.edit("setup", setup)
    # 8 rows: no new row's middle falls on an old seam (each old row becomes two).
    assert edits.set_row_count(s, 8)
    rows = s.design.gores.panel_rows
    length = float(design_profile(s.design).meridian_length)
    assert [r.letter for r in rows] == list("ABCDEFGH")
    assert sum(r.finished_height for r in rows) == pytest.approx(length, abs=1e-9)
    assert max(r.finished_height for r in rows) - min(r.finished_height for r in rows) < 1e-3
    # Old rows A..D (equal) -> new A, B in old A; C, D in old B; ... by their middles.
    assert rows[0].zone is not None and rows[1].zone is not None and rows[2].zone is None
    assert [r.half_gore for r in rows] == [False] * 6 + [True, True]
    # Row settings follow; the marks of the old rows do not.
    assert s.patterns.row("C").grain_angle_deg == 5.0
    assert s.patterns.row("C").notches == []
    assert s.patterns.row("D").grain_angle_deg == 5.0
    # The applique on old row B (1/4..2/4 of the tape) covers new rows C and D.
    assert sorted(z.row for z in s.design.gores.panel_zones) == ["C", "D"]
    assert len({z.name for z in s.design.gores.panel_zones}) == 2
    # The vents over old rows C, D (the top half) open new rows E to H.
    assert all(v.rows == ["E", "F", "G", "H"] for v in s.design.turning_vents)
    assert not edits.set_row_count(s, 8)
    s.undo()
    assert len(s.design.gores.panel_rows) == 4
    assert s.patterns.row("B").notches
    with pytest.raises(ValueError):
        edits.set_row_count(s, 0)
