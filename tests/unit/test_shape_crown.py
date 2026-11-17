"""Where a special shape's panels meet at the crown: seam angles at the cap (the seams turn
from their rim angles) and a cap moved off the tip (ADR-0049)."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.export.build_pack import export_build_pack
from envelopelab.export.qa import check_pack
from envelopelab.features.builder import build_appendage
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    PrimitiveDesign,
    PrimitiveError,
    Revolved,
    Tube,
    crown_seam_angles,
    design_primitive,
    primitive_appendage,
    seam_angles,
    twisted,
)
from envelopelab.features.scene import designed_display
from envelopelab.project.gore_design import standard_gore_design
from envelopelab.solvers.model import OperatingConditions
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.primitives import SPHERE_RADIUS, sphere_envelope

SPHERE = sphere_envelope()
EQUATOR = 0.5 * math.pi * SPHERE_RADIUS - SPHERE.profile.s[0] - 0.15 * math.pi * SPHERE_RADIUS
HOT = OperatingConditions.hot_air(
    celsius_to_kelvin(100.0), mouth_height=float(SPHERE.profile.z[0]), self_weight=False
)


def _length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _dome(**layout: object) -> Dome:
    return Dome("d", Placement(2, EQUATOR), 0.8, 0.9, gores=8, cap_radius=0.15, **layout)  # type: ignore[arg-type]


def _angles(design: PrimitiveDesign, points: np.ndarray) -> np.ndarray:
    rel = points - design.base_point
    out: np.ndarray = np.arctan2(rel @ design.b2, rel @ design.b1)
    return out


def _errors(design: object) -> list[str]:
    return [c.name for c in design.checks if c.severity == "error"]  # type: ignore[attr-defined]


def _wrap(a: np.ndarray) -> np.ndarray:
    return (np.asarray(a) + math.pi) % (2.0 * math.pi) - math.pi


def test_crown_angles_default_to_the_rim_and_follow_turn_and_widths() -> None:
    plain = _dome(panel_widths=(2, 1, 1, 1, 1, 1, 1, 1))
    assert np.array_equal(crown_seam_angles(plain), seam_angles(plain))
    assert not twisted(plain)
    equal = dataclasses.replace(plain, crown_widths=(1,) * 8)
    want = seam_angles(_dome())
    assert _wrap(crown_seam_angles(equal) - want) == pytest.approx(np.zeros(9), abs=1e-12)
    turned = _dome(crown_offset=0.3)
    assert crown_seam_angles(turned) - seam_angles(turned) == pytest.approx(np.full(9, 0.3))
    # On the branch nearest the rim: a turn of nearly a whole circle is a small one back.
    back = _dome(crown_offset=2.0 * math.pi - 0.1)
    assert crown_seam_angles(back) - seam_angles(back) == pytest.approx(np.full(9, -0.1))
    with pytest.raises(PrimitiveError):
        _dome(crown_widths=(1, 1)).validate()


@pytest.mark.parametrize(
    "layout",
    [
        {"crown_offset": math.radians(20)},
        {"panel_widths": (2, 1, 1, 1, 1, 1, 1, 1), "crown_widths": (1,) * 8},
    ],
)
def test_the_seams_leave_the_rim_where_they_did_and_meet_the_crown_at_its_angles(
    layout: dict[str, object],
) -> None:
    prim = _dome(**layout)
    plain = design_primitive(dataclasses.replace(prim, crown_offset=None, crown_widths=()), SPHERE)
    d = design_primitive(prim, SPHERE)
    psi = seam_angles(prim)[:-1]
    skin = d._skin
    rim = _angles(d, skin.at(np.zeros(len(psi)), psi))
    assert _wrap(rim - psi) == pytest.approx(np.zeros(len(psi)), abs=1e-9)
    top = _angles(d, skin.at(np.ones(len(psi)), psi))
    assert _wrap(top - crown_seam_angles(prim)[:-1]) == pytest.approx(np.zeros(len(psi)), abs=1e-6)
    # The footprint, marks and attachment are the plain shape's: the rim did not move.
    assert d.footprint_points == pytest.approx(plain.footprint_points)
    assert [m.piece_xy for m in d.marks] != [] and len(d.marks) == len(plain.marks)
    # The pattern is sound: seams, rim and the cap's edge match.
    assert _errors(d) == []
    cap = next(c for c in d.pieces if c.role == "tip")
    assert _length(cap.edges["top"]) == pytest.approx(2 * math.pi * 0.15, rel=1e-3)
    # The cap's seam points sit at the crown angles.
    ends = np.array(cap.seam_points)
    assert _wrap(np.arctan2(ends[:, 1], ends[:, 0]) - crown_seam_angles(prim)[:-1]) == (
        pytest.approx(np.zeros(len(psi)), abs=1e-6)
    )


def test_a_moved_cap_is_flat_off_the_tip_and_sewn_round_by_the_gores() -> None:
    prim = _dome(cap_shift=0.08, cap_direction=0.5)
    d = design_primitive(prim, SPHERE)
    assert _errors(d) == []
    skin = d._skin
    origin, _e1, _e2, normal = skin.cap_frame()
    # The cap's centre moved off the axis, towards cap_direction.
    rel = origin - d.base_point
    off = rel - (rel @ d.axis) * d.axis
    assert np.linalg.norm(off) > 0.03
    assert math.atan2(off @ d.b2, off @ d.b1) == pytest.approx(0.5, abs=0.05)
    # Every gore ends on the cap's plane.
    psi = np.linspace(0.0, 2.0 * math.pi, 73)
    edge = skin.at(np.ones(len(psi)), psi)
    assert (edge - origin) @ normal == pytest.approx(np.zeros(len(psi)), abs=1e-6)
    # The gores' tops are as long as the flat cap's edge they are sewn to.
    m = prim.pieces
    tops = sum(_length(c.edges["top"]) for c in d.pieces[:m])
    cap = next(c for c in d.pieces if c.role == "tip")
    assert tops == pytest.approx(_length(cap.edges["top"]), abs=1e-3)
    assert cap.flat_area == pytest.approx(cap.surface_area)
    # A sphere's cap moved round its surface is the same size.
    centred = design_primitive(_dome(), SPHERE)
    centred_cap = next(c for c in centred.pieces if c.role == "tip")
    assert cap.surface_area == pytest.approx(centred_cap.surface_area, rel=0.05)


def test_a_cap_cannot_move_off_the_tip_altogether() -> None:
    with pytest.raises(PrimitiveError, match="no longer covers the tip"):
        design_primitive(_dome(cap_shift=0.4), SPHERE)
    with pytest.raises(PrimitiveError, match="only a cap"):
        dataclasses.replace(_dome(cap_shift=0.05), cap_radius=0.0).validate()


def test_crown_layouts_build_one_sewn_skin_for_the_simulation() -> None:
    prim = _dome(crown_offset=0.4, cap_shift=0.06, cap_direction=1.0, splits=(0.45,))
    d = design_primitive(prim, SPHERE, feed_hole_radius=0.2)
    assert _errors(d) == []
    spec = primitive_appendage(d, 0.15, load_tape=GENERIC_TAPE, rim_tape=GENERIC_TAPE)
    am = build_appendage(spec, HOT, {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC})
    skin = am.model.triangles[am.skin_triangles]
    edges = np.sort(np.concatenate([skin[:, [0, 1]], skin[:, [1, 2]], skin[:, [2, 0]]]), axis=1)
    uniq, count = np.unique(edges, axis=0, return_counts=True)
    free = uniq[count == 1]
    assert np.isin(free, am.rim_nodes).all() and len(free) == len(am.rim_nodes)
    rest = am.model.rest_uv[am.skin_triangles]
    area = 0.5 * (
        (rest[:, 1, 0] - rest[:, 0, 0]) * (rest[:, 2, 1] - rest[:, 0, 1])
        - (rest[:, 1, 1] - rest[:, 0, 1]) * (rest[:, 2, 0] - rest[:, 0, 0])
    )
    assert np.all(area > 0.0)
    assert area.sum() == pytest.approx(sum(p.flat_area for p in d.pieces), rel=0.02)
    shown = designed_display(d)
    assert len(shown.seams) == 8 + 1 + 1  # gore seams, the split, the cap's edge


def test_revolved_and_tube_shapes_take_crown_layouts() -> None:
    bulb = Revolved(
        "r",
        Placement(2, EQUATOR),
        ((0.6, 0.0), (0.7, 0.5), (0.4, 1.0), (0.0, 1.2)),
        10,
        cap_radius=0.15,
        cap_shift=0.05,
        crown_offset=0.2,
    )
    d = design_primitive(bulb, SPHERE)
    assert _errors(d) == []
    horn = Tube("t", Placement(2, EQUATOR), 0.4, 0.2, 1.0, 6, crown_offset=math.radians(30))
    d = design_primitive(horn, SPHERE)
    assert _errors(d) == []
    psi = seam_angles(horn)[:-1]
    top = _angles(d, d._skin.at(np.ones(len(psi)), psi))
    assert _wrap(top - psi - math.radians(30)) == pytest.approx(np.zeros(6), abs=1e-6)


def test_a_build_pack_with_crown_layouts_passes_the_checks(tmp_path: Path) -> None:
    design = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
    surface = EnvelopeSurface.from_design(design)
    ear = Dome(
        "ear",
        Placement(3, 12.0),
        1.0,
        1.2,
        gores=8,
        cap_radius=0.2,
        crown_widths=(1, 2) * 4,
        cap_shift=0.1,
        splits=(0.4,),
    )
    export_build_pack(design, [design_primitive(ear, surface)], tmp_path)
    assert check_pack(tmp_path) == []


# -- project shapes -------------------------------------------------------------------------


def test_crown_layout_of_a_shape_reaches_its_primitive_and_survives_save_and_load() -> None:
    from envelopelab.project import edits
    from envelopelab.project.model import dump_project, load_project_text
    from envelopelab.project.session import ProjectSession
    from envelopelab.project.shapes import DomeShape, default_shape, to_primitive

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
    session = ProjectSession.open(fixture)
    spec = default_shape("dome", session.design, "Ear")
    assert isinstance(spec, DomeShape)
    spec = spec.model_copy(
        update={
            "gores": 6,
            "crown_seam_offset_deg": 15.0,
            "crown_panel_widths": [1.0, 2.0, 1.0, 2.0, 1.0, 2.0],
            "cap_shift": 0.05,
            "cap_direction_deg": 30.0,
        }
    )
    spec = DomeShape.model_validate(spec.model_dump())
    prim = to_primitive(spec)
    assert isinstance(prim, Dome)
    assert prim.crown_offset == pytest.approx(math.radians(15.0))
    assert prim.crown_widths == (1.0, 2.0, 1.0, 2.0, 1.0, 2.0)
    assert prim.cap_shift == 0.05 and prim.cap_direction == pytest.approx(math.radians(30))
    edits.add_shape(session, spec)
    back = load_project_text(dump_project(session.project))
    assert back.state.shapes == session.state.shapes
    # Shapes without a crown layout leave the keys at their defaults.
    plain = DomeShape.model_validate(default_shape("dome", session.design, "P").model_dump())
    assert plain.crown_seam_offset_deg is None and plain.cap_shift == 0.0
    assert not twisted(to_primitive(plain))


@pytest.mark.parametrize(
    ("kind", "update", "message"),
    [
        ("dome", {"crown_panel_widths": [1.0, 2.0]}, "2 widths for"),
        ("tube", {"cap_shift": 0.05}, "tip disc"),
        ("dome", {"cap_shift": -0.1}, "greater than or equal to 0"),
    ],
)
def test_crown_layouts_out_of_range_are_refused(
    kind: str, update: dict[str, object], message: str
) -> None:
    from envelopelab.project.session import ProjectSession
    from envelopelab.project.shapes import default_shape

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
    session = ProjectSession.open(fixture)
    spec = default_shape(kind, session.design, "S")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=message):
        type(spec).model_validate({**spec.model_dump(), **update})


def test_a_mirror_twin_mirrors_the_crown_layout() -> None:
    from envelopelab.project.session import ProjectSession
    from envelopelab.project.shape_groups import mirrored
    from envelopelab.project.shapes import DomeShape, default_shape

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
    session = ProjectSession.open(fixture)
    spec = DomeShape.model_validate(
        {
            **default_shape("dome", session.design, "E").model_dump(),
            "gores": 4,
            "crown_seam_offset_deg": 20.0,
            "crown_panel_widths": [1.0, 2.0, 3.0, 4.0],
            "cap_direction_deg": 40.0,
        }
    )
    twin = DomeShape.model_validate(mirrored(spec, 4.0, 8))
    assert twin.crown_seam_offset_deg == pytest.approx(-20.0)
    assert twin.crown_panel_widths == [1.0, 4.0, 3.0, 2.0]
    assert twin.cap_direction_deg == pytest.approx(-40.0)
