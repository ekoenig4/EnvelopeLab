"""Special shapes drawn by their cut panels in the placement views and inlays."""

from __future__ import annotations

import numpy as np

from envelopelab_app.main_window import MainWindow
from envelopelab_app.placement_view import PANEL_FILL, PANEL_FILL_SELECTED, piece_colours


def test_neighbouring_pieces_have_different_shades() -> None:
    for pieces in (2, 5, 8, 9):
        piece = np.arange(pieces)
        colours = piece_colours(piece, pieces, pieces, selected=False)
        for i in range(pieces):
            assert not np.array_equal(colours[i], colours[(i + 1) % pieces]), (pieces, i)
    # A tip disc has its own shade; a selected shape is tinted.
    tip = piece_colours(np.array([0, 1, 4]), 4, 3, selected=False)
    assert tuple(tip[2]) == PANEL_FILL[3]
    assert tuple(piece_colours(np.array([0]), 4, 1, selected=True)[0]) == PANEL_FILL_SELECTED[0]
    # Unknown pieces: one shade.
    assert piece_colours(None, 4, 3, selected=False).tolist() == [list(PANEL_FILL[0])] * 3


def test_a_placed_shape_carries_its_pieces_and_seams(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    gore_window.shapes.add_shape("dome")
    assert gore_window.controller.shapes.wait(120_000)
    (shape,) = gore_window.shapes.placement_data().shapes
    assert shape.piece is not None and len(shape.piece) == len(shape.triangles)
    assert shape.pieces > 1
    assert set(shape.piece.tolist()) >= set(range(shape.pieces))
    assert len(shape.seams) >= shape.pieces  # every gore seam, plus splits and the cap
    for seam in shape.seams:
        assert seam.shape[1] == 3
