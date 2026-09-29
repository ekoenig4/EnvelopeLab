from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.geometry.parachute import (
    arc_segments_for,
    centre_outline,
    gore_edge_lengths,
    gore_outline,
    parachute_pieces,
)
from envelopelab.geometry.polygon import signed_area


def test_gore_seam_lengths_match_closed_form() -> None:
    radius, centre, n = 2.86, 0.5, 20
    edges = gore_edge_lengths(gore_outline(radius, centre, n))
    theta = 2 * math.pi / n
    assert edges["bottom"] == pytest.approx(theta * radius, rel=1e-5)
    assert edges["top"] == pytest.approx(theta * centre, rel=1e-5)
    assert edges["left"] == pytest.approx(radius - centre, abs=1e-9)
    assert edges["right"] == pytest.approx(radius - centre, abs=1e-9)


def test_gore_frame_rim_through_origin_centre_above() -> None:
    gore = gore_outline(3.0, 0.4, 16)
    assert signed_area(gore) > 0  # counter-clockwise
    assert gore[:, 1].min() == pytest.approx(0.0, abs=1e-12)
    top = gore[np.argmax(gore[:, 1])]
    # Inner arc corners lie at distance r_c from the parachute centre (0, R).
    assert math.hypot(top[0], top[1] - 3.0) == pytest.approx(0.4, rel=1e-12)


def test_gores_and_disc_tile_the_flat_canopy() -> None:
    pieces = parachute_pieces(diameter=5.72, centre_diameter=1.0, n_gores=20, allowance=0.0)
    assert pieces.finished_area == pytest.approx(math.pi * 2.86**2, rel=2e-5)
    # The N inner arcs sew to the disc circumference.
    inner = pieces.n_gores * pieces.gore_edges["top"]
    assert inner == pytest.approx(pieces.centre_circumference, rel=1e-6)
    assert pieces.rim_length == pytest.approx(math.pi * 5.72, rel=1e-5)
    assert pieces.radial_seam_length == pytest.approx(20 * 2.36, rel=1e-9)


def test_allowance_is_added_all_round() -> None:
    a = 0.025
    pieces = parachute_pieces(5.72, 1.0, 20, a)
    edges = pieces.gore_edges
    perimeter = sum(edges.values())
    finished = abs(signed_area(pieces.gore_finished))
    # A constant outward offset adds about perimeter * a (plus the corner mitres).
    added = abs(signed_area(pieces.gore_cut)) - finished
    assert perimeter * a < added < perimeter * a + 4 * a * a * 4
    disc_added = abs(signed_area(pieces.centre_cut)) - abs(signed_area(pieces.centre_finished))
    assert disc_added == pytest.approx(math.pi * ((0.5 + a) ** 2 - 0.25), rel=1e-3)


def test_disc_vertices_match_the_gore_inner_arcs() -> None:
    disc = centre_outline(0.5, 20)
    assert len(disc) == 20 * arc_segments_for(20) == 20 * 36  # 0.5 deg per segment
    assert np.allclose(np.hypot(disc[:, 0], disc[:, 1]), 0.5)


@pytest.mark.parametrize(("radius", "centre", "n"), [(2.0, 0.0, 12), (2.0, 2.0, 12), (2.0, 0.5, 2)])
def test_invalid_parachutes_are_rejected(radius: float, centre: float, n: int) -> None:
    with pytest.raises(ValueError):
        gore_outline(radius, centre, n)


def test_edge_lengths_need_four_corners() -> None:
    triangle = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
    with pytest.raises(ValueError, match="four corners"):
        gore_edge_lengths(triangle)


@pytest.mark.parametrize("n", [3, 8, 20, 48])
def test_sampling_error_bounds(n: int) -> None:
    pieces = parachute_pieces(4.0, 0.6, n, 0.0)
    assert pieces.finished_area == pytest.approx(math.pi * 4.0, rel=2e-5)
    assert pieces.gore_edges["bottom"] == pytest.approx(2 * math.pi * 2.0 / n, rel=5e-6)
