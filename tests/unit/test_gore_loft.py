"""Gore loft: lobe-radius ratio along the gore, lofted widths, volume and area, the design
schema, editor edits, shape files and the display surface."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from envelopelab.design.model import (
    CURRENT_SCHEMA_VERSION,
    DesignDocument,
    dump_design_document,
    load_design_document,
)
from envelopelab.geometry.gore import (
    GoreLoft,
    GoreWidthModel,
    MeridianProfile,
    half_width_chord,
    lobe_area_factor,
    loft_extra_width,
    lofted_area,
    lofted_volume,
    split_rows,
)
from envelopelab.io.shape_file import ShapeFileError, parse_shape_file
from envelopelab.project import edits
from envelopelab.project.dependencies import group_hashes, input_groups
from envelopelab.project.gore_design import (
    design_profile,
    design_volume,
    display_surface,
    fit_row_heights,
    gore_outputs,
    lobe_ring,
    panel_rows,
    standard_gore_design,
)
from envelopelab.project.model import PatternSet
from envelopelab.project.session import ProjectSession
from envelopelab.project.shape_family import evaluate, shape_design
from envelopelab.project.templates import new_design

SPHERE_POINTS = [
    (8.0 * math.cos(t), 8.0 * math.sin(t)) for t in np.linspace(-1.2, 1.35, 9).tolist()
]


SPHERE_R = np.array([p[0] for p in SPHERE_POINTS])
SPHERE_Z = np.array([p[1] for p in SPHERE_POINTS])


def sphere_profile() -> MeridianProfile:
    return MeridianProfile.from_control_points(SPHERE_R, SPHERE_Z)


def sphere_design(loft: GoreLoft | None = None, gores: int = 16) -> DesignDocument:
    profile = sphere_profile()
    return new_design(
        "sphere",
        SPHERE_POINTS,
        gore_count=gores,
        row_heights=fit_row_heights([1.0] * 5, profile.meridian_length),
        mouth_diameter=2 * SPHERE_POINTS[0][0],
        top_diameter=2 * SPHERE_POINTS[-1][0],
        loft=loft,
    )


# --------------------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------------------


def test_loft_interpolates_linearly_and_holds_the_end_values() -> None:
    loft = GoreLoft(stations=(0.2, 0.6), ratios=(1.4, 1.0))
    assert loft.ratio_at([0.0, 0.2, 0.4, 0.6, 1.0]) == pytest.approx([1.4, 1.4, 1.2, 1.0, 1.0])
    assert GoreLoft.constant(1.3).ratio_at(0.77) == pytest.approx(1.3)


@pytest.mark.parametrize(
    ("stations", "ratios", "message"),
    [
        ((), (), "one or more"),
        ((0.0, 0.5), (1.0,), "one or more"),
        ((0.5, 0.5), (1.0, 1.1), "strictly increasing"),
        ((-0.1,), (1.0,), "fractions"),
        ((0.0,), (0.0,), "positive"),
        ((0.0,), (math.inf,), "positive and finite"),
    ],
)
def test_invalid_lofts_are_refused(
    stations: tuple[float, ...], ratios: tuple[float, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        GoreLoft(stations, ratios)


def test_area_factor_limits() -> None:
    n = 16
    assert float(lobe_area_factor(n, 1.0)) == pytest.approx(1.0, abs=1e-14)
    polygon = n * math.sin(2 * math.pi / n) / (2 * math.pi)
    assert float(lobe_area_factor(n, math.inf)) == pytest.approx(polygon, rel=1e-14)
    # A half-circle lobe (k = sin(pi/N)): N-gon plus N half discs on its sides.
    half = math.sin(math.pi / n)
    disc = n * math.pi * half**2 / 2
    expected = (n / 2 * math.sin(2 * math.pi / n) + disc) / math.pi
    assert float(lobe_area_factor(n, half)) == pytest.approx(expected, rel=1e-12)
    k = np.array([half, 0.5, 1.0, 2.0, 10.0])
    assert np.all(np.diff(lobe_area_factor(n, k)) < 0.0)
    with pytest.raises(ValueError, match="sin"):
        lobe_area_factor(n, 0.9 * half)


def test_extra_width_limits() -> None:
    n = 12
    assert float(loft_extra_width(n, math.inf)) == 0.0
    small = (math.pi / n) / math.sin(math.pi / n) - 1.0
    assert float(loft_extra_width(n, 1.0)) == pytest.approx(small, rel=1e-12)
    assert float(loft_extra_width(n, math.sin(math.pi / n))) == pytest.approx(
        math.pi / 2 - 1.0, rel=1e-12
    )


def test_lofted_width_model_needs_the_station_and_a_valid_ratio() -> None:
    model = GoreWidthModel.lofted(12, GoreLoft.constant(1.2))
    with pytest.raises(ValueError, match="station fraction"):
        model.half_width(1.0)
    with pytest.raises(ValueError, match="half circle"):
        GoreWidthModel.lofted(6, GoreLoft.constant(0.4))  # sin(pi/6) = 0.5
    with pytest.raises(ValueError, match="at most one"):
        GoreWidthModel(12, "chord", bulge_ratio=1.2, loft=GoreLoft.constant(1.2))
    assert GoreWidthModel.lofted(12, None).form == "small_bulge"


def test_ratio_one_is_the_small_bulge_gore() -> None:
    r = np.linspace(0.0, 5.0, 11)
    small = GoreWidthModel(12)
    lofted = GoreWidthModel.lofted(12, GoreLoft.constant(1.0))
    assert lofted.half_width(r, 0.5) == pytest.approx(small.half_width(r), abs=1e-12)
    assert lofted.radius_from_full_width(small.full_width(r), 0.5) == pytest.approx(r, abs=1e-12)


def test_width_with_a_ratio_is_finite_where_the_tapes_meet() -> None:
    # r = 0 at a closed pole: the lobe radius k r is 0 too and the width is 0, not NaN.
    out = half_width_chord(np.array([0.0, 1.0]), 12, np.array([0.0, 1.5]))
    assert np.all(np.isfinite(out)) and out[0] == 0.0


def test_lofted_volume_and_area_of_the_small_bulge_gore_are_the_tape_surface() -> None:
    profile = sphere_profile()
    small = GoreWidthModel(16)
    assert lofted_volume(profile, small) == profile.volume
    assert lofted_area(profile, small) == profile.area
    unit = GoreWidthModel.lofted(16, GoreLoft.constant(1.0))
    assert lofted_volume(profile, unit) == pytest.approx(profile.volume, rel=1e-12)
    assert lofted_area(profile, unit) == pytest.approx(profile.area, rel=1e-12)


def test_lofted_area_is_the_area_of_the_flat_panels() -> None:
    profile = sphere_profile()
    model = GoreWidthModel.lofted(16, GoreLoft((0.0, 0.5, 1.0), (1.6, 0.9, 1.3)))
    rows = split_rows(profile, model, [profile.meridian_length / 5] * 5)
    panels = 16 * sum(row.finished_area for row in rows)
    assert lofted_area(profile, model) == pytest.approx(panels, rel=1e-5)


def test_rows_of_a_varying_loft_still_match_at_horizontal_seams() -> None:
    profile = sphere_profile()
    model = GoreWidthModel.lofted(16, GoreLoft((0.0, 1.0), (2.0, 0.8)))
    rows = split_rows(profile, model, [profile.meridian_length / 4] * 4)
    for lower, upper in zip(rows, rows[1:], strict=False):
        assert lower.top_width == pytest.approx(upper.bottom_width, abs=1e-9)
    # The ratio falls towards the top, so the gores widen relative to the tape circle.
    ratio = [
        row.loft[2].width / (2 * math.pi * float(profile.radius_at(row.s_bottom + row.loft[2].y)))
        for row in rows
    ]
    assert np.all(np.diff(ratio) > 0.0)


# --------------------------------------------------------------------------------------
# Design schema
# --------------------------------------------------------------------------------------


def test_version_2_documents_migrate_to_no_loft_and_keep_their_hash() -> None:
    design = sphere_design()
    raw = json.loads(dump_design_document(design))
    raw["schema_version"] = 2
    del raw["gores"]["loft"]
    raw["meta"]["content_hash"] = None
    text = json.dumps(raw)
    loaded = load_design_document(text)
    assert loaded.schema_version == CURRENT_SCHEMA_VERSION == 3
    assert loaded.gores is not None and loaded.gores.loft is None
    raw["meta"]["name"] = "tampered"
    raw["meta"]["content_hash"] = "0" * 64
    with pytest.raises(ValueError, match="content hash"):
        load_design_document(json.dumps(raw))


def test_loft_round_trips_through_the_design_document() -> None:
    design = sphere_design(GoreLoft((0.0, 0.7), (1.3, 1.05)))
    loaded = load_design_document(dump_design_document(design))
    assert loaded.gores is not None and loaded.gores.loft is not None
    assert [(p.station, p.ratio) for p in loaded.gores.loft] == [(0.0, 1.3), (0.7, 1.05)]


@pytest.mark.parametrize(
    ("loft", "message"),
    [
        ([], "at least one station"),
        ([{"station": 0.5, "ratio": 1.0}, {"station": 0.2, "ratio": 1.0}], "increasing"),
        ([{"station": 0.0, "ratio": 0.1}], "half circle"),
        ([{"station": 1.5, "ratio": 1.0}], "less than or equal"),
    ],
)
def test_schema_refuses_invalid_lofts(loft: list[dict[str, float]], message: str) -> None:
    raw = sphere_design().model_dump(by_alias=True, mode="json")
    raw["gores"]["loft"] = loft
    with pytest.raises(ValidationError, match=message):
        DesignDocument.model_validate(raw)


# --------------------------------------------------------------------------------------
# Design outputs and patterns
# --------------------------------------------------------------------------------------


def test_explicit_unit_loft_matches_the_design_without_a_loft() -> None:
    plain = sphere_design()
    unit = sphere_design(GoreLoft.constant(1.0))
    a, b = gore_outputs(plain, PatternSet()), gore_outputs(unit, PatternSet())
    assert b.volume == pytest.approx(a.volume, rel=1e-12)
    assert b.area == pytest.approx(a.area, rel=1e-12)
    for x, y in zip(panel_rows(plain, PatternSet()), panel_rows(unit, PatternSet()), strict=True):
        assert y.cut_outline == pytest.approx(x.cut_outline, abs=1e-12)


def test_flatter_loft_narrows_the_gores_and_reduces_volume_and_lift() -> None:
    plain, flat = sphere_design(), sphere_design(GoreLoft.constant(2.0))
    a, b = gore_outputs(plain, PatternSet()), gore_outputs(flat, PatternSet())
    factor = float(lobe_area_factor(16, 2.0))
    assert b.volume == pytest.approx(factor * a.volume, rel=1e-9)
    assert b.volume == pytest.approx(design_volume(flat), rel=1e-15)
    assert b.gross_lift == pytest.approx(factor * a.gross_lift, rel=1e-9)
    assert b.area < a.area
    rows_a, rows_b = panel_rows(plain, PatternSet()), panel_rows(flat, PatternSet())
    for x, y in zip(rows_a, rows_b, strict=True):
        assert y.bottom_width < x.bottom_width
        assert y.side_length == pytest.approx(x.side_length, rel=1e-3)
    # The mass estimate uses the narrower cut panels.
    assert b.envelope_mass is not None and a.envelope_mass is not None
    assert b.envelope_mass < a.envelope_mass


def test_wizard_holds_the_lofted_target_volume() -> None:
    design = standard_gore_design(
        "lofted", 2200.0, 17.0, 16.0, gore_count=12, row_count=5, loft=GoreLoft.constant(1.5)
    )
    assert design.gores is not None and design.gores.loft is not None
    assert design_volume(design) == pytest.approx(2200.0, rel=1e-3)
    assert design_profile(design).volume > 2200.0  # the tape surface encloses more


def test_display_surface_draws_lobes_between_the_tapes() -> None:
    n, k = 16, 1.5
    surface = display_surface(sphere_design(GoreLoft.constant(k), gores=n), per_gore=4)
    ring = lobe_ring(2.0, k, n, 4)
    radius = np.hypot(ring[:, 0], ring[:, 1])
    assert radius[::4] == pytest.approx(2.0, abs=1e-12)  # on the tapes
    rho = k * 2.0
    half_chord = 2.0 * math.sin(math.pi / n)
    apex = 2.0 * math.cos(math.pi / n) + rho - math.sqrt(rho**2 - half_chord**2)
    assert radius[2::4] == pytest.approx(apex, abs=1e-12)  # gore centres: lobe apex
    assert np.all(radius <= 2.0 + 1e-12)  # flatter than the tape circle
    assert np.all(np.isfinite(surface.points))
    # Without a loft the lobes are the circle through the tapes.
    circle = lobe_ring(2.0, 1.0, n, 4)
    assert np.hypot(circle[:, 0], circle[:, 1]) == pytest.approx(2.0, abs=1e-12)


# --------------------------------------------------------------------------------------
# Editor edits
# --------------------------------------------------------------------------------------


def test_set_loft_is_one_undoable_edit_and_changes_the_geometry_fingerprint() -> None:
    session = ProjectSession.new(sphere_design())
    before = session.fingerprints()
    assert edits.set_loft(session, [(0.6, 1.1), (0.0, 1.4)])
    assert session.design.gores is not None and session.design.gores.loft is not None
    assert [p.station for p in session.design.gores.loft] == [0.0, 0.6]  # sorted
    after = session.fingerprints()
    assert after["patterns"] != before["patterns"] and after["simulation"] != before["simulation"]
    assert not edits.set_loft(session, [(0.0, 1.4), (0.6, 1.1)])  # unchanged: no command
    assert session.undo()
    assert session.design.gores is not None and session.design.gores.loft is None
    assert session.fingerprints() == before
    with pytest.raises(ValueError):
        edits.set_loft(session, [(0.0, 0.05)])
    assert session.design.gores.loft is None


def test_set_loft_keeps_a_locked_volume() -> None:
    session = ProjectSession.new(sphere_design())
    edits.set_lock(session, "volume", True)
    locked = session.project.locks.volume
    assert locked is not None
    edits.set_loft(session, [(0.0, 1.8)])
    assert design_volume(session.design) == pytest.approx(locked, rel=1e-3)
    assert session.design.gores is not None
    total = sum(r.finished_height for r in session.design.gores.panel_rows)
    assert total == pytest.approx(design_profile(session.design).meridian_length, abs=1e-3)
    # A later profile edit holds the lofted volume, not the tape-surface volume.
    edits.move_control_point(session, 4, 7.5, float(SPHERE_POINTS[4][1]))
    assert design_volume(session.design) == pytest.approx(locked, rel=1e-3)


def test_unlofted_designs_keep_their_fingerprints() -> None:
    design = sphere_design()
    data = design.model_dump(by_alias=True, mode="json")
    without_key = json.loads(json.dumps(data))
    del without_key["gores"]["loft"]
    patterns = PatternSet().model_dump(mode="json")
    assert group_hashes(input_groups(data, patterns)) == group_hashes(
        input_groups(without_key, patterns)
    )


# --------------------------------------------------------------------------------------
# Shape files
# --------------------------------------------------------------------------------------


def _raw_shape(loft: Any = None) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "format": "envelopelab.shape",
        "format_version": 1,
        "name": "lofted",
        "profile": {
            "source": "assumed",
            "stations": [[0.0, 0.0], [0.25, 0.2], [0.5, 0.3], [0.75, 0.2], [1.0, 0.0]],
        },
        "stations": {"mouth": 0.1, "vent": 0.9},
        "design": {
            "hold": {"gore_length": "20 m", "mouth_station": "mouth", "top_station": "vent"},
            "gore_count": 12,
            "seam_allowance": "0 m",
        },
    }
    if loft is not None:
        raw["loft"] = loft
    return raw


def test_shape_file_loft_by_station_name_reaches_the_design() -> None:
    sf = parse_shape_file(
        _raw_shape({"stations": [["vent", 1.0], [0.1, 1.4]]}), Path("lofted.yaml")
    )
    assert sf.shape.loft == GoreLoft((0.1, 0.9), (1.4, 1.0))
    solution = sf.solve()
    assert solution.converged
    design = shape_design(sf.name, sf.shape, solution, row_count=4)
    assert design.gores is not None and design.gores.loft is not None
    # Cut exactly at the loft stations: 0..1 of the design's tape.
    assert [(p.station, p.ratio) for p in design.gores.loft] == pytest.approx(
        [(0.0, 1.4), (1.0, 1.0)]
    )
    # The editor shows the volume the shape solve computed.
    assert design_volume(design) == pytest.approx(solution.values["envelope_volume"], rel=1e-6)


def test_shape_file_loft_changes_volume_and_cut_width() -> None:
    plain = parse_shape_file(_raw_shape(), Path("p.yaml"))
    flat = parse_shape_file(_raw_shape({"ratio": 2.0}), Path("f.yaml"))
    a, b = evaluate(plain.shape, plain.start()), evaluate(flat.shape, flat.start())
    assert b["envelope_volume"] < a["envelope_volume"]
    assert b["nominal_volume"] < a["nominal_volume"]
    assert b["max_cut_gore_width"] < a["max_cut_gore_width"]
    assert b["height"] == a["height"] and b["tape_length"] == a["tape_length"]


def test_design_loft_re_expresses_the_stations_of_the_cut() -> None:
    sf = parse_shape_file(
        _raw_shape({"stations": [[0.0, 2.0], [0.5, 1.0], [1.0, 2.0]]}), Path("v.yaml")
    )
    loft = sf.shape.design_loft(0.25, 0.75)
    assert loft is not None
    assert loft.stations == pytest.approx((0.0, 0.5, 1.0))
    assert loft.ratios == pytest.approx((1.5, 1.0, 1.5))


@pytest.mark.parametrize(
    ("loft", "message"),
    [
        ({"ratio": 1.0, "stations": [[0, 1]]}, "either"),
        ({"stations": [["neck", 1.0]]}, "unknown station"),
        ({"stations": [[0.0]]}, r"\[s, k\]"),
        ({"stations": []}, r"\[s, k\]"),
        ({"ratio": 0.1}, "half circle"),
        ({"ratio": "wide"}, "loft"),
    ],
)
def test_shape_file_loft_errors_name_the_key(loft: Any, message: str) -> None:
    with pytest.raises(ShapeFileError, match=message):
        parse_shape_file(_raw_shape(loft), Path("bad.yaml"))
