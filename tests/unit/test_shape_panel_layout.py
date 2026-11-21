"""Panel layout of special shapes: seam turn, panel widths and horizontal splits."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.export.build_pack import export_build_pack, primitive_seam_pairs
from envelopelab.export.qa import check_pack
from envelopelab.features.builder import build_appendage
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    FreeformShape,
    Placement,
    PrimitiveError,
    Tube,
    design_primitive,
    primitive_appendage,
    seam_angles,
)
from envelopelab.features.scene import designed_display
from envelopelab.project import edits
from envelopelab.project.gore_design import standard_gore_design
from envelopelab.project.model import dump_project, load_project_text
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import (
    DomeShape,
    MeshShape,
    ShapePlacement,
    auto_cap_diameter,
    default_shape,
    mesh_shape,
    to_primitive,
)
from envelopelab.solvers.model import OperatingConditions
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.primitives import SPHERE_RADIUS, ellipsoid_mesh, sphere_envelope

SPHERE = sphere_envelope()
EQUATOR = 0.5 * math.pi * SPHERE_RADIUS - SPHERE.profile.s[0] - 0.15 * math.pi * SPHERE_RADIUS
HOT = OperatingConditions.hot_air(
    celsius_to_kelvin(100.0), mouth_height=float(SPHERE.profile.z[0]), self_weight=False
)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


def _length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _dome(**layout: object) -> Dome:
    return Dome("d", Placement(2, EQUATOR), 0.8, 0.6, gores=8, **layout)  # type: ignore[arg-type]


# -- seams round the axis -----------------------------------------------------------------


def test_equal_seams_are_unchanged_and_turn_with_the_offset() -> None:
    m = 8
    old = 2.0 * math.pi * np.arange(m + 1) / m - math.pi / m
    assert np.array_equal(seam_angles(_dome()), old)
    turned = seam_angles(_dome(seam_offset=0.3))
    assert np.allclose(turned, old + 0.3, atol=1e-15)


@given(st.lists(st.floats(0.2, 5.0), min_size=3, max_size=12), st.floats(-math.pi, math.pi))
@settings(max_examples=50, deadline=None)
def test_widths_split_the_turn_in_proportion(widths: list[float], offset: float) -> None:
    prim = Dome(
        "d",
        Placement(2, EQUATOR),
        0.8,
        0.6,
        gores=len(widths),
        seam_offset=offset,
        panel_widths=tuple(widths),
    )
    seams = seam_angles(prim)
    assert seams[-1] - seams[0] == pytest.approx(2.0 * math.pi, abs=1e-12)
    assert np.allclose(np.diff(seams), 2.0 * math.pi * np.asarray(widths) / sum(widths))
    # Piece 1 is centred on the seam turn.
    assert 0.5 * (seams[0] + seams[1]) == pytest.approx(offset)


@pytest.mark.parametrize(
    ("layout", "message"),
    [
        ({"panel_widths": (1.0, 2.0)}, "2 panel widths given for 8 pieces"),
        ({"panel_widths": (1.0,) * 7 + (-1.0,)}, "must be positive"),
        ({"panel_widths": (1.0,) * 7 + (1e-4,)}, "narrower than one degree"),
        ({"splits": (0.5, 0.3)}, "must increase"),
        ({"splits": (0.995,)}, "must increase"),
    ],
)
def test_layouts_that_cannot_be_cut_are_refused(layout: dict[str, object], message: str) -> None:
    with pytest.raises(PrimitiveError, match=message):
        _dome(**layout).validate()


def test_turning_the_seams_moves_the_pieces_not_the_cloth() -> None:
    plain = design_primitive(_dome(), SPHERE)
    turned = design_primitive(_dome(seam_offset=math.radians(20)), SPHERE)
    assert turned.footprint_length == pytest.approx(plain.footprint_length, rel=1e-6)
    total = sum(p.flat_area for p in plain.pieces)
    assert sum(p.flat_area for p in turned.pieces) == pytest.approx(total, rel=1e-3)
    assert all(c.passed or c.name == "area distortion" for c in turned.checks)
    # Match marks stay 2 pi / n apart and each lies on the piece it names.
    assert [m.phi_deg for m in turned.marks] == pytest.approx([m.phi_deg for m in plain.marks])
    seams = np.degrees(seam_angles(turned.primitive))
    for mark in turned.marks:
        k = int(mark.piece.split("G")[1]) - 1
        rel = (mark.phi_deg - seams[0]) % 360.0
        assert seams[k] - seams[0] - 1e-6 <= rel <= seams[k + 1] - seams[0] + 1e-6


def test_wider_panels_get_proportionally_more_rim() -> None:
    widths = (1.0, 3.0, 1.0, 3.0, 1.0, 3.0, 1.0, 3.0)
    d = design_primitive(_dome(panel_widths=widths), SPHERE)
    rims = np.array([_length(p.rim) for p in d.pieces if p.rim is not None])
    assert rims.sum() == pytest.approx(d.footprint_length, abs=1e-3)
    # The footprint is close to a circle round the axis on the sphere.
    assert rims / rims.sum() == pytest.approx(np.asarray(widths) / sum(widths), rel=0.02)
    assert all(c.severity != "error" for c in d.checks)


# -- horizontal splits ----------------------------------------------------------------------


def test_splits_cut_every_gore_into_tiers_sewn_edge_to_edge() -> None:
    d = design_primitive(_dome(splits=(0.35, 0.7), cap_radius=0.1), SPHERE)
    panels = [p for p in d.pieces if p.role == "panel"]
    assert [p.label for p in panels[:2]] == ["d-G1A", "d-G2A"]
    assert [p.label for p in panels[-1:]] == ["d-G8C"]
    assert [p.tier for p in panels] == [0] * 8 + [1] * 8 + [2] * 8
    assert d.pieces[-1].label == "d-TIP" and d.pieces[-1].role == "tip"
    # Only the first tier has a rim; the others are sewn to the tier below.
    assert all((p.rim is not None) == (p.tier == 0) for p in panels)
    assert all("bottom" in p.edges for p in panels if p.tier > 0)
    for k in range(8):
        for i in range(2):
            lower, upper = panels[8 * i + k], panels[8 * (i + 1) + k]
            assert _length(lower.edges["top"]) == pytest.approx(
                _length(upper.edges["bottom"]), abs=1e-6
            )
    check = {c.name: c for c in d.checks}
    assert check["split seam match"].passed and check["skin seam match"].passed
    assert check["rim length"].passed
    # Marks are on the rim, so only on the first tier's pieces.
    assert {m.piece[-1] for m in d.marks} == {"A"}


def test_splitting_a_frustum_keeps_its_exact_development() -> None:
    whole = design_primitive(Tube("t", Placement(2, EQUATOR), 0.6, 0.2, 1.5), SPHERE)
    split = design_primitive(Tube("t", Placement(2, EQUATOR), 0.6, 0.2, 1.5, splits=(0.4,)), SPHERE)
    area = sum(p.flat_area for p in whole.pieces)
    assert sum(p.flat_area for p in split.pieces) == pytest.approx(area, rel=2e-4)
    assert {c.name: c for c in split.checks}["area distortion"].passed


def test_a_split_below_the_footprint_is_refused() -> None:
    # Leant 35 deg, the footprint climbs to 22 % of the tube's length on its high side.
    lean = Placement(2, EQUATOR, lean_deg=35.0)
    with pytest.raises(PrimitiveError, match="lowest horizontal split .* above 24%"):
        design_primitive(Tube("t", lean, 0.6, 0.2, 1.5, splits=(0.2,)), SPHERE)
    design_primitive(Tube("t", lean, 0.6, 0.2, 1.5, splits=(0.3,)), SPHERE)


def test_split_seams_are_sewn_pairs_of_the_build_pack(tmp_path: Path) -> None:
    d = design_primitive(_dome(splits=(0.5,)), SPHERE)
    pairs = primitive_seam_pairs(d)
    split = [p for p in pairs if p.a[0][1] == "top" and p.b[0][1] == "bottom"]
    assert len(split) == 8
    assert {(p.a[0][0], p.b[0][0]) for p in split} >= {("d-G3A", "d-G3B")}
    design = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
    surface = EnvelopeSurface.from_design(design)
    ear = Dome("ear", Placement(3, 12.0), 1.0, 1.2, gores=6, splits=(0.4,), panel_widths=(1, 2) * 3)
    export_build_pack(design, [design_primitive(ear, surface)], tmp_path)
    assert check_pack(tmp_path) == []
    index = json.loads((tmp_path / "cad" / "index.json").read_text(encoding="utf-8"))
    assert "cad/ear-G2B.dxf" in {s["file"] for s in index["sheets"]}


def test_split_skin_is_one_sewn_surface() -> None:
    prim = _dome(splits=(0.45,), panel_widths=(1, 2) * 4, seam_offset=0.2)
    d = design_primitive(prim, SPHERE, feed_hole_radius=0.2)
    spec = primitive_appendage(d, 0.15, load_tape=GENERIC_TAPE, rim_tape=GENERIC_TAPE)
    am = build_appendage(spec, HOT, {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC})
    skin = am.model.triangles[am.skin_triangles]
    edges = np.sort(np.concatenate([skin[:, [0, 1]], skin[:, [1, 2]], skin[:, [2, 0]]]), axis=1)
    uniq, count = np.unique(edges, axis=0, return_counts=True)
    free = uniq[count == 1]
    assert np.isin(free, am.rim_nodes).all() and len(free) == len(am.rim_nodes)
    names = {s.name for s in am.model.seams}
    assert {"d:split 1", "d:seam 1", "d:seam 8"} <= names
    rest = am.model.rest_uv[am.skin_triangles]
    area = 0.5 * (
        (rest[:, 1, 0] - rest[:, 0, 0]) * (rest[:, 2, 1] - rest[:, 0, 1])
        - (rest[:, 1, 1] - rest[:, 0, 1]) * (rest[:, 2, 0] - rest[:, 0, 0])
    )
    assert np.all(area > 0.0)
    assert area.sum() == pytest.approx(sum(p.flat_area for p in d.pieces), rel=0.02)
    shown = designed_display(d)
    assert len(shown.seams) == 8 + 1  # the gore seams and the split circle


def test_mesh_shapes_turn_and_widen_their_panels() -> None:
    mesh = ellipsoid_mesh(0.8, 0.8, 0.7, -0.1)
    prim = FreeformShape(
        "m", Placement(2, EQUATOR), mesh, panels=6, panel_widths=(1, 2) * 3, seam_offset=0.3
    )
    d = design_primitive(prim, SPHERE)
    rims = np.array([_length(p.rim) for p in d.pieces if p.rim is not None])
    assert rims / rims.sum() == pytest.approx(np.repeat([[1, 2]], 3, 0).ravel() / 9, rel=0.05)
    assert not any(c.severity == "error" for c in d.checks)


# -- project shapes -------------------------------------------------------------------------


def test_shape_layout_reaches_the_primitive_and_survives_save_and_load() -> None:
    session = ProjectSession.open(FIXTURE)
    spec = default_shape("dome", session.design, "Nose")
    assert isinstance(spec, DomeShape)
    spec = spec.model_copy(
        update={
            "gores": 4,
            "seam_offset_deg": 45.0,
            "panel_widths": [1.0, 2.0, 1.0, 2.0],
            "splits": [0.5],
        }
    )
    prim = to_primitive(DomeShape.model_validate(spec.model_dump()))
    assert prim.seam_offset == pytest.approx(math.pi / 4)
    assert prim.panel_widths == (1.0, 2.0, 1.0, 2.0) and prim.splits == (0.5,)
    edits.add_shape(session, DomeShape.model_validate(spec.model_dump()))
    back = load_project_text(dump_project(session.project))
    assert back.state.shapes == session.state.shapes
    # The narrowest top sets an automatic cap.
    assert auto_cap_diameter(back.state.shapes[0]) > auto_cap_diameter(
        back.state.shapes[0].model_copy(update={"panel_widths": []})
    )


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"panel_widths": [1.0, 2.0]}, "2 widths for 16"),
        ({"splits": [0.6, 0.4]}, "must increase"),
        ({"splits": [1.2]}, "must increase"),
        ({"seam_offset_deg": 200.0}, "less than or equal to 180"),
    ],
)
def test_invalid_shape_layouts_are_refused(update: dict[str, object], message: str) -> None:
    session = ProjectSession.open(FIXTURE)
    data = default_shape("dome", session.design, "Nose").model_dump() | update
    with pytest.raises(ValueError, match=message):
        DomeShape.model_validate(data)


def test_mesh_shapes_cannot_be_split_across() -> None:
    mesh = ellipsoid_mesh(0.2, 0.15, 0.25, -0.05, rings=8, segments=12)
    spec = mesh_shape(
        "Blob", mesh.vertices, mesh.triangles, ShapePlacement(gore=3, tape_position=4)
    )
    with pytest.raises(ValueError, match="cannot be split across"):
        MeshShape.model_validate(spec.model_dump() | {"splits": [0.5]})


def test_old_project_shapes_read_with_the_default_layout() -> None:
    session = ProjectSession.open(FIXTURE)
    edits.add_shape(session, default_shape("dome", session.design, "Nose"))
    data = json.loads(dump_project(session.project))
    data["format_version"] = 3
    for key in ("seam_offset_deg", "panel_widths", "splits"):
        del data["state"]["shapes"][0][key]
    back = load_project_text(json.dumps(data))
    shape = back.state.shapes[0]
    assert (shape.seam_offset_deg, shape.panel_widths, shape.splits) == (0.0, [], [])
    assert back.format_version == 8
