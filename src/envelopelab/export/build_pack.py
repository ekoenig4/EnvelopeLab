"""Build-pack export: cutting patterns as 1:1 DXF and PDF sheets with an index.

A build pack holds one *sheet* per piece to cut or mark:

* the envelope's row panels (cut once per gore);
* the parachute's radial panel (cut once per radial panel) and, when it has one, its
  circular centre panel (cut once);
* every piece of every special shape's skin (its gores or panels and a tip disc);
* a *marking* sheet for every envelope panel a shape crosses or lies over: the panel with
  the footprint line (the shape's rim is sewn on it; short ticks point into the shape),
  the numbered match marks (each naming the skin piece that carries the same number) and
  the feed holes, drawn at their cut and finished sizes.

Sewing directions are written on the sheets from the same data: each skin piece says what
every edge is sewn to (the rim to the envelope line with its mark numbers, each seam to
the neighbouring piece, the top to the tip disc or the apex), and each envelope row says
which of its gores carry a marking sheet or a feed hole.

Each sheet is written as a DXF file in millimetres (``$INSUNITS`` = 4) and as one or more
pages of ``pattern.pdf``, whose pages are as wide as the fabric roll; a sheet wider than
the roll is split into strips of the roll width. ``index.json`` lists every file with
its piece, cut count, fabric and finished size, and the pairs of edges that are sewn
together. :func:`envelopelab.export.qa.check_pack` checks a pack against AGENTS.md §6.6.

Sheet contents (DXF layers)
---------------------------
``CUT`` cut outline (with seam allowance); ``SEW`` finished outline; ``EDGE_<NAME>`` each
finished edge on its own (for the sewn-edge check); ``MARKS`` match marks and their
numbers; ``ATTACH`` footprint line on a marking sheet; ``ATTACH_SIDE`` ticks on the side
of the footprint line the shape covers; ``HOLE`` feed hole, finished; ``HOLE_CUT`` feed
hole as cut (before the hem is turned); ``NOTES`` sewing directions placed on the piece;
``GRAIN`` warp direction; ``LABEL`` the header and the notes under it; ``CAL`` the
calibration line, its ticks and its label. The header and the calibration label are
generated from the same values that draw the geometry, never typed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from ezdxf.enums import TextEntityAlignment

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
    kind : {"envelope panel", "parachute panel", "skin piece", "marking"}
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
        Holes: centre and finished radius, m.
    note : str
        Extra line in the header.
    hole_cuts : list of (float, float, float)
        Holes as cut: centre and radius, m.
    ticks : list of ndarray, shape (2, 2)
        Short lines on the side of a footprint line the shape covers, m.
    texts : list of (float, float, str)
        Directions placed on the sheet: position (m) and text.
    notes : list of str
        More lines under the header.
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
    hole_cuts: list[tuple[float, float, float]] = field(default_factory=list)
    ticks: list[FloatArray] = field(default_factory=list)
    texts: list[tuple[float, float, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

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
        out.append(
            Sheet(
                name=f"envelope-row-{row.label}",
                piece=f"row {row.label}",
                kind="envelope panel",
                cut_count=design.gores.count,
                fabric=design.zones.get(zone, zone),
                finished=row.finished_outline,
                cut=row.cut_outline,
                edges=_panel_edges(row.right_edge),
            )
        )
    return out


def _panel_edges(right: FloatArray) -> dict[str, FloatArray]:
    """Left, right, bottom and top finished edges of a mirrored panel (right side given)."""
    left = right[::-1] * np.array([-1.0, 1.0])
    return {
        "left": left[::-1],
        "right": right,
        "bottom": np.array([left[-1], right[0]]),
        "top": np.array([left[0], right[-1]]),
    }


def parachute_sheets(design: DesignDocument) -> list[Sheet]:
    """Sheets of the parachute: its radial panel and its centre panel (if any).

    Parameters
    ----------
    design : DesignDocument
        Standard-gore design, m.

    Returns
    -------
    list of Sheet
        Empty when the design has no parachute; else the radial panel (cut once per
        radial panel, bottom = the parachute edge) and the centre panel (cut once, its
        edge ``rim``).

    Raises
    ------
    BuildPackError
        When the design has a parachute but its pattern cannot be made (the rigging
        analysis' errors are named), so a pack never leaves it out silently.
    """
    from envelopelab.rigging import rigging_outputs

    if design.parachute is None:
        return []
    result = rigging_outputs(design)
    pr = result.parachute
    if pr is None or pr.panel is None:
        errors = [f.message for f in result.findings if f.target == "parachute"]
        raise BuildPackError(
            "the parachute pattern cannot be made: " + ("; ".join(errors) or "no geometry")
        )
    zone = design.parachute.zone or next(iter(design.zones), "default")
    fabric = design.zones.get(zone, zone)
    centre = pr.centre_panel
    top = "centre panel" if centre is not None else "centre ring"
    out = [
        Sheet(
            name="parachute-panel",
            piece="parachute panel",
            kind="parachute panel",
            cut_count=pr.panel_count,
            fabric=fabric,
            finished=pr.panel.finished_outline,
            cut=pr.panel.cut_outline,
            edges=_panel_edges(pr.panel.right_edge),
            note=f"bottom: parachute edge (shroud and centralising lines at the seams); top: {top}",
        )
    ]
    if centre is not None:
        out.append(
            Sheet(
                name="parachute-centre",
                piece="parachute centre panel",
                kind="parachute panel",
                cut_count=1,
                fabric=fabric,
                finished=centre.finished_outline,
                cut=centre.cut_outline,
                edges={"rim": np.vstack((centre.finished_outline, centre.finished_outline[:1]))},
                note=f"edge sewn to the tops of the {pr.panel_count} radial panels",
            )
        )
    return out


def parachute_seam_pairs(sheets: Sequence[Sheet]) -> list[SeamPair]:
    """Edges of the parachute sewn together: the radial seams and, with a centre panel,
    the radial panels' tops (all of them) against its edge."""
    panel = next((s for s in sheets if s.name == "parachute-panel"), None)
    if panel is None:
        return []
    pairs = [SeamPair(((panel.name, "left"),), ((panel.name, "right"),))]
    centre = next((s for s in sheets if s.name == "parachute-centre"), None)
    if centre is not None:
        tops = tuple((panel.name, "top") for _ in range(panel.cut_count))
        pairs.append(SeamPair(tops, ((centre.name, "rim"),)))
    return pairs


def primitive_sheets(
    design: PrimitiveDesign,
    fabric: str = "skin",
    seam_allowance: float | None = None,
    hole_hem: float = 0.0,
    hole_tape: str = "",
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
    hole_hem : float
        Width of cloth turned back round a feed hole, m: the hole is cut that much smaller
        in radius than finished (0: cut at the finished size).
    hole_tape : str
        Tape class the feed-hole hem is turned over (named on the sheet).

    Returns
    -------
    list of Sheet
        Skin pieces first, then one marking sheet per host panel.
    """
    name = design.primitive.name
    out: list[Sheet] = []
    rim_pieces = [p for p in design.pieces if p.rim is not None]
    tip = [p for p in design.pieces if p.rim is None]
    order = {p.label: k for k, p in enumerate(rim_pieces)}
    for piece in design.pieces:
        own = [m for m in design.marks if m.piece == piece.label]
        marks = [(m.piece_xy[0], m.piece_xy[1], str(m.number)) for m in own]
        edges = {k: v for k, v in piece.edges.items()}
        if piece.rim is not None:
            edges["rim"] = piece.rim
        texts, notes = _piece_directions(piece, own, rim_pieces, tip, order, name)
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
                note=f"part of {name}: sew the seams between the pieces first, then the rim "
                "to the envelope",
                texts=texts,
                notes=notes,
            )
        )
    from envelopelab.features.primitives import band_outline

    surface = design.surface
    holes = design.feed_holes
    panels = {(a.gore, a.row) for a in design.attachment} | {(h.gore, h.row) for h in holes}
    row_order = {b.label: i for i, b in enumerate(surface.rows)}
    inside = _inside_sign(design)
    for gore, row in sorted(panels):
        index = row_order[row]
        finished = band_outline(surface, index)
        cut = offset_polygon(finished, seam_allowance) if seam_allowance else finished.copy()
        lines = [a.points for a in design.attachment if (a.gore, a.row) == (gore, row)]
        here = [h for h in holes if (h.gore, h.row) == (gore, row)]
        texts = [
            (
                h.centre_xy[0],
                h.centre_xy[1] + h.radius + 0.04,
                _hole_text(h.radius, hole_hem, hole_tape),
            )
            for h in here
        ]
        if lines:
            notes = [
                f"sew the rim of {name} on the footprint line (ATTACH); the ticks point into "
                f"{name}",
                "match each number to the same number on the skin piece named beside it; "
                "work any ease in between the numbers",
            ]
        else:
            notes = [f"this panel lies under {name}: mark and cut the feed hole only"]
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
                    (m.host_xy[0], m.host_xy[1], f"{m.number} ({_short(m.piece, name)})")
                    for m in design.marks
                    if (m.gore, m.row) == (gore, row)
                ],
                lines=lines,
                holes=[(h.centre_xy[0], h.centre_xy[1], h.radius) for h in here],
                hole_cuts=[
                    (h.centre_xy[0], h.centre_xy[1], max(h.radius - hole_hem, 0.0)) for h in here
                ],
                ticks=[tick for line in lines for tick in _side_ticks(line, inside)],
                texts=texts,
                note=f"mark {name} on this panel before assembly",
                notes=notes,
            )
        )
    return out


def default_hole_hem(design: DesignDocument) -> tuple[float, str]:
    """Hem turned back round a feed hole by default, m, and the tape it is turned over.

    A double fold over the design's hole tape: twice the tape width (source: design tape
    width; the double fold is the usual hem of a hole, assumed).
    """
    tape = design.tapes.hole
    return 2.0 * tape.width, tape.tape_class


#: Spacing and length of the ticks on the shape's side of a footprint line, m.
TICK_SPACING = 0.15
TICK_LENGTH = 0.04
#: How far a direction is placed inside a piece from the edge it names, m.
TEXT_INSET = 0.08


def _short(label: str, name: str) -> str:
    """A piece label without its shape name (``ear-G3`` -> ``G3``)."""
    prefix = f"{name}-"
    return label[len(prefix) :] if label.startswith(prefix) else label


def _hole_text(radius: float, hem: float, tape: str) -> str:
    finished = 2.0 * radius * MM
    if hem <= 0.0:
        return f"FEED HOLE: cut and finished diameter {finished:.0f} mm"
    cut = 2.0 * max(radius - hem, 0.0) * MM
    over = f" over {tape}" if tape else ""
    return (
        f"FEED HOLE: cut diameter {cut:.0f} mm, turn a {hem * MM:.0f} mm hem{over} to "
        f"{finished:.0f} mm finished"
    )


def _inside_sign(design: PrimitiveDesign) -> float:
    """+1 when the shape lies to the left of its footprint lines as drawn, else -1.

    The footprint lines run round the footprint in the order of its points; panel
    coordinates grow with the gore position and the tape position, so the shape is on the
    left of the lines where the footprint runs counter-clockwise in (gore, tape) position.
    """
    surface = design.surface
    n = surface.gore_count
    g_centre = design.primitive.placement.gore - 0.5 + design.primitive.placement.across
    g = surface.gore_position(design.footprint_theta)
    g = g_centre + np.mod(g - g_centre + 0.5 * n, n) - 0.5 * n
    s = design.footprint_s
    area = 0.5 * float(np.sum(g * np.roll(s, -1) - np.roll(g, -1) * s))
    return 1.0 if area > 0.0 else -1.0


def _side_ticks(line: FloatArray, sign: float) -> list[FloatArray]:
    """Short ticks every :data:`TICK_SPACING` on the ``sign`` side (+1 left) of a line."""
    pts = np.asarray(line, dtype=np.float64)
    seg = np.diff(pts, axis=0)
    lengths = np.linalg.norm(seg, axis=1)
    if len(pts) < 2 or lengths.sum() <= 0.0:
        return []
    arc = np.concatenate([[0.0], np.cumsum(lengths)])
    out = []
    for at in np.arange(0.5 * TICK_SPACING, arc[-1], TICK_SPACING):
        k = min(int(np.searchsorted(arc, at, side="right")) - 1, len(seg) - 1)
        if lengths[k] <= 0.0:
            continue
        d = seg[k] / lengths[k]
        p = pts[k] + (at - arc[k]) * d
        normal = sign * np.array([-d[1], d[0]])
        out.append(np.vstack([p, p + TICK_LENGTH * normal]))
    return out


def _piece_directions(
    piece: Any,
    own_marks: Sequence[Any],
    rim_pieces: Sequence[Any],
    tip: Sequence[Any],
    order: dict[str, int],
    name: str,
) -> tuple[list[tuple[float, float, str]], list[str]]:
    """What every edge of a skin piece is sewn to: texts placed on the piece, and notes."""
    centre = piece.finished.mean(axis=0)

    def at(points: FloatArray) -> tuple[float, float]:
        pts = np.asarray(points, dtype=np.float64)
        mid = pts[len(pts) // 2]
        toward = centre - mid
        norm = float(np.linalg.norm(toward))
        p = mid + (TEXT_INSET * toward / norm if norm > 0.0 else 0.0)
        return float(p[0]), float(p[1])

    texts: list[tuple[float, float, str]] = []
    notes: list[str] = []
    if piece.rim is None:  # the tip disc
        texts.append((*at(piece.finished), f"TIP DISC: sew round the tops of all {name} panels"))
        return texts, notes
    k, m = order[piece.label], len(rim_pieces)
    nxt = _short(rim_pieces[(k + 1) % m].label, name)
    prv = _short(rim_pieces[(k - 1) % m].label, name)
    numbers = sorted(mk.number for mk in own_marks)
    span = f", marks {numbers[0]}-{numbers[-1]}" if numbers else ""
    texts.append((*at(piece.rim), f"RIM: sew to the envelope{span}"))
    texts.append((*at(piece.edges["right"]), f"sew to {nxt} (its left side)"))
    texts.append((*at(piece.edges["left"]), f"sew to {prv} (its right side)"))
    top = np.asarray(piece.edges.get("top", np.zeros((0, 2))))
    if tip and len(top) > 1:
        texts.append((*at(top), "TOP: sew to the tip disc"))
    elif len(top):
        texts.append((float(top[0][0]), float(top[0][1]) - TEXT_INSET, f"APEX of {name}"))
    panels = sorted({(mk.gore, mk.row) for mk in own_marks})
    if panels:
        where = ", ".join(f"gore {g} row {r}" for g, r in panels)
        notes.append(f"rim marks {numbers[0]}-{numbers[-1]} lie on the envelope at {where}")
    return texts, notes


def shape_row_notes(primitives: Sequence[PrimitiveDesign]) -> dict[str, list[str]]:
    """Per envelope row, which gores carry a shape's marking sheet or feed hole."""
    out: dict[str, list[str]] = {}
    for design in primitives:
        name = design.primitive.name
        rows: dict[str, set[int]] = {}
        holes: dict[str, set[int]] = {}
        for a in design.attachment:
            rows.setdefault(a.row, set()).add(a.gore)
        for h in design.feed_holes:
            rows.setdefault(h.row, set()).add(h.gore)
            holes.setdefault(h.row, set()).add(h.gore)
        for row, gores in rows.items():
            text = f"{name}: mark gores {', '.join(str(g) for g in sorted(gores))} of this row"
            if row in holes:
                text += "; feed hole in gore " + ", ".join(str(g) for g in sorted(holes[row]))
            out.setdefault(row, []).append(text + f" (sheets {name}-mark-G<gore>-{row})")
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
    layers = ["CUT", "SEW", "MARKS", "ATTACH", "ATTACH_SIDE", "HOLE", "HOLE_CUT", "NOTES"]
    layers += ["GRAIN", "LABEL", "CAL"]
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
    for x, y, r in sheet.hole_cuts:
        if r > 0.0:
            msp.add_circle((x * MM, y * MM), r * MM, dxfattribs={"layer": "HOLE_CUT"})
    for seg in sheet.ticks:
        (ax, ay), (bx, by) = seg * MM
        msp.add_line((ax, ay), (bx, by), dxfattribs={"layer": "ATTACH_SIDE"})
    for x, y, text in sheet.texts:  # centred on their point
        msp.add_text(text, height=25.0, dxfattribs={"layer": "NOTES"}).set_placement(
            (x * MM, y * MM), align=TextEntityAlignment.MIDDLE_CENTER
        )
    lo, hi = sheet.finished.min(axis=0), sheet.finished.max(axis=0)
    cx, cy = 0.5 * (lo[0] + hi[0]) * MM, 0.5 * (lo[1] + hi[1]) * MM
    g = 0.25 * (hi[1] - lo[1]) * MM
    msp.add_line((cx, cy - g), (cx, cy + g), dxfattribs={"layer": "GRAIN"})
    msp.add_line((cx, cy + g), (cx - 15, cy + g - 40), dxfattribs={"layer": "GRAIN"})
    msp.add_line((cx, cy + g), (cx + 15, cy + g - 40), dxfattribs={"layer": "GRAIN"})
    lines = [sheet.header()] + ([sheet.note] if sheet.note else []) + sheet.notes
    # Header first (also the first LABEL text, which the QA reads), the notes under it.
    for k, text in enumerate(lines):
        y = (hi[1] + 0.08) * MM + 45 * (len(lines) - 1 - k)
        msp.add_text(text, height=30.0, dxfattribs={"layer": "LABEL", "insert": (lo[0] * MM, y)})
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
            ang = np.linspace(0.0, 2 * math.pi, 73)
            for x, y, r in sheet.holes:
                canvas.polygon(
                    [p(x + r * math.cos(t), y + r * math.sin(t)) for t in ang],
                    stroke=(0.8, 0.1, 0.1),
                )
            for x, y, r in sheet.hole_cuts:
                if r > 0.0:
                    canvas.polygon(
                        [p(x + r * math.cos(t), y + r * math.sin(t)) for t in ang],
                        stroke=(0.0, 0.0, 0.0),
                    )
            for seg in sheet.ticks:
                (ax, ay), (bx, by) = (p(float(u), float(v)) for u, v in seg)
                canvas.line(ax, ay, bx, by, color=(0.8, 0.1, 0.1), width=0.8)
            for x, y, text in sheet.texts:  # centred on their point (Helvetica ~0.52 em)
                tx, ty = p(x, y)
                canvas.text(tx - 0.26 * 10 * len(text), ty - 3.5, text, size=10)
            for x, y, text in sheet.marks:
                cx, cy = p(x, y)
                canvas.line(cx - 8, cy, cx + 8, cy, width=0.8)
                canvas.line(cx, cy - 8, cx, cy + 8, width=0.8)
                canvas.text(cx + 6, cy + 6, text, size=10)
            hx, hy = p(float(sheet.cut[:, 0].min()), float(sheet.cut[:, 1].max()) + 0.06)
            strip = f"  [strip {k + 1} of {len(strips)}]" if len(strips) > 1 else ""
            canvas.text(max(hx, 10.0), hy, sheet.header() + strip, size=12, bold=True)
            extra = ([sheet.note] if sheet.note else []) + sheet.notes
            for j, extra_line in enumerate(extra):
                canvas.text(max(hx, 10.0), hy + 16 * (j + 1), extra_line, size=10)
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
    hole_hem: float | None = None,
) -> Path:
    """Export the envelope rows, the parachute, and every primitive's pieces and marking
    sheets.

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
    hole_hem : float, optional
        Hem turned back round each feed hole, m (default: a double fold over the design's
        hole tape, twice its width).

    Returns
    -------
    Path
        ``index.json``.
    """
    hem, hole_tape = default_hole_hem(design)
    hem = hem if hole_hem is None else hole_hem
    sheets = envelope_sheets(design, patterns)
    row_notes = shape_row_notes(primitives)
    for sheet in sheets:
        sheet.notes += row_notes.get(sheet.piece.removeprefix("row "), [])
    pairs = envelope_seam_pairs(sheets)
    chute = parachute_sheets(design)
    sheets += chute
    pairs += parachute_seam_pairs(chute)
    for p in primitives:
        name = p.primitive.name
        fabric = skin_fabric if isinstance(skin_fabric, str) else skin_fabric.get(name, "skin")
        sheets += primitive_sheets(p, fabric, marking_allowance, hem, hole_tape)
        pairs += primitive_seam_pairs(p)
    return write_pack(sheets, out_dir, pairs, roll_width, title=design.meta.name)
