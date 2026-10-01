"""Project sessions: command history, save/load, snapshots, versions, runs, provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from envelopelab.commands import Command, CommandStack
from envelopelab.project import edits
from envelopelab.project.gore_design import editable_outline, panel_rows
from envelopelab.project.model import RunRecord, load_project, utc_now
from envelopelab.project.recovery import (
    autosave_file,
    discard,
    find_recoverable,
    read_autosave,
    write_autosave,
)
from envelopelab.project.session import ProjectSession

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


def fixture_session() -> ProjectSession:
    return ProjectSession.open(FIXTURE)


def fake_run(session: ProjectSession, solver: str = "envelopelab-preview") -> RunRecord:
    """A run record of the current state (no solve; for bookkeeping tests only)."""
    return RunRecord(
        run_id=f"test-{solver}-{len(session.project.runs)}",
        created=utc_now(),
        solver=solver,  # type: ignore[arg-type]
        solver_version="test",
        status="converged",
        converged=True,
        residual=1e-7,
        residual_measure="test",
        iterations=10,
        run_time=0.1,
        n_nodes=3,
        n_elements=1,
        n_tape_elements=0,
        mesh_target_mm=800.0,
        load_case="test",
        material_sources=["assumed"],
        design_content_hash=session.content_hash(),
        input_fingerprint=session.fingerprints()["simulation"],
        volume=1.0,
        lift=1.0,
        height=1.0,
        max_width=1.0,
    )


class Append(Command):
    def __init__(self, log: list[int], value: int) -> None:
        self.log, self.value = log, value

    @property
    def description(self) -> str:
        return f"append {self.value}"

    def execute(self) -> None:
        self.log.append(self.value)

    def undo(self) -> None:
        self.log.pop()


def test_command_stack_history_go_to_and_clean_state() -> None:
    log: list[int] = []
    stack = CommandStack()
    calls: list[int] = []
    stack.add_listener(lambda: calls.append(stack.index))
    for v in (1, 2, 3):
        stack.do(Append(log, v))
    stack.set_clean()
    stack.go_to(1)
    assert log == [1] and stack.history() == ["append 1", "append 2", "append 3"]
    assert not stack.is_clean and stack.redo_text() == "append 2"
    stack.go_to(3)
    assert log == [1, 2, 3] and stack.is_clean
    stack.go_to(1)
    stack.do(Append(log, 9))  # discards the saved state from the redo history
    assert stack.history() == ["append 1", "append 9"] and not stack.is_clean
    assert calls[-1] == 2
    with pytest.raises(IndexError):
        stack.go_to(5)


def test_edit_undo_redo_save_reopen_keeps_the_content_hash(tmp_path: Path) -> None:
    s = fixture_session()
    original = s.content_hash()
    assert edits.move_control_point(s, 2, 3.25, 4.4)
    edited = s.content_hash()
    assert edited != original
    assert s.undo() and s.content_hash() == original
    assert s.redo() and s.content_hash() == edited
    path = s.save(tmp_path / "p.elproj")
    assert not s.is_dirty
    reopened = ProjectSession.open(path)
    assert reopened.content_hash() == edited
    assert reopened.design == s.design
    assert reopened.patterns == s.patterns


def test_invalid_edit_changes_nothing() -> None:
    s = fixture_session()
    before = s.content_hash()
    with pytest.raises(ValueError):
        s.set_design_value(("gores", "count"), 2)  # schema: count >= 3
    assert s.content_hash() == before and not s.stack.can_undo


def test_noop_edit_is_not_recorded() -> None:
    s = fixture_session()
    count = s.design.gores.count if s.design.gores else 0
    assert s.set_design_value(("gores", "count"), count) is False
    assert not s.stack.can_undo and not s.is_dirty


def test_dirty_groups_follow_the_saved_state(tmp_path: Path) -> None:
    s = fixture_session()
    s.set_design_value(("operating", "internal_temperature"), 380.0)
    assert s.unsaved_groups() == {"operating"}
    s.save(tmp_path / "a.elproj")
    assert s.unsaved_groups() == set() and not s.is_dirty
    s.undo()
    assert s.unsaved_groups() == {"operating"} and s.is_dirty
    s.redo()
    assert s.unsaved_groups() == set()


def test_snapshots_and_versions() -> None:
    s = fixture_session()
    s.create_snapshot("baseline")
    edits.move_control_point(s, 1, 2.8, 2.0)
    changed = s.content_hash()
    assert s.restore_snapshot("baseline")
    assert s.design.gores == fixture_session().design.gores
    s.undo()
    assert s.content_hash() == changed
    parent = s.design.meta.version_id
    version = s.commit_version("wider shoulder")
    assert version.parent_id == parent and s.design.meta.version_id == version.version_id
    assert s.design.meta.parent_id == parent
    edits.move_control_point(s, 1, 2.6, 2.0)
    s.checkout_version(version.version_id)
    assert s.content_hash() == version.content_hash
    with pytest.raises(KeyError):
        s.restore_snapshot("missing")


def test_run_records_become_stale_and_round_trip(tmp_path: Path) -> None:
    s = fixture_session()
    run = fake_run(s)
    arrays = {"positions": np.arange(9.0).reshape(3, 3), "triangles": np.array([[0, 1, 2]])}
    s.add_run(run, arrays)
    assert s.run_status(run) == "current" and s.unsaved_runs() == [run.run_id]
    s.set_design_value(("operating", "internal_temperature"), 390.0)
    assert s.run_status(run) == "stale"
    path = s.save(tmp_path / "runs.elproj")
    assert (tmp_path / "runs.elproj.runs" / f"{run.run_id}.npz").is_file()
    reopened = ProjectSession.open(path)
    loaded = reopened.run_arrays(run.run_id)
    assert loaded is not None
    np.testing.assert_array_equal(loaded["positions"], arrays["positions"])
    assert reopened.run_status(reopened.project.runs[0]) == "stale"
    reopened.undo()  # nothing to undo in a freshly opened project
    reopened.set_design_value(("operating", "internal_temperature"), 373.15)
    assert reopened.run_status(reopened.project.runs[0]) == "current"


def test_manual_outline_is_flagged_in_provenance_and_audit() -> None:
    from envelopelab.project.gore_design import seam_mismatches

    s = fixture_session()
    row = panel_rows(s.design, s.patterns)[0]
    points = editable_outline(row)
    points[4] = (points[4][0] + 0.10, points[4][1])  # bulge the right side by 10 cm
    assert edits.set_manual_outline(s, row.label, points, "test bulge")
    entry = s.project.provenance[-1]
    assert entry.action == "manual outline override" and "test bulge" in entry.detail
    override = s.patterns.row(row.label).manual_outline
    assert override is not None and override.base_hash == s.group_hashes()["geometry"]
    findings = seam_mismatches(panel_rows(s.design, s.patterns), s.patterns)
    assert any(f.code == "seam_mismatch" and f.target == row.label for f in findings)
    s.undo()
    assert s.patterns.row(row.label).manual_outline is None
    assert s.project.provenance[-1].action == "undo manual outline override"
    assert not seam_mismatches(panel_rows(s.design, s.patterns), s.patterns)


def test_locks_are_saved_but_not_undoable(tmp_path: Path) -> None:
    s = fixture_session()
    locks = edits.set_lock(s, "volume", True)
    assert locks.volume is not None and s.is_dirty and not s.stack.can_undo
    s.save(tmp_path / "locks.elproj")
    assert load_project(tmp_path / "locks.elproj").locks.volume == pytest.approx(locks.volume)


def test_autosave_and_recovery(tmp_path: Path) -> None:
    s = fixture_session()
    s.set_design_value(("operating", "payload_mass"), 120.0)
    target = autosave_file(tmp_path / "recovery", "abc")
    write_autosave(s.project, target, FIXTURE)
    items = find_recoverable(tmp_path / "recovery")
    assert [i.autosave_path for i in items] == [target]
    assert items[0].original_path == FIXTURE and items[0].name == s.design.meta.name
    assert find_recoverable(tmp_path / "recovery", exclude=target) == []
    project, original = read_autosave(target)
    assert original == FIXTURE
    assert project.state.design.compute_content_hash() == s.content_hash()
    discard(target)
    assert find_recoverable(tmp_path / "recovery") == []


def test_project_files_reject_other_formats(tmp_path: Path) -> None:
    bad = tmp_path / "bad.elproj"
    bad.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    with pytest.raises(ValueError, match="not an EnvelopeLab project"):
        load_project(bad)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["state"]["design"]["gores"]["count"] = 9  # without updating the content hash
    tampered = tmp_path / "tampered.elproj"
    tampered.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="content hash mismatch"):
        load_project(tampered)


EDITS = st.lists(
    st.one_of(
        st.tuples(st.just("point"), st.integers(1, 3), st.floats(-0.2, 0.2), st.floats(-0.2, 0.2)),
        st.tuples(st.just("temperature"), st.floats(330.0, 400.0)),
        st.tuples(st.just("allowance"), st.floats(0.005, 0.05)),
        st.tuples(st.just("grain"), st.sampled_from("ABCD"), st.floats(-90.0, 90.0)),
    ),
    min_size=1,
    max_size=6,
)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(EDITS)
def test_any_edit_sequence_undoes_to_the_original_and_saves_losslessly(
    tmp_path_factory: pytest.TempPathFactory, sequence: list[Any]
) -> None:
    s = fixture_session()
    original = s.content_hash()
    for step in sequence:
        if step[0] == "point":
            _, i, dr, dz = step
            pts = s.design.gores.meridian_profile_control_points  # type: ignore[union-attr]
            edits.move_control_point(s, i, pts[i].x + dr, pts[i].y + dz)
        elif step[0] == "temperature":
            s.set_design_value(("operating", "internal_temperature"), step[1])
        elif step[0] == "allowance":
            edits.set_seam_allowance(s, step[1])
        else:
            s.set_row_pattern(step[1], {"grain_angle_deg": step[2]})
    edited = s.content_hash()
    path = s.save(tmp_path_factory.mktemp("prop") / "p.elproj")
    reopened = ProjectSession.open(path)
    assert reopened.content_hash() == edited and reopened.patterns == s.patterns
    s.stack.go_to(0)
    assert s.content_hash() == original


def test_restoring_a_version_or_snapshot_reproduces_its_content_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkout and restore give back the recorded state exactly, whatever the clock says.

    Edits stamp ``meta.modified``; a clock that advances one second per call makes every
    edit and the checkout fall in different seconds (as on a slow CI runner).
    """
    import itertools
    from datetime import timedelta

    import envelopelab.project.session as session_module

    start = utc_now()
    ticks = itertools.count()
    monkeypatch.setattr(session_module, "utc_now", lambda: start + timedelta(seconds=next(ticks)))
    s = fixture_session()
    snap = s.create_snapshot("baseline")
    version = s.commit_version("first")
    edits.move_control_point(s, 1, 2.7, 2.0)
    assert s.checkout_version(version.version_id)
    assert s.content_hash() == version.content_hash
    assert s.restore_snapshot("baseline")
    assert s.content_hash() == snap.content_hash


def test_new_from_template_copies_the_design_state_not_the_history(tmp_path: Path) -> None:
    from envelopelab.rigging import default_scoop, with_default_rigging

    base = ProjectSession.open(FIXTURE)
    design = with_default_rigging(base.design)
    design = design.model_copy(update={"scoop": default_scoop(design)})
    base.set_design_value(("scoop",), design.scoop.model_dump(mode="json"))  # type: ignore[union-attr]
    base.set_design_value(("parachute",), design.parachute.model_dump(by_alias=True, mode="json"))  # type: ignore[union-attr]
    base.set_row_pattern("B", {"grain_angle_deg": 12.0}, "grain")
    base.create_snapshot("before")
    template_path = base.save(tmp_path / "template.elproj")

    s = ProjectSession.from_template(template_path, "My second balloon")
    d = s.design
    assert d.meta.name == "My second balloon"
    assert d.meta.version_id != base.design.meta.version_id and d.meta.parent_id is None
    assert d.meta.content_hash == d.compute_content_hash()
    assert d.scoop is not None and d.parachute is not None
    assert s.patterns.row("B").grain_angle_deg == 12.0
    assert s.project.snapshots == [] and s.project.runs == [] and s.project.versions == []
    assert [e.action for e in s.project.provenance] == ["new from template"]
    assert s.path is None and not s.is_dirty
    # Editing the copy leaves the template file unchanged.
    s.set_design_value(("operating", "payload_mass"), 123.0)
    assert load_project(template_path).state.design.operating.payload_mass != 123.0


def test_new_from_template_needs_a_name() -> None:
    with pytest.raises(ValueError, match="needs a name"):
        ProjectSession.from_template(FIXTURE, "  ")


def test_library_fabric_edit_makes_runs_stale_but_not_the_file_dirty() -> None:
    """A fabric edited in the shared library changes results, not the project file."""
    from envelopelab.materials.repository import FabricLibraryRepository, fabric_data

    library = FabricLibraryRepository()
    library.seed_example_data()
    values: dict[str, dict[str, Any] | None] = {}

    def lookup(fabric_id: str) -> dict[str, Any] | None:
        if fabric_id in values:
            return values[fabric_id]
        fabric = library.fabric(fabric_id)
        return None if fabric is None else fabric_data(fabric)

    s = fixture_session()
    events: list[str] = []
    s.add_listener(events.append)
    s.set_fabric_lookup(lookup)
    run = fake_run(s)
    s.add_run(run, {})
    s.mark_built("nesting")
    s.mark_built("profile")
    assert s.run_status(run) == "current"
    fabric_id = next(iter(s.design.zones.values()))
    changed = dict(lookup(fabric_id) or {})
    changed["areal_mass"] = [60.0, "measured - coupon"]
    values[fabric_id] = changed
    events.clear()
    s.refresh_fabrics()
    assert events == ["artifacts"]
    assert s.run_status(run) == "stale"
    assert s.artifact_status("nesting") == "stale"
    assert s.artifact_status("profile") == "current"
    assert s.unsaved_groups() == set()
    # Restoring the values makes the run current again (fingerprints, not edit order).
    del values[fabric_id]
    s.refresh_fabrics()
    assert s.run_status(run) == "current"
    # A fabric the library does not have is part of the fingerprint too.
    values[fabric_id] = None
    s.refresh_fabrics()
    assert s.run_status(run) == "stale"


def test_adding_an_unused_library_fabric_keeps_results_current() -> None:
    import dataclasses

    from envelopelab.materials.repository import FabricLibraryRepository, fabric_data

    library = FabricLibraryRepository()
    library.seed_example_data()
    s = fixture_session()
    s.set_fabric_lookup(lambda i: None if (f := library.fabric(i)) is None else fabric_data(f))
    run = fake_run(s)
    s.add_run(run, {})
    template = library.fabric("nomex")
    assert template is not None and "nomex" not in s.design.zones.values()
    library.add_fabric(dataclasses.replace(template, fabric_id="new_fabric", name="New"))
    s.refresh_fabrics()
    assert s.run_status(run) == "current"
