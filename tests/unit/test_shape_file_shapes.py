"""Special shapes in shape files, several feed holes, and flat-chord panel mapping."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from envelopelab.export.build_pack import primitive_sheets
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    _panel_xy,
    band_outline,
    design_primitive,
    primitive_appendage,
)
from envelopelab.io.shape_file import ShapeFileError, load_shape_file, parse_shape_file
from envelopelab.project.gore_design import panel_rows
from envelopelab.project.model import PatternSet
from envelopelab.project.shapes import DomeShape, MeshShape, RevolvedShape, TubeShape
from envelopelab.validation.primitives import sphere_envelope

SPHERE = sphere_envelope()
PATH = Path("cut.yaml")


def _raw(shapes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": "envelopelab.shape",
        "format_version": 2,
        "name": "cut",
        "profile": {
            "span": "cut",
            "interpolation": "linear",
            "stations": [[0.0, 0.1], [0.25, 0.22], [0.5, 0.3], [0.75, 0.25], [1.0, 0.12]],
        },
        "design": {
            "construction": "flat_chord",
            "hold": {"tape_length": "20 m"},
            "gore_count": 16,
            "seam_allowance": "25 mm",
        },
        "rows": [
            {"name": "A", "top": 0.25, "bow": ["0 mm", "20 mm"]},
            {"name": "B", "top": 0.5, "bow": ["20 mm", "30 mm"]},
            {"name": "C", "top": 0.75, "bow": ["30 mm", "10 mm"]},
            {"name": "D", "bow": ["10 mm", "0 mm"]},
        ],
        "zones": {"body": "ripstop_nylon", "black": "ripstop_nylon"},
        "special_shapes": shapes,
    }


DOME = {
    "name": "pod",
    "kind": "dome",
    "placement": {"gore": 3, "row": "B", "at": 0.5},
    "base_radius": "600 mm",
    "height": "400 mm",
    "gores": 8,
    "zone": "black",
    "feed_holes": [
        {"gore": 3, "row": "B", "above": "2.0 m", "across": 0.1, "radius": "100 mm"},
        {"gore": 3, "row": "B", "at": 0.6, "radius": "80 mm"},
    ],
}


def test_shapes_are_placed_on_the_rows() -> None:
    sf = parse_shape_file(_raw([DOME]), PATH)
    design = sf.design()
    (spec,) = sf.shapes(design)
    assert isinstance(spec, DomeShape)
    rows = {r.label: r for r in panel_rows(design, PatternSet())}
    b = rows["B"]
    assert spec.placement.tape_position == pytest.approx(0.5 * (b.s_bottom + b.s_top))
    assert spec.base_radius == pytest.approx(0.6)
    assert spec.fabric == "ripstop_nylon"
    # `above` runs up the panel centreline (bows included); `at` along the tape.
    first, second = spec.feed_holes
    assert first.tape_position == pytest.approx(
        b.s_bottom + 2.0 / b.centre_height * (b.s_top - b.s_bottom)
    )
    assert first.across == pytest.approx(0.1)
    assert second.tape_position == pytest.approx(b.s_bottom + 0.6 * (b.s_top - b.s_bottom))


def test_tube_revolved_and_mesh_shapes(tmp_path: Path) -> None:
    obj = tmp_path / "blob.obj"
    verts = [
        (0, 0, -0.2),
        (0.3, 0, 0.1),
        (0, 0.3, 0.1),
        (-0.3, 0, 0.1),
        (0, -0.3, 0.1),
        (0, 0, 0.4),
    ]
    faces = [(1, 2, 3), (1, 3, 4), (1, 4, 5), (1, 5, 2), (6, 3, 2), (6, 4, 3), (6, 5, 4), (6, 2, 5)]
    obj.write_text(
        "\n".join(
            [f"v {x} {y} {z}" for x, y, z in verts] + [f"f {a} {b} {c}" for a, b, c in faces]
        ),
        encoding="utf-8",
    )
    shapes: list[dict[str, Any]] = [
        {
            "name": "horn",
            "kind": "tube",
            "placement": {"gore": 5, "tape_position": "8 m", "lean_deg": 20},
            "base_radius": "300 mm",
            "tip_radius": "100 mm",
            "length": "1 m",
            "panels": 2,
        },
        {
            "name": "nose",
            "kind": "revolved",
            "placement": {"gore": 7, "row": "C", "above": "500 mm"},
            "profile": {"unit": "mm", "points": [[400, 0], [300, 300], [0, 500]]},
        },
        {
            "name": "blob",
            "kind": "mesh",
            "placement": {"gore": 9, "row": "B", "at": 0.3},
            "mesh": {"file": "blob.obj", "up": "Z"},
        },
    ]
    path = tmp_path / "shape.yaml"
    path.write_text(yaml.safe_dump(_raw(shapes)), encoding="utf-8")
    sf = load_shape_file(path)
    tube, nose, blob = sf.shapes(sf.design())
    assert isinstance(tube, TubeShape) and tube.placement.tape_position == pytest.approx(8.0)
    assert isinstance(nose, RevolvedShape) and nose.profile[1] == pytest.approx((0.3, 0.3))
    assert isinstance(blob, MeshShape) and len(blob.vertices) == 6 and blob.source == "blob.obj"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"placement": {"gore": 3}}, "either 'row'"),
        ({"placement": {"gore": 3, "row": "Z", "at": 0.5}}, "unknown row"),
        ({"placement": {"gore": 3, "row": "B"}}, "either 'at' or 'above'"),
        ({"placement": {"gore": 3, "row": "B", "at": 1.5}}, "fraction of the row"),
        ({"placement": {"gore": 3, "row": "B", "above": "9 m"}}, "within the row"),
        ({"zone": "gold"}, "unknown zone"),
        ({"fabric": "nomex"}, "'zone' or 'fabric'"),
        ({"base_radius": 0.6}, "give a unit"),
        ({"colour": "red"}, "unknown key"),
        ({"feed_holes": [{"row": "B", "at": 0.5}]}, "feed_holes"),
        ({"gores": 2}, "special_shapes\\[0\\]"),
    ],
)
def test_shape_errors_name_the_key(change: dict[str, Any], message: str) -> None:
    sf = parse_shape_file(_raw([{**DOME, **change}]), PATH)
    with pytest.raises(ShapeFileError, match=message):
        sf.shapes(sf.design())


def test_duplicate_shape_names_are_refused() -> None:
    sf = parse_shape_file(_raw([DOME, DOME]), PATH)
    with pytest.raises(ShapeFileError, match="used twice"):
        sf.shapes(sf.design())


def test_extra_feed_holes_are_cut_checked_and_fed() -> None:
    dome = Dome("pod", Placement(3, 12.0), 1.0, 1.0)
    theta = SPHERE.theta_at(3, 0.15)
    d = design_primitive(dome, SPHERE, feed_holes=[(12.3, theta, 0.2), (11.8, theta, 0.15)])
    assert d.feed_hole is None and len(d.extra_feed_holes) == 2
    assert d.feed_holes == d.extra_feed_holes
    hole = d.extra_feed_holes[0]
    assert hole.gore == 3
    r = float(np.interp(12.3, SPHERE.profile.s, SPHERE.profile.r))
    assert hole.chart_xy == pytest.approx((r * 0.15 * SPHERE.gore_angle, 0.3), abs=1e-6)
    checks = [c for c in d.checks if c.name == "feed hole inside footprint"]
    assert len(checks) == 2 and all(c.severity == "info" for c in checks)
    spec = primitive_appendage(d)
    assert [h.name for h in spec.holes] == ["feed 2", "feed 3"]
    assert len(d.as_dict()["extra_feed_holes"]) == 2
    outside = design_primitive(dome, SPHERE, feed_holes=[(12.0, SPHERE.theta_at(5), 0.2)])
    assert any(c.severity == "error" for c in outside.checks if c.name.startswith("feed hole"))


def test_marking_sheets_cover_panels_with_only_a_feed_hole() -> None:
    dome = Dome("pod", Placement(3, 12.0), 2.5, 1.0)
    centre = SPHERE.theta_at(3)
    d = design_primitive(dome, SPHERE, feed_holes=[(12.0, centre, 0.2)])
    lined = {(a.gore, a.row) for a in d.attachment}
    hole = d.extra_feed_holes[0]
    sheets = primitive_sheets(d, "black")
    marking = [s for s in sheets if s.kind == "marking"]
    assert {(hole.gore, hole.row)} | lined == {
        (int(s.piece.split()[1]), s.piece.split()[3]) for s in marking
    }
    with_hole = [s for s in marking if s.holes]
    assert len(with_hole) == 1 and with_hole[0].holes[0][2] == pytest.approx(0.2)


def test_flat_chord_panel_mapping_follows_the_bowed_seams() -> None:
    sf = parse_shape_file(_raw([]), PATH)
    design = sf.design()
    surface = EnvelopeSurface.from_design(design)
    band = surface.rows[1]
    assert band.rise is not None and band.bow_top == pytest.approx(0.03)
    # A point on the top seam lands on the bowed seam as cut, at any position across.
    for across in (-0.4, -0.1, 0.0, 0.25):
        xy = _panel_xy(surface, np.array([band.s_top]), np.array([4.5 + across]), 4, 1)[0]
        y_seam = band.rise + band.bow_top * (1.0 - (xy[0] / band.half_top) ** 2)
        assert xy[1] == pytest.approx(y_seam, abs=1e-12)
        assert xy[0] == pytest.approx(2 * across * band.half_top)
    # The marking outline of a flat-chord row is the panel as cut.
    row = panel_rows(design, PatternSet())[1]
    outline = band_outline(surface, 1)
    assert outline[:, 1].max() == pytest.approx(row.corner_height + 0.03)
    assert (
        abs(
            float(
                np.sum(
                    outline[:, 0] * np.roll(outline[:, 1], -1)
                    - np.roll(outline[:, 0], -1) * outline[:, 1]
                )
            )
            / 2
            - row.finished_area
        )
        < 1e-6
    )
    assert math.isclose(band.half_bottom * 2, row.bottom_width)
