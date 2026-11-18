"""Where a number acts, shown on the balloon, and numbers changed in real time
(ADR-0050)."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit

from envelopelab_app.hints import HINT_PROPERTY, hint_of
from envelopelab_app.live_number import step_size, stepped
from envelopelab_app.main_window import MainWindow

#: Number boxes that set how the app shows or computes, not the design (object names).
VIEW_ONLY = {
    "axisLine",  # where a symmetry axis is drawn before it is added
    "faceNumber",  # which seam the 3D view turns to
    "shapeMeshSize",  # the preview solver's mesh size
}


def _editor(window: MainWindow, key: str) -> QLineEdit:
    found = [
        w for w in window.properties.findChildren(QLineEdit) if w.property(HINT_PROPERTY) == key
    ]
    assert found, key
    return found[0]


def test_every_design_number_box_says_where_it_acts(gore_window: MainWindow) -> None:
    gore_window.shapes.add_shape("dome")
    assert gore_window.controller.shapes.wait(120_000)
    missing = []
    for name in ("gore_editor", "properties", "rigging", "patterns", "shapes", "view3d"):
        panel = getattr(gore_window, name)
        for box in panel.findChildren(QAbstractSpinBox):
            if hint_of(box) is None and box.objectName() not in VIEW_ONLY:
                missing.append(f"{name}: {box.objectName() or box.toolTip()[:40]}")
    # The Properties panel's number fields are line edits.
    for line in gore_window.properties.findChildren(QLineEdit):
        if line.objectName().startswith("prop_") and hint_of(line) is None:
            missing.append(f"properties: {line.objectName()}")
    assert not missing


def test_pointing_at_a_number_shows_where_it_acts(gore_window: MainWindow) -> None:
    gore_window.mode_tabs.setCurrentIndex(0)  # Shape
    controller = gore_window.controller
    editor = gore_window.gore_editor.lock_values["mouth_diameter"]
    QApplication.sendEvent(editor, QEvent(QEvent.Type.Enter))
    assert controller.hint == "field:gores.mouth_diameter"
    h = controller.hint_highlight()
    assert h is not None and "mouth" in h.label
    inlay = gore_window.gore_editor.inlay
    inlay.refresh()
    assert inlay.data.hint is not None and inlay.data.hint.key == "field:gores.mouth_diameter"
    assert "mouth" in inlay.caption.text()
    QApplication.sendEvent(editor, QEvent(QEvent.Type.Leave))
    assert controller.hint is None
    inlay.refresh()
    assert inlay.data.hint is None


def test_a_focused_number_turns_the_views_to_it(gore_window: MainWindow) -> None:
    controller = gore_window.controller
    controller.set_hint("field:gores.panel_rows.1.height", True)
    assert controller.hint_focused
    gore_window.mode_tabs.setCurrentIndex(0)
    inlay = gore_window.gore_editor.inlay
    inlay.refresh()
    assert inlay.data.hint is not None and inlay.data.hint_face
    assert inlay.data.facing_key == "hint:field:gores.panel_rows.1.height"


def test_a_special_shape_number_shows_its_part_of_the_shape(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    assert gore_window.controller.shapes.wait(120_000)
    controller = gore_window.controller
    QApplication.sendEvent(panel.seam_turn, QEvent(QEvent.Type.Enter))
    assert controller.hint == "shape:seam_offset_deg"
    h = controller.hint_highlight()
    assert h is not None and h.lines and "seams" in h.label
    assert panel.placement.data.hint is not None


def test_the_wheel_changes_a_number_in_real_time_as_one_undo_step(
    gore_window: MainWindow,
) -> None:
    controller = gore_window.controller
    session = controller.session
    assert session is not None
    editor = _editor(gore_window, "field:operating.payload_mass")
    before = float(editor.text())
    depth = session.stack.index
    for _ in range(3):
        wheel = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(editor, wheel)
    expected = before
    for _ in range(3):
        expected = stepped(expected, 1.0)
    design = controller.design
    assert design is not None
    assert design.operating.payload_mass == expected
    assert float(editor.text()) == expected
    assert session.stack.index == depth + 1  # one undo step for the whole scrub
    session.undo()
    design = controller.design
    assert design is not None
    assert design.operating.payload_mass == before


def test_live_edits_wait_for_the_event_loop_and_keep_only_the_newest(
    gore_window: MainWindow, qtbot: object
) -> None:
    controller = gore_window.controller
    controller.live_deferred = True
    applied: list[int] = []
    for i in range(5):
        controller.edit_live("probe", partial(applied.append, i))
    assert applied == []
    controller.flush_live()
    assert applied == [4]


def test_the_step_is_a_unit_of_the_second_significant_digit() -> None:
    assert step_size(4.0) == 0.1
    assert step_size(25.0) == 1.0
    assert step_size(0.35) == 0.01
    assert step_size(7, integer=True) == 1.0
    assert stepped(4.0, 3) == 4.3
    assert stepped(0.35, -1) == 0.34
