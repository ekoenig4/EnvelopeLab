"""Build-pack export: cutting patterns as 1:1 DXF and PDF sheets with an index.

A build pack holds one *sheet* per piece to cut or mark:

* the envelope's row panels (cut once per gore);
* the parachute's radial panel (cut once per radial panel) and, when it has one, its
  circular centre panel (cut once);
* every piece of every special shape's skin (its gores or panels and a tip disc);
* every overlay (an appliqué sewn on top of the envelope, ADR-0056) and a marking sheet
  for every panel its outline crosses (:mod:`envelopelab.export.overlays`);
* a *marking* sheet for every envelope panel a shape crosses or lies over: the panel with
  the footprint line (the shape's rim is sewn on it; short ticks point into the shape),
  the numbered match marks (each naming the skin piece that carries the same number) and
  the feed holes, drawn at their cut and finished sizes.

Sewing directions are written on the sheets from the same data: each skin piece says what
every edge is sewn to (the rim to the envelope line with its mark numbers, each seam to
the neighbouring piece, the top to the tip disc or the apex), and each envelope row says
which of its gores carry a marking sheet or a feed hole.

Each sheet is written as a DXF file in millimetres (``$INSUNITS`` = 4) in the pack's
``cad/`` folder, and at 1:1 on the template PDFs at the top of the pack
(:mod:`envelopelab.export.templates`: one PDF per piece, each page as large
as its piece with one side no longer than the fabric roll). ``cad/index.json`` lists
every file with its piece, cut count, fabric and finished size, the template pages, and
the pairs of edges that are sewn together. :func:`envelopelab.export.qa.check_pack` checks
a pack against AGENTS.md §6.6.

Format 3 moved the DXFs and the index into ``cad/`` and replaced ``pattern.pdf`` (roll-wide
pages) by the template files (ADR-0037). A pack can also hold *documents*
(:mod:`envelopelab.export.documents`):
a cover and index, a spec summary, a cut list, a rigging sheet, a sewing schedule and a
self-contained 3D view (:mod:`envelopelab.export.viewer`), chosen with
:class:`PackExtras`. ``index.json`` lists them under ``documents`` with the export's
provenance.

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
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from ezdxf.enums import TextEntityAlignment

from envelopelab.geometry.polygon import offset_polygon
from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.features.primitives import PrimitiveDesign
    from envelopelab.project.colours import PanelColours
    from envelopelab.project.model import PatternSet
    from envelopelab.project.overlays import OverlaySpec

MM = 1000.0  # mm per m
PT_PER_M = 72.0 / 0.0254  # PDF points per m
PACK_FORMAT = "envelopelab-build-pack/4"
CAD_DIR = "cad"
INDEX = "index.json"
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
    kind : {"envelope panel", "parachute panel", "skin piece", "overlay", "marking"}
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
    whole : Sheet, optional
        For half of a row panel cut as half gores: the whole row panel's sheet (drawn by
        the documents that show the envelope row by row, :func:`row_sheets`).
    colours : list of (str or None, list of int)
        Panel colours (ADR-0055) of the pieces cut from this sheet: each colour
        (``#rrggbb``; None: no colour chosen) with the gores (envelope panels) or piece
        numbers (skin pieces) cut in it, from 1. Empty: the design has no panel colours.
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
    whole: Sheet | None = field(default=None, repr=False)
    colours: list[tuple[str | None, list[int]]] = field(default_factory=list)

    @property
    def letter(self) -> str:
        """Row letter of an envelope panel sheet (or of the row its half belongs to)."""
        return (self.whole or self).piece.removeprefix("row ").strip()

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

    def colour_line(self) -> str:
        """The sheet's panel colours in words ("" when the design has none), generated
        from :attr:`colours` (:func:`colour_line`)."""
        return colour_line(self.colours, self.kind)


def colour_line(colours: Sequence[tuple[str | None, Sequence[int]]], kind: str) -> str:
    """Panel colours of a sheet in words, as printed on the sheet and checked by the QA.

    ``colour #c00000`` for a single skin piece; ``colours: cut 3 in #c00000 (gores 1, 5,
    7), 5 with no colour (gores 2, 3, 4, 6, 8)`` for an envelope row; "" for none.

    Parameters
    ----------
    colours : sequence of (str or None, sequence of int)
        Colour (``#rrggbb``; None: none chosen) and the gores or piece numbers cut in it.
    kind : str
        Sheet kind (``envelope panel`` names gores).
    """
    if not colours:
        return ""
    if kind != "envelope panel" and len(colours) == 1:
        colour = colours[0][0]
        return f"colour {colour}" if colour else "colour: none chosen"
    word = "gore" if kind == "envelope panel" else "piece"
    parts = []
    for colour, where in colours:
        what = f"in {colour}" if colour else "with no colour"
        numbers = ", ".join(str(n) for n in where)
        parts.append(f"{len(where)} {what} ({word}{'s' if len(where) != 1 else ''} {numbers})")
    return "colours: cut " + ", ".join(parts)


def sheet_colours(
    sheets: Sequence[Sheet],
    colours: PanelColours | None,
    gores: int,
    primitives: Sequence[PrimitiveDesign] = (),
) -> None:
    """Set :attr:`Sheet.colours` of the envelope row sheets (each half of a half-gore row
    its half's colours: its own, else the panel's) and the skin pieces from the design's
    panel colours (ADR-0055); nothing when no panel is coloured, so uncoloured designs
    export as before.

    Parameters
    ----------
    sheets : sequence of Sheet
        The pack's sheets (changed in place).
    colours : PanelColours or None
        Panel colours.
    gores : int
        Gore count (every row panel is cut once per gore).
    primitives : sequence of PrimitiveDesign
        The placed special shapes (their skin pieces' tiers and numbers).
    """
    from envelopelab.project.colours import CAP, HALVES, TIER_LETTERS, PanelRef

    if colours is None or colours.is_empty():
        return

    def grouped(pairs: Sequence[tuple[int, str | None]]) -> list[tuple[str | None, list[int]]]:
        out: dict[str | None, list[int]] = {}
        for number, colour in pairs:
            out.setdefault(colour, []).append(number)
        # Most pieces first; no colour last.
        return sorted(out.items(), key=lambda kv: (kv[0] is None, -len(kv[1]), kv[1][0]))

    for sheet in sheets:
        if sheet.kind == "envelope panel":
            # A half's sheet is named envelope-row-<R>-<left|right>-half.
            side = sheet.name.rsplit("-", 2)[-2] if sheet.whole is not None else None
            half = next((h for h in HALVES if h == side), None)
            sheet.colours = grouped(
                [
                    (g, colours.colour_of(PanelRef(None, sheet.letter, g, half)))
                    for g in range(1, gores + 1)
                ]
            )
    by_label: dict[str, tuple[str, str, int]] = {}
    for p in primitives:
        name = p.primitive.name
        for piece in p.pieces:
            if piece.role == "tip":
                by_label[piece.label] = (name, CAP, 1)
            else:
                by_label[piece.label] = (name, TIER_LETTERS[piece.tier], piece.index + 1)
    for sheet in sheets:
        if sheet.kind == "overlay":  # an overlay is coloured as piece 1 of tier A
            name = sheet.piece.removesuffix(" overlay")
            sheet.colours = [(colours.shapes.get(name, {}).get("A", {}).get(1), [1])]
            continue
        if sheet.kind != "skin piece" or sheet.name not in by_label:
            continue
        name, group, index = by_label[sheet.name]
        colour = colours.shapes.get(name, {}).get(group, {}).get(index)
        sheet.colours = [(colour, [index])]


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
    from envelopelab.geometry.gore import half_panel
    from envelopelab.project.gore_design import (
        half_gore_rows,
        panel_rows,
        row_allowance,
        row_zone,
    )
    from envelopelab.project.model import PatternSet

    assert design.gores is not None
    patterns = patterns or PatternSet()
    halves = half_gore_rows(design)
    out = []
    for row in panel_rows(design, patterns):
        zone = row_zone(design, patterns, row.label)
        whole = Sheet(
            name=f"envelope-row-{row.label}",
            piece=f"row {row.label}",
            kind="envelope panel",
            cut_count=design.gores.count,
            fabric=design.zones.get(zone, zone),
            finished=row.finished_outline,
            cut=row.cut_outline,
            edges=_panel_edges(row.right_edge),
        )
        if row.label not in halves:
            out.append(whole)
            continue
        # Half gores: each panel cut as two halves, sewn together down the centre first.
        for half in half_panel(row, row_allowance(design, patterns, row.label)):
            e = half.edges
            other = "right" if half.side == "left" else "left"
            out.append(
                Sheet(
                    name=f"envelope-row-{row.label}-{half.side}-half",
                    piece=f"row {row.label} {half.side} half",
                    kind="envelope panel",
                    cut_count=design.gores.count,
                    fabric=whole.fabric,
                    finished=half.finished,
                    cut=half.cut,
                    edges={
                        half.side: e["side"],
                        "centre": e["centre"],
                        "bottom": e["bottom"],
                        "top": e["top"],
                    },
                    note=f"half gore: sew to the {other} half along the centre seam first",
                    whole=whole,
                )
            )
    return out


def row_sheets(sheets: Sequence[Sheet]) -> list[Sheet]:
    """One sheet per envelope panel row, mouth first: the row's own sheet, or the whole
    panel of a row cut as half gores (for documents that show the envelope row by row)."""
    out: list[Sheet] = []
    for s in sheets:
        if s.kind != "envelope panel":
            continue
        row = s.whole or s
        if not out or out[-1] is not row:
            out.append(row)
    return out


def row_pieces_of(sheets: Sequence[Sheet], row: Sheet) -> list[Sheet]:
    """The sheets cut for envelope row ``row`` (itself, or its two halves)."""
    return [s for s in sheets if s.kind == "envelope panel" and (s.whole or s) is row]


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
    group: str | None = None,
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
    group : str, optional
        The object (shape group) the primitive belongs to, named on its skin sheets.

    Returns
    -------
    list of Sheet
        Skin pieces first, then one marking sheet per host panel.
    """
    name = design.primitive.name
    out: list[Sheet] = []
    skin = {(p.tier, p.index): p for p in design.pieces if p.role == "panel"}
    tip = [p for p in design.pieces if p.role == "tip"]
    for piece in design.pieces:
        own = [m for m in design.marks if m.piece == piece.label]
        marks = [(m.piece_xy[0], m.piece_xy[1], str(m.number)) for m in own]
        edges = {k: v for k, v in piece.edges.items()}
        if piece.rim is not None:
            edges["rim"] = piece.rim
        texts, notes = _piece_directions(piece, own, skin, design.primitive.pieces, tip, name)
        ticks = [
            np.vstack([pt, pt + TICK_LENGTH * (piece.finished.mean(axis=0) - pt) / d])
            for pt in (np.asarray(q, dtype=np.float64) for q in piece.seam_points)
            if (d := float(np.linalg.norm(piece.finished.mean(axis=0) - pt))) > 0.0
        ]
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
                note=f"part of {name}{f' (object {group})' if group else ''}: sew the seams "
                "between the pieces first, then the rim to the envelope",
                texts=texts,
                notes=notes,
                ticks=ticks,
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
    skin: dict[tuple[int, int], Any],
    m: int,
    tip: Sequence[Any],
    name: str,
) -> tuple[list[tuple[float, float, str]], list[str]]:
    """What every edge of a skin piece is sewn to: texts placed on the piece, and notes.

    ``skin`` holds the gores or panels by (tier, index round the axis); ``m`` is the
    number round the axis.
    """
    centre = piece.finished.mean(axis=0)
    tiers = len(skin) // m

    def at(points: FloatArray) -> tuple[float, float]:
        pts = np.asarray(points, dtype=np.float64)
        mid = pts[len(pts) // 2]
        toward = centre - mid
        norm = float(np.linalg.norm(toward))
        p = mid + (TEXT_INSET * toward / norm if norm > 0.0 else 0.0)
        return float(p[0]), float(p[1])

    texts: list[tuple[float, float, str]] = []
    notes: list[str] = []
    if piece.role == "tip":  # the tip disc or cap
        texts.append((float(centre[0]), float(centre[1]), "TIP DISC"))
        notes.append(f"TIP DISC: sew round the tops of all {name} panels")
        if piece.seam_points:
            # Each panel's top is sewn along the edge between the ticks of its two seams.
            for k, mid in enumerate(_between(piece.finished, piece.seam_points)):
                inward = centre - mid
                norm = float(np.linalg.norm(inward))
                p = mid + (0.6 * TEXT_INSET * inward / norm if norm > 0.0 else 0.0)
                label = _short(skin[(tiers - 1, k % m)].label, name)
                texts.append((float(p[0]), float(p[1]), label))
            notes.append(
                "the ticks on the edge are where the seams between the panels meet it: sew "
                "each panel's top between the ticks either side of its name"
            )
        return texts, notes
    k, i = piece.index, piece.tier
    nxt = _short(skin[(i, (k + 1) % m)].label, name)
    prv = _short(skin[(i, (k - 1) % m)].label, name)
    numbers = sorted(mk.number for mk in own_marks)
    span = f", marks {numbers[0]}-{numbers[-1]}" if numbers else ""
    if piece.rim is not None:
        texts.append((*at(piece.rim), f"RIM: sew to the envelope{span}"))
    else:  # a piece of an upper tier: its bottom is sewn to the top of the piece below
        below = _short(skin[(i - 1, k)].label, name)
        texts.append((*at(piece.edges["bottom"]), f"BOTTOM: sew to {below} (its top)"))
    texts.append((*at(piece.edges["right"]), f"sew to {nxt} (its left side)"))
    texts.append((*at(piece.edges["left"]), f"sew to {prv} (its right side)"))
    top = np.asarray(piece.edges.get("top", np.zeros((0, 2))))
    if i < tiers - 1:
        above = _short(skin[(i + 1, k)].label, name)
        texts.append((*at(top), f"TOP: sew to {above} (its bottom)"))
    elif tip and len(top) > 1:
        texts.append((*at(top), "TOP: sew to the tip disc"))
    elif len(top):
        texts.append((float(top[0][0]), float(top[0][1]) - TEXT_INSET, f"APEX of {name}"))
    panels = sorted({(mk.gore, mk.row) for mk in own_marks})
    if panels:
        where = ", ".join(f"gore {g} row {r}" for g, r in panels)
        notes.append(f"rim marks {numbers[0]}-{numbers[-1]} lie on the envelope at {where}")
    return texts, notes


def _between(ring: FloatArray, points: Sequence[tuple[float, float]]) -> list[FloatArray]:
    """Midpoints along a closed outline (CCW) between successive points on it, m."""
    pts = np.vstack([ring, ring[:1]])
    seg = np.diff(pts, axis=0)
    lengths = np.linalg.norm(seg, axis=1)
    arc = np.concatenate([[0.0], np.cumsum(lengths)])
    total = float(arc[-1])

    def param(q: FloatArray) -> float:
        rel = q - pts[:-1]
        t = np.clip(np.einsum("ij,ij->i", rel, seg) / np.maximum(lengths**2, 1e-30), 0.0, 1.0)
        d = np.linalg.norm(pts[:-1] + t[:, None] * seg - q, axis=1)
        k = int(np.argmin(d))
        return float(arc[k] + t[k] * lengths[k])

    at = [param(np.asarray(q, dtype=np.float64)) for q in points]
    out = []
    for j, a in enumerate(at):
        b = at[(j + 1) % len(at)]
        mid = (a + 0.5 * ((b - a) % total or total)) % total
        out.append(np.array([np.interp(mid, arc, pts[:, c]) for c in (0, 1)]))
    return out


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
    """Edges of a primitive sewn together: skin seams (in every tier), the horizontal
    splits (each piece's top to the bottom of the piece above it), tip, and the rim to
    the envelope.

    The rim is sewn to the footprint lines marked on the envelope panels (the marking
    sheets of :func:`primitive_sheets`). Those lines are on the flat panels, so they
    differ from the rim by the attachment ease of the design
    (:attr:`~envelopelab.features.primitives.PrimitiveDesign.mark_ease`, checked per
    match-mark interval); the pair carries that total as its ``ease``.
    """
    m = design.primitive.pieces
    by = {(p.tier, p.index): p for p in design.pieces if p.role == "panel"}
    tiers = len(by) // m
    pieces = [by[(0, k)] for k in range(m)]
    pairs = [
        SeamPair(((by[(i, k)].label, "right"),), ((by[(i, (k + 1) % m)].label, "left"),))
        for i in range(tiers)
        for k in range(m)
    ]
    # Horizontal splits: every piece's top to the bottom of the piece above it.
    pairs += [
        SeamPair(((by[(i, k)].label, "top"),), ((by[(i + 1, k)].label, "bottom"),))
        for i in range(tiers - 1)
        for k in range(m)
    ]
    tip = [p for p in design.pieces if p.role == "tip"]
    if tip:
        top = tuple((by[(tiers - 1, k)].label, "top") for k in range(m))
        pairs.append(SeamPair(top, ((tip[0].label, "top"),)))
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
    """Edges of the envelope rows sewn together: the centre seams of rows cut as half
    gores, the gore sides (a panel's left side to the next gore's right side) and the row
    seams (a row's top to the next row's bottom, both halves together)."""
    rows = row_sheets(sheets)
    pieces = [row_pieces_of(sheets, r) for r in rows]
    pairs: list[SeamPair] = []
    for parts in pieces:
        if len(parts) == 2:
            left, right = parts
            pairs.append(SeamPair(((left.name, "centre"),), ((right.name, "centre"),)))
    for parts in pieces:
        left = next(p for p in parts if "left" in p.edges)
        right = next(p for p in parts if "right" in p.edges)
        pairs.append(SeamPair(((left.name, "left"),), ((right.name, "right"),)))
    for low, high in zip(pieces[:-1], pieces[1:], strict=True):
        pairs.append(
            SeamPair(tuple((p.name, "top") for p in low), tuple((p.name, "bottom") for p in high))
        )
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
    colour = sheet.colour_line()
    lines = [sheet.header()] + ([colour] if colour else [])
    lines += ([sheet.note] if sheet.note else []) + sheet.notes
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


def write_pack(
    sheets: Sequence[Sheet],
    out_dir: str | Path,
    seam_pairs: Sequence[SeamPair] = (),
    roll_width: float = DEFAULT_ROLL_WIDTH,
    title: str = "",
    documents: Sequence[dict[str, str]] = (),
    provenance: dict[str, str] | None = None,
    shape_groups: dict[str, list[str]] | None = None,
) -> Path:
    """Write a build pack: the 1:1 template PDFs at the top of ``out_dir``
    (:mod:`envelopelab.export.templates`) and, in ``cad/``, one DXF per sheet and
    ``index.json``.

    Parameters
    ----------
    sheets : sequence of Sheet
        Sheets in m (names unique).
    out_dir : str or Path
        Directory to write (created; files of the same names are replaced).
    seam_pairs : sequence of SeamPair
        Edges sewn together (checked by the QA).
    roll_width : float
        Fabric roll width, m: one side of every template page is no longer.
    title : str
        Pack title (the design name; also the file-name prefix of the templates).
    documents : sequence of dict
        Documents already written to ``out_dir`` (``file``, ``kind``, ``description``;
        paths relative to ``out_dir``), listed in the index.
    provenance : dict, optional
        Where the pack comes from (:class:`envelopelab.export.documents.Provenance`).
    shape_groups : dict of str to list of str, optional
        Members of every shape group (object), listed in the index.

    Returns
    -------
    Path
        The index file (``cad/index.json``).
    """
    from envelopelab.export.templates import template_files, write_template_pdf

    names = [s.name for s in sheets]
    if len(set(names)) != len(names):
        raise BuildPackError("sheet names must be unique")
    if roll_width <= 2 * PDF_MARGIN:
        raise BuildPackError("roll width must exceed the page margins")
    if not sheets:
        raise BuildPackError("no sheets to write")
    out = Path(out_dir)
    cad = out / CAD_DIR
    cad.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for sheet in sheets:
        write_dxf(sheet, cad / f"{sheet.name}.dxf")
        w, h = sheet.finished_size
        entries.append(
            {
                "file": f"{CAD_DIR}/{sheet.name}.dxf",
                "piece": sheet.piece,
                "kind": sheet.kind,
                "cut_count": sheet.cut_count,
                "fabric": sheet.fabric,
                "finished_width_mm": round(w * MM, 3),
                "finished_height_mm": round(h * MM, 3),
            }
        )
        if sheet.colours:
            entries[-1]["colours"] = [
                {"colour": colour, "count": len(where), "numbers": list(where)}
                for colour, where in sheet.colours
            ]
    files = template_files(title, sheets)
    templates = []
    for tfile in files:
        pages = write_template_pdf(tfile, out / tfile.name, roll_width)
        templates.append(
            {
                "file": tfile.name,
                "description": tfile.description,
                "pages": pages,
            }
        )
    index = {
        "format": PACK_FORMAT,
        "title": title,
        "units": "mm",
        "roll_width_mm": round(roll_width * MM, 3),
        "provenance": provenance or {},
        "templates": templates,
        "documents": list(documents),
        "sheets": entries,
        "shape_groups": shape_groups or {},
        "seam_pairs": [
            {
                "a": [{"file": f"{CAD_DIR}/{n}.dxf", "edge": e} for n, e in pair.a],
                "b": [{"file": f"{CAD_DIR}/{n}.dxf", "edge": e} for n, e in pair.b],
                "tolerance_mm": SEWN_EDGE_TOLERANCE * MM,
                "ease_mm": round(pair.ease * MM, 3),
            }
            for pair in seam_pairs
        ],
    }
    path = cad / INDEX
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
    extras: PackExtras | None = None,
    groups: dict[str, str] | None = None,
    colours: PanelColours | None = None,
    overlays: Sequence[OverlaySpec] = (),
) -> Path:
    """Export the envelope rows, the parachute, and every primitive's pieces and marking
    sheets, and the documents chosen in ``extras``.

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
    extras : PackExtras, optional
        Documents to write with the sheets (default: none, the sheets only).
    groups : dict of str to str, optional
        Shape group (object) of each primitive that has one, by primitive name; listed in
        ``index.json`` (``shape_groups``) and named on the skin sheets.
    colours : PanelColours, optional
        Panel colours (ADR-0055): each envelope row and skin piece sheet says which
        pieces to cut in which colour (header notes, template, ``index.json``
        ``colours``), the 3D view draws them and the documents add the colour plan.
    overlays : sequence of OverlaySpec
        Appliqués sewn on the envelope (ADR-0056): each gets its cut piece, a marking
        sheet per panel its outline crosses and a seam pair
        (:mod:`envelopelab.export.overlays`). The fabric of each is its own, else that of
        the row under its centre.

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
        if sheet.kind == "envelope panel":
            sheet.notes += row_notes.get(sheet.letter, [])
    pairs = envelope_seam_pairs(sheets)
    chute = parachute_sheets(design)
    sheets += chute
    pairs += parachute_seam_pairs(chute)
    for p in primitives:
        name = p.primitive.name
        fabric = skin_fabric if isinstance(skin_fabric, str) else skin_fabric.get(name, "skin")
        group = (groups or {}).get(name)
        sheets += primitive_sheets(p, fabric, marking_allowance, hem, hole_tape, group)
        pairs += primitive_seam_pairs(p)
    layouts: list[Any] = []
    if overlays:
        from envelopelab.export.overlays import overlay_pack
        from envelopelab.project.model import PatternSet as Patterns
        from envelopelab.project.shapes import envelope_surface

        surface = envelope_surface(design, patterns if patterns is not None else Patterns())
        rows = {s.letter: s.fabric for s in sheets if s.kind == "envelope panel"}
        fabric_of = {}
        for o in overlays:
            if o.fabric:
                fabric_of[o.name] = o.fabric
            else:
                row = surface.rows[int(surface.row_index(np.array([o.placement.tape_position]))[0])]
                fabric_of[o.name] = rows.get(row.label, "applique")
        more, more_pairs, layouts = overlay_pack(overlays, surface, fabric_of)
        sheets += more
        pairs += more_pairs
    gores = design.gores.count if design.gores is not None else 0
    sheet_colours(sheets, colours, gores, primitives)
    documents: list[dict[str, str]] = []
    prov = None
    if extras is not None and extras.include:
        documents, prov = write_documents(
            design,
            sheets,
            pairs,
            Path(out_dir),
            extras,
            patterns,
            primitives,
            roll_width,
            colours,
            layouts,
        )
    return write_pack(
        sheets,
        out_dir,
        pairs,
        roll_width,
        title=design.meta.name,
        documents=documents,
        provenance=None if prov is None else prov.as_dict(),
        shape_groups=_group_lists(primitives, groups or {}),
    )


def _group_lists(
    primitives: Sequence[PrimitiveDesign], groups: dict[str, str]
) -> dict[str, list[str]]:
    """Members of every shape group, in the order of the primitives."""
    out: dict[str, list[str]] = {}
    for p in primitives:
        group = groups.get(p.primitive.name)
        if group:
            out.setdefault(group, []).append(p.primitive.name)
    return out


@dataclass
class PackExtras:
    """The documents of a build pack and what they are made from.

    Attributes
    ----------
    include : frozenset of str
        Keys of :data:`envelopelab.export.documents.DOCUMENTS` to write.
    outputs : GoreOutputs, optional
        The design's live outputs (:func:`envelopelab.project.gore_design.gore_outputs`)
        for the spec summary, cut list (tapes) and rigging sheet; computed when missing.
    shape_scenes : dict of str to Scene, optional
        One 3D view per special shape (by name), written as ``<slug>-<shape>-3d.html``.
    scene : Scene, optional
        The 3D view to write (default :func:`envelopelab.export.viewer.design_scene`:
        the design and its rigging, no solver result).
    provenance : Provenance, optional
        Where the pack comes from (default: this installation, now, an empty hash).
    status : str
        The structural result in one line for the index (e.g. "Preview run ...,
        converged, not verified with CalculiX"), "" for none.
    table_length : float
        Cutting-table length, m (a shop limit printed in the index).
    fabrics : FabricLibraryRepository or FabricCatalog, optional
        Fabric library; the lift chart takes its top-temperature limit from it (the
        generic ``assumed`` limit without it).
    """

    include: frozenset[str] = frozenset()
    outputs: Any = None
    scene: Any = None
    shape_scenes: Any = None
    provenance: Any = None
    status: str = ""
    table_length: float = 12 * 0.3048  # m (12 ft, a common cutting table; source: assumed)
    fabrics: Any = None


def write_documents(
    design: DesignDocument,
    sheets: Sequence[Sheet],
    pairs: Sequence[SeamPair],
    out: Path,
    extras: PackExtras,
    patterns: PatternSet | None = None,
    primitives: Sequence[PrimitiveDesign] = (),
    roll_width: float = DEFAULT_ROLL_WIDTH,
    colours: PanelColours | None = None,
    overlays: Sequence[Any] = (),
) -> tuple[list[dict[str, str]], Any]:
    """Write the documents of ``extras`` into ``out``; returns their index entries and the
    provenance used. The build-pack index is written last: it lists every file. With
    panel ``colours`` the 3D view draws them (when it is the default design scene) and
    the planning documents add the colour plan."""
    from envelopelab.export import documents as docs
    from envelopelab.export.shop import (
        FileEntry,
        PackContext,
        write_build_log,
        write_index,
        write_spec_summary,
    )
    from envelopelab.export.templates import slug, template_files
    from envelopelab.export.viewer import design_scene, write_viewer

    unknown = set(extras.include) - set(docs.DOCUMENTS)
    if unknown:
        raise BuildPackError(f"unknown build-pack documents: {sorted(unknown)}")
    out.mkdir(parents=True, exist_ok=True)
    outputs = extras.outputs
    if outputs is None:
        from envelopelab.project.gore_design import gore_outputs
        from envelopelab.project.model import PatternSet as Patterns

        try:
            outputs = gore_outputs(design, patterns if patterns is not None else Patterns())
        except ValueError:
            outputs = None
    prov = extras.provenance or docs.provenance(design.compute_content_hash())
    stem = slug(design.meta.name)
    templates = template_files(design.meta.name, sheets)
    ctx = PackContext(
        design,
        outputs,
        sheets,
        pairs,
        primitives,
        templates,
        roll_width,
        extras.table_length,
        prov,
        extras.status,
        stem,
        colours=None if colours is None or colours.is_empty() else colours,
        overlays=list(overlays),
    )
    written: list[tuple[Path, str, str, str, str]] = []  # path, kind, group, tag, what

    def add(kind: str, *paths: Path) -> None:
        for path in paths:
            _key, group, tag, what = docs.document_description(path.name, stem)
            written.append((path, kind, group, tag, what))

    if "viewer" in extras.include:
        scene = extras.scene
        if scene is None:
            scene = design_scene(
                design, None if outputs is None else outputs.rigging, colours=ctx.colours
            )
        add("viewer", write_viewer(scene, out / docs.document_files(stem, "viewer")[0]))
        from envelopelab.export.templates import piece_name

        for shape_name, shape_scene in (extras.shape_scenes or {}).items():
            path = write_viewer(shape_scene, out / f"{stem}-{piece_name(shape_name)}-3d.html")
            written.append(
                (
                    path,
                    "viewer",
                    "APPENDAGES",
                    "REF",
                    f"{shape_name}: 3D model, designed and inflated, with its simulation metrics",
                )
            )
    if "spec" in extras.include:
        add("spec", write_spec_summary(ctx, out / docs.document_files(stem, "spec")[0]))
    if "planning" in extras.include:
        from envelopelab.export import planning

        add(
            "planning",
            planning.write_layout_diagram(ctx, out),
            *planning.write_panel_map(ctx, out),
            planning.write_gore_layout(ctx, out / ctx.file("gore-layout.pdf")),
            *planning.write_dimensions(ctx, out),
        )
        if ctx.colours is not None:
            from envelopelab.export.colour_plan import write_colour_plan

            for path, what in write_colour_plan(ctx, out):
                written.append((path, "planning", "LAYOUT & PLANNING", "REF", what))
    if "lift_chart" in extras.include:
        from envelopelab.export.lift_chart import write_lift_chart

        pdf_name, csv_name = docs.document_files(stem, "lift_chart")
        add("lift_chart", *write_lift_chart(ctx, out / pdf_name, out / csv_name, extras.fabrics))
    if "sewing" in extras.include:
        from envelopelab.export.planning import write_sewing_schedule

        add("sewing", write_sewing_schedule(ctx, out / docs.document_files(stem, "sewing")[0]))
    if "build_log" in extras.include:
        add("build_log", write_build_log(ctx, out / docs.document_files(stem, "build_log")[0]))
    if "assembly" in extras.include:
        from envelopelab.export import assembly
        from envelopelab.export.templates import piece_name

        written.append(
            (
                assembly.write_envelope_assembly(ctx, out / ctx.file("assembly-envelope.pdf")),
                "assembly",
                "LAYOUT & PLANNING",
                "REF",
                "picture instructions: the base envelope, step by step",
            )
        )
        for prim in primitives:
            shape = prim.primitive.name
            path = out / ctx.file(f"assembly-{piece_name(shape)}.pdf")
            written.append(
                (
                    assembly.write_shape_assembly(ctx, prim, path),
                    "assembly",
                    "APPENDAGES",
                    "REF",
                    f"picture instructions: {shape}, step by step",
                )
            )
    if "appendages" in extras.include:
        from envelopelab.export import appendages as app

        for prim in primitives:
            spec_name, build_name, _patterns = app.shape_files(ctx, prim)
            name = prim.primitive.name
            written.append(
                (
                    app.write_shape_spec(ctx, prim, out / spec_name),
                    "appendages",
                    "APPENDAGES",
                    "REF",
                    f"{name}: spec, marking, skin cut list, match marks, feed holes",
                )
            )
            written.append(
                (
                    app.write_shape_build(ctx, prim, out / build_name),
                    "appendages",
                    "APPENDAGES",
                    "REF",
                    f"{name}: build procedure, step by step",
                )
            )
        if design.turning_vents:
            vents, vent_panels = app.write_turning_vents(ctx, out)
            written.append(
                (vents, "appendages", "APPENDAGES", "REF", "vent placement and assembly")
            )
            written.append(
                (vent_panels, "appendages", "APPENDAGES", "REF", "which panels carry the vents")
            )
    if "top_bottom" in extras.include:
        from envelopelab.export import appendages as app

        add(
            "top_bottom",
            app.write_parachute(ctx, out / ctx.file("parachute.pdf")),
            app.write_scoop(ctx, out / ctx.file("scoop.pdf")),
        )
    if "cad" in extras.include:
        from envelopelab.export.cad import write_cad

        for path, what in write_cad(ctx, out):
            written.append((path, "cad", "TOP & BOTTOM / CAD", "CAD", what))
    entries = [
        {"file": path.name, "kind": kind, "description": what}
        for path, kind, _group, _tag, what in written
    ]
    if "index" in extras.include:
        index_name = docs.document_files(stem, "index")[0]
        files = [FileEntry(index_name, *docs.document_description(index_name, stem)[1:])]
        files += [FileEntry(path.name, group, tag, what) for path, _k, group, tag, what in written]
        groups = {
            "envelope panel": "PANEL TEMPLATES",
            "parachute panel": "TOP & BOTTOM / CAD",
            "skin piece": "APPENDAGES",
            "overlay": "APPENDAGES",
        }
        for t in templates:
            group = groups.get(t.pages[0].sheet.kind, "PANEL TEMPLATES")
            files.append(FileEntry(t.name, group, "1:1", t.description))
        files.append(
            FileEntry(
                f"{CAD_DIR}/", "TOP & BOTTOM / CAD", "CAD", "one DXF per piece (mm), index.json"
            )
        )
        ctx.files = files
        write_index(ctx, out / index_name)
        entries.insert(
            0,
            {
                "file": index_name,
                "kind": "index",
                "description": docs.document_description(index_name, stem)[3],
            },
        )
    return entries, prov
