"""Arranging pattern pieces to fill the view (display only)."""

from __future__ import annotations

import pytest

from envelopelab_app.pattern_layout import shelf_layout


def _boxes(
    layout_positions: list[tuple[float, float]], sizes: list[tuple[float, float]]
) -> list[tuple[float, float, float, float]]:
    """(left, top, right, bottom) of every placed piece."""
    return [(x, y, x + w, y + h) for (x, y), (w, h) in zip(layout_positions, sizes, strict=True)]


def test_tall_pieces_go_side_by_side_in_a_wide_view() -> None:
    sizes = [(1.0, 2.4)] * 4  # four gore rows, taller than wide
    wide = shelf_layout(sizes, aspect=2.4, gap=0.4)
    assert wide.shelves == 1
    assert [x for x, _ in wide.positions] == pytest.approx([0.0, 1.4, 2.8, 4.2])
    assert wide.width == pytest.approx(5.2) and wide.height == pytest.approx(2.4)
    # In a tall view the same pieces stack in more shelves.
    tall = shelf_layout(sizes, aspect=0.4, gap=0.4)
    assert tall.shelves > 1 and tall.height > tall.width


def test_pieces_keep_their_order_and_never_overlap() -> None:
    sizes = [(0.8, 1.0), (2.9, 1.7), (2.9, 1.7), (2.6, 1.7), (1.5, 1.7), (1.2, 2.4), (0.6, 0.6)]
    for aspect in (0.5, 1.0, 1.6, 3.0):
        layout = shelf_layout(sizes, aspect)
        boxes = _boxes(layout.positions, sizes)
        for a, b in zip(boxes, boxes[1:], strict=False):
            assert b[0] >= a[2] or b[1] >= a[3]  # right of it, or on a lower shelf
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
        assert max(b[2] for b in boxes) == pytest.approx(layout.width)
        assert max(b[3] for b in boxes) == pytest.approx(layout.height)


def test_the_chosen_shelf_count_draws_largest() -> None:
    sizes = [(1.0, 2.4)] * 9
    best = shelf_layout(sizes, aspect=1.6)
    scale = min(1.6 / best.width, 1.0 / best.height)
    for shelves in (1, 9):  # one row, one column: both draw smaller in a 1.6 view
        width = 9 * 1.0 + 8 * 0.4 if shelves == 1 else 1.0
        height = 2.4 if shelves == 1 else 9 * 2.4 + 8 * 0.4
        assert scale > min(1.6 / width, 1.0 / height)


def test_edge_cases() -> None:
    assert shelf_layout([], 1.0).positions == []
    with pytest.raises(ValueError, match="aspect"):
        shelf_layout([(1.0, 1.0)], 0.0)
