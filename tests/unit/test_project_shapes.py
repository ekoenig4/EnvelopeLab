"""Special shapes in projects: format version 2, migration, edits, undo and fingerprints."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from envelopelab.project import edits
from envelopelab.project.model import (
    PROJECT_FORMAT_VERSION,
    dump_project,
    load_project,
    load_project_text,
    save_project,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import (
    DomeShape,
    MeshShape,
    ShapePlacement,
    TubeShape,
    default_shape,
    envelope_surface,
    host_row,
    mesh_shape,
    shape_design,
    shape_fabrics,
)
from envelopelab.project.templates import state_from_template
from envelopelab.validation.primitives import ellipsoid_mesh

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


@pytest.fixture
def session() -> ProjectSession:
    return ProjectSession.open(FIXTURE)


def _dome(s: ProjectSession, name: str = "Nose") -> DomeShape:
    spec = default_shape("dome", s.design, name)
    assert isinstance(spec, DomeShape)
    return spec


def test_version_1_file_reads_without_shapes() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert raw["format_version"] == 1
    project = load_project(FIXTURE)
    assert project.format_version == PROJECT_FORMAT_VERSION == 2
    assert project.state.shapes == []


def test_version_1_snapshots_are_migrated_too(session: ProjectSession) -> None:
    session.create_snapshot("before")
    data = json.loads(dump_project(session.project))
    data["format_version"] = 1
    for state in [data["state"]] + [s["state"] for s in data["snapshots"]]:
        del state["shapes"]
    project = load_project_text(json.dumps(data))
    assert project.snapshots[0].state.shapes == []


def test_unknown_version_is_refused(session: ProjectSession) -> None:
    data = json.loads(dump_project(session.project))
    data["format_version"] = 3
    with pytest.raises(ValueError, match="unsupported project format version 3"):
        load_project_text(json.dumps(data))


def test_shapes_survive_save_and_load(session: ProjectSession, tmp_path: Path) -> None:
    edits.add_shape(session, _dome(session))
    mesh = ellipsoid_mesh(0.2, 0.15, 0.25, -0.05, rings=8, segments=12)
    placement = ShapePlacement(gore=3, tape_position=4.0)
    edits.add_shape(session, mesh_shape("Blob", mesh.vertices, mesh.triangles, placement, "b.obj"))
    path = save_project(session.project, tmp_path / "shapes.elproj")
    back = load_project(path)
    assert back.state.shapes == session.state.shapes
    blob = back.state.shapes[1]
    assert isinstance(blob, MeshShape) and blob.source == "b.obj"
    assert np.allclose(np.asarray(blob.vertices), mesh.vertices)


def test_add_update_remove_are_undoable(session: ProjectSession) -> None:
    assert edits.add_shape(session, _dome(session))
    assert edits.update_shape(session, "Nose", {"height": 0.3, "placement": {"gore": 4}})
    spec = session.state.shapes[0]
    assert isinstance(spec, DomeShape)
    assert spec.height == 0.3 and spec.placement.gore == 4
    assert spec.placement.tape_position > 0.0  # merged, not replaced
    assert edits.remove_shape(session, "Nose")
    assert session.state.shapes == []
    session.undo()
    session.undo()
    restored = session.state.shapes[0]
    assert isinstance(restored, DomeShape) and restored.height != 0.3
    session.undo()
    assert session.state.shapes == []
    session.redo()
    assert [s.name for s in session.state.shapes] == ["Nose"]


def test_invalid_shape_edits_change_nothing(session: ProjectSession) -> None:
    edits.add_shape(session, _dome(session))
    copy = edits.duplicate_shape(session, "Nose")
    assert copy == "Nose copy"
    assert session.state.shapes[1].placement.gore == session.state.shapes[0].placement.gore + 1
    before = session.state.model_copy(deep=True)
    with pytest.raises(ValueError, match="unique"):
        edits.update_shape(session, "Nose copy", {"name": "Nose"})
    with pytest.raises(ValueError, match="exists"):
        edits.add_shape(session, _dome(session))
    with pytest.raises(ValueError):
        edits.update_shape(session, "Nose", {"height": -1.0})
    with pytest.raises(ValueError, match="kind"):
        edits.update_shape(session, "Nose", {"kind": "tube"})
    with pytest.raises(KeyError):
        edits.remove_shape(session, "Tail")
    assert session.state == before


def test_design_edits_keep_the_shapes(session: ProjectSession) -> None:
    edits.add_shape(session, _dome(session))
    edits.set_gore_count(session, 12)
    assert [s.name for s in session.state.shapes] == ["Nose"]
    session.create_snapshot("with nose")
    edits.remove_shape(session, "Nose")
    session.restore_snapshot("with nose")
    assert [s.name for s in session.state.shapes] == ["Nose"]


def test_shapes_only_change_the_shapes_fingerprint(session: ProjectSession) -> None:
    before = session.fingerprints()
    edits.add_shape(session, _dome(session))
    after = session.fingerprints()
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"shapes"}
    assert session.unsaved_groups() == {"shapes"}
    session.undo()
    assert session.fingerprints() == before


def test_template_keeps_shapes(session: ProjectSession) -> None:
    edits.add_shape(session, _dome(session))
    state = state_from_template(session.project, "From template")
    assert [s.name for s in state.shapes] == ["Nose"]


def test_shape_fabric_defaults_to_the_host_row(session: ProjectSession) -> None:
    spec = TubeShape(
        name="Horn",
        placement=ShapePlacement(gore=2, tape_position=4.0),
        base_radius=0.2,
        tip_radius=0.05,
        length=0.5,
    )
    placed = shape_design(spec, envelope_surface(session.design, session.patterns))
    row = host_row(placed)
    band = next(r for r in placed.surface.rows if r.label == row)
    assert band.s_bottom <= placed.base_s <= band.s_top
    host, skin = shape_fabrics(spec, session.design, session.patterns, placed)
    assert host == skin == "ripstop_nylon"
    other = spec.model_copy(update={"fabric": "nomex"})
    assert shape_fabrics(other, session.design, session.patterns, placed) == (host, "nomex")
