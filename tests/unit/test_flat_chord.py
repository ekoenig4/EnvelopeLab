"""Flat-chord gores: straight-sided rows, bowed seams and the crest loft."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from envelopelab.design.model import (
    CURRENT_SCHEMA_VERSION,
    CrestLoftSpec,
    PanelZone,
    TaperPoint,
    dump_design_document,
    load_design_document,
)
from envelopelab.geometry.gore import (
    CrestLoft,
    MeridianProfile,
    SeamAllowance,
    bowed_seam,
    crest_bows,
    flat_chord_rows,
)
from envelopelab.project.gore_design import (
    design_profile,
    design_volume,
    panel_rows,
    seam_mismatches,
)
from envelopelab.project.model import PatternSet
from envelopelab.project.templates import new_design


def _cone() -> MeridianProfile:
    return MeridianProfile.from_control_points([1.0, 2.0], [0.0, 3.0], interpolation="linear")


def _polyline() -> MeridianProfile:
    """Three straight tape segments with two convex corners (m)."""
    return MeridianProfile.from_control_points(
        [1.0, 3.0, 3.5, 2.0], [0.0, 2.0, 5.0, 7.0], interpolation="linear"
    )


def test_linear_profile_keeps_control_points_and_straight_segments() -> None:
    r, z = np.array([1.0, 3.0, 3.5, 2.0]), np.array([0.0, 2.0, 5.0, 7.0])
    profile = MeridianProfile.from_control_points(r, z, samples=101, interpolation="linear")
    chords = np.hypot(np.diff(r), np.diff(z))
    assert profile.meridian_length == pytest.approx(chords.sum(), rel=1e-12)
    for s, radius in zip(np.cumsum(np.r_[0.0, chords]), r, strict=True):
        assert float(profile.radius_at(s)) == pytest.approx(radius, abs=1e-12)
    frusta = np.pi / 3 * (r[:-1] ** 2 + r[:-1] * r[1:] + r[1:] ** 2) * np.diff(z)
    assert profile.volume == pytest.approx(frusta.sum(), rel=1e-12)


def test_unknown_interpolation_is_refused() -> None:
    with pytest.raises(ValueError, match="interpolation"):
        MeridianProfile.from_control_points([1.0, 2.0], [0.0, 1.0], interpolation="cubic")  # type: ignore[arg-type]


def test_straight_row_is_the_flat_chord_trapezoid() -> None:
    cone = _cone()
    (row,) = flat_chord_rows(cone, 20, [cone.meridian_length])
    sin_n = math.sin(math.pi / 20)
    assert row.bottom_width == pytest.approx(2.0 * sin_n)
    assert row.top_width == pytest.approx(4.0 * sin_n)
    # The side is sewn to the tape: its length is the tape length of the row.
    assert row.side_length == pytest.approx(cone.meridian_length)
    side = np.hypot(*(row.right_edge[-1] - row.right_edge[0]))
    assert side == pytest.approx(cone.meridian_length, rel=1e-12)
    assert row.centre_height == pytest.approx(row.corner_height)
    expected = 0.5 * (row.bottom_width + row.top_width) * row.corner_height
    assert row.finished_area == pytest.approx(expected, rel=1e-12)


def test_bowed_seam_is_a_parabola_through_the_corners() -> None:
    seam = bowed_seam(1.5, 0.02)
    assert seam[0] == pytest.approx([1.5, 0.0])
    assert seam[-1] == pytest.approx([-1.5, 0.0])
    assert seam[len(seam) // 2] == pytest.approx([0.0, 0.02])
    # Arc length of y = b(1 - (x/w)^2) over [-w, w].
    w, b = 1.5, 0.02
    a = 2 * b / w  # slope at the corner
    exact = w * math.sqrt(1 + a * a) + (w / a) * math.asinh(a)
    length = float(np.sum(np.hypot(*np.diff(seam, axis=0).T)))
    assert length == pytest.approx(exact, rel=1e-6)


def test_bowed_row_outline_and_seam_lengths() -> None:
    cone = _cone()
    (row,) = flat_chord_rows(cone, 20, [cone.meridian_length], bows=[(0.01, 0.025)])
    outline = row.finished_outline
    assert outline[:, 1].min() == pytest.approx(-0.01)
    assert outline[:, 1].max() == pytest.approx(row.corner_height + 0.025)
    assert row.centre_height == pytest.approx(row.corner_height + 0.035)
    assert row.top_seam_length > row.top_width
    assert row.bottom_seam_length > row.bottom_width
    # Counter-clockwise polygon.
    x, y = outline[:, 0], outline[:, 1]
    assert 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) > 0.0


def _distances(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    closed = np.vstack((polygon, polygon[:1]))
    a, b = closed[:-1], closed[1:]
    ab = b - a
    out = []
    for p in points:
        t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.einsum("ij,ij->i", ab, ab), 0, 1)
        out.append(np.min(np.hypot(*(a + t[:, None] * ab - p).T)))
    return np.array(out)


def test_bowed_cut_outline_keeps_the_allowance() -> None:
    cone = _cone()
    allowance = SeamAllowance(side=0.025, bottom=0.025, top=0.025)
    (row,) = flat_chord_rows(
        cone, 20, [cone.meridian_length], bows=[(0.01, 0.025)], allowance=allowance
    )
    d = _distances(row.cut_outline, row.finished_outline)
    # Every cut point is at least the allowance away; mitred corners are farther.
    assert d.min() == pytest.approx(0.025, abs=1e-6)
    assert row.cut_area > row.finished_area


def test_straight_rows_keep_the_existing_cut_outline() -> None:
    cone = _cone()
    allowance = SeamAllowance(side=0.025, bottom=0.025, top=0.025)
    (row,) = flat_chord_rows(cone, 20, [cone.meridian_length], allowance=allowance)
    assert len(row.cut_outline) >= 4
    d = _distances(row.cut_outline, row.finished_outline)
    assert d.min() == pytest.approx(0.025, abs=1e-6)


def test_crest_bows_at_a_single_corner() -> None:
    profile = _polyline()
    boundaries = np.cumsum(
        np.r_[0.0, np.hypot(np.diff([1.0, 3.0, 3.5, 2.0]), np.diff([0.0, 2.0, 5.0, 7.0]))]
    )
    crest = CrestLoft(0.02)
    bows = crest_bows(profile, boundaries, crest)
    d = np.column_stack((np.diff([1.0, 3.0, 3.5, 2.0]), np.diff([0.0, 2.0, 5.0, 7.0])))
    phi1 = math.atan2(d[0, 0] * d[1, 1] - d[0, 1] * d[1, 0], float(d[0] @ d[1]))
    beta1 = 0.02 * 3.0 * math.tan(phi1 / 2)
    assert bows[0] == pytest.approx((0.0, beta1))
    assert bows[1][0] == pytest.approx(beta1)
    assert bows[2][1] == 0.0  # the top opening stays straight


def test_crest_taper_zero_gives_straight_seams() -> None:
    profile = _polyline()
    rows = flat_chord_rows(
        profile, 16, [profile.meridian_length / 3] * 3, crest=CrestLoft(0.02, (0.0,), (0.0,))
    )
    assert all(r.bottom_bow == 0.0 and r.top_bow == 0.0 for r in rows)


def test_crest_loft_and_measured_bows_are_exclusive() -> None:
    cone = _cone()
    with pytest.raises(ValueError, match="not both"):
        flat_chord_rows(cone, 20, [cone.meridian_length], bows=[(0, 0)], crest=CrestLoft(0.02))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"fraction": -0.1}, "fraction"),
        ({"fraction": 0.02, "stations": (0.5, 0.2), "taper": (1.0, 1.0)}, "increasing"),
        ({"fraction": 0.02, "stations": (0.0,), "taper": (-1.0,)}, "taper"),
        ({"fraction": 0.02, "stations": (0.0, 1.5), "taper": (1.0, 1.0)}, "fractions"),
    ],
)
def test_crest_loft_validation(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CrestLoft(**kwargs)  # type: ignore[arg-type]


def _flat_chord_design(**gores: object):  # type: ignore[no-untyped-def]
    design = new_design(
        name="flat chord",
        points=[(1.0, 0.0), (3.0, 2.0), (3.5, 5.0), (2.0, 7.0)],
        gore_count=16,
        row_heights=[1.0],
        mouth_diameter=2.0,
        top_diameter=4.0,
        rigging=False,
    )
    assert design.gores is not None
    profile = MeridianProfile.from_control_points(
        [1.0, 3.0, 3.5, 2.0], [0.0, 2.0, 5.0, 7.0], interpolation="linear"
    )
    third = profile.meridian_length / 3
    rows = [
        {"letter": "A", "finished_height": third},
        {"letter": "B", "finished_height": third},
        {"letter": "C", "finished_height": third},
    ]
    raw = json.loads(dump_design_document(design))
    raw["gores"].update(
        {"construction": "flat_chord", "profile_interpolation": "linear", "panel_rows": rows}
    )
    raw["gores"].update(gores)
    raw["meta"]["content_hash"] = None
    return load_design_document(json.dumps(raw))


def test_flat_chord_design_rows_and_volume() -> None:
    crest = {"fraction": 0.02, "taper": [{"station": 0.0, "taper": 1.0}]}
    design = _flat_chord_design(crest_loft=crest)
    profile = design_profile(design)
    rows = panel_rows(design, PatternSet(), profile)
    assert [r.label for r in rows] == ["A", "B", "C"]
    assert rows[0].top_bow == pytest.approx(rows[1].bottom_bow)
    assert rows[0].top_bow > 0.0
    assert seam_mismatches(rows, PatternSet()) == []
    # The flat-chord volume is that of the flat-gore polygon.
    polygon = 16 / 2 * math.sin(2 * math.pi / 16) / math.pi
    assert design_volume(design, profile) == pytest.approx(profile.volume * polygon, rel=1e-9)


def test_flat_chord_design_uses_measured_bows() -> None:
    design = _flat_chord_design()
    assert design.gores is not None
    raw = json.loads(dump_design_document(design))
    for row, (b, t) in zip(
        raw["gores"]["panel_rows"], [(0.0, 0.01), (0.01, 0.02), (0.02, 0.0)], strict=True
    ):
        row["bow_bottom"], row["bow_top"] = b, t
    raw["meta"]["content_hash"] = None
    measured = load_design_document(json.dumps(raw))
    rows = panel_rows(measured, PatternSet())
    assert [(r.bottom_bow, r.top_bow) for r in rows] == [(0.0, 0.01), (0.01, 0.02), (0.02, 0.0)]


def test_flat_chord_validation() -> None:
    with pytest.raises(ValueError, match="flat_chord gore is lofted by crest_loft"):
        _flat_chord_design(loft=[{"station": 0.0, "ratio": 1.0}])
    with pytest.raises(ValueError, match="both seam bows"):
        _flat_chord_design(
            panel_rows=[
                {"letter": "A", "finished_height": 3.0, "bow_bottom": 0.0},
                {"letter": "B", "finished_height": 3.0},
            ]
        )


def test_lobe_designs_refuse_bows_and_crest() -> None:
    design = _flat_chord_design()
    raw = json.loads(dump_design_document(design))
    raw["gores"]["construction"] = "lobe"
    raw["gores"]["crest_loft"] = {"fraction": 0.02, "taper": [{"station": 0.0, "taper": 1.0}]}
    raw["meta"]["content_hash"] = None
    with pytest.raises(ValueError, match="flat_chord construction"):
        load_design_document(json.dumps(raw))


def test_crest_loft_spec_stations_increase() -> None:
    with pytest.raises(ValueError, match="increasing"):
        CrestLoftSpec(
            fraction=0.02,
            taper=[TaperPoint(station=0.5, taper=1.0), TaperPoint(station=0.5, taper=0.0)],
        )


def test_panel_zone_validation() -> None:
    with pytest.raises(ValueError, match="start at 1"):
        PanelZone(name="x", row="A", gores=[0], zone="black")
    with pytest.raises(ValueError, match="unique"):
        PanelZone(name="x", row="A", gores=[2, 2], zone="black")
    zone = {"name": "doubler", "row": "Z", "gores": [1], "zone": "body"}
    with pytest.raises(ValueError, match="unknown row"):
        _flat_chord_design(panel_zones=[zone])


def test_version_3_documents_migrate_to_lobe_gores() -> None:
    design = _flat_chord_design()
    raw = json.loads(dump_design_document(design))
    raw["schema_version"] = 3
    for key in ("construction", "profile_interpolation", "crest_loft", "panel_zones"):
        del raw["gores"][key]
    for row in raw["gores"]["panel_rows"]:
        del row["bow_bottom"], row["bow_top"]
    raw["meta"]["content_hash"] = None
    loaded = load_design_document(json.dumps(raw))
    assert loaded.schema_version == CURRENT_SCHEMA_VERSION == 4
    assert loaded.gores is not None
    assert loaded.gores.construction == "lobe"
    assert loaded.gores.profile_interpolation == "spline"
    assert loaded.gores.panel_zones == []


def test_panel_zones_split_the_fabric_mass() -> None:
    from envelopelab.project.gore_design import gore_outputs, panel_zone

    base = _flat_chord_design()
    zones = [
        {"name": "applique", "row": "B", "gores": [1, 2, 16], "zone": "black"},
        {"name": "doubler", "row": "C", "gores": [4], "zone": "black"},
    ]
    zoned = _flat_chord_design(panel_zones=zones)
    assert panel_zone(zoned, PatternSet(), "B", 2) == "black"
    assert panel_zone(zoned, PatternSet(), "B", 3) == panel_zone(base, PatternSet(), "B", 3)
    plain = gore_outputs(base, PatternSet())
    split = gore_outputs(zoned, PatternSet())
    assert plain.mass is not None and split.mass is not None
    rows = panel_rows(zoned, PatternSet())
    black = 3 * rows[1].cut_area + rows[2].cut_area
    assert split.mass.zones["black"].cut_area == pytest.approx(black, rel=1e-12)
    total = sum(z.cut_area for z in split.mass.zones.values())
    assert total == pytest.approx(sum(z.cut_area for z in plain.mass.zones.values()), rel=1e-12)
    assert any(f.code == "zone" and "black" in f.message for f in split.findings)


def test_overlapping_panel_zones_are_refused() -> None:
    zones = [
        {"name": "a", "row": "B", "gores": [1, 2], "zone": "black"},
        {"name": "b", "row": "B", "gores": [2], "zone": "red"},
    ]
    with pytest.raises(ValueError, match="already has a panel zone"):
        _flat_chord_design(panel_zones=zones)


def test_flat_chord_lobe_ring_is_the_polygon() -> None:
    from envelopelab.project.gore_design import lobe_ring

    ring = lobe_ring(2.0, math.inf, 8, 4)
    assert np.all(np.isfinite(ring))
    # Every point lies on a side of the regular octagon of circumradius 2 m.
    angle = np.arctan2(ring[:, 1], ring[:, 0])
    gore = np.floor(angle / (2 * np.pi / 8))
    mid = (gore + 0.5) * 2 * np.pi / 8
    apothem = ring[:, 0] * np.cos(mid) + ring[:, 1] * np.sin(mid)
    assert apothem == pytest.approx(np.full(len(ring), 2.0 * math.cos(math.pi / 8)))
