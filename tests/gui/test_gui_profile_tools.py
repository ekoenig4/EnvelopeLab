"""Bulk profile editing in the gore editor: selection, soft drag, tools, Simplify."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPointF

from envelopelab.project.gore_design import control_arrays, design_profile, standard_gore_design
from envelopelab_app.main_window import MainWindow


def _dense(window: MainWindow, points: int = 30) -> None:
    session = window.new_project(standard_gore_design("dense", 2600.0, 17.0, 18.0, 16, 8))
    profile = design_profile(session.design)
    s = np.linspace(0.0, profile.meridian_length, points)
    pts = list(zip(profile.radius_at(s).tolist(), profile.height_at(s).tolist(), strict=True))
    window.controller.edit("set_control_points", pts, "Trace")


def test_canvas_and_table_selections_follow_each_other(window: MainWindow) -> None:
    _dense(window)
    editor = window.gore_editor
    editor.canvas.select([3, 4, 5])
    rows = sorted(i.row() for i in editor.points_table.selectionModel().selectedRows())
    assert rows == [3, 4, 5]
    assert editor.selection_label.text() == "3 point(s) selected"
    editor.points_table.selectRow(7)
    assert editor.canvas.selected_indices() == [7]
    editor.select_all_points()
    assert len(editor.canvas.selected_indices()) == 30


def test_dragging_a_selection_moves_it_with_soft_neighbours(
    window: MainWindow, qtbot: object
) -> None:
    _dense(window)
    session = window.controller.session
    assert session is not None
    editor = window.gore_editor
    canvas = editor.canvas
    r0, _ = control_arrays(session.design)
    editor.soft_radius.setValue(3.0)
    canvas.select([14, 15])
    handle = canvas.handles[15]
    start = handle.scenePos()
    canvas.begin_drag(handle, start, toggle=False)
    canvas.drag_to(QPointF(start.x() + 0.4, start.y()))
    # The preview moves the neighbours before anything is committed.
    assert canvas.handles[12].pos().x() > r0[12]
    canvas.end_drag()
    qtbot.waitUntil(lambda: control_arrays(session.design)[0][15] != r0[15])  # type: ignore[attr-defined]
    r1, _ = control_arrays(session.design)
    assert r1[14] == pytest.approx(r0[14] + 0.4) and r1[15] == pytest.approx(r0[15] + 0.4)
    assert 0.0 < r1[12] - r0[12] < 0.4 and r1[0] == r0[0]
    assert canvas.selected_indices() == [14, 15]  # kept across the refresh
    session.undo()
    assert np.array_equal(control_arrays(session.design)[0], r0)


def test_tools_scale_straighten_smooth_and_comb(window: MainWindow) -> None:
    _dense(window)
    session = window.controller.session
    assert session is not None
    editor = window.gore_editor
    r0, _ = control_arrays(session.design)
    editor.canvas.select([10, 11, 12])
    editor.scale_r.setValue(150.0)
    editor.scale_selected()
    r1, _ = control_arrays(session.design)
    assert np.mean(r1[10:13]) == pytest.approx(np.mean(r0[10:13]))
    assert np.ptp(r1[10:13]) == pytest.approx(1.5 * np.ptp(r0[10:13]))
    editor.canvas.select([4, 9])
    editor.straighten_selected()
    r2, z2 = control_arrays(session.design)
    slope = (z2[9] - z2[4]) / (r2[9] - r2[4])
    assert (z2[6] - z2[4]) / (r2[6] - r2[4]) == pytest.approx(slope)
    editor.canvas.select([])
    editor.smooth_selected()  # nothing selected: the whole profile
    assert session.stack.can_undo
    editor.comb_box.setChecked(True)
    assert not editor.canvas.comb.path().isEmpty()
    editor.comb_box.setChecked(False)
    assert editor.canvas.comb.path().isEmpty()


def test_straighten_needs_two_points(window: MainWindow) -> None:
    _dense(window)
    messages: list[str] = []
    window.controller.editRejected.connect(messages.append)
    window.gore_editor.canvas.select([4])
    window.gore_editor.straighten_selected()
    assert messages and "at least 2" in messages[-1]


def test_simplify_button(window: MainWindow) -> None:
    _dense(window)
    session = window.controller.session
    assert session is not None
    editor = window.gore_editor
    editor.simplify_tolerance.setValue(2.0)
    editor.simplify()
    count = control_arrays(session.design)[0].size
    assert count < 30 and len(editor.canvas.handles) == count
    assert editor.simplify_status.text().startswith(f"30 → {count} points")
