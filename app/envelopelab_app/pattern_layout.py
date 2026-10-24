"""Arranging pattern pieces to fill the drawing area (display only, never the cut layout).

Gore panels are tall and narrow. Stacked as an assembled gore they make one column that
fills only a narrow strip of a wide window. :func:`shelf_layout` instead puts the pieces
side by side on shelves, in their order, and chooses the number of shelves for which the
arrangement can be drawn largest in a view of the given aspect ratio.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ShelfLayout:
    """Where each piece goes, and the size of the whole arrangement (m).

    Attributes
    ----------
    positions : list of (float, float)
        Left edge and top edge of each piece's bounding box, in order; y grows downward
        (screen order), shelves from the top.
    width, height : float
        Extent of the arrangement.
    shelves : int
        Number of shelves used.
    """

    positions: list[tuple[float, float]]
    width: float
    height: float
    shelves: int


def _shelves(widths: Sequence[float], target: float, gap: float) -> list[list[int]]:
    """Consecutive pieces per shelf, starting a shelf when the next piece would make it
    wider than ``target`` (a piece wider than ``target`` gets a shelf of its own)."""
    out: list[list[int]] = [[]]
    width = 0.0
    for i, w in enumerate(widths):
        added = w if not out[-1] else width + gap + w
        if out[-1] and added > target:
            out.append([i])
            width = w
        else:
            out[-1].append(i)
            width = added
    return out


def shelf_layout(
    sizes: Sequence[tuple[float, float]], aspect: float, gap: float = 0.4
) -> ShelfLayout:
    """Pieces side by side on shelves, as large as possible in a view of ``aspect``.

    Parameters
    ----------
    sizes : sequence of (float, float)
        Width and height of each piece's bounding box, in order, m.
    aspect : float
        Width over height of the view (> 0).
    gap : float
        Space between pieces and between shelves, m.

    Returns
    -------
    ShelfLayout
        For every shelf count from 1 to the number of pieces, pieces are filled in order
        up to the width that count needs; the arrangement with the largest drawing scale
        :math:`\\min(A / W, 1 / H)` wins, the fewest shelves on a tie.
    """
    if not aspect > 0.0:
        raise ValueError("the view aspect ratio must be positive")
    if not sizes:
        return ShelfLayout([], 0.0, 0.0, 0)
    widths = [float(w) for w, _ in sizes]
    heights = [float(h) for _, h in sizes]
    best: tuple[float, list[list[int]]] | None = None
    for count in range(1, len(sizes) + 1):
        target = (sum(widths) + gap * (len(sizes) - count)) / count
        shelves = _shelves(widths, target, gap)
        width = max(sum(widths[i] for i in s) + gap * (len(s) - 1) for s in shelves)
        height = sum(max(heights[i] for i in s) for s in shelves) + gap * (len(shelves) - 1)
        scale = min(aspect / width, 1.0 / height)
        if best is None or scale > best[0] * (1.0 + 1e-9):
            best = (scale, shelves)
    assert best is not None
    shelves = best[1]
    positions: list[tuple[float, float]] = [(0.0, 0.0)] * len(sizes)
    top = 0.0
    width = 0.0
    for shelf in shelves:
        x = 0.0
        for i in shelf:
            positions[i] = (x, top)
            x += widths[i] + gap
        width = max(width, x - gap)
        top += max(heights[i] for i in shelf) + gap
    return ShelfLayout(positions, width, top - gap, len(shelves))
