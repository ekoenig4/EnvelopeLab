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


def test_segment_profile_in_the_points_table(window: MainWindow) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox

    session = window.new_project(standard_gore_design("seg", 2600.0, 17.0, 18.0, 16, 8))
    pts = [(2.7, 0.0), (6.5, 3.0), (9.0, 6.5), (9.0, 10.0), (6.0, 15.0), (1.2, 17.0)]
    window.controller.edit("set_control_points", pts, "Shape")
    editor = window.gore_editor
    index = editor.interpolation.findData("segments")
    editor.interpolation.setCurrentIndex(index)
    editor.interpolation.activated.emit(index)
    gores = session.design.gores
    assert gores is not None and gores.profile_interpolation == "segments"
    table = editor.points_table
    assert table.columnCount() == 5
    # Span 3 (points 3 to 4) becomes a line, span 4 an arc with a corner and its own bulge.
    combo = table.cellWidget(2, 2)
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(combo.findData("line"))
    combo.activated.emit(combo.currentIndex())
    combo = table.cellWidget(3, 2)
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(combo.findData("arc"))
    combo.activated.emit(combo.currentIndex())
    joint = table.item(3, 3)
    assert joint is not None and joint.checkState() == Qt.CheckState.Checked
    joint.setCheckState(Qt.CheckState.Unchecked)
    bulge = table.item(3, 4)
    assert bulge is not None and bulge.flags() & Qt.ItemFlag.ItemIsEditable
    bulge.setText("0.2")
    gores = session.design.gores
    assert gores is not None and gores.profile_segments is not None
    assert [s.kind for s in gores.profile_segments] == ["curve", "curve", "line", "arc", "curve"]
    assert gores.profile_segments[3].smooth is False and gores.profile_segments[3].bulge == 0.2
    # The corner is drawn with a dark ring; old span widgets do not pile up.
    assert "corner" in editor.canvas.handles[3].toolTip()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    live = [c for c in table.findChildren(QComboBox) if c.isVisible()]
    assert len(live) == 5


def test_rows_and_equator_are_marked_on_the_profile(window: MainWindow) -> None:
    session = window.new_project(standard_gore_design("rows", 2600.0, 17.0, 18.0, 16, 8))
    canvas = window.gore_editor.canvas
    texts = [label.text() for label in canvas.labels]
    assert texts[:8] == ["A", "B", "C", "D", "E", "F", "G", "H"]
    assert texts[8].startswith("equator Ø 18.00 m")
    assert canvas.seam_ticks.path().elementCount() == 2 * 9  # a tick at each of 9 seams
    assert canvas.row_highlight.path().isEmpty()
    window.gore_editor.rows_table.selectRow(3)
    assert canvas.highlighted_row == 3 and not canvas.row_highlight.path().isEmpty()
    assert "above the mouth" in window.gore_editor.outputs["equator"].text()
    # The marks follow the curve during a drag (rows stay fitted).
    before = canvas.seam_ticks.path().boundingRect()
    handle = canvas.handles[5]
    canvas.begin_drag(handle, handle.scenePos(), toggle=False)
    canvas.drag_to(QPointF(handle.scenePos().x() + 1.0, handle.scenePos().y()))
    assert canvas.seam_ticks.path().boundingRect() != before
    canvas.end_drag()
    assert session.design.gores is not None


def test_mouth_top_hole_and_parachute_are_marked(window: MainWindow) -> None:
    session = window.new_project(standard_gore_design("open", 2600.0, 17.0, 18.0, 16, 8))
    editor = window.gore_editor
    canvas = editor.canvas
    gores = session.design.gores
    assert gores is not None and session.design.parachute is not None
    texts = [label.text() for label in canvas.labels]
    assert f"mouth Ø {gores.mouth_diameter:.2f} m" in texts
    assert f"top hole Ø {gores.parachute_hole_diameter:.2f} m" in texts
    rigging = window.controller.rigging
    assert rigging is not None and rigging.parachute is not None
    chute = rigging.parachute.geometry.diameter
    assert f"parachute Ø {chute:.2f} m" in texts  # same edge as the rigging analysis
    assert editor.outputs["parachute"].text() == f"{chute:.3f} m"
    assert editor.outputs["openings"].text().startswith(f"{gores.mouth_diameter:.3f} m / ")
    # A wider overlap moves the parachute edge down and out.
    window.rigging.set_seal_overlap(gores.seal_overlap + 0.3)
    wider = [label.text() for label in canvas.labels if label.text().startswith("parachute")]
    assert wider and wider[0] != f"parachute Ø {chute:.2f} m"
    # No parachute: no parachute mark.
    window.rigging.remove_parachute()
    assert canvas.parachute.path().isEmpty()
    assert not [label for label in canvas.labels if label.text().startswith("parachute")]


def test_locked_opening_nodes_keep_their_radius(window: MainWindow, qtbot: object) -> None:
    from PySide6.QtCore import Qt

    session = window.new_project(standard_gore_design("lock", 2600.0, 17.0, 18.0, 16, 8))
    editor = window.gore_editor
    canvas = editor.canvas
    editor.locks["mouth_diameter"].click()
    editor.locks["top_diameter"].click()
    r0, z0 = control_arrays(session.design)
    # The table's radius cells of the two opening nodes are read-only.
    for row in (0, len(r0) - 1):
        item = editor.points_table.item(row, 0)
        assert item is not None and not item.flags() & Qt.ItemFlag.ItemIsEditable
    # Dragging the mouth node sideways and up: it only moves up, during the drag too.
    handle = canvas.handles[0]
    start = handle.scenePos()
    canvas.begin_drag(handle, start, toggle=False)
    canvas.drag_to(QPointF(start.x() + 0.5, start.y() - 0.3))
    assert canvas.handles[0].pos().x() == pytest.approx(r0[0])
    canvas.end_drag()
    qtbot.waitUntil(lambda: control_arrays(session.design)[1][0] != z0[0])  # type: ignore[attr-defined]
    r1, z1 = control_arrays(session.design)
    assert r1[0] == pytest.approx(r0[0]) and z1[0] == pytest.approx(z0[0] + 0.3)
    # A drag that the locks undo entirely leaves no handle out of place.
    top = canvas.handles[-1]
    start = top.scenePos()
    canvas.begin_drag(top, start, toggle=False)
    canvas.drag_to(QPointF(start.x() + 0.5, start.y()))
    canvas.end_drag()
    qtbot.wait(50)  # type: ignore[attr-defined]
    assert canvas.handles[-1].pos().x() == pytest.approx(r0[-1])


def test_reference_profiles_overlay_the_design(window: MainWindow) -> None:
    from pathlib import Path

    from PySide6.QtCore import Qt

    shape = Path(__file__).resolve().parents[1] / "fixtures" / "flat_chord_pattern" / "shape.yaml"
    session = window.new_project(standard_gore_design("ref", 2600.0, 17.0, 18.0, 16, 8))
    editor = window.gore_editor
    canvas = editor.canvas
    assert editor.add_reference_file(str(shape))
    editor.snapshot_reference()
    assert [r.name for r in session.project.references][0] == "shape"
    assert len(canvas.reference_items) == 2
    legend = [label.text() for label in canvas.labels if label.text().startswith("- - ")]
    assert legend[0] == "- - shape"
    table = editor.refs_table
    gap = table.item(1, 2)
    assert gap is not None and gap.text() in ("0 mm", "1 mm")  # the snapshot is the design
    # Edits are compared with the snapshot.
    window.controller.edit("scale_points", [4, 5, 6, 7], 1.1, 1.0)
    gap = table.item(1, 2)
    assert gap is not None and int(gap.text().split()[0]) > 50
    # Hide one, shift the other, rename.
    show = table.item(0, 0)
    assert show is not None
    show.setCheckState(Qt.CheckState.Unchecked)
    assert not session.project.references[0].visible and len(canvas.reference_items) == 1
    offset = table.item(1, 1)
    assert offset is not None
    offset.setText("0.5")
    assert session.project.references[1].z_offset == 0.5
    name = table.item(1, 0)
    assert name is not None
    name.setText("before scaling")
    assert session.project.references[1].name == "before scaling"
    # A file that holds no profile is refused with a message.
    messages: list[str] = []
    window.controller.editRejected.connect(messages.append)
    assert not editor.add_reference_file(str(shape.with_name("README.md")))
    assert messages and "no reference" in messages[-1]
    table.selectRow(0)
    editor._remove_reference()
    assert [r.name for r in session.project.references] == ["before scaling"]
