"""Overlays in the Special shapes mode and the Colours mode (ADR-0056)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from envelopelab.project.colours import PanelRef
from envelopelab_app.main_window import MainWindow
from envelopelab_app.overlay_editor import PiecePreview
from envelopelab_app.panels.shapes import ShapesPanel


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


def _polygon_overlay(gore_window: MainWindow) -> tuple[ShapesPanel, PiecePreview]:
    gore_window.set_mode("shapes")
    panel = gore_window.shapes
    panel.add_overlay()
    square = [[-0.4, -0.4], [0.4, -0.4], [0.4, 0.4], [-0.4, 0.4]]
    panel.overlay_editor.changed.emit({"outline": "polygon", "points": square}, False)
    preview = panel.overlay_editor.preview
    preview.resize(400, 400)
    return panel, preview


def test_polygon_corners_are_dragged_in_the_drawing(gore_window: MainWindow) -> None:
    panel, preview = _polygon_overlay(gore_window)
    session = gore_window.controller.session
    assert session is not None
    assert preview.corners is not None and len(preview.corners) == 4
    assert not panel.overlay_editor.width_box.isEnabled()
    corner = preview.to_screen(0.4, 0.4).toPoint()
    target = preview.to_screen(0.6, 0.7).toPoint()
    depth = session.stack.index
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    QTest.mousePress(preview, left, none, corner)
    for k in range(1, 6):
        step = corner + (target - corner) * (k / 5)
        QTest.mouseMove(preview, step)
    QTest.mouseRelease(preview, left, none, target)
    (spec,) = session.state.overlays
    assert spec.points[2] == pytest.approx((0.6, 0.7), abs=0.01)
    assert session.stack.index == depth + 1  # the whole drag is one undo step
    # Double click an edge: a corner is added there; right click a corner: removed.
    edge = preview.to_screen(0.0, -0.4).toPoint()
    QTest.mouseDClick(preview, left, none, edge)
    assert len(session.state.overlays[0].points) == 5
    added = preview.to_screen(0.0, -0.4).toPoint()
    QTest.mouseClick(preview, Qt.MouseButton.RightButton, none, added)
    assert len(session.state.overlays[0].points) == 4
    session.undo()
    assert len(session.state.overlays[0].points) == 5


def test_a_drag_that_crosses_the_outline_is_not_applied(gore_window: MainWindow) -> None:
    _panel, preview = _polygon_overlay(gore_window)
    session = gore_window.controller.session
    assert session is not None
    before = list(session.state.overlays[0].points)
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    corner = preview.to_screen(0.4, 0.4).toPoint()
    across = preview.to_screen(-0.6, -0.1).toPoint()  # past the opposite edge: a bow tie
    QTest.mousePress(preview, left, none, corner)
    QTest.mouseMove(preview, across)
    assert "crosses itself" in preview.toolTip()
    QTest.mouseRelease(preview, left, none, across)
    assert list(session.state.overlays[0].points) == before


def test_symmetry_axes_and_the_scale_dial(gore_window: MainWindow) -> None:
    import numpy as np

    from envelopelab.project.overlays import outline_points

    panel, preview = _polygon_overlay(gore_window)
    session = gore_window.controller.session
    assert session is not None
    editor = panel.overlay_editor
    # Two axes: the square keeps its shape, stored as one slice (a single corner).
    editor.symmetry.setCurrentIndex(2)
    spec = session.state.overlays[0]
    assert spec.symmetry == 2 and spec.points == [(-0.4, 0.4)]
    assert preview.corners is not None and len(preview.corners) == 4
    # Drag one corner: all four follow (their images), in one undo step.
    depth = session.stack.index
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    corner = preview.to_screen(0.4, -0.4).toPoint()  # an image of the stored corner
    target = preview.to_screen(0.5, -0.3).toPoint()
    QTest.mousePress(preview, left, none, corner)
    QTest.mouseMove(preview, target)
    QTest.mouseRelease(preview, left, none, target)
    spec = session.state.overlays[0]
    assert spec.points[0] == pytest.approx((-0.5, 0.3), abs=0.01)
    assert session.stack.index == depth + 1
    outline = outline_points(spec)
    assert np.allclose(
        np.sort(np.abs(outline), axis=0), np.sort(np.abs(outline[:1]).repeat(4, 0), axis=0)
    )
    # Double click an edge off the axes: a corner is added in every slice (4); on an
    # axis it is its own mirror image (2 more).
    edge = preview.to_screen(-0.25, 0.3).toPoint()
    QTest.mouseDClick(preview, left, none, edge)
    assert len(outline_points(session.state.overlays[0])) == 8
    # The dial scales the whole shape: a turn of +100 steps doubles it, one undo step.
    before = np.asarray(session.state.overlays[0].points)
    depth = session.stack.index
    editor.scale_dial.setValue(100)
    editor._scale_done()
    after = np.asarray(session.state.overlays[0].points)
    assert np.allclose(after, 2.0 * before, atol=1e-4)
    assert session.stack.index == depth + 1 and editor.scale_dial.value() == 0
    # Back to no symmetry: the whole outline becomes the corners.
    editor.symmetry.setCurrentIndex(0)
    spec = session.state.overlays[0]
    assert spec.symmetry == 0 and len(spec.points) == 8


def test_an_overlay_shows_and_exports_its_own_pattern(
    gore_window: MainWindow, tmp_path: Path
) -> None:
    from envelopelab.export.qa import _check_cal_pdf, _page_boxes, _read_dxf

    gore_window.set_mode("shapes")
    panel = gore_window.shapes
    name = panel.add_overlay()
    assert name is not None
    panel.overlay_editor.changed.emit({"placement": {"across": 0.5}}, False)  # on a seam
    # Cut pieces: the overlay's piece; Checks: its fit; Envelope panels: its markings.
    assert panel.pieces.topLevelItemCount() == 1
    first = panel.pieces.topLevelItem(0)
    assert first is not None and first.text(0) == f"{name}-overlay"
    assert [p.label for p in panel.preview.pieces] == [f"{name}-overlay"]
    items = [panel.checks.topLevelItem(i) for i in range(panel.checks.topLevelItemCount())]
    checks = [item.text(0) for item in items if item is not None]
    assert any("fit on the envelope" in c for c in checks)
    _surface, layout, _error = panel.overlay_layout()
    assert layout is not None
    panels = {(r.gore, r.row) for r in layout.runs}
    assert len(panel.markings.sheets) == len(panels) >= 2
    assert panel.attachment.topLevelItemCount() == len(layout.runs)
    # Its own pattern: a 1:1 template and DXFs (mm), calibration lines as labelled.
    files = panel.export_overlay_pattern(tmp_path)
    names = {f.name for f in files}
    assert any(n.endswith(f"-{name}-overlay.pdf") for n in names)
    assert f"{name}-overlay.dxf" in names
    assert sum(n.startswith(f"{name}-mark-") for n in names) == len(panels)
    pdf = next(f for f in files if f.suffix == ".pdf")
    for k, (_w, _h, content) in enumerate(_page_boxes(pdf), 1):
        assert "%CAL" in content and _check_cal_pdf(pdf.name, k, content) == []
    assert _read_dxf(tmp_path / f"{name}-overlay.dxf")["units"] == 4
