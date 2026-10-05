"""Build-pack export: cutting patterns as 1:1 DXF and PDF sheets with an index.

A build pack holds one *sheet* per piece to cut or mark:

* the envelope's row panels (cut once per gore);
* every piece of every special shape's skin (its gores or panels and a tip disc);
* a *marking* sheet for every envelope panel a shape crosses: the panel with the
  footprint line, the numbered match marks and the feed hole drawn on it.

Each sheet is written as a DXF file in millimetres (``$INSUNITS`` = 4) and as one or more
pages of ``pattern.pdf``, whose pages are as wide as the fabric roll; a sheet wider than
the roll is split into strips of the roll width. ``index.json`` lists every file with
its piece, cut count, fabric and finished size, and the pairs of edges that are sewn
together. :func:`envelopelab.export.qa.check_pack` checks a pack against AGENTS.md §6.6.

Sheet contents (DXF layers)
---------------------------
``CUT`` cut outline (with seam allowance); ``SEW`` finished outline; ``EDGE_<NAME>`` each
finished edge on its own (for the sewn-edge check); ``MARKS`` match marks and their
numbers; ``ATTACH`` footprint line on a marking sheet; ``HOLE`` feed hole; ``GRAIN``
warp direction; ``LABEL`` the header; ``CAL`` the calibration line, its ticks and its
label. The header and the calibration label are generated from the same values that
draw the geometry, never typed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from envelopelab.geometry.polygon import offset_polygon
from envelopelab.report.pdf import PdfCanvas
from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.features.primitives import PrimitiveDesign
    from envelopelab.project.model import PatternSet

MM = 1000.0  # mm per m
PT_PER_M = 72.0 / 0.0254  # PDF points per m
PACK_FORMAT = "envelopelab-build-pack/1"
INDEX = "index.json"
PDF_NAME = "pattern.pdf"
DEFAULT_ROLL_WIDTH = 60 * 0.0254  # m (60 in roll, AGENTS.md example)
SEWN_EDGE_TOLERANCE = 0.003  # m (AGENTS.md §6.6 default; source: assumed)
PDF_MARGIN = 0.02  # m round each page's content
CALIBRATION_LENGTHS = (0.5, 0.2, 0.1)  # m, longest that fits is used
CALIBRATION_TICK = 0.1  # m between ticks (0.05 m for lines under 0.2 m)


class BuildPackError(ValueError):
    """An export that cannot be written as asked."""


@dataclass
class Sheet:
    """One piece to cut or mark, in its finished pattern coordinates (m).

    Attributes
    ----------
    name : str
        File stem (unique in the pack).
    piece : str
        Piece label printed in the header.
    kind : {"envelope panel", "skin piece", "marking"}
        What the sheet is for.
    cut_count : int
        Pieces to cut from this sheet (0 for a marking sheet).
    fabric : str
        Fabric (or zone) name.
    finished : ndarray, shape (n, 2)
        Finished outline, m.
    cut : ndarray, shape (m, 2)
        Cut outline, m.
    edges : dict of str to ndarray
        Finished edges sewn to other edges, m.
    marks : list of (float, float, str)
        Match marks: position (m) and text.
    lines : list of ndarray
        Lines to draw (footprint runs), m.
    holes : list of (float, float, float)
        Holes: centre and radius, m.
    note : str
        Extra line in the header.
    """

    name: str
    piece: str
    kind: str
    cut_count: int
    fabric: str
    finished: FloatArray
    cut: FloatArray
    edges: dict[str, FloatArray] = field(default_factory=dict)
    marks: list[tuple[float, float, str]] = field(default_factory=list)
    lines: list[FloatArray] = field(default_factory=list)
    holes: list[tuple[float, float, float]] = field(default_factory=list)
    note: str = ""

    @property
    def finished_size(self) -> tuple[float, float]:
        """Finished width and height, m."""
        span = self.finished.max(axis=0) - self.finished.min(axis=0)
        return float(span[0]), float(span[1])

    def header(self) -> str:
        """Header line (generated from the sheet data)."""
        w, h = self.finished_size
        return (
            f"{self.piece} | {self.kind} | cut {self.cut_count} | fabric {self.fabric} | "
            f"finished {w * MM:.0f} x {h * MM:.0f} mm"
        )


@dataclass(frozen=True)
class SeamPair:
    """Two groups of finished edges sewn together (lengths summed per side).

    Attributes
    ----------
    a, b : tuple of (sheet name, edge name)
        Edges of each side. ``attach<k>`` names the k-th footprint line drawn on a
        marking sheet (layer ``ATTACH``).
    ease : float
        Intended length of side ``a`` minus side ``b``, m, worked in between match marks
        (0 for edges cut to the same length). The QA checks the files against it.
    """

    a: tuple[tuple[str, str], ...]
    b: tuple[tuple[str, str], ...]
    ease: float = 0.0


def calibration(width: float) -> tuple[float, float]:
    """Calibration line length and tick spacing for a sheet ``width`` m wide, m."""
    for length in CALIBRATION_LENGTHS:
        if length <= width or length == CALIBRATION_LENGTHS[-1]:
            return length, CALIBRATION_TICK if length >= 0.2 else 0.05
    raise AssertionError  # pragma: no cover


def calibration_label(length: float, tick: float) -> str:
    """Label of a calibration line, generated from its drawn length and ticks (m)."""
    return f"must measure {length * MM:.0f} mm at 1:1, ticks every {tick * MM:.0f} mm"


# --------------------------------------------------------------------------------------
# Sheets from the design
# --------------------------------------------------------------------------------------


def envelope_sheets(design: DesignDocument, patterns: PatternSet | None = None) -> list[Sheet]:
    """Sheets of the envelope's row panels (each cut once per gore).

    Parameters
    ----------
    design : DesignDocument
        Standard-gore design, m.
    patterns : PatternSet, optional
        Row annotations (allowances, zones).

    Returns
    -------
    list of Sheet
        One per row, mouth first.
    """
    from envelopelab.project.gore_design import panel_rows, row_zone
    from envelopelab.project.model import PatternSet

    assert design.gores is not None
    patterns = patterns or PatternSet()
    out = []
    for row in panel_rows(design, patterns):
        zone = row_zone(design, patterns, row.label)
        right = row.right_edge
        left = right[::-1] * np.array([-1.0, 1.0])
        out.append(
            Sheet(
                name=f"envelope-row-{row.label}",
                piece=f"row {row.label}",
                kind="envelope panel",
                cut_count=design.gores.count,
                fabric=design.zones.get(zone, zone),
                finished=row.finished_outline,
                cut=row.cut_outline,
                edges={
                    "left": left[::-1],
                    "right": right,
                    "bottom": np.array([left[-1], right[0]]),
                    "top": np.array([left[0], right[-1]]),
                },
            )
        )
    return out


def primitive_sheets(
    design: PrimitiveDesign, fabric: str = "skin", seam_allowance: float | None = None
) -> list[Sheet]:
    """Sheets of a placed primitive: its skin pieces and its envelope marking sheets.

    Parameters
    ----------
    design : PrimitiveDesign
        Placed primitive (:func:`~envelopelab.features.primitives.design_primitive`).
    fabric : str
        Fabric name of the skin.
    seam_allowance : float, optional
        Allowance of the marking sheets' cut outline, m (default: none drawn).

    Returns
    -------
    list of Sheet
        Skin pieces first, then one marking sheet per host panel.
    """
    name = design.primitive.name
    out: list[Sheet] = []
    for piece in design.pieces:
        marks = [
            (m.piece_xy[0], m.piece_xy[1], str(m.number))
            for m in design.marks
            if m.piece == piece.label
        ]
        edges = {k: v for k, v in piece.edges.items()}
        if piece.rim is not None:
            edges["rim"] = piece.rim
        out.append(
            Sheet(
                name=piece.label,
                piece=piece.label,
                kind="skin piece",
                cut_count=piece.cut_count,
                fabric=fabric,
                finished=piece.finished,
                cut=piece.cut,
                edges=edges,
                marks=marks,
            )
        )
    surface = design.surface
    hole = design.feed_hole
    for gore, row in sorted({(a.gore, a.row) for a in design.attachment}):
        band = next(b for b in surface.rows if b.label == row)
        s = np.linspace(band.s_bottom, band.s_top, 97)
        half = surface.half_width(s)
        right = np.column_stack([half, s - band.s_bottom])
        finished = np.vstack([right, right[::-1] * np.array([-1.0, 1.0])])
        cut = offset_polygon(finished, seam_allowance) if seam_allowance else finished.copy()
        out.append(
            Sheet(
                name=_marking_name(design, gore, row),
                piece=f"gore {gore} row {row}",
                kind="marking",
                cut_count=0,
                fabric="envelope",
                finished=finished,
                cut=cut,
                marks=[
                    (m.host_xy[0], m.host_xy[1], str(m.number))
                    for m in design.marks
                    if (m.gore, m.row) == (gore, row)
                ],
                lines=[a.points for a in design.attachment if (a.gore, a.row) == (gore, row)],
                holes=(
                    [(hole.centre_xy[0], hole.centre_xy[1], hole.radius)]
                    if hole is not None and (hole.gore, hole.row) == (gore, row)
                    else []
                ),
                note=f"mark {name} on this panel before assembly",
            )
        )
    return out


def primitive_seam_pairs(design: PrimitiveDesign) -> list[SeamPair]:
    """Edges of a primitive sewn together: skin seams, tip, and the rim to the envelope.

    The rim is sewn to the footprint lines marked on the envelope panels (the marking
    sheets of :func:`primitive_sheets`). Those lines are on the flat panels, so they
    differ from the rim by the attachment ease of the design
    (:attr:`~envelopelab.features.primitives.PrimitiveDesign.mark_ease`, checked per
    match-mark interval); the pair carries that total as its ``ease``.
    """
    pieces = [p for p in design.pieces if p.rim is not None]
    m = len(pieces)
    pairs = [
        SeamPair(((pieces[k].label, "right"),), ((pieces[(k + 1) % m].label, "left"),))
        for k in range(m)
    ]
    tip = [p for p in design.pieces if p.rim is None]
    if tip:
        pairs.append(SeamPair(tuple((p.label, "top") for p in pieces), ((tip[0].label, "top"),)))
    lines: list[tuple[str, str]] = []
    for gore, row in sorted({(a.gore, a.row) for a in design.attachment}):
        runs = [a for a in design.attachment if (a.gore, a.row) == (gore, row)]
        sheet = _marking_name(design, gore, row)
        lines += [(sheet, f"attach{k + 1}") for k in range(len(runs))]
    rim = sum(_length(p.rim) for p in pieces if p.rim is not None)
    marked = sum(a.length for a in design.attachment)
    pairs.append(SeamPair(tuple((p.label, "rim") for p in pieces), tuple(lines), rim - marked))
    return pairs


def _marking_name(design: PrimitiveDesign, gore: int, row: str) -> str:
    return f"{design.primitive.name}-mark-G{gore}-{row}"


def _length(points: FloatArray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def envelope_seam_pairs(sheets: Sequence[Sheet]) -> list[SeamPair]:
    """Edges of the envelope rows sewn together (gore sides, row seams)."""
    rows = [s for s in sheets if s.kind == "envelope panel"]
    pairs = [SeamPair(((s.name, "left"),), ((s.name, "right"),)) for s in rows]
    pairs += [
        SeamPair(((a.name, "top"),), ((b.name, "bottom"),))
        for a, b in zip(rows[:-1], rows[1:], strict=True)
    ]
    return pairs


# --------------------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------------------


def _cal_origin(sheet: Sheet) -> tuple[float, float]:
    lo = sheet.cut.min(axis=0)
    return float(lo[0]), float(lo[1]) - 0.06


def write_dxf(sheet: Sheet, path: str | Path) -> Path:
    """Write one sheet as a DXF file in mm.

    Parameters
    ----------
    sheet : Sheet
        Sheet in m.
    path : str or Path
        Output file.

    Returns
    -------
    Path
        The written file.
    """
    from ezdxf.filemanagement import new as new_dxf

    doc = new_dxf("R2010", setup=False)
    doc.header["$INSUNITS"] = 4  # millimetres
    doc.header["$MEASUREMENT"] = 1  # metric
    layers = ["CUT", "SEW", "MARKS", "ATTACH", "HOLE", "GRAIN", "LABEL", "CAL"]
    layers += [f"EDGE_{e.upper()}" for e in sheet.edges]
    for layer in layers:
        doc.layers.add(layer)
    msp = doc.modelspace()

    def pts(points: FloatArray) -> list[tuple[float, float]]:
        return [(float(x * MM), float(y * MM)) for x, y in points]

    msp.add_lwpolyline(pts(sheet.cut), close=True, dxfattribs={"layer": "CUT"})
    msp.add_lwpolyline(pts(sheet.finished), close=True, dxfattribs={"layer": "SEW"})
    for e, line in sheet.edges.items():
        msp.add_lwpolyline(pts(line), dxfattribs={"layer": f"EDGE_{e.upper()}"})
    for x, y, text in sheet.marks:
        c = (x * MM, y * MM)
        msp.add_line((c[0] - 10, c[1]), (c[0] + 10, c[1]), dxfattribs={"layer": "MARKS"})
        msp.add_line((c[0], c[1] - 10), (c[0], c[1] + 10), dxfattribs={"layer": "MARKS"})
        msp.add_text(
            text, height=25.0, dxfattribs={"layer": "MARKS", "insert": (c[0] + 12, c[1] + 12)}
        )
    for line in sheet.lines:
        msp.add_lwpolyline(pts(line), dxfattribs={"layer": "ATTACH"})
    for x, y, r in sheet.holes:
        msp.add_circle((x * MM, y * MM), r * MM, dxfattribs={"layer": "HOLE"})
    lo, hi = sheet.finished.min(axis=0), sheet.finished.max(axis=0)
    cx, cy = 0.5 * (lo[0] + hi[0]) * MM, 0.5 * (lo[1] + hi[1]) * MM
    g = 0.25 * (hi[1] - lo[1]) * MM
    msp.add_line((cx, cy - g), (cx, cy + g), dxfattribs={"layer": "GRAIN"})
    msp.add_line((cx, cy + g), (cx - 15, cy + g - 40), dxfattribs={"layer": "GRAIN"})
    msp.add_line((cx, cy + g), (cx + 15, cy + g - 40), dxfattribs={"layer": "GRAIN"})
    lines = [sheet.header()] + ([sheet.note] if sheet.note else [])
    for k, text in enumerate(lines):
        msp.add_text(
            text,
            height=30.0,
            dxfattribs={"layer": "LABEL", "insert": (lo[0] * MM, (hi[1] + 0.08) * MM + 45 * k)},
        )
    width = float(sheet.cut[:, 0].max() - sheet.cut[:, 0].min())
    length, tick = calibration(width)
    x0, y0 = _cal_origin(sheet)
    msp.add_line((x0 * MM, y0 * MM), ((x0 + length) * MM, y0 * MM), dxfattribs={"layer": "CAL"})
    for k in range(int(round(length / tick)) + 1):
        x = (x0 + k * tick) * MM
        msp.add_line((x, y0 * MM), (x, y0 * MM + 15), dxfattribs={"layer": "CAL"})
    msp.add_text(
        calibration_label(length, tick),
        height=20.0,
        dxfattribs={"layer": "CAL", "insert": (x0 * MM, y0 * MM - 35)},
    )
    target = Path(path)
    doc.saveas(target)
    return target


def _strips(sheet: Sheet, roll_width: float) -> list[tuple[float, float]]:
    """x ranges (m) of the roll-width strips covering a sheet, with the page margins."""
    lo = float(sheet.cut[:, 0].min()) - PDF_MARGIN
    hi = float(sheet.cut[:, 0].max()) + PDF_MARGIN
    usable = roll_width
    count = max(1, math.ceil((hi - lo) / usable - 1e-9))
    return [(lo + k * usable, lo + (k + 1) * usable) for k in range(count)]


def write_pdf(sheets: Sequence[Sheet], path: str | Path, roll_width: float) -> list[int]:
    """Write all sheets at 1:1 on pages as wide as the roll.

    Parameters
    ----------
    sheets : sequence of Sheet
        Sheets in m.
    path : str or Path
        Output PDF.
    roll_width : float
        Fabric roll width, m.

    Returns
    -------
    list of int
        Number of pages (strips) of each sheet.
    """
    page_w = roll_width * PT_PER_M
    canvas: PdfCanvas | None = None
    counts = []
    for sheet in sheets:
        strips = _strips(sheet, roll_width)
        counts.append(len(strips))
        y_lo = float(sheet.cut[:, 1].min()) - 0.12
        y_hi = float(sheet.cut[:, 1].max()) + 0.18
        size = (page_w, (y_hi - y_lo) * PT_PER_M)
        for k, (x_lo, _) in enumerate(strips):
            if canvas is None:
                canvas = PdfCanvas(size)
            else:
                canvas.new_page(size)

            def p(
                x: float, y: float, x_lo: float = x_lo, y_lo: float = y_lo
            ) -> tuple[float, float]:
                return ((x - x_lo) * PT_PER_M, (y - y_lo) * PT_PER_M)

            canvas.polygon([p(x, y) for x, y in sheet.cut], stroke=(0, 0, 0), width=0.8)
            canvas.polygon([p(x, y) for x, y in sheet.finished], stroke=(0.1, 0.3, 0.8), width=0.5)
            for line in sheet.lines:
                q = [p(x, y) for x, y in line]
                for a, b in zip(q[:-1], q[1:], strict=True):
                    canvas.line(*a, *b, color=(0.8, 0.1, 0.1), width=0.8)
            for x, y, r in sheet.holes:
                ang = np.linspace(0.0, 2 * math.pi, 73)
                canvas.polygon(
                    [p(x + r * math.cos(t), y + r * math.sin(t)) for t in ang],
                    stroke=(0.8, 0.1, 0.1),
                )
            for x, y, text in sheet.marks:
                cx, cy = p(x, y)
                canvas.line(cx - 8, cy, cx + 8, cy, width=0.8)
                canvas.line(cx, cy - 8, cx, cy + 8, width=0.8)
                canvas.text(cx + 6, cy + 6, text, size=10)
            hx, hy = p(float(sheet.cut[:, 0].min()), float(sheet.cut[:, 1].max()) + 0.06)
            strip = f"  [strip {k + 1} of {len(strips)}]" if len(strips) > 1 else ""
            canvas.text(max(hx, 10.0), hy, sheet.header() + strip, size=12, bold=True)
            if sheet.note:
                canvas.text(max(hx, 10.0), hy + 16, sheet.note, size=10)
            # Calibration line at the left of every page: its label comes from the same
            # length and tick that draw it; the comment lets the QA find and measure it.
            length, tick = calibration(min(roll_width - 2 * PDF_MARGIN, 0.5))
            x0 = PDF_MARGIN * PT_PER_M
            y0 = 0.05 * PT_PER_M
            canvas.comment(f"CAL {length * MM:.0f} {tick * MM:.0f}")
            canvas.line(x0, y0, x0 + length * PT_PER_M, y0, width=1.0)
            for j in range(int(round(length / tick)) + 1):
                xt = x0 + j * tick * PT_PER_M
                canvas.line(xt, y0, xt, y0 + 10, width=0.6)
            canvas.text(x0, y0 - 14, calibration_label(length, tick), size=10)
    if canvas is None:
        raise BuildPackError("no sheets to write")
    canvas.save(path)
    return counts


# --------------------------------------------------------------------------------------
# Pack
# --------------------------------------------------------------------------------------


def write_pack(
    sheets: Sequence[Sheet],
    out_dir: str | Path,
    seam_pairs: Sequence[SeamPair] = (),
    roll_width: float = DEFAULT_ROLL_WIDTH,
    title: str = "",
) -> Path:
    """Write a build pack: one DXF per sheet, ``pattern.pdf`` and ``index.json``.

    Parameters
    ----------
    sheets : sequence of Sheet
        Sheets in m (names unique).
    out_dir : str or Path
        Directory to write (created; files of the same names are replaced).
    seam_pairs : sequence of SeamPair
        Edges sewn together (checked by the QA).
    roll_width : float
        Fabric roll width, m (PDF page width).
    title : str
        Pack title for the index.

    Returns
    -------
    Path
        The index file.
    """
    names = [s.name for s in sheets]
    if len(set(names)) != len(names):
        raise BuildPackError("sheet names must be unique")
    if roll_width <= 2 * PDF_MARGIN:
        raise BuildPackError("roll width must exceed the page margins")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for sheet in sheets:
        write_dxf(sheet, out / f"{sheet.name}.dxf")
    pages = write_pdf(sheets, out / PDF_NAME, roll_width)
    for sheet, n_pages in zip(sheets, pages, strict=True):
        w, h = sheet.finished_size
        entries.append(
            {
                "file": f"{sheet.name}.dxf",
                "piece": sheet.piece,
                "kind": sheet.kind,
                "cut_count": sheet.cut_count,
                "fabric": sheet.fabric,
                "finished_width_mm": round(w * MM, 3),
                "finished_height_mm": round(h * MM, 3),
                "pdf_pages": n_pages,
            }
        )
    index = {
        "format": PACK_FORMAT,
        "title": title,
        "units": "mm",
        "roll_width_mm": round(roll_width * MM, 3),
        "pdf": PDF_NAME,
        "sheets": entries,
        "seam_pairs": [
            {
                "a": [{"file": f"{n}.dxf", "edge": e} for n, e in pair.a],
                "b": [{"file": f"{n}.dxf", "edge": e} for n, e in pair.b],
                "tolerance_mm": SEWN_EDGE_TOLERANCE * MM,
                "ease_mm": round(pair.ease * MM, 3),
            }
            for pair in seam_pairs
        ],
    }
    path = out / INDEX
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return path


def export_build_pack(
    design: DesignDocument,
    primitives: Sequence[PrimitiveDesign],
    out_dir: str | Path,
    patterns: PatternSet | None = None,
    skin_fabric: str | dict[str, str] = "skin",
    roll_width: float = DEFAULT_ROLL_WIDTH,
    marking_allowance: float | None = None,
) -> Path:
    """Export the envelope rows and every primitive's pieces and marking sheets.

    Parameters
    ----------
    design : DesignDocument
        Standard-gore design, m.
    primitives : sequence of PrimitiveDesign
        Placed primitives on that design.
    out_dir : str or Path
        Output directory.
    patterns : PatternSet, optional
        Row annotations.
    skin_fabric : str or dict of str to str
        Skin fabric, or one per primitive name.
    roll_width : float
        Fabric roll width, m.
    marking_allowance : float, optional
        Seam allowance drawn round the marking sheets, m.

    Returns
    -------
    Path
        ``index.json``.
    """
    sheets = envelope_sheets(design, patterns)
    pairs = envelope_seam_pairs(sheets)
    for p in primitives:
        name = p.primitive.name
        fabric = skin_fabric if isinstance(skin_fabric, str) else skin_fabric.get(name, "skin")
        sheets += primitive_sheets(p, fabric, marking_allowance)
        pairs += primitive_seam_pairs(p)
    return write_pack(sheets, out_dir, pairs, roll_width, title=design.meta.name)
