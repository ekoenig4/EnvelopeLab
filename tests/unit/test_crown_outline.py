"""Crown outlines and the files they are read from (ADR-0054)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.features.crown import (
    CrownOutline,
    CrownOutlineError,
    ellipse,
    polygon,
    scaled,
    widest_width,
)
from envelopelab.io.outline_file import OutlineFileError, read_outline


def test_an_ellipse_reaches_its_half_width_across_and_half_length_up() -> None:
    e = ellipse(0.4, 0.6)
    r = e.radius(np.array([0.0, 0.5 * math.pi, math.pi, 1.5 * math.pi]))
    assert r == pytest.approx([0.2, 0.3, 0.2, 0.3], rel=1e-12)
    assert e.size == pytest.approx(0.6, rel=1e-6)
    # Turned 90 deg, the length lies across.
    assert ellipse(0.4, 0.6, 90.0).radius(np.array([0.0]))[0] == pytest.approx(0.3, rel=1e-9)


def test_a_square_s_radius_is_the_exact_edge_crossing() -> None:
    sq = polygon([[0.1, 0.1], [-0.1, 0.1], [-0.1, -0.1], [0.1, -0.1]])
    angles = np.linspace(-math.pi / 4, math.pi / 4, 9)
    assert sq.radius(angles) == pytest.approx(0.1 / np.cos(angles), rel=1e-12)
    assert sq.inside(0.05, 0.05) > 0 and sq.inside(0.12, 0.0) < 0


@settings(max_examples=40, deadline=None)
@given(st.lists(st.floats(0.05, 0.3), min_size=3, max_size=12))
def test_star_polygons_pass_through_their_corners(radii: list[float]) -> None:
    n = len(radii)
    ang = 2 * math.pi * np.arange(n) / n + 0.1
    pts = np.column_stack([np.cos(ang), np.sin(ang)]) * np.asarray(radii)[:, None]
    outline = polygon(pts)
    assert outline.radius(ang) == pytest.approx(radii, rel=1e-9)
    # The same outline given clockwise is the same outline.
    assert polygon(pts[::-1]).radius(ang) == pytest.approx(radii, rel=1e-9)


def test_smoothed_polygons_pass_through_their_corners() -> None:
    corners = np.array([[0.2, 0.0], [0.0, 0.1], [-0.2, 0.0], [0.0, -0.1]])
    smooth = polygon(corners, smooth=True)
    for c in corners:
        theta = math.atan2(c[1], c[0])
        assert smooth.radius(np.array([theta]))[0] == pytest.approx(np.hypot(*c), rel=1e-9)
    assert len(smooth.points) > len(corners)


def test_an_outline_not_seen_whole_from_the_point_is_refused() -> None:
    with pytest.raises(CrownOutlineError):
        polygon([[0.1, 0.0], [0.0, 0.1], [-0.1, 0.0], [0.05, 0.02], [0.0, -0.1]])
    with pytest.raises(CrownOutlineError):  # the point outside the outline
        polygon([[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]])
    with pytest.raises(CrownOutlineError):
        polygon([[0.1, 0.0], [0.0, 0.1]])


def test_scaled_outlines_are_centred_and_their_widest_width_is_the_size() -> None:
    tri = np.array([[10.0, 0.0], [40.0, 0.0], [25.0, 30.0]])  # any units
    out = scaled(tri, 0.25, turn_deg=30.0)
    assert out.size == pytest.approx(0.25, rel=1e-12)
    # Area centroid on the meeting point.
    p = out.points
    cross = p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]
    centroid = ((p + np.roll(p, -1, axis=0)) * cross[:, None]).sum(axis=0) / (3 * cross.sum())
    assert centroid == pytest.approx([0.0, 0.0], abs=1e-12)
    assert widest_width(tri) == pytest.approx(math.hypot(15.0, 30.0))
    assert isinstance(out, CrownOutline)


def test_outlines_are_read_from_svg_and_dxf(tmp_path: Path) -> None:
    svg = tmp_path / "star.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="0" y="0" width="5" height="5"/>'
        '<path d="M 50 5 L 61 38 L 95 38 L 68 59 L 79 92 L 50 72 L 21 92 L 32 59 L 5 38 '
        'L 39 38 Z"/>'
        '<path d="m10 10 c 10 0 20 10 20 20 s -10 20 -20 20 z"/>'
        "</svg>"
    )
    star = read_outline(svg)
    assert len(star) == 10  # the largest outline: the star's ten corners
    assert star[:, 1].max() == pytest.approx(-5.0)  # y turned up
    from ezdxf.filemanagement import new

    doc = new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    msp.add_circle((300, 0), 10)
    msp.add_line((0, 0), (500, 500))
    dxf = tmp_path / "box.dxf"
    doc.saveas(dxf)
    box = read_outline(dxf)
    assert np.ptp(box, axis=0) == pytest.approx([100.0, 50.0])
    with pytest.raises(OutlineFileError):
        read_outline(tmp_path / "x.png")
    (tmp_path / "open.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><polyline points="0,0 10,0 10,10"/></svg>'
    )
    with pytest.raises(OutlineFileError):
        read_outline(tmp_path / "open.svg")
