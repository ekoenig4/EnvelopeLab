"""Colour plan of a build pack: the panels in their colours and the cloth per colour.

Written with the planning documents when the design has panel colours (ADR-0055):

* ``<slug>-colour-plan.pdf``: page 1 draws every gore side by side as cut (the row panels
  stacked mouth to crown, :func:`envelopelab.export.planning.gore_outline`), each panel
  filled with its colour (a half-gore panel each half in its own), and every special
  shape as a grid of its pieces (one column per gore or panel round the axis, one band
  per tier, its cap on top;
  :class:`envelopelab.project.colours.ShapeGrid`); page 2 lists the cloth per colour;
* ``<slug>-colour-cloth.csv``: the same table, for ordering cloth.

The cloth table sums, for every colour, the pieces cut in it and their finished and cut
areas (m², the cut area including seam allowances, before nesting waste). Pieces with no
colour chosen (and the parachute, which is not coloured) are one row, so the table's
totals equal the fabric totals of the cut list.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from envelopelab.export.documents import pdf_text
from envelopelab.geometry.polygon import signed_area
from envelopelab.project.colours import HALVES, PanelRef

if TYPE_CHECKING:
    from envelopelab.export.build_pack import Sheet
    from envelopelab.export.shop import PackContext
    from envelopelab.features.primitives import PrimitiveDesign
    from envelopelab.project.colours import ShapeGrid

#: Fill of a panel with no colour chosen (light grey, display only).
NO_COLOUR = (0.93, 0.94, 0.96)
#: Label of pieces with no colour chosen.
NONE_LABEL = "no colour chosen"


def cloth_per_colour(sheets: Sequence[Sheet]) -> list[tuple[str | None, int, float, float]]:
    """Pieces and cloth area per colour over every piece cut.

    Parameters
    ----------
    sheets : sequence of Sheet
        The pack's sheets (with :attr:`~envelopelab.export.build_pack.Sheet.colours`).

    Returns
    -------
    list of (str or None, int, float, float)
        Colour (``#rrggbb``; None: no colour chosen, last), pieces, finished area and cut
        area, m²; the most cloth first.
    """
    totals: dict[str | None, tuple[int, float, float]] = {}
    for s in sheets:
        if s.cut_count <= 0:
            continue
        fin, cut = abs(signed_area(s.finished)), abs(signed_area(s.cut))
        if s.colours:
            counts = [(colour, len(where)) for colour, where in s.colours]
        else:
            counts = [(None, s.cut_count)]
        for colour, n in counts:
            a, b, c = totals.get(colour, (0, 0.0, 0.0))
            totals[colour] = (a + n, b + fin * n, c + cut * n)
    rows = [(colour, n, fin, cut) for colour, (n, fin, cut) in totals.items()]
    return sorted(rows, key=lambda r: (r[0] is None, -r[3]))


def primitive_grid(p: PrimitiveDesign) -> ShapeGrid:
    """The grid of a placed special shape's pieces (its count, widths, splits and cap)."""
    from envelopelab.project.colours import ShapeGrid

    prim = p.primitive
    n = int(prim.pieces)
    widths = np.asarray(getattr(prim, "panel_widths", ()) or [1.0] * n, dtype=np.float64)
    widths = widths / widths.sum()
    splits = getattr(prim, "splits", ()) or ()
    return ShapeGrid(
        prim.name,
        n,
        tuple(float(w) for w in widths),
        (0.0, *(float(f) for f in splits), 1.0),
        any(c.role == "tip" for c in p.pieces),
    )


def half_outline(outline: np.ndarray, side: str) -> np.ndarray:
    """The ``left`` (x <= 0) or ``right`` (x >= 0) part of a closed outline (m), cut down
    x = 0 as a half gore is (Sutherland-Hodgman clipping against one line)."""
    sign = -1.0 if side == "left" else 1.0
    pts = np.asarray(outline, dtype=np.float64)
    out: list[np.ndarray] = []
    for a, b in zip(pts, np.roll(pts, -1, axis=0), strict=True):
        a_in, b_in = sign * a[0] >= 0.0, sign * b[0] >= 0.0
        if a_in:
            out.append(a)
        if a_in != b_in:
            t = a[0] / (a[0] - b[0])
            out.append(a + t * (b - a))
    return np.asarray(out, dtype=np.float64).reshape(-1, 2)


def _rgb(colour: str | None) -> tuple[float, float, float]:
    from envelopelab.project.colours import colour_rgb

    return NO_COLOUR if colour is None else colour_rgb(colour)


def write_colour_plan(ctx: PackContext, out: Path) -> list[tuple[Path, str]]:
    """Write the colour plan PDF and the cloth CSV (module docstring); returns each file
    with its description. Nothing is written when the design has no panel colours."""
    from envelopelab.export.planning import gore_outline
    from envelopelab.export.shop import A3_LANDSCAPE
    from envelopelab.report.pdf import PdfCanvas

    colours = ctx.colours
    if colours is None or colours.is_empty():
        return []
    page_w, page_h = A3_LANDSCAPE
    canvas = PdfCanvas(A3_LANDSCAPE)
    margin = 40.0
    name = ctx.design.meta.name
    canvas.text(margin, page_h - margin, pdf_text(f"Colour plan - {name}"), 16, bold=True)
    canvas.text(
        margin,
        page_h - margin - 18,
        "every panel in its colour, gores side by side as cut (gore 1 at the left); "
        "grey: no colour chosen",
        9,
    )
    grids = [primitive_grid(p) for p in ctx.primitives]
    stack = gore_outline(ctx)
    top = page_h - margin - 50
    bottom = margin + 20
    if stack:
        height = stack[-1][2] + float(np.ptp(stack[-1][1][:, 1]))
        widest = max(float(np.ptp(o[:, 0])) for _l, o, _y in stack)
        n = ctx.gores
        share = 0.72 if grids else 1.0
        sc = min((page_w - 2 * margin) * share / (n * widest * 1.1), (top - bottom) / height)
        halved = {s.letter for s in ctx.sheets if s.whole is not None}
        for k in range(1, n + 1):
            ox = margin + (k - 0.5) * widest * 1.1 * sc
            for letter, outline, y in stack:
                if letter in halved:
                    # Each half in its own colour (left: towards the previous gore).
                    parts = [
                        (
                            half_outline(outline, side),
                            colours.colour_of(PanelRef(None, letter, k, side)),
                        )
                        for side in HALVES
                    ]
                else:
                    parts = [(outline, colours.colour_of(PanelRef(None, letter, k)))]
                for part, colour in parts:
                    pts = [(ox + x * sc, bottom + (y + yy) * sc) for x, yy in part]
                    canvas.polygon(pts, fill=_rgb(colour), stroke=(0.2, 0.2, 0.2), width=0.5)
            canvas.text(ox - 4, bottom + height * sc + 6, str(k), 8)
        for letter, outline, y in stack:
            mid = bottom + (y + 0.5 * float(np.ptp(outline[:, 1]))) * sc
            canvas.text(margin - 14, mid, letter, 8)
        x0 = margin + n * widest * 1.1 * sc + 30
    else:
        x0 = margin
    box_w = page_w - margin - x0
    y = top
    for grid in grids:
        h = min(90.0, (top - bottom) / max(len(grids), 1) - 30)
        w = min(box_w, max(h, grid.pieces * h / 6.0))
        cap = 0.14 if grid.cap else 0.0
        y_low = y - (1.0 + cap) * h
        canvas.text(x0, y + 6, pdf_text(grid.name), 9, bold=True)
        for ref, cell in grid.cells():
            colour = colours.colour_of(ref)
            pts = [(x0 + u * w, y_low + v * h) for u, v in cell]
            canvas.polygon(pts, fill=_rgb(colour), stroke=(0.2, 0.2, 0.2), width=0.4)
        y = y_low - 30
    # Page 2: cloth per colour.
    rows = cloth_per_colour(ctx.sheets)
    canvas.new_page()
    canvas.text(margin, page_h - margin, pdf_text(f"Cloth per colour - {name}"), 16, bold=True)
    canvas.text(
        margin,
        page_h - margin - 18,
        "pieces cut in each colour and their area; cut area includes seam allowances, "
        "not nesting waste",
        9,
    )
    columns = (margin + 30, margin + 160, margin + 240, margin + 380)
    y = page_h - margin - 50
    for x, text in zip(
        columns, ("Colour", "Pieces", "Finished area (m2)", "Cut area (m2)"), strict=True
    ):
        canvas.text(x, y, text, 10, bold=True)
    for colour, n, fin, cut in rows:
        y -= 18
        canvas.rect(margin, y - 3, 16, 12, fill=_rgb(colour), stroke=(0.2, 0.2, 0.2))
        values = (colour or NONE_LABEL, str(n), f"{fin:.2f}", f"{cut:.2f}")
        for x, text in zip(columns, values, strict=True):
            canvas.text(x, y, text, 10)
    y -= 22
    total = (sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows))
    for x, text in zip(
        columns,
        ("Total", str(total[0]), f"{total[1]:.2f}", f"{total[2]:.2f}"),
        strict=True,
    ):
        canvas.text(x, y, text, 10, bold=True)
    pdf = out / ctx.file("colour-plan.pdf")
    canvas.save(pdf)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["colour", "pieces", "finished_area_m2", "cut_area_m2"])
    for colour, n, fin, cut in rows:
        writer.writerow([colour or NONE_LABEL, n, f"{fin:.4f}", f"{cut:.4f}"])
    table = out / ctx.file("colour-cloth.csv")
    table.write_text(buffer.getvalue(), encoding="utf-8")
    return [
        (pdf, "colour plan: every panel in its colour, cloth per colour"),
        (table, "cloth per colour: pieces, finished and cut area (m2)"),
    ]


__all__ = [
    "NONE_LABEL",
    "cloth_per_colour",
    "half_outline",
    "primitive_grid",
    "write_colour_plan",
]
