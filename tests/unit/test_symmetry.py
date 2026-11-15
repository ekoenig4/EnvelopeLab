"""Symmetry axes and linked mirror twins of special shapes."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from envelopelab.project import edits
from envelopelab.project.model import dump_project, load_project_text
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import (
    DomeShape,
    MeshShape,
    ShapePlacement,
    default_shape,
    envelope_surface,
    mesh_shape,
    shape_design,
)
from envelopelab.project.symmetry import axis_gore_label
from envelopelab.validation.primitives import ellipsoid_mesh

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
LINE = 5.5  # the centreline of gore 6


@pytest.fixture
def session() -> ProjectSession:
    s = ProjectSession.open(FIXTURE)
    ear = default_shape("dome", s.design, "Ear")
    assert isinstance(ear, DomeShape)
    ear = ear.model_copy(
        update={
            "placement": ShapePlacement(
                gore=4, tape_position=6.5, across=0.2, lean_deg=20.0, lean_toward_deg=60.0
            ),
            "gores": 6,
            "seam_offset_deg": 15.0,
            "panel_widths": [3.0, 1.0, 2.0, 1.0, 1.0, 1.0],
        }
    )
    edits.add_shape(s, DomeShape.model_validate(ear.model_dump()))
    assert edits.add_symmetry_axis(s, "Face centre", LINE)
    return s


def _shape(s: ProjectSession, name: str) -> DomeShape | MeshShape:
    spec = next(x for x in s.state.shapes if x.name == name)
    assert isinstance(spec, DomeShape | MeshShape)
    return spec


def _g(spec: DomeShape | MeshShape) -> float:
    return spec.placement.gore - 0.5 + spec.placement.across


def _n(s: ProjectSession) -> int:
    assert s.design.gores is not None
    return s.design.gores.count


def _same_gore(a: float, b: float, n: int) -> None:
    """Gore positions ``a`` and ``b`` are the same azimuth (modulo the ``n`` gores)."""
    assert abs((a - b + 0.5 * n) % n - 0.5 * n) < 1e-5


def _is_mirror(s: ProjectSession, a: str, b: str, line: float = LINE) -> None:
    x, y = _shape(s, a), _shape(s, b)
    _same_gore(_g(x) + _g(y), 2 * line, _n(s))
    assert y.placement.tape_position == pytest.approx(x.placement.tape_position)
    assert y.placement.lean_toward_deg == pytest.approx(-x.placement.lean_toward_deg)
    if isinstance(x, DomeShape) and isinstance(y, DomeShape):
        assert (y.base_radius, y.height, y.gores) == (x.base_radius, x.height, x.gores)
        w = x.panel_widths
        assert y.panel_widths == ([w[0], *w[1:][::-1]] if w else [])
        assert y.seam_offset_deg == pytest.approx(-x.seam_offset_deg)


def test_axes_are_named_saved_and_described(session: ProjectSession) -> None:
    assert [a.name for a in session.state.symmetry_axes] == ["Face centre"]
    back = load_project_text(dump_project(session.project))
    assert back.state.symmetry_axes == session.state.symmetry_axes
    assert axis_gore_label(5.5, 12) == "centre of gore 6"
    assert axis_gore_label(6.0, 12) == "seam 6|7"
    assert axis_gore_label(0.0, 12) == "seam 12|1"
    assert axis_gore_label(5.75, 12) == "gore 6 +0.25"
    with pytest.raises(ValueError, match="exists"):
        edits.add_symmetry_axis(session, "Face centre", 1.0)


def test_mirror_makes_a_linked_twin_across_the_axis(session: ProjectSession) -> None:
    twin = edits.mirror_shape(session, "Ear", "Face centre")
    assert twin == "Ear mirror"
    spec = _shape(session, twin)
    assert spec.mirror is not None and (spec.mirror.of, spec.mirror.axis) == ("Ear", "Face centre")
    _is_mirror(session, "Ear", twin)
    surface = envelope_surface(session.design, session.patterns)
    a, b = shape_design(_shape(session, "Ear"), surface), shape_design(spec, surface)
    assert sorted(p.flat_area for p in a.pieces) == pytest.approx(
        sorted(p.flat_area for p in b.pieces), rel=1e-3
    )
    session.undo()
    assert [s.name for s in session.state.shapes] == ["Ear"]


def test_editing_either_side_keeps_them_mirror_images(session: ProjectSession) -> None:
    edits.mirror_shape(session, "Ear", "Face centre")
    # The source: the twin follows.
    assert edits.update_shape(session, "Ear", {"base_radius": 0.4, "panel_widths": []})
    _is_mirror(session, "Ear", "Ear mirror")
    assert _shape(session, "Ear mirror").base_radius == pytest.approx(0.4)  # type: ignore[union-attr]
    # The twin (as dragging it does): the source follows, in one undo step.
    history = len(session.stack.history())
    assert edits.update_shape(
        session, "Ear mirror", {"placement": {"gore": 8, "tape_position": 7.0, "across": 0.1}}
    )
    assert len(session.stack.history()) == history + 1
    _is_mirror(session, "Ear", "Ear mirror")
    assert _shape(session, "Ear").placement.tape_position == pytest.approx(7.0)
    # Feed holes are mirrored too.
    hole = {"gore": 4, "tape_position": 6.6, "across": 0.0, "radius": 0.05}
    edits.update_shape(session, "Ear", {"feed_holes": [hole]})
    (mirrored_hole,) = _shape(session, "Ear mirror").feed_holes
    _same_gore(mirrored_hole.gore - 0.5 + mirrored_hole.across + 3.5, 2 * LINE, _n(session))


def test_moving_the_axis_moves_the_twins(session: ProjectSession) -> None:
    edits.mirror_shape(session, "Ear", "Face centre")
    before = _g(_shape(session, "Ear"))
    assert edits.update_symmetry_axis(session, "Face centre", line=6.0, new_name="Nose line")
    assert _g(_shape(session, "Ear")) == pytest.approx(before)
    _is_mirror(session, "Ear", "Ear mirror", 6.0)
    assert _shape(session, "Ear mirror").mirror.axis == "Nose line"  # type: ignore[union-attr]


def test_renaming_removing_and_unlinking(session: ProjectSession) -> None:
    edits.mirror_shape(session, "Ear", "Face centre")
    edits.update_shape(session, "Ear", {"name": "Left ear"})
    assert _shape(session, "Ear mirror").mirror.of == "Left ear"  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="unlink or remove"):
        edits.remove_symmetry_axis(session, "Face centre")
    assert edits.unlink_mirror(session, "Ear mirror")
    assert _shape(session, "Ear mirror").mirror is None
    # Unlinked, it no longer follows.
    edits.update_shape(session, "Left ear", {"base_radius": 0.3})
    assert _shape(session, "Ear mirror").base_radius != pytest.approx(0.3)  # type: ignore[union-attr]
    assert edits.remove_symmetry_axis(session, "Face centre")
    # Removing a source leaves its twin as an ordinary shape.
    s = ProjectSession.open(FIXTURE)
    edits.add_shape(s, _shape(session, "Left ear").model_copy(update={"name": "A"}))
    edits.add_symmetry_axis(s, "X", LINE)
    edits.mirror_shape(s, "A", "X")
    edits.remove_shape(s, "A")
    assert [(x.name, x.mirror) for x in s.state.shapes] == [("A mirror", None)]


def test_twins_cannot_be_made_twice_of_twins_or_on_the_axis(session: ProjectSession) -> None:
    edits.mirror_shape(session, "Ear", "Face centre")
    with pytest.raises(ValueError, match="already has a mirror twin"):
        edits.mirror_shape(session, "Ear", "Face centre")
    with pytest.raises(ValueError, match="already the mirror twin"):
        edits.mirror_shape(session, "Ear mirror", "Face centre")
    nose = _shape(session, "Ear").model_copy(
        update={"name": "Nose", "placement": ShapePlacement(gore=6, tape_position=6.0)}
    )
    edits.add_shape(session, nose)
    with pytest.raises(ValueError, match="its own mirror image"):
        edits.mirror_shape(session, "Nose", "Face centre")


def test_a_group_with_its_twins_moves_with_its_axis(session: ProjectSession) -> None:
    edits.mirror_shape(session, "Ear", "Face centre")
    # A twin is in its source's group: grouping one side groups the pair.
    edits.set_shape_group(session, ["Ear"], "Head")
    assert {s.group for s in session.state.shapes} == {"Head"}
    other = _shape(session, "Ear").model_copy(update={"name": "Other", "group": None})
    edits.add_shape(session, other)
    edits.mirror_shape(session, "Other", "Face centre")
    with pytest.raises(ValueError, match="outside group Head"):
        edits.move_shape_group(session, "Head", 1.0, 0.0)
    edits.remove_shape(session, "Other mirror")
    before = {s.name: _g(s) for s in session.state.shapes}  # type: ignore[arg-type]
    assert edits.move_shape_group(session, "Head", 2.0, 0.3)
    for s in session.state.shapes:
        if s.group == "Head":
            _same_gore(_g(s) - before[s.name], 2.0, _n(session))  # type: ignore[arg-type]
    assert session.state.symmetry_axes[0].line == pytest.approx(LINE + 2.0)
    _is_mirror(session, "Ear", "Ear mirror", LINE + 2.0)


def test_mirroring_a_group_across_an_axis_links_every_member(session: ProjectSession) -> None:
    mesh = ellipsoid_mesh(0.2, 0.12, 0.25, -0.05, rings=8, segments=12)
    edits.add_shape(
        session,
        mesh_shape("Horn", mesh.vertices, mesh.triangles, ShapePlacement(gore=3, tape_position=7)),
    )
    edits.set_shape_group(session, ["Ear", "Horn"], "Head")
    added = edits.mirror_shape_group(session, "Head", axis="Face centre")
    assert added == ["Ear mirror", "Horn mirror"]
    horn, twin = _shape(session, "Horn"), _shape(session, "Horn mirror")
    assert isinstance(horn, MeshShape) and isinstance(twin, MeshShape)
    assert np.asarray(twin.vertices)[:, 1] == pytest.approx(-np.asarray(horn.vertices)[:, 1])
    assert edits.mirror_shape_group(session, "Head", axis="Face centre") == []  # done already


def test_older_files_have_no_axes(session: ProjectSession) -> None:
    data = json.loads(dump_project(session.project))
    data["format_version"] = 3
    del data["state"]["symmetry_axes"]
    for shape in data["state"]["shapes"]:
        del shape["mirror"]
    back = load_project_text(json.dumps(data))
    assert back.state.symmetry_axes == []


def test_changing_the_gore_count_mirrors_the_twins_again(session: ProjectSession) -> None:
    edits.mirror_shape(session, "Ear", "Face centre")
    assert edits.set_gore_count(session, 10)
    assert _n(session) == 10
    _is_mirror(session, "Ear", "Ear mirror")
