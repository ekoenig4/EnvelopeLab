"""Editing flat-chord gores: construction, crest loft, measured bows, split and merge."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from envelopelab.geometry.gore import crest_bows
from envelopelab.io.shape_file import load_shape_file
from envelopelab.project import edits
from envelopelab.project.gore_design import (
    DEFAULT_CREST_LOFT,
    LockError,
    design_crest_loft,
    design_profile,
    design_seam_bows,
    design_volume,
    panel_rows,
    seam_mismatches,
    standard_gore_design,
)
from envelopelab.project.model import PatternSet
from envelopelab.project.session import ProjectSession

ROOT = Path(__file__).resolve().parents[2]
SHAPE = load_shape_file(ROOT / "tests" / "fixtures" / "flat_chord_pattern" / "shape.yaml")
SMALLEY = load_shape_file(ROOT / "tests" / "fixtures" / "smalley_90k" / "shape.yaml")


def measured() -> ProjectSession:
    """The synthetic pattern set: flat chord, measured bows, linear profile."""
    return ProjectSession.new(SHAPE.design())


def lobe() -> ProjectSession:
    return ProjectSession.new(SMALLEY.design(row_count=8))


def bows(s: ProjectSession) -> list[tuple[float, float]]:
    assert s.design.gores is not None
    return [(r.bow_bottom or 0.0, r.bow_top or 0.0) for r in s.design.gores.panel_rows]


def sews(s: ProjectSession) -> bool:
    return seam_mismatches(panel_rows(s.design, PatternSet()), PatternSet()) == []


def test_lobe_to_flat_chord_and_back() -> None:
    s = lobe()
    before = s.design
    assert edits.set_construction(s, "flat_chord")
    gores = s.design.gores
    assert gores is not None and gores.construction == "flat_chord"
    assert gores.loft is None and gores.crest_loft == DEFAULT_CREST_LOFT
    assert all(r.bow_bottom is None for r in gores.panel_rows)
    assert sews(s)
    assert not edits.set_construction(s, "flat_chord")
    assert edits.set_construction(s, "lobe")
    gores = s.design.gores
    assert gores is not None and gores.construction == "lobe" and gores.crest_loft is None
    s.undo()
    s.undo()
    assert s.design == before


def test_switching_to_lobe_drops_measured_bows() -> None:
    s = measured()
    assert edits.set_construction(s, "lobe")
    assert s.design.gores is not None
    assert all(r.bow_bottom is None and r.bow_top is None for r in s.design.gores.panel_rows)


def test_construction_switch_holds_a_locked_volume() -> None:
    s = lobe()
    volume = design_volume(s.design)
    edits.set_lock(s, "volume", True)
    assert edits.set_construction(s, "flat_chord")
    # The flat-chord volume is the chord polygon's: the profile grows to hold the lock.
    assert design_volume(s.design) == pytest.approx(volume, rel=1e-3)
    assert s.design.gores is not None
    total = sum(r.finished_height for r in s.design.gores.panel_rows)
    assert total == pytest.approx(design_profile(s.design).meridian_length, abs=1e-6)


def test_set_crest_loft_replaces_measured_bows() -> None:
    s = measured()
    assert edits.set_crest_loft(s, 0.03, [(0.5, 1.0), (0.0, 0.0), (1.0, 0.2)])
    gores = s.design.gores
    assert gores is not None and gores.crest_loft is not None
    assert gores.crest_loft.fraction == 0.03
    assert [p.station for p in gores.crest_loft.taper] == [0.0, 0.5, 1.0]
    assert all(r.bow_bottom is None for r in gores.panel_rows)
    assert sews(s)
    # None: straight seams.
    assert edits.set_crest_loft(s, None)
    assert s.design.gores is not None and s.design.gores.crest_loft is None
    assert all(b == (0.0, 0.0) for b in design_seam_bows(s.design))


@pytest.mark.parametrize(
    ("fraction", "taper"),
    [(-0.01, [(0.0, 1.0)]), (0.02, [(0.5, 1.0), (0.5, 0.0)]), (0.02, [])],
)
def test_invalid_crest_lofts_change_nothing(
    fraction: float, taper: list[tuple[float, float]]
) -> None:
    s = measured()
    before = s.design
    with pytest.raises(ValueError):
        edits.set_crest_loft(s, fraction, taper)
    assert s.design == before and not s.stack.can_undo


def test_crest_loft_is_refused_on_a_lobe_design() -> None:
    s = lobe()
    with pytest.raises(ValueError, match="flat_chord"):
        edits.set_crest_loft(s, 0.02, [(0.0, 1.0)])


def test_freezing_the_crest_bows_keeps_every_seam() -> None:
    s = measured()
    edits.set_crest_loft(s, 0.025, [(0.0, 0.0), (0.5, 1.0), (1.0, 0.0)])
    crest_rows = panel_rows(s.design, PatternSet())
    crest = design_crest_loft(s.design)
    assert crest is not None
    boundaries = [r.s_bottom for r in crest_rows] + [crest_rows[-1].s_top]
    expected = crest_bows(design_profile(s.design), boundaries, crest)
    assert edits.freeze_crest_bows(s)
    assert s.design.gores is not None and s.design.gores.crest_loft is None
    assert bows(s) == pytest.approx([(r.bottom_bow, r.top_bow) for r in crest_rows], abs=1e-12)
    assert [b for pair in bows(s) for b in pair] == pytest.approx(
        [b for pair in expected for b in pair], abs=1e-12
    )
    assert sews(s)
    assert not edits.freeze_crest_bows(s)


def test_editing_one_bow_keeps_the_others() -> None:
    s = measured()
    old = bows(s)
    assert edits.set_row_bows(s, 3, 0.004, 0.006)
    new = bows(s)
    assert new[3] == (0.004, 0.006)
    assert new[:3] == old[:3] and new[4:] == old[4:]
    # From a crest loft, the computed bows become measured ones.
    s = measured()
    edits.set_crest_loft(s, 0.02, [(0.0, 1.0)])
    computed = design_seam_bows(s.design)
    assert edits.set_row_bows(s, 0, 0.0, computed[0][1])
    assert s.design.gores is not None and s.design.gores.crest_loft is None
    assert bows(s)[1:] == pytest.approx(computed[1:], abs=1e-12)


def test_splitting_a_bowed_row_puts_a_straight_seam_in_it() -> None:
    s = measured()
    old = bows(s)
    assert edits.split_row(s, 4)
    new = bows(s)
    assert len(new) == len(old) + 1
    assert new[4] == (old[4][0], 0.0) and new[5] == (0.0, old[4][1])
    assert s.design.gores is not None
    assert s.design.gores.panel_rows[5].zone == s.design.gores.panel_rows[4].zone
    assert sews(s)


def test_merging_bowed_rows_keeps_the_outer_seams() -> None:
    s = measured()
    old = bows(s)
    assert edits.merge_row_with_next(s, 4)
    assert bows(s)[4] == (old[4][0], old[5][1])


def test_split_gives_a_free_letter_past_z() -> None:
    assert edits._next_letter([chr(ord("A") + i) for i in range(26)]) == "AA"


def test_locked_volume_that_cannot_be_held_changes_nothing() -> None:
    s = lobe()
    edits.set_lock(s, "volume", True)
    edits.set_lock(s, "height", True)
    edits.set_lock(s, "max_diameter", True)
    before = s.design
    try:
        edits.set_construction(s, "flat_chord")
    except LockError:
        assert s.design == before


@pytest.mark.parametrize(
    ("construction", "interpolation"),
    [("flat_chord", "spline"), ("flat_chord", "linear"), ("lobe", "linear")],
)
def test_wizard_designs_meet_their_targets_for_every_construction(
    construction: Literal["lobe", "flat_chord"], interpolation: Literal["spline", "linear"]
) -> None:
    design = standard_gore_design(
        "wizard", 2600.0, 17.0, 18.0, 16, 8, construction=construction, interpolation=interpolation
    )
    gores = design.gores
    assert gores is not None
    assert gores.construction == construction and gores.profile_interpolation == interpolation
    assert (gores.crest_loft == DEFAULT_CREST_LOFT) == (construction == "flat_chord")
    profile = design_profile(design)
    assert design_volume(design) == pytest.approx(2600.0, rel=1e-3)
    assert profile.height == pytest.approx(17.0, abs=1e-3)
    assert profile.max_width == pytest.approx(18.0, abs=1e-3)
    assert sum(r.finished_height for r in gores.panel_rows) == pytest.approx(
        profile.meridian_length, abs=1e-6
    )
    assert design.meta.content_hash == design.compute_content_hash()


def _anchors(s: ProjectSession) -> list[tuple[float, str | None]]:
    gores = s.design.gores
    assert gores is not None and gores.crest_loft is not None
    return [(p.station, p.at_row) for p in gores.crest_loft.taper]


def _bottom(s: ProjectSession, letter: str) -> float:
    gores = s.design.gores
    assert gores is not None
    heights = [r.finished_height for r in gores.panel_rows]
    index = [r.letter for r in gores.panel_rows].index(letter)
    return sum(heights[:index]) / sum(heights)


def test_taper_stations_can_follow_row_seams() -> None:
    s = measured()
    # No loft below row E, the full 3 % from row F up.
    assert edits.set_crest_loft(s, 0.03, [(0.0, 0.0), ("E", 0.0), ("F", 1.0), (1.0, 1.0)])
    anchors = _anchors(s)
    assert [a for _, a in anchors] == [None, "E", "F", None]
    assert anchors[1][0] == pytest.approx(_bottom(s, "E"))
    bows = design_seam_bows(s.design)
    assert all(b == pytest.approx(0.0) and t == pytest.approx(0.0) for b, t in bows[:5])
    assert bows[5][1] > 0.01  # the E/F seam bows
    # Resizing rows moves the anchored stations with their seams.
    gores = s.design.gores
    assert gores is not None
    heights = [r.finished_height for r in gores.panel_rows]
    heights[2], heights[3] = heights[2] + 0.4, heights[3] - 0.4
    assert edits.set_row_heights(s, heights, "resize")
    anchors = _anchors(s)
    assert anchors[1][0] == pytest.approx(_bottom(s, "E"))
    assert anchors[2][0] == pytest.approx(_bottom(s, "F"))
    # Renaming and splitting keep them attached.
    assert edits.rename_row(s, "E", "EQ")
    assert [a for _, a in _anchors(s)] == [None, "EQ", "F", None]
    assert edits.split_row(s, 1)
    assert _anchors(s)[1][0] == pytest.approx(_bottom(s, "EQ"))
    # Merging away the row a station sits under leaves a free station where it was.
    index = [r.letter for r in s.design.gores.panel_rows].index("EQ")  # type: ignore[union-attr]
    where = _anchors(s)[2][0]
    assert edits.merge_row_with_next(s, index)
    station, anchor = _anchors(s)[2]
    assert station == pytest.approx(where) and anchor is None


def test_row_anchored_stations_are_checked() -> None:
    s = measured()
    before = s.design
    with pytest.raises(ValueError, match="unknown row"):
        edits.set_crest_loft(s, 0.03, [("Z", 1.0)])
    with pytest.raises(ValueError, match="strictly increasing"):
        edits.set_crest_loft(s, 0.03, [("E", 0.0), (_bottom(s, "E"), 1.0)])
    assert s.design == before
