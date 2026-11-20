"""Splitting a special shape's gore or panel in two, and the gore or panel being edited
highlighted in every view of the shape (Panel layout)."""

from __future__ import annotations

import numpy as np

from envelopelab_app.main_window import MainWindow
from envelopelab_app.placement_view import PANEL_FILL_EDITED, piece_colours


def test_a_selected_panel_is_highlighted_and_split_in_two(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    controller = gore_window.controller
    panel.add_shape("dome")
    assert controller.shapes.wait(120_000)
    spec = panel.spec()
    assert spec is not None
    count = spec.gores  # type: ignore[union-attr]
    assert not panel.split_piece_button.isEnabled()  # nothing picked yet
    # Picking row 3 of the widths table highlights gore 3 everywhere.
    panel.widths_table.setCurrentCell(2, 0)
    assert panel.edited_piece == 2
    assert panel.placement.data.edited_piece == 2
    assert panel.placement_data().edited_piece == 2  # the inlays of the other modes too
    assert panel.preview.edited == 2 and panel.meeting_pad.edited == 2
    assert panel.split_piece_button.isEnabled()
    (shape,) = panel.placement.data.shapes
    colours = piece_colours(shape.piece, shape.pieces, len(shape.triangles), True, 2)
    assert np.all(colours[shape.piece == 2] == PANEL_FILL_EDITED)
    assert not np.any(np.all(colours[shape.piece != 2] == PANEL_FILL_EDITED, axis=1))
    # Split it: one more gore, the two halves half as wide, the first half still picked.
    session = controller.session
    assert session is not None
    depth = session.stack.index
    panel.split_piece_button.click()
    spec = panel.spec()
    assert spec is not None and spec.gores == count + 1  # type: ignore[union-attr]
    assert spec.panel_widths[2] == spec.panel_widths[3] == 0.5
    assert panel.edited_piece == 2 and panel.widths_table.currentRow() == 2
    assert session.stack.index == depth + 1
    assert controller.shapes.wait(120_000)
    result = controller.shapes.result(spec.name)
    assert result is not None and result.design is not None, result
    assert panel.preview.edited == 2
    # Undo merges them again; another shape starts with nothing picked.
    session.undo()
    spec = panel.spec()
    assert spec is not None and spec.gores == count and spec.panel_widths == []  # type: ignore[union-attr]
    panel.add_shape("dome")
    assert panel.edited_piece is None and panel.placement.data.edited_piece is None


def test_the_meeting_pad_shows_a_piece_where_the_balloon_does(gore_window: MainWindow) -> None:
    # The pad is drawn as the shape is seen from outside the balloon: right is towards the
    # next gore (larger azimuth), up is up the tape.
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    assert gore_window.controller.shapes.wait(120_000)
    spec = panel.spec()
    assert spec is not None
    result = gore_window.controller.shapes.result(spec.name)
    assert result is not None and result.design is not None
    placed = result.design
    (shape,) = panel.placement_data().shapes
    pad = panel.meeting_pad
    for k in (1, 3, 6, 10):
        # On the shape: the piece's centre, across (towards the next gore) and up.
        centre = shape.points[shape.triangles[shape.piece == k]].mean(axis=(0, 1))
        rel = centre - shape.base3d
        hoop = np.array([-np.sin(placed.base_theta), np.cos(placed.base_theta), 0.0])
        across, up = float(rel @ hoop), float(rel @ placed.b1)
        # In the pad: the middle of its stretch of the rim.
        a, b = pad.seams[k], pad.seams[(k + 1) % len(pad.seams)]
        mid = a + ((b - a) % (2 * np.pi)) / 2.0
        x, y = pad.rim_at(float(mid))
        assert np.sign(x) == np.sign(across) and np.sign(y) == np.sign(up), k
