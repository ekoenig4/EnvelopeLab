"""Overlays in the Special shapes mode and the Colours mode (ADR-0056)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from envelopelab.project.colours import PanelRef
from envelopelab_app.main_window import MainWindow


def test_add_edit_move_and_remove_an_overlay(gore_window: MainWindow) -> None:
    gore_window.set_mode("shapes")
    panel = gore_window.shapes
    session = gore_window.controller.session
    assert session is not None
    name = panel.add_overlay()
    assert name == "overlay" and panel.selected == name
    assert panel.editor_stack.currentIndex() == 1  # the overlay editor
    assert panel.remove_button.isEnabled() and panel.duplicate_button.isEnabled()
    # Edited through the editor's signal (as its fields do): one undo step each.
    depth = session.stack.index
    panel.overlay_editor.changed.emit({"width": 1.5, "placement": {"gore": 3}}, False)
    (spec,) = session.state.overlays
    assert spec.width == 1.5 and spec.placement.gore == 3 and session.stack.index == depth + 1
    assert "lies over" in panel.overlay_editor.info.text()
    # It is drawn on the gore map and on the balloon, and moves like a shape.
    placed = next(s for s in panel.placement.data.shapes if s.name == name)
    assert placed.footprint and len(placed.triangles) > 0
    assert panel.nudge(0.0, 0.25)
    moved = session.state.overlays[0].placement.tape_position
    assert abs(moved - (spec.placement.tape_position + 0.25)) < 1e-3  # nudges round to mm
    # Refused edits change nothing and say why.
    rejected: list[str] = []
    gore_window.controller.editRejected.connect(rejected.append)
    panel.overlay_editor.changed.emit({"placement": {"tape_position": 0.05}}, False)
    assert rejected and "mouth" in rejected[-1]
    copy = panel.duplicate_selected()
    assert copy == "overlay 2" and panel.selected == copy
    panel.remove_selected()
    assert [o.name for o in session.state.overlays] == ["overlay"]
    # Shapes still work beside overlays.
    assert panel.add_shape("dome") is not None
    assert panel.editor_stack.currentIndex() == 0


def test_overlays_are_painted_in_the_colours_mode(gore_window: MainWindow) -> None:
    gore_window.set_mode("shapes")
    name = gore_window.shapes.add_overlay()
    assert name is not None
    gore_window.set_mode("colours")
    panel = gore_window.colours
    session = gore_window.controller.session
    assert session is not None
    ref = PanelRef(name, "A", 1)
    assert name in panel.grid.scene.overlays
    assert any(r == ref for r, _poly in panel.grid.scene.cells)
    # Fill row paints the panels under it, never the overlay; a click on it paints it.
    panel.set_tool("row")
    assert panel.targets(ref) == [ref]
    panel.picker.set_colour("#ffc000")
    at = panel.grid.centre_of(ref).toPoint()
    QTest.mouseClick(panel.grid, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert session.state.colours.colour_of(ref) == "#ffc000"
    # The validation panel says nothing about an overlay that fits.
    assert not [f for f in gore_window.controller.findings() if f.target == f"shape:{name}"]
