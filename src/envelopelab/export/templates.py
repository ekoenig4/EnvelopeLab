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
on one page**, never split. Pages are drawn in the print roll's frame (pack format 4,
ADR-0042): the **page width runs across the roll** and is never wider than it, the
**page height runs along the roll** and may be any length, so a page prints at 100 %
without being rotated. The piece is turned on the page to fit (:func:`roll_fit`): a
quarter turn first, the row height across the roll as panels are cut across the bolt,
then upright, then the narrowest turn of a piece that fits no other way. A piece wider
than the roll at any turn stays whole and its page says so in red (join paper or plot it
in parts). The bottom margin of every page says how it goes on the roll: an arrow across
the page with its width and the roll's, and the piece's turn; the UP / warp arrow turns
with the piece, so the template is laid on the cloth by its grain, not by the page.

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
    from envelopelab.features.primitives import DesignCheck

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


#: Turns tried first, in order (deg, counter-clockwise on the page): the row height across
#: the roll, as panels are cut across the bolt (the shop pack's rule), then upright.
PREFERRED_TURNS = (90.0, 0.0)


def turn_points(points: FloatArray, angle: float) -> FloatArray:
    """``points`` (m) turned ``angle`` degrees counter-clockwise about the origin."""
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    pts = np.asarray(points, dtype=np.float64)
    out: FloatArray = np.column_stack(
        [c * pts[:, 0] - s * pts[:, 1], s * pts[:, 0] + c * pts[:, 1]]
    )
    return out


@dataclass(frozen=True)
class RollFit:
    """How a piece's 1:1 page lies on the print roll.

    The page is drawn in the roll's frame: its **width runs across the roll** (it must not
    be wider than the roll) and its **height along the roll** (any length). The page is
    the cut outline, turned ``angle`` degrees, plus :data:`MARGIN` all round.

    Attributes
    ----------
    angle : float
        Turn of the piece on the page, deg counter-clockwise: 90 puts the piece's height
        (its UP / warp arrow) across the roll, 0 is upright, anything else the narrowest
        turn of a piece that fits no other way.
    across : float
        Page width, across the roll, m.
    along : float
        Page height, along the roll, m.
    roll_width : float
        Roll width, m.
    """

    angle: float
    across: float
    along: float
    roll_width: float

    @property
    def fits(self) -> bool:
        """True when the page is no wider than the roll."""
        return self.across <= self.roll_width

    @property
    def oversize(self) -> bool:
        """True when the piece is wider than the roll however it is turned."""
        return not self.fits

    @property
    def short_side(self) -> float:
        """The page's width across the roll, m (the narrowest found)."""
        return self.across

    def describe(self) -> str:
        """How the piece is printed, in words (e.g. ``turned 90° (its height across the
        roll)``)."""
        if self.angle == 90.0:
            return "turned 90° (its height across the roll)"
        if self.angle == 0.0:
            return "upright (its width across the roll)"
        return f"turned {self.angle:.1f}°"


def roll_fit(cut: FloatArray, roll_width: float) -> RollFit:
    """How the 1:1 page of a piece with cut outline ``cut`` lies on the roll.

    The turns of :data:`PREFERRED_TURNS` are tried in order and the first whose page is
    no wider than the roll is taken. Otherwise the piece is turned to its narrowest: the
    width of a convex outline is least across one of its hull edges (rotating calipers,
    [Toussaint]), so every hull edge is laid along the roll in turn and the narrowest
    page kept; when even that is wider than the roll the piece is oversize.

    Parameters
    ----------
    cut : ndarray, shape (n, 2)
        Cut outline of the piece, m.
    roll_width : float
        Width of the roll the page is printed on, m.

    Returns
    -------
    RollFit
        Turn (deg) and page size across and along the roll (m).

    References
    ----------
    .. [Toussaint] G. T. Toussaint, "Solving geometric problems with the rotating
       calipers", Proc. IEEE MELECON '83 (1983).
    """
    pts = np.asarray(cut, dtype=np.float64)

    def page(angle: float) -> RollFit:
        span = np.ptp(turn_points(pts, angle), axis=0)
        return RollFit(
            angle, float(span[0]) + 2 * MARGIN, float(span[1]) + 2 * MARGIN, float(roll_width)
        )

    for angle in PREFERRED_TURNS:
        fit = page(angle)
        if fit.fits:
            return fit
    from scipy.spatial import ConvexHull

    hull = pts[ConvexHull(pts).vertices]
    edges = np.roll(hull, -1, axis=0) - hull
    # Turn each edge to run up the page (along the roll); angles in (-90, 90]. Every
    # turn's width across the roll at once: hull x after the turn, per turn (row).
    turns = np.round(90.0 - np.mod(np.degrees(np.arctan2(edges[:, 1], edges[:, 0])), 180.0), 3)
    a = np.radians(turns)
    across = np.ptp(np.cos(a)[:, None] * hull[:, 0] - np.sin(a)[:, None] * hull[:, 1], axis=1)
    return page(float(turns[int(np.argmin(across))]))


@dataclass(frozen=True)
class PageLayout:
    """How a sheet sits on its page, in the roll's frame (:class:`RollFit`): the turn
    (deg), the page width across the roll and height along it (m), and the lower-left
    corner (m) of the turned cut outline, :data:`MARGIN` inside the page's corner."""

    angle: float
    width: float
    height: float
    origin: tuple[float, float]

    def to_page(self, x: float, y: float) -> tuple[float, float]:
        """Page coordinates (pt) of the sheet point ``(x, y)`` (m)."""
        ((px, py),) = turn_points(np.array([[x, y]]), self.angle)
        return (
            (float(px) - self.origin[0] + MARGIN) * PT_PER_M,
            (float(py) - self.origin[1] + MARGIN) * PT_PER_M,
        )


def layout(sheet: Sheet, roll_width: float) -> PageLayout:
    """The page of ``sheet`` on a roll ``roll_width`` m wide (:func:`roll_fit`): always
    the whole piece on one page, the page's width across the roll and height along it."""
    fit = roll_fit(sheet.cut, roll_width)
    lo = turn_points(sheet.cut, fit.angle).min(axis=0)
    return PageLayout(fit.angle, fit.across, fit.along, (float(lo[0]), float(lo[1])))


def oversize(sheet: Sheet, roll_width: float) -> bool:
    """True when a piece is wider than the roll however it is turned (it cannot be
    printed on one width of the roll; its page says so)."""
    return roll_fit(sheet.cut, roll_width).oversize


def roll_checks(pieces: Sequence[tuple[str, FloatArray]], roll_width: float) -> list[DesignCheck]:
    """Check that every piece's 1:1 page fits the roll (:func:`roll_fit`).

    A piece whose page is wider than the roll however it is turned cannot be printed on
    one width of the roll: it gets a *warning* of its own (paper must be joined, or the
    piece split with more panels or a horizontal split). When every piece fits, one
    informative check gives the widest page across the roll.

    Parameters
    ----------
    pieces : sequence of (str, ndarray)
        Label and cut outline (m) of each piece, as drawn on its page.
    roll_width : float
        Roll width, m.

    Returns
    -------
    list of DesignCheck
        Named ``roll width``; value and limit in m (the page's width across the roll and
        the roll).
    """
    from envelopelab.features.primitives import DesignCheck

    out: list[DesignCheck] = []
    widest = 0.0
    for label, cut in pieces:
        fit = roll_fit(cut, roll_width)
        widest = max(widest, fit.short_side)
        if fit.oversize:
            out.append(
                DesignCheck(
                    "roll width",
                    fit.short_side,
                    roll_width,
                    "m",
                    "warning",
                    f"piece {label} is {fit.across * 1000:.0f} mm across the roll at its "
                    f"narrowest ({fit.describe()}): LARGER THAN THE {roll_width * 1000:.0f} mm "
                    "ROLL AT ANY TURN; join paper, or split the piece (more panels or a "
                    "horizontal split)",
                )
            )
    if pieces and not out:
        out.append(
            DesignCheck(
                "roll width",
                widest,
                roll_width,
                "m",
                "info",
                f"every piece's page fits the {roll_width * 1000:.0f} mm roll (widest "
                f"{widest * 1000:.0f} mm across it)",
            )
        )
    return out


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
        size = (lay.width * PT_PER_M, lay.height * PT_PER_M)
        if canvas is None:
            canvas = PdfCanvas(size)
        else:
            canvas.new_page(size)
        over = ",".join(o.source for o in tpage.overlays if o.source) or "-"
        canvas.comment(f"PAGE {sheet.name} 1 1 {lay.angle:g} {over}")
        written.append(
            {
                "sheet": sheet.name,
                "band": 1,
                "bands": 1,
                "turn_deg": lay.angle,
                "across_roll_mm": round(lay.width * 1000.0, 1),
                "along_roll_mm": round(lay.height * 1000.0, 1),
                "markings": [o.source for o in tpage.overlays if o.source],
            }
        )
        _draw_page(canvas, tpage, lay.to_page, size, 0, 1)
        _draw_roll(canvas, lay, size, roll_width)
    if canvas is None:
        raise ValueError(f"template {tfile.name} has no pages")
    canvas.save(path)
    return written


def _draw_roll(canvas: object, lay: PageLayout, size: tuple[float, float], roll: float) -> None:
    """How the page goes on the roll, in its bottom margin: a double arrow across the
    page labelled with its width and the roll's, and the piece's turn; in red when the
    page is wider than the roll."""
    from envelopelab.report.pdf import PdfCanvas

    assert isinstance(canvas, PdfCanvas)
    pw, _ph = size
    fits = lay.width <= roll
    colour = BLUE if fits else RED
    y = 0.55 * MARGIN * PT_PER_M
    s = min(0.3 * MARGIN * PT_PER_M, 9.0)
    canvas.line(4.0, y, pw - 4.0, y, color=colour, width=0.8)
    for x, d in ((4.0, 1.0), (pw - 4.0, -1.0)):
        canvas.line(x, y, x + d * s, y + 0.5 * s, color=colour, width=0.8)
        canvas.line(x, y, x + d * s, y - 0.5 * s, color=colour, width=0.8)
    turn = "upright" if lay.angle == 0.0 else f"piece turned {lay.angle:g} deg"
    text = (
        f"ACROSS THE ROLL: {lay.width * 1000:.0f} mm of the {roll * 1000:.0f} mm roll - "
        f"{turn} - print at 100 %, page width across the roll, do not rotate"
        if fits
        else f"LARGER THAN THE {roll * 1000:.0f} MM ROLL AT ANY TURN: {lay.width * 1000:.0f} mm "
        "across at its narrowest - join paper, or plot this sheet in parts"
    )
    size_t = min(s, 0.9 * (pw - 16.0) / max(len(text), 1) / 0.5)
    canvas.text(2.0 * s, y + 0.35 * s, text, size=size_t, bold=not fits, color=colour)


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
