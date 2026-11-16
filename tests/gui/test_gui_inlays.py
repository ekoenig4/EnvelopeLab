"""The balloon in 3D in every design mode, and the 3D / Simulation mode's selection tools
(ADR-0047)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab_app.main_window import MainWindow


def _placed(window: MainWindow) -> None:
    assert window.controller.shapes.wait(120_000)


def _page(window: MainWindow) -> str:
    """Object name of the mode page shown."""
    page = window.mode_stack.currentWidget()
    assert page is not None
    return page.objectName()


def test_the_shape_mode_shows_the_selected_row_or_point_on_the_balloon(
    gore_window: MainWindow,
) -> None:
    gore_window.mode_tabs.setCurrentIndex(0)  # Shape
    inlay = gore_window.gore_editor.inlay
    gore_window.controller.select("row:B")
    inlay.refresh()
    assert inlay.data.sketch is not None
    assert inlay.data.highlight is not None and inlay.data.highlight.key == "row:B"
    assert "row B" in inlay.caption.text()
    # The view turned to the row's panel (gore 1).
    focus = inlay.data.highlight.focus
    assert inlay.sketch.azimuth == pytest.approx(math.degrees(math.atan2(focus[1], focus[0])))
    # A control point picked on the profile wins over the workspace selection.
    gore_window.gore_editor.canvas.select([2])
    inlay.changed()
    inlay.refresh()
    assert inlay.data.highlight.key == "point:2"
    assert "control point 3" in inlay.caption.text()
    gore_window.gore_editor.canvas.select([])
    inlay.changed()
    inlay.refresh()
    assert inlay.data.highlight.key == "row:B"


def test_the_patterns_mode_shows_the_selected_row_on_the_balloon(
    gore_window: MainWindow,
) -> None:
    gore_window.show_panel("patterns")
    inlay = gore_window.patterns.inlay
    inlay.refresh()
    first = gore_window.patterns.selected_letter()
    assert inlay.data.highlight is not None and inlay.data.highlight.key == f"row:{first}"
    gore_window.controller.select("row:C")
    inlay.refresh()
    assert inlay.data.highlight.key == "row:C"
    bottom, top, _panel = inlay.data.highlight.lines
    assert top[:, 2].mean() > bottom[:, 2].mean()


def test_the_rigging_mode_highlights_the_component_clicked_or_edited(
    gore_window: MainWindow,
) -> None:
    gore_window.show_panel("rigging")
    rigging = gore_window.rigging
    rigging.add_parachute()
    rigging.add_flying_wires()
    inlay = rigging.inlay
    inlay.refresh()
    lines = gore_window.controller.rigging_polylines()
    assert len(inlay.data.context) == sum(len(v) for v in lines.values())
    rigging.cards["flying_wires"].clicked.emit("flying_wires")
    assert gore_window.controller.selection == "flying_wires"
    inlay.refresh()
    assert inlay.data.highlight is not None
    assert len(inlay.data.highlight.lines) == len(lines["flying_wires"])
    # Editing a value in a card selects its component.
    rigging._focus_changed(None, rigging.settings["overlap"])
    assert gore_window.controller.selection == "parachute"
    inlay.refresh()
    assert "parachute" in inlay.caption.text()


def test_the_inlays_draw_the_special_shapes_but_do_not_move_them(
    gore_window: MainWindow,
) -> None:
    gore_window.show_panel("shapes")
    gore_window.shapes.add_shape("dome")
    _placed(gore_window)
    gore_window.show_panel("patterns")
    inlay = gore_window.patterns.inlay
    inlay.refresh()
    assert len(inlay.data.shapes) == 1 and len(inlay.data.shapes[0].triangles) > 0
    assert inlay.data.place_at is None
    assert inlay.data.selected is None  # the row is faced, not the shape


def test_the_3d_mode_highlights_faces_and_nudges_the_selection(
    gore_window: MainWindow,
) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    session = gore_window.controller.session
    assert session is not None
    name = session.state.shapes[0].name
    gore_window.show_panel("view3d")
    view = gore_window.view3d
    # Selecting a shape from the 3D mode keeps the 3D mode (it is highlighted there).
    gore_window.controller.select(f"shape:{name}")
    assert _page(gore_window) == "simulateModePage"
    assert f"special shape {name}" in view.selection_label.text()
    h = view.selection_highlight()
    assert h is not None and len(h.lines) == 1
    assert np.allclose(h.lines[0][0], h.lines[0][-1])
    assert all(b.isEnabled() for b in view.nudge_buttons.values())
    s0 = session.state.shapes[0].placement.tape_position
    view.nudge_buttons["up"].click()
    assert session.state.shapes[0].placement.tape_position == pytest.approx(s0 + 0.05)
    # A row: highlighted, the nudge arrows off.
    gore_window.controller.select("row:A")
    assert "row A" in view.selection_label.text()
    assert not any(b.isEnabled() for b in view.nudge_buttons.values())
    # Symmetry axis… opens the live placement on the balloon.
    gore_window.controller.select(f"shape:{name}")
    view.axisRequested.emit()
    assert _page(gore_window) == "shapesModePage"
    assert panel.result_tabs.currentWidget() is panel.placement
    assert panel.placement.axis_bar.isVisibleTo(panel.placement)
    panel.cancel_axis()
