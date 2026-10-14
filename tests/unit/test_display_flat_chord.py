"""The 3D display of flat-chord gores, panel zones, pattern marks and feed holes."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.geometry.gore import CrestLoft, crest_bows, crest_offsets_from_bows
from envelopelab.io.shape_file import load_shape_file
from envelopelab.project import edits
from envelopelab.project.gore_design import (
    design_crest_offset,
    design_profile,
    display_points,
    display_surface,
    envelope_marks,
    panel_rows,
)
from envelopelab.project.model import PatternSet
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import (
    display_offset,
    envelope_surface,
    feed_hole_rings,
    shape_design,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "flat_chord_pattern"
SHAPE = load_shape_file(FIXTURE / "shape.yaml")
SPECIAL = load_shape_file(FIXTURE / "special.yaml")
#: The crest loft make_fixture.py measured the fixture's bows from (fixture data).
FIXTURE_CREST = CrestLoft(0.025, (0.1, 0.5, 1.0), (0.0, 1.0, 0.0))


def test_offsets_from_crest_bows_give_back_the_crest() -> None:
    design = SHAPE.design(seams="crest")
    profile = design_profile(design)
    rows = panel_rows(design, PatternSet())
    bounds = np.array([r.s_bottom for r in rows] + [rows[-1].s_top])
    crest = FIXTURE_CREST
    bows = crest_bows(profile, bounds, crest)
    delta = crest_offsets_from_bows(profile, bounds, bows)
    expected = crest.offset(bounds / profile.meridian_length, profile.radius_at(bounds))
    assert delta[0] == 0.0 and delta[-1] == 0.0
    # First order in the variation of the offset between seams: within 3 mm here.
    assert np.max(np.abs(delta[1:-1] - expected[1:-1])) < 3e-3


def test_measured_bows_show_the_crest_they_were_measured_from() -> None:
    design = SHAPE.design()  # measured bows, from a 2.5 % crest with 0.8 mm asymmetry
    profile = design_profile(design)
    rows = panel_rows(design, PatternSet())
    s = np.array([r.s_bottom for r in rows[1:]])
    got = design_crest_offset(design, s, profile)
    expected = FIXTURE_CREST.offset(s / profile.meridian_length, profile.radius_at(s))
    assert np.max(np.abs(got - expected)) < 3e-3


def test_crest_offsets_are_zero_on_a_straight_tape() -> None:
    from envelopelab.geometry.gore import MeridianProfile

    cylinder = MeridianProfile.from_control_points([3.0, 3.0], [0.0, 10.0], samples=11)
    delta = crest_offsets_from_bows(cylinder, [0.0, 5.0, 10.0], [(0.0, 0.01), (0.01, 0.0)])
    assert np.all(delta == 0.0)


@pytest.mark.parametrize("fraction", [0.0, 0.03])
def test_flat_chord_crest_stands_out_by_the_offset(fraction: float) -> None:
    session = ProjectSession.new(SHAPE.design())
    if fraction:
        edits.set_crest_loft(session, fraction, [(0.0, 1.0)])
    else:
        edits.set_crest_loft(session, None)
    design = session.design
    assert design.gores is not None
    n = design.gores.count
    profile = design_profile(design)
    s = np.linspace(0.1, 0.9, 9) * profile.meridian_length
    gore_angle = 2.0 * math.pi / n
    tape = display_points(design, s, np.zeros_like(s), profile)
    crest = display_points(design, s, np.full_like(s, 0.5 * gore_angle), profile)
    # The tapes lie on the profile.
    assert np.allclose(np.hypot(tape[:, 0], tape[:, 1]), profile.radius_at(s), atol=1e-9)
    assert np.allclose(tape[:, 2], profile.height_at(s), atol=1e-9)
    # The crest stands the crest offset out from the middle of the flat chord.
    r = profile.radius_at(s)
    mid = np.column_stack(
        (
            r * math.cos(math.pi / n) * math.cos(0.5 * gore_angle),
            r * math.cos(math.pi / n) * math.sin(0.5 * gore_angle),
            profile.height_at(s),
        )
    )
    gap = np.linalg.norm(crest - mid, axis=1)
    delta = design_crest_offset(design, s, profile)
    assert np.allclose(gap, np.abs(delta), atol=1e-9)
    if fraction:
        assert np.allclose(delta, fraction * r)
    else:
        assert np.all(gap < 1e-9)


def test_display_points_lie_on_the_mesh() -> None:
    smalley = load_shape_file(ROOT / "tests" / "fixtures" / "smalley_90k" / "shape.yaml")
    for design in (SHAPE.design(), smalley.design()):
        assert design.gores is not None
        n, per_gore, per_row = design.gores.count, 6, 8
        surf = display_surface(design, per_gore=per_gore, per_row=per_row)
        profile = design_profile(design)
        # The stations display_surface uses: per_row steps in every row.
        bounds = [0.0]
        for row in design.gores.panel_rows:
            bounds.append(min(bounds[-1] + row.finished_height, profile.meridian_length))
        stations = [0.0]
        for s0, s1 in zip(bounds[:-1], bounds[1:], strict=True):
            stations += list(np.linspace(s0, s1, per_row + 1)[1:])
        m = n * per_gore
        cols = np.repeat(np.arange(n), per_gore) + np.tile(np.arange(per_gore) / per_gore, n)
        theta = 2.0 * np.pi * cols / n
        for i in (5, 37, len(stations) - 3):
            pts = display_points(design, np.full(m, stations[i]), theta, profile)
            assert np.max(np.abs(pts - surf.points[i * m : (i + 1) * m])) < 1e-9


def test_panel_details_are_drawn_where_they_are_designed() -> None:
    design = SPECIAL.design()
    assert design.gores is not None
    patterns = PatternSet()
    rows = panel_rows(design, patterns)
    marks = envelope_marks(design, patterns, rows)
    panels = sum(len(z.gores) for z in design.gores.panel_zones)
    assert len(marks["panel_zones"]) == panels
    assert "tape_paths" not in marks and "feature_locations" not in marks
    letter = rows[3].label
    patterns = PatternSet.model_validate(
        {
            "rows": {
                letter: {
                    "tape_paths": [{"name": "t", "points": [(-0.3, 0.5), (0.3, 0.5)]}],
                    "feature_locations": [{"feature": 0, "x": 0.0, "y": 1.0, "radius": 0.2}],
                }
            }
        }
    )
    marks = envelope_marks(design, patterns, rows)
    n = design.gores.count
    assert len(marks["tape_paths"]) == n and len(marks["feature_locations"]) == n
    # A mark lies within its row's height band.
    profile = design_profile(design)
    z = marks["tape_paths"][0][:, 2]
    assert (
        profile.height_at(rows[3].s_bottom) <= z.min()
        and z.max() <= profile.height_at(rows[3].s_top) + 0.05
    )


def test_shapes_sit_on_the_drawn_surface_with_their_feed_holes() -> None:
    design = SPECIAL.design()
    surface = envelope_surface(design, PatternSet())
    for spec in SPECIAL.shapes(design):
        placed = shape_design(spec, surface)
        shift = display_offset(design, placed)
        base = placed.surface.point(np.array([placed.base_s]), np.array([placed.base_theta]))[0]
        on_display = display_points(design, [placed.base_s], [placed.base_theta])[0]
        assert np.allclose(base + shift, on_display)
        rings = feed_hole_rings(design, placed)
        assert len(rings) == len(placed.feed_holes)
        for ring, hole in zip(rings, placed.feed_holes, strict=True):
            centre = ring.mean(axis=0)
            assert (
                np.max(np.abs(np.linalg.norm(ring - centre, axis=1) - hole.radius))
                < 0.05 * hole.radius + 0.01
            )
