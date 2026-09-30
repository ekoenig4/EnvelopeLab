"""Parachute, red line, flying wires and turning vents of a standard-gore design."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.design.model import DesignDocument
from envelopelab.project.gore_design import (
    design_findings,
    design_profile,
    gore_outputs,
    standard_gore_design,
)
from envelopelab.project.model import PatternSet
from envelopelab.project.simulation import build_solver_model, solve_preview, write_build_pack
from envelopelab.rigging import (
    rigging_outputs,
    rigging_polylines,
    turning_vent_pair,
    with_default_rigging,
)
from envelopelab.rigging.parachute import opening, seated_geometry

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


@pytest.fixture(scope="module")
def design() -> DesignDocument:
    return standard_gore_design("rig", 2000.0, 17.0, 16.0, 12, 6, payload_mass=400.0)


def _with(design: DesignDocument, path: tuple[str, ...], value: object) -> DesignDocument:
    data = design.model_dump(by_alias=True, mode="json")
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return DesignDocument.model_validate(data)


def _codes(design: DesignDocument) -> dict[str, str]:
    return {f.code: f.severity for f in rigging_outputs(design).findings}


def test_new_designs_have_parachute_red_line_and_flying_wires(design: DesignDocument) -> None:
    assert design.parachute is not None and design.parachute.panel_count == 12
    assert design.rigging.red_line is not None and design.rigging.flying_wires is not None
    assert design.rigging.flying_wires.count == 4  # 12 gores, 4-point frame
    out = rigging_outputs(design)
    assert out.findings == []
    assert out.parachute is not None and out.parachute.shroud.passes
    assert out.flying_wires is not None and out.flying_wires.wires.passes
    assert out.red_line is not None and out.red_line.anchor is not None


def test_parachute_panels_cover_the_parachute(design: DesignDocument) -> None:
    out = rigging_outputs(design)
    assert out.parachute is not None and out.parachute.panel is not None
    area = out.parachute.panel_count * out.parachute.panel.finished_area
    assert area == pytest.approx(out.parachute.geometry.area, rel=0.02)  # flat gores vs revolution
    assert out.parachute.panel.cut_area > out.parachute.panel.finished_area


def test_parachute_is_sized_from_the_crown_opening(design: DesignDocument) -> None:
    out = rigging_outputs(design)
    assert out.parachute is not None
    g = out.parachute.geometry
    assert design.gores is not None
    assert g.hole_radius == pytest.approx(design.gores.parachute_hole_diameter / 2.0, abs=1e-3)
    assert g.edge_radius > g.hole_radius  # the edge overlaps the envelope
    assert g.attachment_height < g.edge_height < g.rim_height


def test_rigging_mass_reduces_the_lift_margin(design: DesignDocument) -> None:
    bare = _with(
        _with(_with(design, ("parachute",), None), ("rigging", "red_line"), None),
        ("rigging", "flying_wires"),
        None,
    )
    with_rig = gore_outputs(design, PatternSet())
    without = gore_outputs(bare, PatternSet())
    assert with_rig.rigging_mass is not None and with_rig.rigging_mass > 1.0
    assert without.rigging_mass == 0.0
    assert with_rig.lift_margin is not None and without.lift_margin is not None
    assert without.lift_margin - with_rig.lift_margin == pytest.approx(with_rig.rigging_mass)


def test_missing_rigging_is_reported(design: DesignDocument) -> None:
    bare = _with(
        _with(_with(design, ("parachute",), None), ("rigging", "red_line"), None),
        ("rigging", "flying_wires"),
        None,
    )
    codes = _codes(bare)
    assert codes["parachute_missing"] == "warning"
    assert codes["red_line_missing"] == "warning"
    assert codes["flying_wires_missing"] == "warning"
    assert {f.code for f in design_findings(bare, PatternSet())} >= set(codes)


def test_weak_flying_wire_fails_its_factor_of_safety(design: DesignDocument) -> None:
    weak = _with(design, ("rigging", "flying_wires", "wire", "strength", "value"), 1000.0)
    out = rigging_outputs(weak)
    errors = [f for f in out.findings if f.code == "fos"]
    assert errors and errors[0].severity == "error" and "flying wire" in errors[0].message
    assert out.flying_wires is not None and not out.flying_wires.wires.passes


def test_weak_load_tape_at_the_crows_foot_fails(design: DesignDocument) -> None:
    weak = _with(design, ("tapes", "vertical", "strength"), 300.0)
    msgs = [f.message for f in rigging_outputs(weak).findings if f.code == "fos"]
    assert any("vertical load tape" in m for m in msgs)


def test_weak_shroud_line_fails(design: DesignDocument) -> None:
    weak = _with(design, ("parachute", "shroud_line", "strength", "value"), 100.0)
    msgs = [f.message for f in rigging_outputs(weak).findings if f.code == "fos"]
    assert any("shroud line" in m for m in msgs)


def test_wire_count_must_divide_gore_count(design: DesignDocument) -> None:
    assert _codes(_with(design, ("rigging", "flying_wires", "count"), 5))["flying_wires"] == "error"


def test_unreachable_opening_is_an_error(design: DesignDocument) -> None:
    short = _with(design, ("parachute", "shroud_attachment"), 0.05)
    assert _codes(short)["parachute_opening"] == "error"


def test_red_line_guide_seam_out_of_range(design: DesignDocument) -> None:
    assert _codes(_with(design, ("rigging", "red_line", "guide_seam"), 13))["red_line_seam"] == (
        "error"
    )


def test_turning_vent_pair_turns_without_side_force(design: DesignDocument) -> None:
    vented = design.model_copy(update={"turning_vents": turning_vent_pair(design)})
    out = rigging_outputs(vented)
    assert len(out.turning_vents) == 2
    assert out.net_torque > 0.0  # both counter-clockwise
    assert out.net_side_force < 1e-6 * out.turning_vents[0].jet.thrust
    assert out.total_heat_loss > 0.0
    assert out.findings == []


def test_single_vent_is_unbalanced_and_opposed_vents_cancel(design: DesignDocument) -> None:
    pair = turning_vent_pair(design)
    one = design.model_copy(update={"turning_vents": pair[:1]})
    assert _codes(one)["vent_balance"] == "warning"
    opposed = [pair[0], pair[1].model_copy(update={"direction": "clockwise"})]
    assert _codes(design.model_copy(update={"turning_vents": opposed}))["vent_cancel"] == "warning"


def test_vent_rows_must_be_consecutive(design: DesignDocument) -> None:
    vent = turning_vent_pair(design)[0].model_copy(update={"rows": ["A", "C"]})
    assert _codes(design.model_copy(update={"turning_vents": [vent]}))["vent_rows"] == "error"


def test_special_shapes_are_reported_not_analysed(design: DesignDocument) -> None:
    data = design.model_dump(by_alias=True, mode="json")
    data.update(
        envelope_type="special",
        gores=None,
        parachute=None,
        special={"mesh_reference": "x.obj", "seam_curves": [], "panel_list": []},
    )
    out = rigging_outputs(DesignDocument.model_validate(data))
    assert [f.severity for f in out.findings] == ["info"]


def test_polylines_for_the_3d_view(design: DesignDocument) -> None:
    vented = design.model_copy(update={"turning_vents": turning_vent_pair(design)})
    lines = rigging_polylines(vented, rigging_outputs(vented))
    assert set(lines) == {
        "parachute",
        "shroud_lines",
        "centralizing_lines",
        "red_line",
        "flying_wires",
        "turning_vents",
    }
    assert len(lines["shroud_lines"]) == 12
    assert all(p.ndim == 2 and p.shape[1] == 3 for v in lines.values() for p in v)


def test_defaults_scale_with_the_design() -> None:
    small = standard_gore_design("model", 2.0, 1.7, 1.6, 8, 3, payload_mass=0.5)
    assert small.rigging.flying_wires is not None and small.parachute is not None
    assert small.rigging.flying_wires.frame_drop == pytest.approx(0.6 * small.gores.mouth_diameter)  # type: ignore[union-attr]
    errors = [f for f in rigging_outputs(small).findings if f.severity == "error"]
    assert errors == []


def test_with_default_rigging_keeps_existing_values(design: DesignDocument) -> None:
    custom = _with(design, ("parachute", "billow"), 0.2)
    assert with_default_rigging(custom).parachute.billow == 0.2  # type: ignore[union-attr]


@settings(max_examples=40, deadline=None)
@given(
    overlap=st.floats(0.2, 1.0),
    attach=st.floats(0.5, 4.0),
    depth=st.floats(1.0, 8.0),
    billow=st.floats(0.0, 0.3),
)
def test_opening_keeps_line_lengths(
    overlap: float, attach: float, depth: float, billow: float
) -> None:
    theta = np.linspace(-math.pi / 3.0, math.radians(75.0), 1001)
    from envelopelab.geometry.gore import MeridianProfile

    prof = MeridianProfile.from_points(8.0 * np.cos(theta), 8.0 * np.sin(theta))
    g = seated_geometry(prof, overlap, billow, attach, depth)
    op = opening(g, prof, overlap)
    r, z = op.path_edge_radius, op.path_edge_height
    zc = g.confluence_height - op.path_travel
    assert np.allclose(
        np.hypot(r - g.attachment_radius, z - g.attachment_height), g.shroud_length, atol=1e-9
    )
    assert np.allclose(np.hypot(r, z - zc), g.centralizing_length, atol=1e-9)
    assert np.all(np.diff(op.path_travel) > 0.0)
    if op.seal_open_travel is not None and op.full_open_travel is not None:
        assert 0.0 <= op.seal_open_travel <= op.full_open_travel <= op.max_travel


def test_open_vents_become_open_seams_in_the_build_pack(
    design: DesignDocument, tmp_path: Path
) -> None:
    import yaml

    vents = [v.model_copy(update={"simulate_open": True}) for v in turning_vent_pair(design)]
    vented = design.model_copy(update={"turning_vents": vents})
    config = yaml.safe_load(write_build_pack(vented, PatternSet(), tmp_path).read_text())
    open_seams = config["assembly"]["rings"][0]["open_seams"]
    assert [s["gores"] for s in open_seams] == [[v.seam, v.seam % 12 + 1] for v in vents]
    assert all(s["kind"] == "vent" for s in open_seams)
    closed = write_build_pack(
        design.model_copy(update={"turning_vents": turning_vent_pair(design)}),
        PatternSet(),
        tmp_path / "closed",
    )
    assert yaml.safe_load(closed.read_text())["assembly"]["rings"][0]["open_seams"] == []


@pytest.mark.slow
def test_preview_converges_with_open_turning_vents(tmp_path: Path) -> None:
    from envelopelab.project.model import load_project

    project = load_project(FIXTURE)
    base = with_default_rigging(project.state.design)
    vents = [v.model_copy(update={"simulate_open": True}) for v in turning_vent_pair(base)]
    vented = base.model_copy(update={"turning_vents": vents})
    built = build_solver_model(vented, project.state.patterns, tmp_path, 1600.0)
    result = solve_preview(built)
    assert result.converged
    assert 140.0 < result.volume < 175.0  # the design's profile holds 160.7 m^3
    assert design_profile(vented).volume == pytest.approx(160.7, rel=0.01)


def test_cap_of_negligible_rise_is_flat_and_finite() -> None:
    from envelopelab.rigging.parachute import cap_points

    r, z = cap_points(2.0, 10.0, 1e-300)
    assert np.all(np.isfinite(r)) and np.all(np.isfinite(z))
    assert r[0] == pytest.approx(2.0) and r[-1] == 0.0
    assert np.allclose(z, 10.0)


# -- row zones, rings and scoop ---------------------------------------------------------


@pytest.fixture(scope="module")
def nomex_design() -> DesignDocument:
    return standard_gore_design(
        "rows",
        2000.0,
        17.0,
        16.0,
        12,
        5,
        payload_mass=400.0,
        mouth_fabric_id="nomex",
        mouth_row_height=2.0,
    )


def test_nomex_mouth_row_then_nylon_rows(nomex_design: DesignDocument) -> None:
    from envelopelab.project.gore_design import row_zone

    assert nomex_design.gores is not None
    rows = nomex_design.gores.panel_rows
    assert len(rows) == 6 and rows[0].finished_height == pytest.approx(2.0)
    assert nomex_design.zones == {"body": "ripstop_nylon", "mouth": "nomex"}
    zones = [row_zone(nomex_design, PatternSet(), r.letter) for r in rows]
    assert zones == ["mouth"] + ["body"] * 5
    total = sum(r.finished_height for r in rows)
    assert total == pytest.approx(design_profile(nomex_design).meridian_length, abs=1e-6)
    # The parachute (top panel) is nylon: the first zone.
    out = rigging_outputs(nomex_design)
    assert out.parachute is not None and out.parachute.mass is not None
    assert list(out.parachute.mass.zones) == ["body"]


def test_row_zone_annotation_overrides_design_row(nomex_design: DesignDocument) -> None:
    from envelopelab.project.gore_design import row_zone
    from envelopelab.project.model import RowPattern

    patterns = PatternSet(rows={"A": RowPattern(zone="body")})
    assert row_zone(nomex_design, patterns, "A") == "body"


def test_undefined_design_row_zone_is_an_error(nomex_design: DesignDocument) -> None:
    bad = _with(nomex_design, ("gores", "panel_rows", 0, "zone"), "kevlar")  # type: ignore[arg-type]
    codes = {f.code: f.severity for f in design_findings(bad, PatternSet())}
    assert codes["zone"] == "error"


def test_row_zone_change_is_not_a_geometry_change(nomex_design: DesignDocument) -> None:
    from envelopelab.project.dependencies import changed_groups, group_hashes, input_groups

    def hashes(d: DesignDocument) -> dict[str, str]:
        return group_hashes(input_groups(d.model_dump(by_alias=True, mode="json"), {}))

    changed = _with(nomex_design, ("gores", "panel_rows", 0, "zone"), None)  # type: ignore[arg-type]
    assert changed_groups(hashes(nomex_design), hashes(changed)) == {"row_zones"}


def test_mouth_row_height_must_fit() -> None:
    with pytest.raises(ValueError, match="mouth row height"):
        standard_gore_design(
            "x", 2000.0, 17.0, 16.0, 12, 5, mouth_fabric_id="nomex", mouth_row_height=100.0
        )


def test_default_parachute_has_crown_and_centre_rings(design: DesignDocument) -> None:
    out = rigging_outputs(design)
    assert out.parachute is not None
    rings = out.parachute.rings
    assert set(rings) == {"crown ring", "centre ring"}
    g = out.parachute.geometry
    assert rings["crown ring"].length == pytest.approx(2 * math.pi * g.hole_radius)
    assert g.apex_radius == pytest.approx(0.1)  # 5 % of the 4 m hole
    assert out.parachute.panel is not None
    assert out.parachute.panel.top_width == pytest.approx(2 * math.pi * 0.1 / 12, rel=1e-3)
    assert all(r.passes and r.tension is not None and r.tension > 0 for r in rings.values())
    assert out.masses["parachute:crown ring"] > 0.0


def test_weak_crown_ring_fails(design: DesignDocument) -> None:
    weak = _with(design, ("parachute", "crown_ring", "strength", "value"), 10.0)
    msgs = [f.message for f in rigging_outputs(weak).findings if f.code == "fos"]
    assert any(m.startswith("crown ring") for m in msgs)


def test_flat_parachute_centre_ring_not_assessed(design: DesignDocument) -> None:
    flat = _with(design, ("parachute", "billow"), 0.0)
    out = rigging_outputs(flat)
    assert _codes(flat)["centre_ring_flat"] == "warning"
    assert out.parachute is not None and out.parachute.rings["centre ring"].tension is None


def test_centre_ring_larger_than_hole_is_an_error(design: DesignDocument) -> None:
    big = _with(design, ("parachute", "centre_ring_diameter"), 10.0)
    assert _codes(big)["parachute_geometry"] == "error"


def test_centre_ring_needs_a_diameter(design: DesignDocument) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="centre_ring_diameter"):
        _with(design, ("parachute", "centre_ring_diameter"), None)


def test_scoop_matches_the_mouth_row_and_adds_mass(nomex_design: DesignDocument) -> None:
    from envelopelab.project.gore_design import panel_rows
    from envelopelab.rigging import default_scoop

    scooped = nomex_design.model_copy(update={"scoop": default_scoop(nomex_design)})
    out = rigging_outputs(scooped)
    assert out.scoop is not None and out.scoop.zone == "mouth"  # Nomex by default
    mouth_row = panel_rows(scooped, PatternSet())[0]
    assert abs(out.scoop.panel.top_width - mouth_row.bottom_width) < 3e-3
    assert out.masses["scoop:fabric, tapes and thread"] > 0.0
    assert "scoop" in rigging_polylines(scooped, out)
    assert out.findings == []


def test_scoop_reaching_the_frame_is_warned(design: DesignDocument) -> None:
    from envelopelab.rigging import default_scoop

    deep = default_scoop(design).model_copy(update={"height": 50.0})
    assert _codes(design.model_copy(update={"scoop": deep}))["scoop_frame"] == "warning"


def test_scoop_gores_must_fit(design: DesignDocument) -> None:
    from envelopelab.rigging import default_scoop

    wide = default_scoop(design).model_copy(update={"gore_count": 13})
    assert _codes(design.model_copy(update={"scoop": wide}))["scoop_gores"] == "error"
