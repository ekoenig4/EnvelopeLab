"""Shape groups: several special shapes moved, mirrored and exported as one object."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.export.build_pack import export_build_pack, primitive_sheets
from envelopelab.export.qa import check_pack
from envelopelab.features.primitives import seam_angles
from envelopelab.project import edits
from envelopelab.project.model import dump_project, load_project_text
from envelopelab.project.session import ProjectSession
from envelopelab.project.shape_groups import group_members, group_names, mirrored
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
from envelopelab.validation.primitives import ellipsoid_mesh

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


@pytest.fixture
def session() -> ProjectSession:
    return ProjectSession.open(FIXTURE)


def _head(s: ProjectSession) -> None:
    """A head: a dome on gore 3 with an ear either side and a mesh nose."""
    dome = default_shape("dome", s.design, "Face")
    assert isinstance(dome, DomeShape)
    edits.add_shape(
        s, dome.model_copy(update={"placement": ShapePlacement(gore=3, tape_position=6.0)})
    )
    ear = dome.model_copy(
        update={
            "name": "Ear",
            "placement": ShapePlacement(
                gore=4, tape_position=6.8, across=0.2, lean_deg=20.0, lean_toward_deg=60.0
            ),
            "gores": 6,
            "seam_offset_deg": 15.0,
            "panel_widths": [3.0, 1.0, 2.0, 1.0, 1.0, 1.0],
        }
    )
    edits.add_shape(s, DomeShape.model_validate(ear.model_dump()))
    mesh = ellipsoid_mesh(0.2, 0.12, 0.25, -0.05, rings=8, segments=12)
    nose = mesh_shape(
        "Nose", mesh.vertices, mesh.triangles, ShapePlacement(gore=3, tape_position=5.2)
    )
    edits.add_shape(s, nose)
    assert edits.set_shape_group(s, ["Face", "Ear", "Nose"], "Head")


def _gore_count(s: ProjectSession) -> int:
    assert s.design.gores is not None
    return s.design.gores.count


def test_group_is_one_undo_step_and_survives_save_and_load(session: ProjectSession) -> None:
    _head(session)
    assert group_names(session.state.shapes) == ["Head"]
    assert [m.name for m in group_members(session.state.shapes, "Head")] == ["Face", "Ear", "Nose"]
    back = load_project_text(dump_project(session.project))
    assert back.state.shapes == session.state.shapes
    session.undo()
    assert group_names(session.state.shapes) == []
    session.redo()
    assert edits.rename_shape_group(session, "Head", "Bear head")
    assert group_names(session.state.shapes) == ["Bear head"]
    assert edits.set_shape_group(session, ["Ear"], None)
    assert [m.name for m in group_members(session.state.shapes, "Bear head")] == ["Face", "Nose"]


def test_group_names_follow_the_shape_name_rules(session: ProjectSession) -> None:
    _head(session)
    with pytest.raises(ValueError):
        edits.set_shape_group(session, ["Ear"], "bad/name")
    with pytest.raises(KeyError):
        edits.set_shape_group(session, ["Tail"], "Head")
    with pytest.raises(ValueError, match="exists"):
        edits.rename_shape_group(session, "Head", "Head")


def test_moving_a_group_turns_and_shifts_every_member_and_hole(session: ProjectSession) -> None:
    _head(session)
    edits.update_shape(
        session,
        "Face",
        {"feed_holes": [{"gore": 3, "tape_position": 6.1, "across": 0.1, "radius": 0.05}]},
    )
    before = {s.name: s for s in session.state.shapes}
    assert edits.move_shape_group(session, "Head", 2.5, -0.4)
    after = {s.name: s for s in session.state.shapes}
    n = _gore_count(session)
    for name in before:
        a, b = before[name].placement, after[name].placement
        g_a = a.gore - 0.5 + a.across
        g_b = b.gore - 0.5 + b.across
        assert (g_b - g_a) % n == pytest.approx(2.5)
        assert b.tape_position == pytest.approx(a.tape_position - 0.4)
        assert (b.lean_deg, b.lean_toward_deg) == (a.lean_deg, a.lean_toward_deg)
    hole = after["Face"].feed_holes[0]
    assert hole.gore == 6
    assert hole.across == pytest.approx(-0.4)
    assert hole.tape_position == pytest.approx(5.7)
    session.undo()
    assert session.state.shapes == list(before.values())


def test_a_group_that_would_leave_the_envelope_does_not_move(session: ProjectSession) -> None:
    _head(session)
    before = list(session.state.shapes)
    with pytest.raises(ValueError, match="leave the envelope"):
        edits.move_shape_group(session, "Head", 0.0, -6.0)
    assert session.state.shapes == before


def test_turning_a_group_keeps_its_shapes_on_a_surface_of_revolution(
    session: ProjectSession,
) -> None:
    """A whole number of gores is a symmetry of the envelope: the patterns are unchanged."""
    _head(session)
    surface = envelope_surface(session.design, session.patterns)
    ear = next(s for s in session.state.shapes if s.name == "Ear")
    before = shape_design(ear, surface)
    edits.move_shape_group(session, "Head", 3.0, 0.0)
    ear = next(s for s in session.state.shapes if s.name == "Ear")
    after = shape_design(ear, surface)
    for a, b in zip(before.pieces, after.pieces, strict=True):
        assert np.allclose(a.finished, b.finished, atol=1e-6)


@given(st.floats(-0.5, 0.5), st.floats(-180.0, 180.0), st.floats(0.5, 11.5))
@settings(max_examples=60, deadline=None)
def test_mirroring_twice_gives_the_shape_back(across: float, toward: float, line: float) -> None:
    session = ProjectSession.open(FIXTURE)
    spec = default_shape("dome", session.design, "Ear").model_copy(
        update={
            "placement": ShapePlacement(
                gore=4, tape_position=6.0, across=across, lean_deg=10.0, lean_toward_deg=toward
            ),
            "gores": 5,
            "panel_widths": [1.0, 2.0, 3.0, 4.0, 5.0],
            "seam_offset_deg": 30.0,
        }
    )
    n = 12
    twice = DomeShape.model_validate(
        mirrored(DomeShape.model_validate(mirrored(spec, line, n)), line, n)
    )
    a, b = spec.placement, twice.placement
    assert ((b.gore - 0.5 + b.across) - (a.gore - 0.5 + a.across)) % n == pytest.approx(
        0.0, abs=1e-5
    ) or ((b.gore - 0.5 + b.across) - (a.gore - 0.5 + a.across)) % n == pytest.approx(n, abs=1e-5)
    assert abs(((b.lean_toward_deg - a.lean_toward_deg) + 180.0) % 360.0 - 180.0) < 1e-9
    assert twice.panel_widths == spec.panel_widths
    assert twice.seam_offset_deg == pytest.approx(spec.seam_offset_deg)


def test_mirrored_seams_are_the_mirror_image_round_the_axis() -> None:
    session = ProjectSession.open(FIXTURE)
    spec = default_shape("dome", session.design, "Ear").model_copy(
        update={"gores": 4, "panel_widths": [1.0, 2.0, 3.0, 4.0], "seam_offset_deg": 25.0}
    )
    mirror = DomeShape.model_validate(mirrored(spec, 2.0, 12))
    a = np.degrees(seam_angles(to_primitive(spec)))
    b = np.degrees(seam_angles(to_primitive(mirror)))
    # The seams of the mirror image are those of the shape with every angle negated.
    assert np.sort(np.mod(b[:-1], 360.0)) == pytest.approx(np.sort(np.mod(-a[:-1], 360.0)))


def test_mirror_copy_makes_the_other_side_and_skips_shapes_on_the_line(
    session: ProjectSession,
) -> None:
    _head(session)
    face = next(s for s in session.state.shapes if s.name == "Face")
    line = face.placement.gore - 0.5 + face.placement.across  # the face's centreline
    added = edits.mirror_shape_group(session, "Head", line, copy=True)
    assert added == ["Ear mirror"]  # the nose is on the face's centreline
    shapes = {s.name: s for s in session.state.shapes}
    ear, other = shapes["Ear"], shapes["Ear mirror"]
    assert other.group == "Head"
    g_ear = ear.placement.gore - 0.5 + ear.placement.across
    g_other = other.placement.gore - 0.5 + other.placement.across
    assert g_ear + g_other == pytest.approx(2 * line)
    assert other.placement.lean_toward_deg == pytest.approx(-ear.placement.lean_toward_deg)
    assert other.panel_widths == [3.0, 1.0, 1.0, 1.0, 2.0, 1.0]  # piece 1, then reversed
    # The mirrored ear is placed and its pattern is the mirror image of the ear's.
    surface = envelope_surface(session.design, session.patterns)
    a, b = shape_design(ear, surface), shape_design(other, surface)
    assert sorted(p.flat_area for p in a.pieces) == pytest.approx(
        sorted(p.flat_area for p in b.pieces), rel=1e-3
    )
    assert a.footprint_length == pytest.approx(b.footprint_length, rel=1e-4)


def test_mirroring_a_mesh_turns_its_triangles_over(session: ProjectSession) -> None:
    _head(session)
    nose = next(s for s in session.state.shapes if s.name == "Nose")
    assert isinstance(nose, MeshShape)
    mirror = MeshShape.model_validate(mirrored(nose, 7.0, _gore_count(session)))
    v, w = np.asarray(nose.vertices), np.asarray(mirror.vertices)
    assert w[:, 1] == pytest.approx(-v[:, 1])
    t, u = np.asarray(nose.triangles), np.asarray(mirror.triangles)
    assert (u == t[:, [0, 2, 1]]).all()


def test_mirror_in_place_changes_the_group_in_one_step(session: ProjectSession) -> None:
    _head(session)
    before = list(session.state.shapes)
    assert edits.mirror_shape_group(session, "Head", 6.0, copy=False) == []
    assert [s.name for s in session.state.shapes] == [s.name for s in before]
    assert session.state.shapes != before
    session.undo()
    assert session.state.shapes == before


def test_build_pack_lists_the_groups(session: ProjectSession, tmp_path: Path) -> None:
    _head(session)
    surface = envelope_surface(session.design, session.patterns)
    placed = [shape_design(s, surface) for s in session.state.shapes]
    groups = {s.name: s.group for s in session.state.shapes if s.group}
    export_build_pack(session.design, placed, tmp_path, session.patterns, groups=groups)
    assert check_pack(tmp_path) == []
    index = json.loads((tmp_path / "cad" / "index.json").read_text(encoding="utf-8"))
    assert index["shape_groups"] == {"Head": ["Face", "Ear", "Nose"]}
    ear = next(s for s in index["sheets"] if s["piece"] == "Ear-G1")
    assert math.isfinite(ear["finished_width_mm"])
    sheets = primitive_sheets(placed[1], group="Head")
    assert all("object Head" in s.note for s in sheets if s.kind == "skin piece")
