r"""Shop documents of a build pack: the build-pack index, the spec summary and the build log.

They follow the layout of a builder's hand-made pack (ADR-0037), generated from the
design instead of typed:

* ``<slug>-00-BUILD-PACK-INDEX.pdf`` (A3 landscape, three sheets): the key dimensions in
  metric and English, the features (special shapes, feed holes, turning vents, scoop,
  parachute and rigging), the shop limits the pack is built to (bolt width, cutting
  table, largest cut piece), the printing rules; the index of every file, grouped
  (start here, layout and planning, panel templates, appendages, top and bottom, CAD)
  and tagged ``REF`` (reading), ``1:1`` (print at actual size) or ``CAD``; and the build
  order, each step naming the sheet to work from, with the airworthiness note;
* ``<slug>-spec-summary.pdf`` (A4 landscape): key measurements in metric and English,
  and the configuration;
* ``<slug>-build-log.pdf`` (A3 landscape): sign-off sheets (item, spec, done by, date,
  checked) for cutting, each special shape, the turning vents, and the parachute,
  rigging and final inspection.

Every number comes from the design, its outputs (:func:`envelopelab.project.gore_design.
gore_outputs`), the sheets and the placed shapes; English units are converted only here,
at the output boundary (1 in = 25.4 mm, 1 ft = 0.3048 m, 1 cu ft = 0.028316846592 m^3,
exact by definition). A value tagged ``assumed`` says so; a factor of safety below the
requirement is printed ``FAILS``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from envelopelab.export.documents import (
    SAFETY_NOTICE,
    Provenance,
    assumed_values,
    pdf_text,
    rigging_lines,
)

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.export.build_pack import SeamPair, Sheet
    from envelopelab.export.templates import TemplateFile
    from envelopelab.features.primitives import PrimitiveDesign
    from envelopelab.project.gore_design import GoreOutputs

A3_LANDSCAPE = (1190.55, 841.89)  # points
A4_LANDSCAPE = (841.89, 595.28)
INCH = 0.0254  # m, exact
FOOT = 0.3048  # m, exact
CUBIC_FOOT = FOOT**3  # m^3
#: Default cutting-table length, m (12 ft; a shop limit, source: assumed).
DEFAULT_TABLE_LENGTH = 12 * FOOT
GREEN = (0.20, 0.42, 0.13)
RED = (0.75, 0.12, 0.10)
BLUE = (0.11, 0.37, 0.71)
MUTED = (0.33, 0.36, 0.40)
RULE = (0.80, 0.83, 0.86)

#: File groups of the index, in order.
GROUPS = ("START HERE", "LAYOUT & PLANNING", "PANEL TEMPLATES", "APPENDAGES", "TOP & BOTTOM / CAD")


# --------------------------------------------------------------------------------------
# Units at the output boundary
# --------------------------------------------------------------------------------------


def ft_in(metres: float) -> str:
    """``metres`` as feet and whole inches, e.g. ``60 ft 2 in``."""
    inches = round(metres / INCH)
    feet, rest = divmod(inches, 12)
    return f"{feet} ft {rest} in" if feet else f"{rest} in"


def inches(metres: float, digits: int = 1) -> str:
    """``metres`` in inches, e.g. ``14.2 in``."""
    return f"{metres / INCH:.{digits}f} in"


def mm(metres: float) -> str:
    """``metres`` in whole millimetres with a thousands separator, e.g. ``18,338 mm``."""
    return f"{metres * 1000:,.0f} mm"


def both(metres: float) -> str:
    """Metric and English: ``18,338 mm / 60 ft 2 in`` (lengths over 1 m) or
    ``360 mm / 14.2 in``."""
    return f"{mm(metres)} / {ft_in(metres) if metres >= 1.0 else inches(metres)}"


def volume_both(m3: float) -> str:
    """``2,610 m3 / 92,171 cu ft``."""
    return f"{m3:,.0f} m3 / {m3 / CUBIC_FOOT:,.0f} cu ft"


# --------------------------------------------------------------------------------------
# The pack's contents, as the documents see them
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FileEntry:
    """A file of the pack in the index: name, group, tag and what it is for."""

    name: str
    group: str
    tag: str  # "REF", "1:1" or "CAD"
    description: str


@dataclass
class PackContext:
    """What the shop documents are made from.

    Attributes
    ----------
    design : DesignDocument
        Standard-gore design, SI.
    outputs : GoreOutputs or None
        Its live outputs (None when they cannot be computed: the documents say so).
    sheets, pairs : sequence
        The pack's sheets and sewn edge pairs (:mod:`envelopelab.export.build_pack`).
    primitives : sequence of PrimitiveDesign
        Placed special shapes.
    templates : list of TemplateFile
        The 1:1 template files (:func:`envelopelab.export.templates.template_files`).
    files : list of FileEntry
        Every file of the pack, for the index (filled by the exporter).
    roll_width, table_length : float
        Shop limits, m: fabric bolt width and cutting-table length.
    provenance : Provenance, optional
    status : str
        The structural result in one line ("" for none).
    slug : str
        File-name prefix.
    """

    design: DesignDocument
    outputs: GoreOutputs | None
    sheets: Sequence[Sheet]
    pairs: Sequence[SeamPair]
    primitives: Sequence[PrimitiveDesign]
    templates: list[TemplateFile]
    roll_width: float
    table_length: float = DEFAULT_TABLE_LENGTH
    provenance: Provenance | None = None
    status: str = ""
    slug: str = "design"
    files: list[FileEntry] = field(default_factory=list)

    def shape_pieces(self, shape: str) -> str:
        """The template files of a special shape's skin pieces, as a range in words."""
        from envelopelab.export.templates import shape_piece_files

        names = shape_piece_files(self.design.meta.name, self.sheets, shape)
        if not names:
            return "(no skin pieces)"
        return names[0] if len(names) == 1 else f"{names[0]} ... {names[-1]}"

    def file(self, suffix: str) -> str:
        """The pack file name ``<slug>-<suffix>``."""
        return f"{self.slug}-{suffix}"

    @property
    def rows(self) -> list[Sheet]:
        """Envelope row sheets, mouth first."""
        return [s for s in self.sheets if s.kind == "envelope panel"]

    @property
    def gores(self) -> int:
        g = self.design.gores
        return g.count if g is not None else 0

    def template_for(self, sheet_name: str) -> str:
        """The template file that draws ``sheet_name`` ("" when none)."""
        for t in self.templates:
            if any(p.sheet.name == sheet_name for p in t.pages):
                return t.name
        return ""


def _letters(rows: Sequence[Sheet]) -> list[str]:
    return [r.piece.removeprefix("row ") for r in rows]


def largest_piece(sheets: Sequence[Sheet]) -> tuple[float, float, str]:
    """The largest cut piece: its short side, its long side (m) and its sheet name."""
    best = (0.0, 0.0, "")
    for s in sheets:
        if s.cut_count <= 0:
            continue
        span = s.cut.max(axis=0) - s.cut.min(axis=0)
        short, long = sorted((float(span[0]), float(span[1])))
        if (short, long) > best[:2]:
            best = (short, long, s.name)
    return best


def shape_rows(p: PrimitiveDesign) -> tuple[list[int], list[str]]:
    """Gores and rows a placed shape is sewn on (from its footprint lines)."""
    gores = sorted({a.gore for a in p.attachment})
    rows = sorted({a.row for a in p.attachment})
    return gores, rows


def _range(values: Sequence[Any]) -> str:
    if not values:
        return "-"
    return f"{values[0]}-{values[-1]}" if len(values) > 1 else f"{values[0]}"


def _row_span(rows: Sequence[str]) -> str:
    return f"{rows[0]} .. {rows[-1]}" if len(rows) > 2 else ", ".join(rows)


def key_specs(ctx: PackContext) -> list[tuple[str, str]]:
    """The key dimensions (metric / English) of the index's first sheet."""
    d, out = ctx.design, ctx.outputs
    g = d.gores
    assert g is not None
    rows = _letters(ctx.rows)
    allowance = d.seam_types[0].allowance if d.seam_types else 0.0
    seam = d.seam_types[0].name if d.seam_types else "-"
    specs: list[tuple[str, str]] = []
    if out is not None:
        specs += [
            ("Volume", volume_both(out.volume)),
            ("Envelope height", both(out.height)),
            ("Envelope width", both(out.max_diameter)),
            (
                "Gore length",
                f"{out.meridian_length:.2f} m / {ft_in(out.meridian_length)} - "
                f"{len(rows)} rows, {_row_span(rows)}",
            ),
        ]
    else:
        specs.append(("Size", "not available: the design outputs could not be computed"))
    specs += [
        (
            "Mouth / parachute hole",
            f"O{mm(g.mouth_diameter)} / O{mm(g.parachute_hole_diameter)} "
            f"(seal overlap {mm(g.seal_overlap)})",
        ),
        ("Gores", f"{g.count} gores x {len(rows)} panel rows"),
        ("Seam allowance", f"{mm(allowance)} ({inches(allowance)}), {seam}"),
        (
            "Load tapes",
            f"{d.tapes.vertical.tape_class} {mm(d.tapes.vertical.width)}; "
            f"{d.tapes.horizontal.tape_class}; {d.tapes.rim.tape_class}; "
            f"{d.tapes.hole.tape_class}",
        ),
        ("Fabrics", ", ".join(f"{z}: {f}" for z, f in d.zones.items())),
    ]
    return specs


def features(ctx: PackContext) -> list[tuple[str, str]]:
    """Every feature of the design, one line each, for the index and the spec."""
    d = ctx.design
    out: list[tuple[str, str]] = []
    for p in ctx.primitives:
        gores, rows = shape_rows(p)
        kind = type(p.primitive).__name__.lower()
        rim = sum(a.length for a in p.attachment)
        out.append(
            (
                p.primitive.name,
                f"{kind} on gores {_range(gores)}, rows {_range(rows)} - {len(p.pieces)} skin "
                f"pieces, rim {rim:.2f} m sewn to the envelope over {len(p.marks)} match marks",
            )
        )
        holes = p.feed_holes
        if holes:
            text = "; ".join(f"gore {h.gore} panel {h.row} O{mm(2 * h.radius)}" for h in holes)
            out.append((f"{p.primitive.name} feed holes", f"ENVELOPE panels, finished: {text}"))
    for v in d.turning_vents:
        out.append(("Turning vent", f"{v.name} at seam {v.seam}"))
    if d.scoop is not None:
        out.append(("Scoop", "half scoop in the mouth row's fabric (see the scoop sheet)"))
    if d.parachute is not None:
        out.append(("Parachute", f"{d.parachute.panel_count} radial panels"))
    if d.rigging.red_line is not None:
        out.append(("Red line", f"led down seam {d.rigging.red_line.guide_seam}"))
    if d.rigging.flying_wires is not None:
        out.append(("Flying wires", "to the burner frame (see the scoop sheet)"))
    return out or [("Features", "none: a plain envelope")]


def shop_limits(ctx: PackContext) -> list[str]:
    """The shop limits the pack is built to, and whether every piece keeps to them."""
    short, long, name = largest_piece(ctx.sheets)
    roll, table = ctx.roll_width, ctx.table_length
    lines = [
        f"Cloth {both(roll)} bolt - the largest cut piece is {mm(short)} across ({name}).",
        f"Table {both(table)} - the longest cut piece is {mm(long)}.",
        "Cut envelope panels with the ROW HEIGHT across the bolt and the gore width along "
        "the roll.",
    ]
    if short > roll:
        lines.append(
            f"WARNING: {name} is wider than the bolt both ways; it prints in bands "
            "and must be pieced."
        )
    if long > table:
        lines.append(f"WARNING: {name} is longer than the table ({mm(long)}).")
    return lines


def printing_rules(ctx: PackContext) -> list[str]:
    """Printing rules for the 1:1 sheets."""
    return [
        "All 1:1 sheets print at 100 % - NEVER 'fit to page' or 'shrink oversized pages'.",
        "Measure BOTH calibration lines (across and along) on every 1:1 sheet before you cut.",
        f"Every 1:1 sheet has one side no longer than {mm(ctx.roll_width)} so it fits the roll.",
        "Solid = CUT. Dotted = SEW (finished). Red = feature marks. Blue = finished sizes.",
    ]


def build_order(ctx: PackContext) -> list[tuple[str, str]]:
    """The build order: (step name, what to do and which sheet to work from)."""
    d = ctx.design
    g = d.gores
    assert g is not None
    rows = ctx.rows
    steps: list[tuple[str, str]] = []
    steps.append(
        (
            "PRINT & VERIFY",
            "Print all 1:1 sheets at 100 %. Measure the calibration lines on each - both "
            "directions.",
        )
    )
    counts = ", ".join(f"{s.cut_count} x {s.piece.removeprefix('row ')}" for s in rows)
    steps.append(
        (
            "CUT PANELS",
            f"Cut the envelope panels ({counts}) from the panel templates. Lay the ROW "
            "HEIGHT across the bolt. Mark each panel with its letter and an UP arrow.",
        )
    )
    marked = [t for t in ctx.templates if t.pages and t.pages[0].overlays]
    if marked:
        steps.append(
            (
                "MARK PANELS",
                "Transfer the feature marks onto the panels of the gores named on "
                + ", ".join(t.name for t in marked)
                + " (footprint lines, match marks, feed holes) before assembly.",
            )
        )
    for p in ctx.primitives:
        name = p.primitive.name
        steps.append(
            (
                f"{name.upper()} SKIN",
                f"Cut the {len(p.pieces)} skin pieces 1:1 from "
                f"{ctx.shape_pieces(name)} and sew them into the skin "
                "(seams in the sewing schedule).",
            )
        )
        holes = p.feed_holes
        if holes:
            text = "; ".join(f"gore {h.gore} panel {h.row} O{mm(2 * h.radius)}" for h in holes)
            steps.append((f"{name.upper()} FEED HOLES", f"Cut and hem the feed holes: {text}."))
    first = rows[0].piece.removeprefix("row ") if rows else "A"
    steps.append(
        (
            "BUILD GORES",
            f"Join the panels into {g.count} vertical gores, felling the row seams bottom-up "
            f"(row {first} first).",
        )
    )
    steps.append(
        (
            "JOIN GORES",
            f"Join gores 1-{g.count} over the vertical load tapes ({d.tapes.vertical.tape_class}).",
        )
    )
    if d.turning_vents:
        steps.append(
            (
                "TURNING VENTS",
                "Fit the vents ("
                + ", ".join(f"{v.name} at seam {v.seam}" for v in d.turning_vents)
                + ").",
            )
        )
    for p in ctx.primitives:
        gores, rows_on = shape_rows(p)
        steps.append(
            (
                p.primitive.name.upper(),
                f"Sew the rim of {p.primitive.name} onto the footprint line marked on gores "
                f"{_range(gores)}, rows {_range(rows_on)}, matching the {len(p.marks)} "
                "numbered marks.",
            )
        )
    steps.append(
        (
            "MOUTH & APERTURE",
            f"Hem the mouth (O{mm(g.mouth_diameter)}) over the rim tape and the aperture "
            f"(O{mm(g.parachute_hole_diameter)}) over the hole tape."
            + (" Fit the scoop." if d.scoop is not None else ""),
        )
    )
    if d.parachute is not None:
        steps.append(
            (
                "PARACHUTE",
                f"Set the parachute with {mm(g.seal_overlap)} seal overlap; rig the lines to "
                f"the lengths on {ctx.file('parachute.pdf')}.",
            )
        )
    if d.rigging.red_line is not None or d.rigging.flying_wires is not None:
        steps.append(("LINES & WIRES", f"Red line and flying wires per {ctx.file('scoop.pdf')}."))
    steps.append(
        (
            "INSPECT & SIGN OFF",
            f"Seam and load checks, parachute seating. Complete every sheet of "
            f"{ctx.file('build-log.pdf')}.",
        )
    )
    return steps


def _slug(name: str) -> str:
    from envelopelab.export.templates import slug

    return slug(name)


# --------------------------------------------------------------------------------------
# Page writer
# --------------------------------------------------------------------------------------


class Pages:
    """Landscape document pages with centred titles, key-value rows and ruled tables."""

    def __init__(self, size: tuple[float, float] = A3_LANDSCAPE, footer: str = "") -> None:
        from envelopelab.report.pdf import PdfCanvas

        self.size = size
        self.canvas = PdfCanvas(size)
        self.footer = pdf_text(footer)
        self.margin = 48.0
        self.started = False
        self._begin()

    def _begin(self) -> None:
        w, h = self.size
        self.y = h - self.margin
        if self.footer:
            self.text_centre(self.margin / 2, self.footer, 8, color=BLUE)

    def new_page(self) -> None:
        self.canvas.new_page()
        self._begin()

    def text_centre(
        self, y: float, text: str, size: float, bold: bool = False, color: Any = (0, 0, 0)
    ) -> None:
        t = pdf_text(text)
        self.canvas.text(self.size[0] / 2 - 0.26 * size * len(t), y, t, size, bold, color)

    def title(self, title: str, subtitle: str = "", subtitle2: str = "") -> None:
        self.text_centre(self.y - 8, title, 20, bold=True)
        self.y -= 34
        if subtitle:
            self.text_centre(self.y, subtitle, 13, bold=True, color=GREEN)
            self.y -= 20
        if subtitle2:
            self.text_centre(self.y, subtitle2, 9, color=MUTED)
            self.y -= 22

    def heading(self, text: str, x: float | None = None, color: Any = (0, 0, 0)) -> None:
        self._need(40)
        if x is None:
            self.text_centre(self.y, text, 11, bold=True, color=color)
        else:
            self.canvas.text(x, self.y, pdf_text(text), 11, bold=True, color=color)
        self.y -= 20

    def _need(self, height: float) -> None:
        if self.y - height < self.margin:
            self.new_page()

    def kv(self, rows: Sequence[tuple[str, str]], key_width: float = 260.0) -> None:
        w = self.size[0]
        left, right = self.margin + 20, w - self.margin - 20
        self.canvas.line(left - 10, self.y + 12, right + 10, self.y + 12, width=0.8)
        for key, value in rows:
            lines = _wrap(pdf_text(value), int((right - left - key_width) / (9 * 0.5)))
            self._need(14 * len(lines) + 6)
            self.canvas.text(left, self.y, pdf_text(key), 9, bold=True)
            for k, line in enumerate(lines):
                self.canvas.text(left + key_width, self.y - 13 * k, line, 9)
            self.y -= 13 * len(lines) + 9
            self.canvas.line(left - 10, self.y + 10, right + 10, self.y + 10, RULE, 0.4)
        self.y -= 10

    def lines(self, texts: Sequence[str], x: float, width: float, size: float = 9) -> float:
        """Wrapped lines at ``x`` (points); returns the y below them."""
        y = self.y
        for text in texts:
            for line in _wrap(pdf_text(text), int(width / (size * 0.5))):
                self.canvas.text(x, y, line, size)
                y -= size + 5
            y -= 3
        return y

    def table(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[str]],
        widths: Sequence[float],
        fails: set[int] | None = None,
        row_height: float = 18.0,
        size: float = 8.0,
    ) -> None:
        fails = fails or set()
        left = self.margin
        total = sum(widths)
        scale = (self.size[0] - 2 * self.margin) / total
        cols = [w * scale for w in widths]

        def draw(values: Sequence[str], bold: bool, colour: Any) -> None:
            self._need(row_height)
            x = left
            for c, value in enumerate(values):
                limit = max(int((cols[c] - 6) / (size * 0.5)), 3)
                text = pdf_text(str(value))
                if len(text) > limit:
                    text = text[: limit - 1] + "~"
                self.canvas.text(x + 3, self.y, text, size, bold, colour)
                x += cols[c]
            self.canvas.line(left, self.y - 5, left + sum(cols), self.y - 5, RULE, 0.5)
            self.y -= row_height

        draw(columns, True, (0, 0, 0))
        for k, values in enumerate(rows):
            if self.y - row_height < self.margin:
                self.new_page()
                draw(columns, True, (0, 0, 0))
            draw(values, k in fails, RED if k in fails else (0, 0, 0))
        self.y -= 8

    def save(self, path: str | Path) -> Path:
        return self.canvas.save(path)


def _wrap(text: str, width: int) -> list[str]:
    words, line, out = text.split(), "", []
    for word in words:
        if line and len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    return out


def _subtitle(ctx: PackContext) -> str:
    d, out = ctx.design, ctx.outputs
    parts = []
    if out is not None:
        parts.append(volume_both(out.volume))
    parts.append(f"{ctx.gores} gores x {len(ctx.rows)} panel rows")
    parts.append(", ".join(sorted(set(d.zones.values()))))
    return "  -  ".join(parts)


# --------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------


def write_index(ctx: PackContext, path: str | Path) -> Path:
    """``<slug>-00-BUILD-PACK-INDEX.pdf`` (module docstring)."""
    name = ctx.design.meta.name or "design"
    doc = Pages(A3_LANDSCAPE)
    doc.title(f'"{name.upper()}" HOT AIR BALLOON', "BUILD PACK", _subtitle(ctx))
    doc.kv(key_specs(ctx))
    doc.heading("FEATURES")
    doc.kv(features(ctx), key_width=200.0)
    w = doc.size[0]
    half = (w - 2 * doc.margin) / 2
    doc._need(140)
    top = doc.y
    doc.canvas.text(doc.margin, top, "SHOP LIMITS THIS PACK IS BUILT TO", 10, True, GREEN)
    doc.canvas.text(
        doc.margin + half + 20, top, "PRINTING - read before you print anything", 10, True, RED
    )
    doc.y = top - 18
    y1 = doc.lines(shop_limits(ctx), doc.margin, half - 30)
    y2 = doc.lines(printing_rules(ctx), doc.margin + half + 20, half - 30)
    doc.y = min(y1, y2) - 10
    doc.text_centre(
        doc.y, "index of every file on sheet 2 - step-by-step build order on sheet 3", 9, color=BLUE
    )
    # Sheet 2: the file index.
    doc.new_page()
    doc.title("BUILD PACK - FILE INDEX")
    doc.text_centre(
        doc.y + 6,
        f"1:1 = print actual size on a {inches(ctx.roll_width, 0)} roll - every page carries "
        "calibration lines. REF = reading, any printer. CAD = DXF.",
        9,
        color=MUTED,
    )
    doc.y -= 14
    for group in GROUPS:
        entries = [f for f in ctx.files if f.group == group]
        if not entries:
            continue
        doc._need(40)
        doc.canvas.text(doc.margin, doc.y, group, 10, True)
        doc.y -= 16
        for f in entries:
            doc._need(16)
            doc.canvas.text(doc.margin + 10, doc.y, pdf_text(f.name), 9)
            doc.canvas.text(doc.margin + 560, doc.y, f.tag, 9, True)
            doc.canvas.text(doc.margin + 620, doc.y, pdf_text(f.description)[:95], 9)
            doc.canvas.line(doc.margin, doc.y - 5, w - doc.margin, doc.y - 5, RULE, 0.4)
            doc.y -= 15
        doc.y -= 6
    # Sheet 3: the build order.
    doc.new_page()
    doc.title("BUILD ORDER", "", "follow in sequence - each step names the sheet to work from")
    for k, (step, text) in enumerate(build_order(ctx), start=1):
        lines = _wrap(pdf_text(text), 150)
        doc._need(14 * len(lines) + 10)
        doc.canvas.text(doc.margin, doc.y, f"{k}", 11, True)
        doc.canvas.text(doc.margin + 30, doc.y, pdf_text(step), 10, True)
        for j, line in enumerate(lines):
            doc.canvas.text(doc.margin + 200, doc.y - 13 * j, line, 9)
        doc.y -= 13 * len(lines) + 12
    doc.y -= 10
    doc._need(60)
    doc.text_centre(
        doc.y, "Airworthiness: this pack documents the design and construction only.", 9, bold=True
    )
    doc.y -= 14
    for line in _wrap(
        SAFETY_NOTICE + " Registration, inspection and any airworthiness "
        "approval are the builder's responsibility - involve your national "
        "authority before the first inflation.",
        160,
    ):
        doc.text_centre(doc.y, line, 9)
        doc.y -= 13
    if ctx.provenance is not None:
        p = ctx.provenance
        doc.y -= 6
        doc.text_centre(
            doc.y,
            f"EnvelopeLab {p.app_version} - commit {p.git_commit[:12]} - design "
            f"{p.design_hash[:12]} - exported {p.created}"
            + (f" - {p.project}" if p.project else ""),
            7,
            color=MUTED,
        )
    return doc.save(path)


def spec_rows(ctx: PackContext) -> list[tuple[str, str, str, str]]:
    """Key measurements: (name, metric, English, note)."""
    d, out = ctx.design, ctx.outputs
    g = d.gores
    assert g is not None
    rows: list[tuple[str, str, str, str]] = []
    if out is not None:
        rows += [
            (
                "Total volume",
                f"{out.volume:,.0f} m3",
                f"{out.volume / CUBIC_FOOT:,.0f} cu ft",
                "lofted design surface",
            ),
            ("Envelope height", mm(out.height), ft_in(out.height), "design shape (as cut)"),
            ("Envelope width", mm(out.max_diameter), ft_in(out.max_diameter), "widest section"),
            (
                "Gore length",
                f"{out.meridian_length:.2f} m",
                ft_in(out.meridian_length),
                "mouth to crown, along the load tape",
            ),
        ]
    rows += [
        ("Mouth diameter", mm(g.mouth_diameter), ft_in(g.mouth_diameter), ""),
        (
            "Parachute hole diameter",
            mm(g.parachute_hole_diameter),
            ft_in(g.parachute_hole_diameter),
            f"radius {mm(g.parachute_hole_diameter / 2)}",
        ),
        ("Parachute seal overlap", mm(g.seal_overlap), inches(g.seal_overlap), "radial"),
    ]
    rig = None if out is None else out.rigging
    if rig is not None and rig.parachute is not None:
        pr = rig.parachute
        rows += [
            (
                "Parachute diameter",
                mm(pr.geometry.diameter),
                ft_in(pr.geometry.diameter),
                f"{pr.panel_count} radial panels",
            ),
            ("Shroud lines", mm(pr.shroud.length), ft_in(pr.shroud.length), f"x{pr.shroud.count}"),
            (
                "Centralising lines",
                mm(pr.centralizing.length),
                ft_in(pr.centralizing.length),
                f"x{pr.centralizing.count}",
            ),
        ]
    if rig is not None and rig.red_line is not None:
        rows.append(
            (
                "Red line",
                f"{rig.red_line.line.length:.2f} m",
                ft_in(rig.red_line.line.length),
                "route plus spare",
            )
        )
    if out is not None:
        rows.append(
            (
                "Gross lift",
                f"{out.gross_lift:,.0f} N",
                f"{out.gross_lift / 4.4482216152605:,.0f} lbf",
                "at the operating point",
            )
        )
        margin = out.lift_margin
        rows.append(
            (
                "Lift margin",
                "not estimated" if margin is None else f"{margin:.1f} kg",
                "-" if margin is None else f"{margin / 0.45359237:.0f} lb",
                "NEGATIVE: cannot lift its mass"
                if margin is not None and margin < 0
                else "after envelope, rigging and payload",
            )
        )
    return rows


def configuration(ctx: PackContext) -> list[tuple[str, str]]:
    """The configuration block of the spec summary."""
    d = ctx.design
    rows = _letters(ctx.rows)
    out = [
        ("Gores / panel rows", f"{ctx.gores} x {len(rows)} ({', '.join(rows)})"),
        (
            "Seams",
            "; ".join(
                f"{s.name}: {mm(s.allowance)} allowance, {s.rows_of_stitching} rows"
                for s in d.seam_types
            )
            or "-",
        ),
        (
            "Tapes",
            f"vertical {d.tapes.vertical.tape_class} ({mm(d.tapes.vertical.width)}), "
            f"horizontal {d.tapes.horizontal.tape_class}, rim {d.tapes.rim.tape_class}, "
            f"hole {d.tapes.hole.tape_class}",
        ),
        ("Fabric zones", ", ".join(f"{z}: {f}" for z, f in d.zones.items())),
        ("Cloth width", f"{both(ctx.roll_width)} bolt"),
        ("Cutting table", both(ctx.table_length)),
        ("Panel orientation", "ROW HEIGHT across the bolt, gore width along the roll"),
    ]
    out += features(ctx)
    return out


def write_spec_summary(ctx: PackContext, path: str | Path) -> Path:
    """``<slug>-spec-summary.pdf`` (A4 landscape, metric and English)."""
    name = ctx.design.meta.name or "design"
    doc = Pages(A4_LANDSCAPE)
    doc.margin = 36.0
    doc.y = doc.size[1] - doc.margin
    doc.title(f'"{name.upper()}" - SPECIFICATION SUMMARY', "", _subtitle(ctx))
    rows = spec_rows(ctx)
    fails = {k for k, r in enumerate(rows) if r[3].startswith("NEGATIVE")}
    doc.heading("KEY MEASUREMENTS", x=doc.margin)
    doc.table(["", "METRIC", "ENGLISH", ""], [list(r) for r in rows], [3, 2, 2, 4], fails, 15)
    doc.heading("CONFIGURATION", x=doc.margin)
    doc.table(["", ""], [list(r) for r in configuration(ctx)], [2, 7], row_height=14)
    if ctx.outputs is not None and ctx.outputs.rigging is not None:
        doc.heading("RIGGING FACTORS OF SAFETY", x=doc.margin)
        lines = rigging_lines(ctx.outputs.rigging)
        table = []
        failing = set()
        for k, (element, line, _ring) in enumerate(lines):
            fos = line.safety_factor
            check = "not assessed" if fos is None else ("ok" if line.passes else "FAILS")
            if not line.passes:
                failing.add(k)
            table.append(
                [
                    element,
                    line.name,
                    "-" if fos is None else f"{fos:.2f}",
                    f"{line.required_safety_factor:g}",
                    check,
                    f"{line.strength.value:.0f} N ({line.strength.source})",
                ]
            )
        doc.table(
            ["Element", "Line", "FoS", "Required", "Check", "Strength"],
            table,
            [2, 3, 1, 1, 1.5, 2.5],
            failing,
            13,
            7,
        )
    doc.y -= 4
    assumed = assumed_values(ctx.design, ctx.outputs)
    notes = [SAFETY_NOTICE]
    if assumed:
        notes.append("Values tagged 'assumed': " + "; ".join(assumed) + ".")
    for note in notes:
        for text in _wrap(note, 170):
            doc._need(10)
            doc.canvas.text(doc.margin, doc.y, pdf_text(text), 7, color=MUTED)
            doc.y -= 10
    return doc.save(path)


def build_log_sheets(ctx: PackContext) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """The build-log sheets: (title, subtitle, items of (item, spec / reference))."""
    d = ctx.design
    sheets: list[tuple[str, str, list[tuple[str, str]]]] = []
    items = []
    for s in reversed(ctx.rows):
        dims = s.finished_size
        items.append(
            (
                f"Panel {s.piece.removeprefix('row ')} x{s.cut_count}",
                f"{s.fabric} - finished {dims[0] * 1000:.0f} x {dims[1] * 1000:.0f} mm",
            )
        )
    items.append(("Scale verified", "calibration lines measured, both axes, every sheet"))
    allowance = d.seam_types[0].allowance if d.seam_types else 0.0
    sheets.append(
        (
            "PANEL CUTTING",
            f"{len(ctx.rows)} rows x {ctx.gores} gores - "
            f"{mm(allowance)} allowance - solid=cut dotted=sew - ROW HEIGHT across "
            "the bolt",
            items,
        )
    )
    for p in ctx.primitives:
        gores, rows = shape_rows(p)
        items = [
            (
                f"{c.label} cut",
                f"from {ctx.template_for(c.label) or ctx.shape_pieces(p.primitive.name)}",
            )
            for c in p.pieces
        ]
        items += [
            (
                "Marks transferred",
                f"footprint line and {len(p.marks)} match marks on "
                f"gores {_range(gores)}, rows {_range(rows)}",
            )
        ]
        for h in p.feed_holes:
            items.append(
                (
                    f"Feed hole gore {h.gore} panel {h.row}",
                    f"O{mm(2 * h.radius)} finished, hemmed over the hole tape",
                )
            )
        items += [
            ("Skin sewn", "every skin seam, see the sewing schedule"),
            (
                "Rim sewn to the envelope",
                f"{sum(a.length for a in p.attachment):.2f} m, marks matched",
            ),
        ]
        sheets.append((p.primitive.name.upper(), f"special shape {p.primitive.name}", items))
    if d.turning_vents:
        sheets.append(
            (
                "TURNING VENTS",
                "vent units",
                [(v.name, f"seam {v.seam}") for v in d.turning_vents]
                + [("Vent function checked", "opens and closes on its control line")],
            )
        )
    final = []
    rig = None if ctx.outputs is None else ctx.outputs.rigging
    if rig is not None:
        for element, line, ring in rigging_lines(rig):
            length = f"dia {line.length / math.pi:.3f} m" if ring else f"{line.length:.3f} m"
            fos = line.safety_factor
            check = "" if fos is None else (" - FoS ok" if line.passes else " - FoS FAILS")
            final.append((f"{element}: {line.name} x{line.count}", length + check))
    final += [
        ("Mouth hemmed", f"O{mm(d.gores.mouth_diameter)} over the rim tape" if d.gores else "-"),
        ("Aperture hemmed", f"O{mm(d.gores.parachute_hole_diameter)}" if d.gores else "-"),
        ("Seam pull tests", "sample seams of each type"),
        ("Parachute seating", "seal overlap all round, red line opens it"),
        ("Final inspection", "every sheet of this log complete"),
    ]
    sheets.append(("PARACHUTE / RIGGING / FINAL", "rigging lengths and final checks", final))
    return sheets


def write_build_log(ctx: PackContext, path: str | Path) -> Path:
    """``<slug>-build-log.pdf``: one sign-off sheet per stage."""
    footer = f"{ctx.design.meta.name} - sign every line before proceeding"
    doc = Pages(A3_LANDSCAPE, footer)
    sheets = build_log_sheets(ctx)
    for k, (title, subtitle, items) in enumerate(sheets, start=1):
        if k > 1:
            doc.new_page()
        doc.title(f"BUILD LOG {k}/{len(sheets)} - {title}", "", subtitle)
        doc.table(
            ["Item", "Spec / reference", "Done by", "Date", "Checked"],
            [[a, b, "", "", ""] for a, b in items],
            [3, 5, 1.5, 1, 1],
            row_height=26,
            size=9,
        )
    return doc.save(path)
