"""Dependency graph: which edits invalidate which derived artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from envelopelab.project import edits
from envelopelab.project.dependencies import (
    ARTIFACTS,
    INPUT_GROUPS,
    artifact_inputs,
    invalidated_by,
)
from envelopelab.project.session import ProjectSession

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


@pytest.fixture
def session() -> ProjectSession:
    s = ProjectSession.open(FIXTURE)
    for spec in ARTIFACTS:
        s.mark_built(spec.name)
    return s


def test_seam_allowance_invalidates_patterns_nesting_and_export_only() -> None:
    assert invalidated_by({"seam_allowance"}) == {"patterns", "nesting", "export"}


def test_geometry_invalidates_every_geometric_artifact() -> None:
    assert invalidated_by({"geometry"}) == {
        "profile",
        "patterns",
        "assembly",
        "rest_mesh",
        "simulation",
        "flattening",
        "nesting",
        "export",
    }


def test_operating_conditions_invalidate_only_the_simulation() -> None:
    assert invalidated_by({"operating"}) == {"simulation"}


def test_labels_do_not_touch_the_physics() -> None:
    assert invalidated_by({"labels"}) == {"patterns", "nesting", "export"}


def test_unknown_group_is_an_error() -> None:
    with pytest.raises(KeyError):
        invalidated_by({"colour"})


def test_every_group_is_read_by_some_artifact() -> None:
    read = set().union(*(artifact_inputs(a.name) for a in ARTIFACTS))
    assert read == set(INPUT_GROUPS)


def test_seam_allowance_edit_keeps_rest_mesh_and_simulation_current(
    session: ProjectSession,
) -> None:
    assert edits.set_seam_allowance(session, 0.03)
    status = session.tracker.statuses()
    assert status["patterns"] == status["nesting"] == status["export"] == "stale"
    for name in ("profile", "assembly", "rest_mesh", "simulation", "flattening"):
        assert status[name] == "current", name


def test_row_allowance_override_behaves_like_the_default(session: ProjectSession) -> None:
    assert edits.set_seam_allowance(session, 0.02, "B")
    assert session.artifact_status("patterns") == "stale"
    assert session.artifact_status("rest_mesh") == "current"


def test_temperature_edit_marks_only_the_simulation_stale(session: ProjectSession) -> None:
    session.set_design_value(("operating", "internal_temperature"), 380.0)
    status = session.tracker.statuses()
    assert status["simulation"] == "stale"
    assert {k for k, v in status.items() if v == "stale"} == {"simulation"}


def test_geometry_edit_marks_everything_stale_and_undo_restores(session: ProjectSession) -> None:
    edits.move_control_point(session, 2, 3.2, 4.5)
    assert all(v == "stale" for v in session.tracker.statuses().values())
    session.undo()
    assert all(v == "current" for v in session.tracker.statuses().values())


def test_manual_outline_invalidates_assembly_and_simulation(session: ProjectSession) -> None:
    from envelopelab.project.gore_design import editable_outline, panel_rows

    row = panel_rows(session.design, session.patterns)[1]
    points = editable_outline(row)
    points[3] = (points[3][0] + 0.05, points[3][1])
    edits.set_manual_outline(session, row.label, points)
    status = session.tracker.statuses()
    assert status["patterns"] == status["rest_mesh"] == status["simulation"] == "stale"
    assert status["profile"] == "current"
