"""Edits that keep references consistent: zones, row zones, row names, lock targets."""

from __future__ import annotations

from pathlib import Path

import pytest

from envelopelab.io.shape_file import load_shape_file
from envelopelab.project import edits
from envelopelab.project.gore_design import (
    LockError,
    design_findings,
    design_profile,
    design_volume,
    row_zone,
)
from envelopelab.project.session import ProjectSession

ROOT = Path(__file__).resolve().parents[2]
SPECIAL = load_shape_file(ROOT / "tests" / "fixtures" / "flat_chord_pattern" / "special.yaml")


def session() -> ProjectSession:
    """Rows with zones, panel zones, a parachute, turning vents on rows E and F."""
    return ProjectSession.new(SPECIAL.design())


def test_zones_are_added_once_and_removed_only_when_unused() -> None:
    s = session()
    assert edits.add_zone(s, "trim", "nomex")
    assert s.design.zones["trim"] == "nomex"
    with pytest.raises(ValueError, match="already"):
        edits.add_zone(s, "trim", "ripstop_nylon")
    with pytest.raises(ValueError, match="name"):
        edits.add_zone(s, " ", "nomex")
    assert edits.remove_zone(s, "trim")
    assert "trim" not in s.design.zones
    users = edits.zone_users(s.design, s.patterns, "accent")
    assert users == ["panel zone badge"]
    with pytest.raises(ValueError, match="panel zone badge"):
        edits.remove_zone(s, "accent")
    with pytest.raises(ValueError, match="row SKIRT"):
        edits.remove_zone(s, "mouth")


def test_renaming_a_zone_follows_every_reference() -> None:
    s = session()
    s.set_design_value(("parachute", "zone"), "mouth")
    edits.set_row_zone(s, "B", "mouth")
    assert edits.rename_zone(s, "mouth", "nomex skirt")
    d = s.design
    assert "mouth" not in d.zones and d.zones["nomex skirt"] == "nomex"
    assert d.gores is not None
    assert d.gores.panel_rows[0].zone == "nomex skirt"
    assert row_zone(d, s.patterns, "B") == "nomex skirt"
    assert d.parachute is not None and d.parachute.zone == "nomex skirt"
    with pytest.raises(ValueError, match="already"):
        edits.rename_zone(s, "nomex skirt", "body")
    s.undo()
    assert "mouth" in s.design.zones


def test_row_zone_has_one_home() -> None:
    s = session()
    s.set_row_pattern("C", {"zone": "accent"}, "old-style annotation")
    assert edits.set_row_zone(s, "C", "mouth")
    gores = s.design.gores
    assert gores is not None
    assert gores.panel_rows[3].zone == "mouth" and s.patterns.row("C").zone is None
    assert edits.set_row_zone(s, "C", None)
    assert row_zone(s.design, s.patterns, "C") == "body"
    with pytest.raises(ValueError, match="zone"):
        edits.set_row_zone(s, "C", "no such zone")


def test_renaming_a_row_follows_every_reference() -> None:
    s = session()
    s.set_row_pattern("E", {"label_text": "EQUATOR"}, "label")
    assert edits.rename_row(s, "E", "EQ")
    d = s.design
    assert d.gores is not None
    assert [r.letter for r in d.gores.panel_rows][5] == "EQ"
    assert s.patterns.row("EQ").label_text == "EQUATOR"
    assert all(v.rows == ["EQ", "F"] for v in d.turning_vents)
    s2 = session()
    edits.rename_row(s2, "C", "CC")
    assert s2.design.gores is not None
    assert s2.design.gores.panel_zones[0].row == "CC"
    with pytest.raises(ValueError, match="already"):
        edits.rename_row(s2, "D", "F")
    with pytest.raises(ValueError):
        edits.rename_row(s2, "D", "")


def test_findings_name_panel_zones_with_an_unknown_zone() -> None:
    s = session()
    s.set_design_value(("gores", "panel_zones", 0, "zone"), "gone")
    messages = [f.message for f in design_findings(s.design, s.patterns)]
    assert any("badge" in m and "gone" in m for m in messages)


def test_lock_targets_solve_the_design() -> None:
    s = ProjectSession.new(load_shape_file(ROOT / "tests/fixtures/smalley_90k/shape.yaml").design())
    volume = design_volume(s.design)
    assert edits.set_lock_target(s, "volume", 1.1 * volume)
    assert design_volume(s.design) == pytest.approx(1.1 * volume, rel=1e-3)
    assert s.project.locks.volume == pytest.approx(1.1 * volume)
    height = design_profile(s.design).height
    assert edits.set_lock_target(s, "height", height + 0.5)
    assert design_profile(s.design).height == pytest.approx(height + 0.5, abs=1e-3)
    # The volume lock is still held.
    assert design_volume(s.design) == pytest.approx(1.1 * volume, rel=1e-3)
    assert edits.set_lock_target(s, "gore_count", 24)
    assert s.design.gores is not None and s.design.gores.count == 24
    before = s.design
    with pytest.raises((LockError, ValueError)):
        edits.set_lock_target(s, "volume", 1e-3)
    assert s.design == before
