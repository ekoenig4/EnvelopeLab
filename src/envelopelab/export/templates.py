"""1:1 pattern templates of a build pack (PDF): one file per piece, one page per file.

Every piece to cut gets its own PDF, as a builder cuts them (ADR-0038):

* ``<slug>-panel-<R>.pdf``: envelope row ``R``, clean (cut once per gore);
* ``<slug>-panel-<R>-gore-<g>.pdf``: the panel ``R`` of gore ``g`` when a special shape
  is sewn on it or a feed hole is cut in it: the same panel with that panel's footprint
  lines, side ticks, numbered match marks and feed holes drawn on (every shape's marks
  on that panel), to mark one cut panel before assembly;
* ``<slug>-parachute-panel.pdf``, ``<slug>-parachute-centre.pdf``: the parachute pieces;
* ``<slug>-<shape>-<piece>.pdf``: every skin piece of every special shape.

The page is exactly the piece at 1:1 plus a 20 mm margin, so the **whole piece is always
on one page**, never split. It is upright when its height fits the roll (the row height
runs across the bolt, the gore width along the roll) and turned a quarter when only its
width fits; a piece larger than the roll both ways stays whole and its page says so in
red (it has to be cut from joined cloth or plotted in parts).

A page shows the cut outline (solid), the sewn outline (dotted), feature marks in red
(footprint lines, match marks, feed holes, side ticks), the finished widths and height in
blue, the panel letter, cut count, fabric and finished size, the warp (UP) arrow, a
legend, and two calibration lines, across and along the page. Their labels are generated
from the lengths that draw them; each line is preceded by a ``%CAL L T`` or ``%CALV L T``
comment in the page stream so that :mod:`envelopelab.export.qa` can measure it, and each
page by ``%PAGE <sheet> 1 1 <turn> <marking sheets drawn over it>``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.export.build_pack import Sheet

PT_PER_M = 72.0 / 0.0254
MARGIN = 0.02  # m round the cut outline (the header, legend and scales sit inside the piece)
CAL_LENGTHS = (0.5, 0.3, 0.2, 0.1)  # m, the longest that fits is drawn
BLACK = (0.0, 0.0, 0.0)
GREY = (0.35, 0.38, 0.42)
RED = (0.8, 0.1, 0.1)
BLUE = (0.11, 0.37, 0.71)


def piece_name(name: str) -> str:
    """A sheet name as it appears in a file name (letters kept as they are: ``eye-G1``)."""
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "piece"


def slug(name: str) -> str:
    """A file-name prefix from a design name (lower case, words joined by hyphens)."""
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return text or "design"


@dataclass
class Overlay:
    """Markings of one gore drawn over a shared panel (a marking sheet, relabelled)."""

    label: str
    lines: list[FloatArray] = field(default_factory=list)
    holes: list[tuple[float, float, float]] = field(default_factory=list)
    hole_cuts: list[tuple[float, float, float]] = field(default_factory=list)
    marks: list[tuple[float, float, str]] = field(default_factory=list)
    ticks: list[FloatArray] = field(default_factory=list)
    source: str = ""  # the marking sheet drawn


@dataclass
class TemplatePage:
    """One piece on its page: the sheet, its big title and the markings drawn over it."""

    sheet: Sheet
    title: str
    overlays: list[Overlay] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class TemplateFile:
    """One template PDF: its file name, a one-line description and its pages."""

    name: str
    description: str
    pages: list[TemplatePage]


def _letter(sheet: Sheet) -> str:
    return sheet.piece.removeprefix("row ").strip()


def _overlay(marking: Sheet) -> Overlay:
    label = marking.piece  # "gore 3 row D"
    gore = label.split(" row ")[0].upper()
    shape = marking.name.split("-mark-")[0]
    return Overlay(
        f"{shape} - {gore}",
        list(marking.lines),
        list(marking.holes),
        list(marking.hole_cuts),
        list(marking.marks),
        list(marking.ticks),
        marking.name,
    )


def template_files(name: str, sheets: Sequence[Sheet]) -> list[TemplateFile]:
    """The template files of a pack (module docstring), in reading order.

    Parameters
    ----------
    name : str
        Design name (for the file-name prefix, :func:`slug`).
    sheets : sequence of Sheet
        Every sheet of the pack (envelope rows, marking sheets, parachute, skin pieces).
    """
    stem = slug(name)
    rows = [s for s in sheets if s.kind == "envelope panel"]
    markings: dict[str, list[Sheet]] = {}
    for s in sheets:
        if s.kind == "marking":
            markings.setdefault(s.name.rsplit("-", 1)[1], []).append(s)
    files: list[TemplateFile] = []

    # Marking sheets by envelope panel: (row letter, gore) -> every shape's marks there.
    by_panel: dict[tuple[str, int], list[Sheet]] = {}
    for m in (m for ms in markings.values() for m in ms):
        gore = int(m.piece.split()[1])
        by_panel.setdefault((m.name.rsplit("-", 1)[1], gore), []).append(m)

    for row in rows:
        letter = _letter(row)
        files.append(
            TemplateFile(
                f"{stem}-panel-{letter}.pdf",
                f"panel {letter}, cut {row.cut_count}",
                [TemplatePage(row, f"PANEL {letter}")],
            )
        )
        for gore in sorted(g for (r, g) in by_panel if r == letter):
            marks = by_panel[(letter, gore)]
            shapes = sorted({m.name.split("-mark-")[0] for m in marks})
            notes = [
                f"MARK ONLY: one of the {row.cut_count} panels {letter} - the one for gore "
                f"{gore}; mark it before the envelope is assembled"
            ]
            for m in marks:
                notes += [n for n in m.notes if n not in notes]
            files.append(
                TemplateFile(
                    f"{stem}-panel-{letter}-gore-{gore}.pdf",
                    f"panel {letter} of gore {gore}, marked for {', '.join(shapes)}",
                    [
                        TemplatePage(
                            row,
                            f"PANEL {letter} - GORE {gore}",
                            [_overlay(m) for m in marks],
                            notes,
                        )
                    ],
                )
            )
    for s in sheets:
        if s.kind == "parachute panel":
            files.append(
                TemplateFile(
                    f"{stem}-{piece_name(s.name)}.pdf",
                    f"{s.piece}, cut {s.cut_count}",
                    [TemplatePage(s, s.piece.upper())],
                )
            )
    for s in sheets:
        if s.kind == "skin piece":
            shape = s.name.rsplit("-", 1)[0]
            files.append(
                TemplateFile(
                    f"{stem}-{piece_name(s.name)}.pdf",
                    f"special shape {shape}: skin piece {s.piece}, cut {s.cut_count}",
                    [TemplatePage(s, s.piece.upper())],
                )
            )
    return files


def shape_piece_files(name: str, sheets: Sequence[Sheet], shape: str) -> list[str]:
    """The template files of a special shape's skin pieces, in order."""
    stem = slug(name)
    return [
        f"{stem}-{piece_name(s.name)}.pdf"
        for s in sheets
        if s.kind == "skin piece" and s.name.rsplit("-", 1)[0] == shape
    ]


def calibration(length_available: float) -> tuple[float, float]:
    """The calibration line that fits in ``length_available`` (m): length and tick, m."""
    from envelopelab.export.build_pack import CALIBRATION_TICK

    for length in CAL_LENGTHS:
        if length <= length_available:
            return length, CALIBRATION_TICK if length >= 0.2 else 0.05
    return CAL_LENGTHS[-1], 0.05


@dataclass(frozen=True)
class PageLayout:
    """How a sheet sits on its pages: turned a quarter or not, and the bands (m, in the
    sheet's own y after turning) of each page."""

    turned: bool
    bands: list[tuple[float, float]]
    width: float  # page width, m
    height: float  # page height of a full band, m


def layout(sheet: Sheet, roll_width: float) -> PageLayout:
    """The page of ``sheet`` on a roll ``roll_width`` m wide (module docstring): always
    the whole piece on one page, upright when its height fits the roll, turned a quarter
    when only its width fits, and upright (marked as larger than the roll) otherwise."""
    lo, hi = sheet.cut.min(axis=0), sheet.cut.max(axis=0)
    w = float(hi[0] - lo[0]) + 2 * MARGIN
    h = float(hi[1] - lo[1]) + 2 * MARGIN
    if h > roll_width and w <= roll_width:
        return PageLayout(True, [(float(lo[0]) - MARGIN, float(hi[0]) + MARGIN)], h, w)
    return PageLayout(False, [(float(lo[1]) - MARGIN, float(hi[1]) + MARGIN)], w, h)


def oversize(sheet: Sheet, roll_width: float) -> bool:
    """True when a piece is larger than the roll both ways (it cannot be cut from one
    width of cloth; its page says so)."""
    span = sheet.cut.max(axis=0) - sheet.cut.min(axis=0) + 2 * MARGIN
    return bool(min(span) > roll_width)


def _edge_length(points: FloatArray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def dimensions(sheet: Sheet) -> list[tuple[str, float]]:
    """Finished dimensions drawn on a page: bottom and top widths and height, m."""
    out: list[tuple[str, float]] = []
    for edge in ("bottom", "top"):
        if edge in sheet.edges and len(sheet.edges[edge]) > 1:
            out.append((edge, _edge_length(sheet.edges[edge])))
    out.append(("height", sheet.finished_size[1]))
    return out


def write_template_pdf(
    tfile: TemplateFile, path: str | Path, roll_width: float
) -> list[dict[str, object]]:
    """Write one template file; returns a record of every page written (sheet, band,
    bands, turned, markings drawn over it). Sheet names are free text (a shape called
    "left ear"), so the records are kept as data, never parsed back from the page."""
    from envelopelab.report.pdf import PdfCanvas

    canvas: PdfCanvas | None = None
    written: list[dict[str, object]] = []
    for tpage in tfile.pages:
        sheet = tpage.sheet
        lay = layout(sheet, roll_width)
        lo, hi = sheet.cut.min(axis=0), sheet.cut.max(axis=0)
        for k, (b0, b1) in enumerate(lay.bands):
            size = (lay.width * PT_PER_M, (b1 - b0) * PT_PER_M)
            if canvas is None:
                canvas = PdfCanvas(size)
            else:
                canvas.new_page(size)
            x_ref = float(lo[0]) - MARGIN

            def p(
                x: float,
                y: float,
                b0: float = b0,
                x_ref: float = x_ref,
                turned: bool = lay.turned,
                y_top: float = float(hi[1]) + MARGIN,
            ) -> tuple[float, float]:
                if turned:  # the piece's x runs up the page, its y to the left
                    return ((y_top - y) * PT_PER_M, (x - b0) * PT_PER_M)
                return ((x - x_ref) * PT_PER_M, (y - b0) * PT_PER_M)

            over = ",".join(o.source for o in tpage.overlays if o.source) or "-"
            line = f"PAGE {sheet.name} {k + 1} {len(lay.bands)} {90 if lay.turned else 0} {over}"
            canvas.comment(line)
            written.append(
                {
                    "sheet": sheet.name,
                    "band": k + 1,
                    "bands": len(lay.bands),
                    "turned": lay.turned,
                    "markings": [o.source for o in tpage.overlays if o.source],
                }
            )
            _draw_page(canvas, tpage, p, size, k, len(lay.bands))
            if oversize(sheet, roll_width):
                u = min(max(min(size) / 400.0, 1.0), 12.0)
                warn = (
                    f"LARGER THAN THE {roll_width * 1000:.0f} MM ROLL BOTH WAYS - join cloth "
                    "before cutting, or plot this sheet in parts"
                )
                canvas.text(10 * u, 8 * u, warn, size=4 * u, bold=True, color=RED)
    if canvas is None:
        raise ValueError(f"template {tfile.name} has no pages")
    canvas.save(path)
    return written


def _draw_page(
    canvas: object,
    tpage: TemplatePage,
    p: Callable[[float, float], tuple[float, float]],
    size: tuple[float, float],
    band: int,
    bands: int,
) -> None:
    from envelopelab.export.build_pack import MM, calibration_label
    from envelopelab.report.pdf import PdfCanvas

    assert isinstance(canvas, PdfCanvas)
    sheet = tpage.sheet
    # Text scales with the piece so that it reads on a sheet a metre or more across.
    u = min(max(min(size) / 400.0, 1.0), 12.0)
    pts: Callable[[FloatArray], list[tuple[float, float]]] = lambda a: [  # noqa: E731
        p(float(x), float(y)) for x, y in a
    ]
    canvas.polygon(pts(sheet.cut), stroke=BLACK, width=1.0)
    canvas.polygon(pts(sheet.finished), stroke=GREY, width=0.6, dash=(3.0, 3.0))
    ang = np.linspace(0.0, 2 * math.pi, 73)
    overlays = [Overlay("", sheet.lines, sheet.holes, sheet.hole_cuts, sheet.marks, sheet.ticks)]
    overlays += tpage.overlays
    for ov in overlays:
        for ln in ov.lines:
            canvas.polygon(pts(ln), stroke=RED, width=0.9, dash=(6.0, 3.0), closed=False)
        for x, y, r in ov.holes:
            ring = np.column_stack((x + r * np.cos(ang), y + r * np.sin(ang)))
            canvas.polygon(pts(ring), stroke=RED, width=0.9)
        for x, y, r in ov.hole_cuts:
            if r > 0.0:
                ring = np.column_stack((x + r * np.cos(ang), y + r * np.sin(ang)))
                canvas.polygon(pts(ring), stroke=BLACK, width=0.8)
        for seg in ov.ticks:
            (ax, ay), (bx, by) = pts(seg)
            canvas.line(ax, ay, bx, by, color=RED, width=0.8)
        for x, y, text in ov.marks:
            cx, cy = p(x, y)
            canvas.line(cx - 4 * u, cy, cx + 4 * u, cy, color=RED, width=0.8)
            canvas.line(cx, cy - 4 * u, cx, cy + 4 * u, color=RED, width=0.8)
            canvas.text(cx + 6 * u, cy + 6 * u, text, size=3 * u, color=RED)
        if ov.label and ov.lines:
            centre = np.vstack(ov.lines).mean(axis=0)
            lx, ly = p(float(centre[0]), float(centre[1]))
            canvas.text(lx - 1.8 * u * len(ov.label), ly, ov.label.upper(), size=4 * u, color=RED)
    for x, y, text in sheet.texts:
        tx, ty = p(x, y)
        canvas.text(tx - 1.3 * u * len(text), ty - 1.5 * u, text, size=3 * u)
    # Finished dimensions in blue, from the drawn edges.
    lo, hi = sheet.finished.min(axis=0), sheet.finished.max(axis=0)
    for name, value in dimensions(sheet) if sheet.kind != "skin piece" else []:
        if name in sheet.edges:
            e = sheet.edges[name]
            a, b = e[0], e[-1]
            inset = -0.04 if name == "top" else 0.04
            (ax, ay), (bx, by) = (
                p(float(a[0]), float(a[1]) + inset),
                p(float(b[0]), float(b[1]) + inset),
            )
            canvas.line(ax, ay, bx, by, color=BLUE, width=0.8)
            mx, my = (ax + bx) / 2, (ay + by) / 2
            canvas.text(mx - 8 * u, my + 2 * u, f"{value * MM:.0f} mm", size=4 * u, color=BLUE)
        else:
            x = float(hi[0]) - 0.06
            (ax, ay), (bx, by) = p(x, float(lo[1])), p(x, float(hi[1]))
            canvas.line(ax, ay, bx, by, color=BLUE, width=0.8)
            label = f"{value * MM:.0f} mm"
            canvas.text(
                (ax + bx) / 2 - 2.4 * u * len(label), (ay + by) / 2, label, 4 * u, color=BLUE
            )
    # Everything else sits inside the piece (the page is only as large as the piece):
    # positions are taken from the part of the cut outline shown on this page.
    pw, ph = size
    shown = np.array(pts(sheet.cut))
    x0p, x1p = max(float(shown[:, 0].min()), 0.0), min(float(shown[:, 0].max()), pw)
    y0p, y1p = max(float(shown[:, 1].min()), 0.0), min(float(shown[:, 1].max()), ph)
    cx, cy = (x0p + x1p) / 2, (y0p + y1p) / 2
    span_x, span_y = x1p - x0p, y1p - y0p
    title = tpage.title
    big = min(14.0 * u, 0.6 * span_x / max(len(title), 1) / 0.62)
    canvas.text(cx - 0.31 * big * len(title), cy + 2 * u, title, size=big, bold=True, color=GREY)
    w, h = sheet.finished_size
    info = [
        f"CUT {sheet.cut_count} - {sheet.fabric}" if sheet.cut_count else "MARK ONLY (cut 0)",
        " - ".join(f"{n} {v * MM:.0f}" for n, v in dimensions(sheet)) + " mm finished",
    ]
    for j, text in enumerate(info):
        canvas.text(cx - 1.25 * u * len(text), cy - 5 * u - 5 * u * j, text, size=4 * u)
    # Warp arrow (UP the piece), in the piece's own direction.
    lo, hi = sheet.finished.min(axis=0), sheet.finished.max(axis=0)
    mid_x = float(lo[0] + hi[0]) / 2 + 0.15 * float(hi[0] - lo[0])
    gx, gy = p(mid_x, float(lo[1]) + 0.40 * float(hi[1] - lo[1]))
    gx2, gy2 = p(mid_x, float(lo[1]) + 0.60 * float(hi[1] - lo[1]))
    canvas.line(gx, gy, gx2, gy2, width=1.0)
    ux, uy = gx2 - gx, gy2 - gy
    n = math.hypot(ux, uy) or 1.0
    ux, uy = ux / n, uy / n
    a, b = 5 * u, 3 * u
    canvas.line(gx2, gy2, gx2 - a * ux + b * uy, gy2 - a * uy - b * ux, width=1.0)
    canvas.line(gx2, gy2, gx2 - a * ux - b * uy, gy2 - a * uy + b * ux, width=1.0)
    canvas.text(gx2 + 3 * u, gy2 + 2 * u, "UP / warp", size=3.5 * u)
    # Header (generated from the sheet data), notes and legend near the top of the piece.
    head = sheet.header() + (f"  [band {band + 1} of {bands}]" if bands > 1 else "")
    top = y1p - 0.12 * span_y
    hs = min(4 * u, 0.8 * span_x / max(len(head), 1) / 0.55)
    canvas.text(cx - 0.27 * hs * len(head), top, head, size=hs, bold=True)
    for j, note in enumerate([*tpage.notes, *sheet.notes][:3]):
        ns = min(3 * u, 0.8 * span_x / max(len(note), 1) / 0.52)
        canvas.text(
            cx - 0.26 * ns * len(note), top - (hs + 1.2 * ns) * (j + 1), note, ns, color=GREY
        )
    legend = [
        ("CUT LINE - cut here", BLACK, None),
        ("SEW LINE - finished (dotted)", GREY, (3.0, 3.0)),
        ("RED - feature marks", RED, (6.0, 3.0)),
        ("BLUE - finished dimensions", BLUE, None),
    ]
    lx = cx - 0.30 * span_x
    for j, (text, colour, dash) in enumerate(legend):
        y = top - 20 * u - 4 * u * j
        canvas.polygon([(lx, y + u), (lx + 14 * u, y + u)], stroke=colour, dash=dash, closed=False)
        canvas.text(lx + 16 * u, y, text, size=3 * u, color=colour)
    # Calibration lines across and along the page, inside the piece; their labels come
    # from the lengths that draw them.
    across, tick = calibration(0.4 * span_x / PT_PER_M)
    ax0, ay0 = cx - across * PT_PER_M / 2, y0p + 0.22 * span_y
    canvas.comment(f"CAL {across * MM:.0f} {tick * MM:.0f}")
    canvas.line(ax0, ay0, ax0 + across * PT_PER_M, ay0, width=1.0)
    for j in range(int(round(across / tick)) + 1):
        xt = ax0 + j * tick * PT_PER_M
        canvas.line(xt, ay0, xt, ay0 + 3 * u, width=0.6)
    canvas.text(ax0, ay0 - 4 * u, calibration_label(across, tick), size=3 * u)
    along, vtick = calibration(0.4 * span_y / PT_PER_M)
    vx, vy = cx - 0.22 * span_x, cy - along * PT_PER_M / 2
    canvas.comment(f"CALV {along * MM:.0f} {vtick * MM:.0f}")
    canvas.line(vx, vy, vx, vy + along * PT_PER_M, width=1.0)
    for j in range(int(round(along / vtick)) + 1):
        yt = vy + j * vtick * PT_PER_M
        canvas.line(vx, yt, vx + 3 * u, yt, width=0.6)
    canvas.text(vx + 4 * u, vy - 4 * u, "along: " + calibration_label(along, vtick), size=3 * u)
