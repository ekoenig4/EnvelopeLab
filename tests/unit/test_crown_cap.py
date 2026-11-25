"""Crown caps shaped by an outline seen from above (ADR-0054)."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.export.build_pack import export_build_pack
from envelopelab.export.qa import check_pack
from envelopelab.features.builder import build_appendage
from envelopelab.features.crown import CrownShape
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    PrimitiveError,
    Revolved,
    design_primitive,
    preview_primitive,
    primitive_appendage,
)
from envelopelab.features.scene import designed_display
from envelopelab.project.gore_design import standard_gore_design
from envelopelab.project.model import dump_project, load_project_text
from envelopelab.project.session import ProjectSession
from envelopelab.project.shape_groups import mirrored
from envelopelab.project.shapes import (
    DomeShape,
    MeshShape,
    ShapePlacement,
    default_shape,
    envelope_surface,
    mesh_shape,
    shape_design,
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
RC = 0.15
SHAPES = {
    "ellipse": CrownShape("ellipse", width=2.4 * RC, length=1.6 * RC, turn_deg=20.0),
    "polygon": CrownShape("polygon", points=((RC, 0.0), (0.0, 1.2 * RC), (-RC, 0.0), (0.0, -RC))),
    "smooth": CrownShape(
        "polygon", points=((RC, 0.0), (0.0, 1.2 * RC), (-RC, 0.0), (0.0, -RC)), smooth=True
    ),
    "footprint": CrownShape("footprint", size=2.0 * RC),
    "outline": CrownShape(
        "outline", size=2.0 * RC, turn_deg=10.0, points=((0, 0), (40, 0), (40, 25), (0, 25))
    ),
}


def _dome(crown: CrownShape | None, **values: Any) -> Dome:
    return Dome("d", Placement(2, EQUATOR), 0.8, 0.9, gores=8, cap_radius=RC, crown=crown, **values)


def _errors(design: Any) -> list[str]:
    return [c.name for c in design.checks if c.severity == "error" and not c.passed]


def _length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


@pytest.mark.parametrize("kind", list(SHAPES))
def test_the_cap_edge_follows_the_outline_seen_from_above(kind: str) -> None:
    d = design_primitive(_dome(SHAPES[kind]), SPHERE)
    assert _errors(d) == []
    skin = d._skin
    crown = skin._crown
    # The top of every gore is on the outline's prism round the meeting point.
    phi = np.linspace(0.0, 2.0 * math.pi, 50, endpoint=False)
    edge = skin.at(np.ones(len(phi)), phi)
    q = skin.plan(edge) - crown.centre
    # Within 10 um (the edge is found on 720 meridians and interpolated between them).
    assert crown.outline.inside(q[:, 0], q[:, 1]) == pytest.approx(np.zeros(len(phi)), abs=1e-5)
    # The cap is cut from the skin, its edge kept at its sewn length.
    tip = next(p for p in d.pieces if p.role == "tip")
    tops = sum(_length(p.edges["top"]) for p in d.pieces if p.role != "tip")
    assert _length(tip.edges["top"]) == pytest.approx(tops, abs=3e-3)
    assert len(tip.seam_points) == 8


def test_an_ellipse_cap_is_wider_across_than_up() -> None:
    d = design_primitive(_dome(CrownShape("ellipse", width=0.36, length=0.2)), SPHERE)
    skin = d._skin
    phi = np.linspace(0.0, 2.0 * math.pi, 400, endpoint=False)
    q = skin.plan(skin.at(np.ones(len(phi)), phi)) - skin._crown.centre
    assert np.ptp(q[:, 0]) == pytest.approx(0.36, rel=2e-3)
    assert np.ptp(q[:, 1]) == pytest.approx(0.2, rel=2e-3)


def test_a_shaped_cap_builds_one_sewn_skin_for_the_simulation() -> None:
    d = design_primitive(_dome(SHAPES["ellipse"], splits=(0.45,)), SPHERE, feed_hole_radius=0.2)
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
    assert np.any(shown.piece == 8)  # the cap is drawn


def test_a_moved_and_turned_layout_takes_a_shaped_cap() -> None:
    d = design_primitive(
        _dome(SHAPES["smooth"], cap_shift=0.05, cap_direction=1.0, crown_offset=0.3), SPHERE
    )
    assert _errors(d) == []
    assert np.linalg.norm(d._skin._crown.centre) > 0.03  # off the axis


def test_a_revolved_shape_takes_a_shaped_cap_and_previews_it() -> None:
    bulb = Revolved(
        "r",
        Placement(2, EQUATOR),
        ((0.6, 0.0), (0.7, 0.5), (0.4, 1.0), (0.0, 1.2)),
        10,
        cap_radius=0.15,
        crown=SHAPES["polygon"],
    )
    d = design_primitive(bulb, SPHERE)
    assert _errors(d) == []
    preview = preview_primitive(bulb, SPHERE)
    a = designed_display(preview, rows=14, per_piece=3)
    b = designed_display(d, rows=14, per_piece=3)
    assert a.points.shape == b.points.shape


def test_outlines_that_do_not_fit_are_refused() -> None:
    with pytest.raises(PrimitiveError, match="footprint"):
        design_primitive(_dome(CrownShape("ellipse", width=1.8, length=1.8)), SPHERE)
    with pytest.raises(PrimitiveError, match="tip"):
        small = CrownShape("ellipse", width=0.04, length=0.04)
        design_primitive(_dome(small, cap_shift=0.2), SPHERE)
    with pytest.raises(PrimitiveError, match="cap"):
        design_primitive(dataclasses.replace(_dome(SHAPES["ellipse"]), cap_radius=0.0), SPHERE)


def test_a_build_pack_with_a_shaped_cap_passes_the_checks(tmp_path: Path) -> None:
    design = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
    surface = EnvelopeSurface.from_design(design)
    ear = Dome(
        "ear",
        Placement(3, 12.0),
        1.0,
        1.2,
        gores=8,
        cap_radius=0.2,
        crown=CrownShape("ellipse", width=0.5, length=0.35),
    )
    export_build_pack(design, [design_primitive(ear, surface)], tmp_path)
    assert check_pack(tmp_path) == []


# -- mesh shapes and project shapes -----------------------------------------------------

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
SESSION = ProjectSession.open(FIXTURE)


def test_a_mesh_shape_s_cap_is_cut_by_the_outline() -> None:
    mesh = ellipsoid_mesh(0.3, 0.25, 0.35, -0.05, rings=16, segments=24)
    spec = mesh_shape(
        "Blob", mesh.vertices, mesh.triangles, ShapePlacement(gore=3, tape_position=4.0)
    )
    spec = MeshShape.model_validate(
        {**spec.model_dump(), "crown_shape": {"kind": "ellipse", "width": 0.36, "length": 0.22}}
    )
    surface = envelope_surface(SESSION.design, SESSION.patterns)
    placed = shape_design(spec, surface)
    skin = placed._skin
    assert skin.cap is not None
    # Every cap node lies inside the ellipse round the meeting point (seen from above).
    rel = skin.cap.x - skin.base
    across, up = -(rel @ skin.b2), rel @ skin.b1
    assert np.all((across / 0.18) ** 2 + (up / 0.11) ** 2 <= 1.0 + 1e-6)


def _dome_spec(**crown: Any) -> DomeShape:
    spec = default_shape("dome", SESSION.design, "X")
    assert isinstance(spec, DomeShape)
    return DomeShape.model_validate({**spec.model_dump(), "crown_shape": crown})


def test_a_crown_shape_reaches_the_primitive_and_survives_save_and_load() -> None:
    spec = _dome_spec(kind="footprint", turn_deg=15.0)
    prim: Any = to_primitive(spec)
    assert prim.crown.kind == "footprint" and prim.crown.size == pytest.approx(2 * prim.cap_radius)
    session = ProjectSession.open(FIXTURE)
    project = session.project.model_copy(
        update={"state": session.state.model_copy(update={"shapes": [spec]})}
    )
    back = load_project_text(dump_project(project))
    assert back.format_version == 11 and back.state.shapes[0].crown_shape == spec.crown_shape
    with pytest.raises(ValueError):
        _dome_spec(kind="ellipse", width=0.2)  # no length
    with pytest.raises(ValueError):
        _dome_spec(kind="polygon", points=[[0.1, 0.0], [0.0, 0.1]])


def test_a_mirror_twin_mirrors_the_crown_outline() -> None:
    spec = _dome_spec(kind="polygon", points=[[0.05, 0.0], [0.0, 0.08], [-0.03, -0.02]])
    data = mirrored(spec, 4.0, SESSION.design.gores.count)  # type: ignore[union-attr]
    assert data["crown_shape"]["points"] == [[-0.05, 0.0], [-0.0, 0.08], [0.03, -0.02]]


def test_shape_files_give_crown_shapes_with_units_or_an_outline_file(tmp_path: Path) -> None:
    from envelopelab.io.shape_file import ShapeFileError, _crown_shape

    ellipse = _crown_shape(
        {"kind": "ellipse", "width": "400 mm", "length": "0.25 m", "turn_deg": 15}, "s", tmp_path
    )
    assert ellipse == {"kind": "ellipse", "width": 0.4, "length": 0.25, "turn_deg": 15}
    corners = _crown_shape(
        {"kind": "polygon", "unit": "mm", "points": [[100, 0], [0, 80], [-100, 0]]}, "s", tmp_path
    )
    assert corners["points"] == [(0.1, 0.0), (0.0, 0.08), (-0.1, 0.0)]
    (tmp_path / "crown.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><polygon points="0,0 30,0 15,20"/></svg>'
    )
    read = _crown_shape({"kind": "outline", "file": "crown.svg"}, "s", tmp_path)
    assert len(read["points"]) == 3 and read["source"] == "crown.svg"
    with pytest.raises(ShapeFileError):
        _crown_shape({"kind": "ellipse", "colour": "red"}, "s", tmp_path)
