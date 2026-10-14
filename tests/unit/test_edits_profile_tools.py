"""Bulk profile edits and Simplify as undoable commands that keep the locks."""

from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.geometry.profile_editing import profile_deviation
from envelopelab.project import edits
from envelopelab.project.gore_design import (
    check_locks,
    control_arrays,
    design_profile,
    design_volume,
    standard_gore_design,
)
from envelopelab.project.session import ProjectSession


def dense_session(points: int = 40) -> ProjectSession:
    """A wizard design whose profile was traced with many control points."""
    session = ProjectSession.new(standard_gore_design("dense", 2600.0, 17.0, 18.0, 16, 8))
    profile = design_profile(session.design)
    s = np.linspace(0.0, profile.meridian_length, points)
    pts = list(zip(profile.radius_at(s).tolist(), profile.height_at(s).tolist(), strict=True))
    edits.set_control_points(session, pts, "Trace")
    session.stack.clear()
    return session


def test_bulk_edits_are_single_undoable_commands() -> None:
    s = dense_session()
    r0, z0 = control_arrays(s.design)
    assert edits.move_points(s, [10, 11, 12], 0.3, 0.0, radius=2.0)
    r1, _ = control_arrays(s.design)
    assert r1[11] == pytest.approx(r0[11] + 0.3)
    assert 0.0 < r1[8] - r0[8] < 0.3  # a neighbour followed part of the way
    assert edits.scale_points(s, [20, 21, 22, 23], 1.1, 1.0)
    assert edits.rotate_points(s, [5, 6, 7], math.radians(5.0))
    assert edits.straighten_points(s, 25, 30)
    assert edits.smooth_points(s, list(range(40)), 0.5, 2)
    for _ in range(5):
        s.undo()
    r, z = control_arrays(s.design)
    assert np.array_equal(r, r0) and np.array_equal(z, z0)
    assert not s.stack.can_undo


def test_bulk_edits_keep_the_locks() -> None:
    s = dense_session()
    for name in ("volume", "height", "mouth_diameter", "top_diameter"):
        edits.set_lock(s, name, True)
    volume = design_volume(s.design)
    edits.scale_points(s, list(range(12, 28)), 1.15, 1.0, radius=3.0)
    edits.smooth_points(s, list(range(40)), 0.5, 3)
    edits.straighten_points(s, 2, 9)
    assert check_locks(s.design, s.project.locks) == []
    assert design_volume(s.design) == pytest.approx(volume, rel=1e-3)
    gores = s.design.gores
    assert gores is not None
    rows = sum(r.finished_height for r in gores.panel_rows)
    assert rows == pytest.approx(design_profile(s.design).meridian_length, abs=1e-6)


def test_simplify_reduces_the_points_within_the_tolerance() -> None:
    s = dense_session()
    before = design_profile(s.design)
    result = edits.simplify_profile(s, 0.002)
    r, z = control_arrays(s.design)
    assert result.count == r.size < 40
    after = design_profile(s.design)
    assert profile_deviation(before, after) <= 0.002 * 1.01
    s.undo()
    assert control_arrays(s.design)[0].size == 40


def test_simplify_with_a_locked_volume_restores_it() -> None:
    s = dense_session()
    edits.set_lock(s, "volume", True)
    volume = design_volume(s.design)
    edits.simplify_profile(s, 0.02)
    assert design_volume(s.design) == pytest.approx(volume, rel=1e-3)


def test_simplify_that_cannot_help_changes_nothing() -> None:
    s = ProjectSession.new(standard_gore_design("w", 2600.0, 17.0, 18.0, 16, 8))
    before = s.design
    with pytest.raises(ValueError, match="no profile with fewer than"):
        edits.simplify_profile(s, 1e-7)
    assert s.design == before and not s.stack.can_undo


def test_bulk_edits_need_a_selection() -> None:
    s = dense_session()
    with pytest.raises(ValueError, match="at least one"):
        edits.move_points(s, [], 0.1, 0.0)
    with pytest.raises(ValueError, match="at least one between"):
        edits.straighten_points(s, 3, 4)
    assert not s.stack.can_undo
