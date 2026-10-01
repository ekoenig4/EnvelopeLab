from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.project.gore_design import design_profile
from envelopelab.project.shape_family import (
    NormalizedShape,
    ShapeParameters,
    check_hold,
    evaluate,
    shape_design,
    solve_shape,
    station_points,
)
from envelopelab.validation.shape_families import sphere_shape

R = 8.0  # m
SPHERE = sphere_shape()
START = ShapeParameters(math.pi * R, 0.2, 0.9, 24, 0.025)


def test_sphere_table_reproduces_closed_form() -> None:
    got = evaluate(SPHERE, START)
    assert got["mouth_diameter"] == pytest.approx(2 * R * math.sin(0.2 * math.pi), abs=1e-3)
    assert got["top_diameter"] == pytest.approx(2 * R * math.sin(0.9 * math.pi), abs=1e-3)
    assert got["max_diameter"] == pytest.approx(2 * R, abs=1e-3)
    assert got["tape_length"] == pytest.approx(0.7 * math.pi * R, abs=1e-3)
    assert got["height"] == pytest.approx(
        R * (math.cos(0.2 * math.pi) + 1.0 * math.cos(0.1 * math.pi)), abs=1e-3
    )
    assert got["nominal_volume"] == pytest.approx(4 / 3 * math.pi * R**3, rel=1e-3)
    assert got["max_cut_gore_width"] == pytest.approx(2 * (math.pi * R / 24 + 0.025), abs=1e-3)


def test_lengths_scale_with_gore_length_and_volumes_with_its_cube() -> None:
    a = evaluate(SPHERE, START)
    b = evaluate(SPHERE, ShapeParameters(2 * START.gore_length, 0.2, 0.9, 24, 0.0))
    for name in ("height", "max_diameter", "mouth_diameter", "tape_length"):
        assert b[name] == pytest.approx(2 * a[name], rel=1e-9)
    for name in ("nominal_volume", "envelope_volume"):
        assert b[name] == pytest.approx(8 * a[name], rel=1e-9)


def test_hold_mouth_diameter_solves_the_scale_and_keeps_the_shape() -> None:
    hold = {"mouth_diameter": 5.0, "mouth_station": 0.2, "top_station": 0.9}
    sol = solve_shape(SPHERE, START, hold)
    assert sol.converged, sol.message
    assert sol.free == ("gore_length",)
    assert sol.values["mouth_diameter"] == pytest.approx(5.0, abs=1e-6)
    assert sol.parameters.gore_length == pytest.approx(
        math.pi * 2.5 / math.sin(0.2 * math.pi), abs=1e-3
    )
    assert sol.parameters.gore_count == 24
    assert sol.iterations > 0


def test_hold_volume_and_mouth_moves_the_mouth_station() -> None:
    volume = 4 / 3 * math.pi * R**3
    hold = {"nominal_volume": volume, "mouth_diameter": 6.0, "top_station": 0.9}
    sol = solve_shape(SPHERE, START, hold)
    assert sol.converged, sol.message
    assert set(sol.free) == {"gore_length", "mouth_station"}
    assert sol.parameters.gore_length == pytest.approx(math.pi * R, rel=1e-3)
    assert sol.parameters.mouth_station == pytest.approx(math.asin(3.0 / R) / math.pi, abs=1e-4)


def test_unreachable_target_is_reported_unconverged_with_its_range() -> None:
    hold = {"mouth_diameter": 20.0, "gore_length": math.pi * R, "top_station": 0.9}
    sol = solve_shape(SPHERE, START, hold)
    assert not sol.converged
    assert "can only be" in sol.message
    with pytest.raises(ValueError, match="did not solve"):
        shape_design("x", SPHERE, sol, row_count=4)


@pytest.mark.parametrize(
    ("hold", "message"),
    [
        ({"mouth_diameter": 5.0}, "exactly 3"),
        ({"mouth_diameter": 5.0, "height": 9.0, "width": 1.0}, "unknown"),
        ({"nominal_volume": 9.0, "gore_length": 9.0, "top_station": 0.9}, "same thing"),
        ({"mouth_diameter": -1.0, "mouth_station": 0.2, "top_station": 0.9}, "positive"),
    ],
)
def test_invalid_hold_is_refused(hold: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_hold(hold)


def test_table_that_is_not_radius_against_tape_length_is_refused() -> None:
    with pytest.raises(ValueError, match="more than the tape length"):
        NormalizedShape(s=np.array([0.0, 0.1, 0.5, 1.0]), r=np.array([0.0, 0.3, 0.3, 0.0]))
    with pytest.raises(ValueError, match="from s = 0"):
        NormalizedShape(s=np.array([0.0, 0.1, 0.5, 0.9]), r=np.array([0.0, 0.1, 0.3, 0.0]))


def test_design_document_profile_matches_solved_values() -> None:
    hold = {"mouth_diameter": 5.0, "mouth_station": 0.2, "top_station": 0.9}
    sol = solve_shape(SPHERE, START, hold)
    doc = shape_design("sphere", SPHERE, sol, row_count=6)
    profile = design_profile(doc)
    assert doc.gores is not None
    assert doc.gores.count == 24
    assert doc.gores.mouth_diameter == pytest.approx(5.0, abs=1e-6)
    assert profile.volume == pytest.approx(sol.values["envelope_volume"], rel=1e-12)
    assert sum(r.finished_height for r in doc.gores.panel_rows) == pytest.approx(
        profile.meridian_length, abs=1e-3
    )
    assert doc.seam_types[0].allowance == pytest.approx(0.025)


def test_station_points_are_measured_from_the_mouth() -> None:
    shape = NormalizedShape(SPHERE.s, SPHERE.r, stations={"mouth": 0.2, "equator": 0.5})
    points = {p.name: p for p in station_points(shape, START)}
    assert points["mouth"].height == pytest.approx(0.0, abs=1e-9)
    assert points["equator"].radius == pytest.approx(R, abs=1e-3)
    assert points["equator"].height == pytest.approx(R * math.cos(0.2 * math.pi), abs=1e-3)
    assert points["equator"].tape_distance == pytest.approx(0.3 * math.pi * R, abs=1e-9)
