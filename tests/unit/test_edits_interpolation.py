"""Editing a design whose profile has straight tape segments (``profile_interpolation``)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.design.model import DesignDocument
from envelopelab.project import edits
from envelopelab.project.gore_design import (
    control_arrays,
    design_profile,
    design_volume,
    fit_row_heights,
    profile_from_arrays,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.templates import new_design

# Few control points, so straight segments and a spline differ by percent, not ppm.
POINTS = [(8.0 * math.cos(t), 8.0 * math.sin(t)) for t in np.linspace(-1.2, 1.3, 6).tolist()]


def linear_session() -> ProjectSession:
    r = np.array([p[0] for p in POINTS])
    z = np.array([p[1] for p in POINTS])
    length = profile_from_arrays(r, z, "linear").meridian_length
    design = new_design(
        "linear",
        POINTS,
        gore_count=16,
        row_heights=fit_row_heights([1.0] * 5, length),
        mouth_diameter=2 * POINTS[0][0],
        top_diameter=2 * POINTS[-1][0],
    )
    assert design.gores is not None
    gores = design.gores.model_copy(update={"profile_interpolation": "linear"})
    session = ProjectSession.new(design.model_copy(update={"gores": gores}))
    return session


def row_total(design: DesignDocument) -> float:
    assert design.gores is not None
    return sum(r.finished_height for r in design.gores.panel_rows)


def test_the_two_interpolations_differ_enough_to_matter() -> None:
    r, z = control_arrays(linear_session().design)
    spline, linear = profile_from_arrays(r, z), profile_from_arrays(r, z, "linear")
    assert abs(spline.volume / linear.volume - 1.0) > 1e-2


@pytest.mark.parametrize(
    "locks", [("volume",), ("volume", "height"), ("height",), ("max_diameter",)]
)
def test_locks_hold_the_linear_profile(locks: tuple[str, ...]) -> None:
    s = linear_session()
    before = design_profile(s.design)
    volume = design_volume(s.design)
    for name in locks:
        edits.set_lock(s, name, True)
    pts = s.design.gores.meridian_profile_control_points  # type: ignore[union-attr]
    assert edits.move_control_point(s, 2, pts[2].x + 0.4, pts[2].y + 0.3)
    after = design_profile(s.design)
    if "volume" in locks:
        assert design_volume(s.design) == pytest.approx(volume, rel=1e-3)
    if "height" in locks:
        assert after.height == pytest.approx(before.height, abs=1e-3)
    if "max_diameter" in locks:
        assert after.max_width == pytest.approx(before.max_width, abs=1e-3)
    # Rows are refitted to the straight-segment tape length.
    assert row_total(s.design) == pytest.approx(after.meridian_length, abs=1e-6)


def test_set_loft_with_a_volume_lock_keeps_the_linear_volume() -> None:
    s = linear_session()
    volume = design_volume(s.design)
    edits.set_lock(s, "volume", True)
    assert edits.set_loft(s, [(0.0, 1.2), (1.0, 1.0)])
    assert design_volume(s.design) == pytest.approx(volume, rel=1e-3)
    assert row_total(s.design) == pytest.approx(design_profile(s.design).meridian_length)


def test_set_profile_interpolation_refits_rows_and_holds_locks() -> None:
    s = linear_session()
    volume = design_volume(s.design)
    edits.set_lock(s, "volume", True)
    assert edits.set_profile_interpolation(s, "spline")
    assert s.design.gores is not None and s.design.gores.profile_interpolation == "spline"
    assert design_volume(s.design) == pytest.approx(volume, rel=1e-3)
    assert row_total(s.design) == pytest.approx(design_profile(s.design).meridian_length)
    assert not edits.set_profile_interpolation(s, "spline")
    s.undo()
    gores = s.design.gores
    assert gores is not None
    assert str(gores.profile_interpolation) == "linear"
    assert design_volume(s.design) == pytest.approx(volume, rel=1e-9)
