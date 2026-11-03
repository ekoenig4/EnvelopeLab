"""Layout and planning documents of a build pack.

Generated from the cutting sheets, the placed special shapes and the design, in the
layout of a builder's pack (ADR-0037):

* ``<slug>-layout-diagram.html``: the gore x row grid of the envelope (face = gore 1),
  every cell in its fabric zone's colour, with every feature located (special shapes,
  their feed holes, turning vents, scoop);
* ``<slug>-panel-map.html`` / ``.csv``: the same grid as a table: which panel of which
  gore carries which feature (else its fabric zone);
* ``<slug>-gore-layout.pdf``: every gore developed (its rows stacked as cut, finished
  outlines) side by side with the features in red and the vents in orange, then one
  page per gore with its row widths;
* ``<slug>-panel-dimensions.html`` / ``.csv``: finished and cut sizes of every panel,
  how it lies on the bolt (across) and the table (along), and the spare on each;
* ``<slug>-panel-loft.html`` / ``.csv``: the finished width of every panel at 0, 25,
  50, 75 and 100 % of its height;
* ``<slug>-sewing-schedule.html``: seam specifications, the tape schedule and the
  assembly sequence with every seam to sew.

Lengths are SI internally and printed in mm (and m for long tapes).
"""

from __future__ import annotations

import csv
import html
import io
import math
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from envelopelab.export.documents import pdf_text, sewing_schedule
from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.export.build_pack import Sheet
    from envelopelab.export.shop import PackContext

LOFT_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)
#: Zone colours of the layout diagram, by order of first use (hex; display only).
ZONE_COLORS = ("#2f5f1a", "#1f4e79", "#7a4b12", "#5b2a6e", "#245e5e", "#6b6b6b")
FEATURE_COLOR = "#2b2b2b"
VENT_COLOR = "#c8640f"
SCOOP_COLOR = "#3a3a3a"

_PAGE_CSS = """
body { font: 14px/1.45 "Segoe UI", "Noto Sans", Inter, system-ui, sans-serif; color: #1f2933;
  margin: 24px; max-width: 1200px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 28px 0 8px;
  border-bottom: 2px solid #2f5f1a; padding-bottom: 4px; }
p.sub { color: #4b5563; margin: 4px 0 16px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #b8c0c8; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: #eef3ea; } td.num { text-align: right; font-variant-numeric: tabular-nums; }
.fail { color: #7c2d12; font-weight: 600; }
"""


def _page(title: str, subtitle: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_PAGE_CSS}</style></head><body>"
        f"<h1>{html.escape(title)}</h1><p class='sub'>{html.escape(subtitle)}</p>{body}"
        "</body></html>\n"
    )


def _table(columns: Sequence[str], rows: Sequence[Sequence[object]], numeric: set[int]) -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body = []
    for r in rows:
        cells = "".join(
            f"<td class='num'>{html.escape(str(v))}</td>"
            if k in numeric
            else f"<td>{html.escape(str(v))}</td>"
            for k, v in enumerate(r)
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _csv(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    w.writerows(rows)
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# Panel geometry (from the finished outlines)
# --------------------------------------------------------------------------------------


def width_at(outline: FloatArray, y: float) -> float:
    """Width of a closed outline (m) on the horizontal line at height ``y`` (m): the
    span between its outermost crossings."""
    p = np.asarray(outline, dtype=np.float64)
    q = np.roll(p, -1, axis=0)
    xs = []
    for (x0, y0), (x1, y1) in zip(p, q, strict=True):
        if (y0 - y) * (y1 - y) <= 0.0 and y0 != y1:
            t = (y - y0) / (y1 - y0)
            xs.append(x0 + t * (x1 - x0))
        elif y0 == y1 == y:
            xs += [x0, x1]
    return float(max(xs) - min(xs)) if len(xs) >= 2 else 0.0


def loft(sheet: Sheet, fractions: Sequence[float] = LOFT_FRACTIONS) -> list[float]:
    """Finished widths (m) of a panel at fractions of its finished height."""
    lo, hi = sheet.finished.min(axis=0), sheet.finished.max(axis=0)
    eps = 1e-9 * max(float(hi[1] - lo[1]), 1.0)
    out = []
    for f in fractions:
        y = float(lo[1] + f * (hi[1] - lo[1]))
        y = min(max(y, float(lo[1]) + eps), float(hi[1]) - eps)
        out.append(width_at(sheet.finished, y))
    return out


def dimension_rows(ctx: PackContext) -> list[list[object]]:
    """Panel dimensions (mm), top row first: finished and cut widths and heights, how
    the cut piece lies on the bolt (across) and the table (along), the spares, and the
    cut count and fabric."""
    rows: list[list[object]] = []
    roll, table = ctx.roll_width, ctx.table_length
    for s in reversed(ctx.rows):
        fin = loft(s, (0.0, 1.0))
        lo, hi = s.cut.min(axis=0), s.cut.max(axis=0)
        cut_h = float(hi[1] - lo[1])
        cut_b = width_at(s.cut, float(lo[1]) + 1e-6)
        cut_t = width_at(s.cut, float(hi[1]) - 1e-6)
        cut_w = float(hi[0] - lo[0])
        across, along = sorted((cut_w, cut_h))
        rows.append(
            [
                s.piece.removeprefix("row "),
                round(fin[0] * 1000),
                round(fin[1] * 1000),
                round(s.finished_size[1] * 1000),
                round(cut_b * 1000),
                round(cut_t * 1000),
                round(cut_h * 1000),
                round(across * 1000),
                round(along * 1000),
                round((roll - across) * 1000),
                round((table - along) * 1000),
                s.cut_count,
                s.fabric,
            ]
        )
    return rows


DIMENSION_COLUMNS = (
    "panel",
    "width_bottom_mm",
    "width_top_mm",
    "height_mm",
    "cut_width_bottom_mm",
    "cut_width_top_mm",
    "cut_height_mm",
    "across_bolt_mm",
    "along_table_mm",
    "bolt_spare_mm",
    "table_spare_mm",
    "cut",
    "fabric",
)


def loft_rows(ctx: PackContext) -> list[list[object]]:
    """Panel widths (mm) at 0/25/50/75/100 % of the height, top row first."""
    return [
        [s.piece.removeprefix("row "), *(round(w * 1000) for w in loft(s))]
        for s in reversed(ctx.rows)
    ]


LOFT_COLUMNS = ("panel", *(f"width@{int(f * 100)}%_mm" for f in LOFT_FRACTIONS))


# --------------------------------------------------------------------------------------
# The panel map
# --------------------------------------------------------------------------------------


def panel_map(ctx: PackContext) -> dict[tuple[str, int], str]:
    """(row letter, gore) to what that panel carries: a feature tag, else its zone."""
    d = ctx.design
    zone_of = (
        {r.letter: (r.zone or next(iter(d.zones), "body")) for r in d.gores.panel_rows}
        if d.gores
        else {}
    )
    cells: dict[tuple[str, int], str] = {}
    letters = [s.piece.removeprefix("row ") for s in ctx.rows]
    for letter in letters:
        for g in range(1, ctx.gores + 1):
            cells[(letter, g)] = zone_of.get(letter, "body").upper()
    if d.scoop is not None and letters:
        for k in range(d.scoop.gore_count):
            g = (d.scoop.first_gore - 1 + k) % ctx.gores + 1
            cells[(letters[0], g)] = "SCOOP"
    for v in d.turning_vents:
        for g in (v.seam, v.seam % ctx.gores + 1):
            for row in v.rows:
                if (row, g) in cells:
                    cells[(row, g)] = "VENT"
    for p in ctx.primitives:
        tag = p.primitive.name.upper()
        for a in p.attachment:
            cells[(a.row, a.gore)] = tag
        for h in p.feed_holes:
            cells[(h.row, h.gore)] = f"{tag} HOLE"
    return cells


def _features_text(ctx: PackContext) -> str:
    from envelopelab.export.shop import features

    return " ".join(f"{name}: {text}." for name, text in features(ctx))


def write_panel_map(ctx: PackContext, out: Path) -> list[Path]:
    """``<slug>-panel-map.html`` and ``.csv``."""
    cells = panel_map(ctx)
    letters = [s.piece.removeprefix("row ") for s in reversed(ctx.rows)]
    columns = ["row\\gore", *(str(g) for g in range(1, ctx.gores + 1))]
    rows = [[r, *(cells[(r, g)] for g in range(1, ctx.gores + 1))] for r in letters]
    page = _page(
        f"Panel map - {ctx.design.meta.name}",
        "which panel carries which feature (else its fabric zone); face = gore 1",
        _table(columns, rows, set()) + f"<p>{html.escape(_features_text(ctx))}</p>",
    )
    h = out / ctx.file("panel-map.html")
    h.write_text(page, encoding="utf-8")
    c = out / ctx.file("panel-map.csv")
    c.write_text(_csv(columns, rows), encoding="utf-8")
    return [h, c]


def write_layout_diagram(ctx: PackContext, out: Path) -> Path:
    """``<slug>-layout-diagram.html``: the gore x row grid as an inline SVG."""
    cells = panel_map(ctx)
    letters = [s.piece.removeprefix("row ") for s in reversed(ctx.rows)]
    zones = list(dict.fromkeys(v for v in cells.values()))
    colour: dict[str, str] = {}
    k = 0
    for z in zones:
        if z == "VENT":
            colour[z] = VENT_COLOR
        elif z == "SCOOP":
            colour[z] = SCOOP_COLOR
        elif any(z.startswith(p.primitive.name.upper()) for p in ctx.primitives):
            colour[z] = FEATURE_COLOR
        else:
            colour[z] = ZONE_COLORS[k % len(ZONE_COLORS)]
            k += 1
    cw, ch, left, top = 56, 34, 60, 20
    width = left + cw * ctx.gores + 20
    height = top + ch * len(letters) + 40
    parts = [
        f"<svg viewBox='0 0 {width} {height}' width='100%' role='img' "
        f"aria-label='gore by row layout'>"
    ]
    for i, letter in enumerate(letters):
        y = top + i * ch
        parts.append(
            f"<text x='{left - 10}' y='{y + ch / 2 + 4}' text-anchor='end' "
            f"font-size='12'>{html.escape(letter)}</text>"
        )
        for g in range(1, ctx.gores + 1):
            x = left + (g - 1) * cw
            tag = cells[(letter, g)]
            parts.append(
                f"<rect x='{x}' y='{y}' width='{cw}' height='{ch}' "
                f"fill='{colour[tag]}' stroke='#9aa3ad'/>"
            )
            if colour[tag] != ZONE_COLORS[0] or tag in ("VENT", "SCOOP"):
                parts.append(
                    f"<text x='{x + cw / 2}' y='{y + ch / 2 + 4}' font-size='9' "
                    f"text-anchor='middle' fill='#fff'>{html.escape(tag[:10])}</text>"
                )
    for g in range(1, ctx.gores + 1):
        parts.append(
            f"<text x='{left + (g - 0.5) * cw}' y='{top + ch * len(letters) + 18}' "
            f"text-anchor='middle' font-size='12'>{g}</text>"
        )
    parts.append("</svg>")
    key = "".join(
        f"<span style='display:inline-block;margin-right:14px'><span style='display:inline-"
        f"block;width:14px;height:12px;background:{c};margin-right:4px'></span>"
        f"{html.escape(z)}</span>"
        for z, c in colour.items()
    )
    sub = f"{ctx.gores} gores x {len(letters)} rows - face = gore 1"
    if ctx.outputs is not None:
        from envelopelab.export.shop import volume_both

        sub = f"envelope {volume_both(ctx.outputs.volume)} - " + sub
    page = _page(
        "Envelope layout diagram",
        sub,
        "".join(parts) + f"<p>{key}</p><p>{html.escape(_features_text(ctx))}</p>",
    )
    path = out / ctx.file("layout-diagram.html")
    path.write_text(page, encoding="utf-8")
    return path


def write_dimensions(ctx: PackContext, out: Path) -> list[Path]:
    """``<slug>-panel-dimensions.html`` / ``.csv`` and ``<slug>-panel-loft.html`` /
    ``.csv``."""
    from envelopelab.export.shop import mm

    dims = dimension_rows(ctx)
    lofts = loft_rows(ctx)
    paths = []
    sub = (
        f"finished and cut sizes of every panel (mm); bolt {mm(ctx.roll_width)}, table "
        f"{mm(ctx.table_length)}; a negative spare means the piece does not fit"
    )
    from envelopelab.export.documents import fabric_totals

    totals = fabric_totals(ctx.sheets)
    body = _table(DIMENSION_COLUMNS, dims, set(range(1, 12)))
    body += f"<h2>{html.escape(totals.title)} (every piece cut)</h2>"
    body += _table(totals.columns, totals.rows, {1, 2, 3})
    h = out / ctx.file("panel-dimensions.html")
    h.write_text(_page(f"Panel dimensions - {ctx.design.meta.name}", sub, body), encoding="utf-8")
    c = out / ctx.file("panel-dimensions.csv")
    c.write_text(_csv(DIMENSION_COLUMNS, dims), encoding="utf-8")
    paths += [h, c]
    h = out / ctx.file("panel-loft.html")
    h.write_text(
        _page(
            f"Panel loft - {ctx.design.meta.name}",
            "finished panel width (mm) at 0/25/50/75/100 % of its height",
            _table(LOFT_COLUMNS, lofts, set(range(1, 6))),
        ),
        encoding="utf-8",
    )
    c = out / ctx.file("panel-loft.csv")
    c.write_text(_csv(LOFT_COLUMNS, lofts), encoding="utf-8")
    return [*paths, h, c]


# --------------------------------------------------------------------------------------
# The gore layout
# --------------------------------------------------------------------------------------


def gore_outline(ctx: PackContext) -> list[tuple[str, FloatArray, float]]:
    """Each row's finished outline stacked as in one gore: (letter, outline m, y offset m),
    mouth first."""
    out = []
    y = 0.0
    for s in ctx.rows:
        lo = s.finished.min(axis=0)
        out.append((s.piece.removeprefix("row "), s.finished - np.array([0.0, lo[1]]), y))
        y += s.finished_size[1]
    return out


def write_gore_layout(ctx: PackContext, path: Path) -> Path:
    """``<slug>-gore-layout.pdf``: all gores, then one page per gore."""
    from envelopelab.export.shop import A3_LANDSCAPE, RED
    from envelopelab.report.pdf import PdfCanvas

    stack = gore_outline(ctx)
    if not stack:
        raise ValueError("no envelope rows")
    height = stack[-1][2] + float(np.ptp(stack[-1][1][:, 1]))
    widest = max(float(np.ptp(o[:, 0])) for _l, o, _y in stack)
    marks: dict[tuple[int, str], list[FloatArray]] = {}
    holes: dict[tuple[int, str], list[tuple[float, float, float]]] = {}
    for s in ctx.sheets:
        if s.kind != "marking":
            continue
        gore = int(s.piece.split()[1])
        row = s.piece.split()[-1]
        marks.setdefault((gore, row), []).extend(s.lines)
        holes.setdefault((gore, row), []).extend(s.holes)
    vents = {
        (g, r)
        for v in ctx.design.turning_vents
        for g in (v.seam, v.seam % ctx.gores + 1)
        for r in v.rows
    }
    offsets = {letter: (y, float(o[:, 1].min())) for letter, o, y in stack}
    row_lo = {s.piece.removeprefix("row "): float(s.finished.min(axis=0)[1]) for s in ctx.rows}
    page_w, page_h = A3_LANDSCAPE
    canvas = PdfCanvas(A3_LANDSCAPE)
    margin, label = 40.0, 28.0
    n = ctx.gores
    scale = min(
        (page_w - 2 * margin - label) / (n * widest * 1.15), (page_h - 2 * margin - 60) / height
    )

    def draw_gore(ox: float, oy: float, k: int, sc: float, letters: bool) -> None:
        for letter, outline, y in stack:
            pts = [(ox + x * sc, oy + (y + yy) * sc) for x, yy in outline]
            canvas.polygon(pts, stroke=(0.2, 0.2, 0.2), width=0.5)
            if (k, letter) in vents:
                lo, hi = outline.min(axis=0), outline.max(axis=0)
                w = 0.25 * float(hi[0] - lo[0])
                canvas.polygon(
                    [
                        (ox - w * sc, oy + (y + 0.1 * float(hi[1])) * sc),
                        (ox + w * sc, oy + (y + 0.1 * float(hi[1])) * sc),
                        (ox + w * sc, oy + (y + 0.9 * float(hi[1])) * sc),
                        (ox - w * sc, oy + (y + 0.9 * float(hi[1])) * sc),
                    ],
                    stroke=(0.78, 0.39, 0.06),
                    width=0.8,
                    dash=(3.0, 2.0),
                )
            for line in marks.get((k, letter), []):
                q = [(ox + x * sc, oy + (y + yy - row_lo[letter]) * sc) for x, yy in line]
                canvas.polygon(q, stroke=RED, width=0.6, dash=(3.0, 2.0), closed=False)
            for x, yy, r in holes.get((k, letter), []):
                t = np.linspace(0, 2 * math.pi, 37)
                canvas.polygon(
                    [
                        (
                            ox + (x + r * math.cos(a)) * sc,
                            oy + (y + yy - row_lo[letter] + r * math.sin(a)) * sc,
                        )
                        for a in t
                    ],
                    stroke=RED,
                    width=0.6,
                )
            if letters:
                canvas.text(
                    margin,
                    oy + (y + 0.4 * float(np.ptp(outline[:, 1]))) * sc,
                    letter,
                    7,
                    color=(0.4, 0.4, 0.4),
                )
        canvas.text(ox - 4, oy - 14, str(k), 9, bold=True)

    del offsets
    name = ctx.design.meta.name
    canvas.text(
        margin,
        page_h - margin,
        pdf_text(f"GORE LAYOUT - ALL {n} GORES (developed) - {name}"),
        16,
        True,
    )
    canvas.text(
        margin,
        page_h - margin - 16,
        pdf_text(
            f"finished outlines, rows stacked as sewn - face = gore 1 - drawing scale "
            f"1:{1 / (scale / 2834.645669):.0f}"
        ),
        9,
        color=(0.33, 0.36, 0.4),
    )
    base = margin + 24 + max((page_h - 2 * margin - 84 - height * scale) / 2, 0.0)
    for k in range(1, n + 1):
        ox = margin + label + (k - 0.5) * widest * 1.15 * scale
        draw_gore(ox, base, k, scale, k == 1)
    canvas.text(
        margin,
        margin / 2,
        "red = special-shape footprint lines and feed holes - "
        "orange = turning-vent units - scale drawing only: cut from the 1:1 templates",
        8,
        color=RED,
    )
    for k in range(1, n + 1):
        canvas.new_page()
        sc = (page_h - 2 * margin - 60) / height
        canvas.text(margin, page_h - margin, pdf_text(f"GORE {k} of {n} - {name}"), 16, True)
        canvas.text(
            margin,
            page_h - margin - 16,
            pdf_text(
                f"drawing scale 1:{1 / (sc / 2834.645669):.0f} - finished widths at each "
                "row seam (mm)"
            ),
            9,
            color=(0.33, 0.36, 0.4),
        )
        ox = page_w / 2
        draw_gore(ox, margin + 24, k, sc, True)
        for letter, outline, y in stack:
            w = width_at(outline, 1e-6)
            canvas.text(
                ox + 0.6 * widest * sc + 10,
                margin + 24 + y * sc,
                f"{letter} bottom {w * 1000:.0f}",
                8,
            )
    canvas.save(path)
    return path


# --------------------------------------------------------------------------------------
# The sewing schedule
# --------------------------------------------------------------------------------------


def seam_specs(ctx: PackContext) -> list[list[str]]:
    """Seam specifications: (seam, type, allowance, stitch)."""
    d = ctx.design
    st = d.seam_types[0] if d.seam_types else None
    name = st.name if st else "-"
    allow = f"{st.allowance * 1000:.0f} mm" if st else "-"
    stitch = f"{st.rows_of_stitching} rows" if st else "-"
    rows = [
        ["Horizontal panel joins (rows)", name, allow, stitch],
        [
            f"Vertical gore joins (seams 1-{ctx.gores})",
            f"{name} over {d.tapes.vertical.tape_class}",
            allow,
            stitch,
        ],
        ["Mouth hem", f"turn-back over {d.tapes.rim.tape_class}", allow, stitch],
        ["Aperture hem", f"turn-back over {d.tapes.hole.tape_class}", allow, stitch],
    ]
    for p in ctx.primitives:
        rows.append(
            [
                f"{p.primitive.name} rim (skin to ENVELOPE)",
                "lapped over the marked footprint line",
                allow,
                f"{len(p.marks)} match marks",
            ]
        )
        rows.append([f"{p.primitive.name} skin seams", name, allow, stitch])
    if d.parachute is not None:
        rows.append(["Parachute panel joins", name, allow, stitch])
    for extra in d.seam_types[1:]:
        rows.append(
            [
                f"(seam type) {extra.name}",
                extra.name,
                f"{extra.allowance * 1000:.0f} mm",
                f"{extra.rows_of_stitching} rows",
            ]
        )
    return rows


def tape_schedule(ctx: PackContext) -> list[list[str]]:
    """Tape schedule: (location, material, length, notes)."""
    d = ctx.design
    out = ctx.outputs
    rows: list[list[str]] = []
    mass = None if out is None else out.mass
    names = {
        "vertical": ("All vertical gore seams", d.tapes.vertical),
        "horizontal": ("Horizontal tapes (row seams)", d.tapes.horizontal),
        "rim": ("Mouth rim", d.tapes.rim),
        "hole": ("Aperture (parachute hole)", d.tapes.hole),
    }
    for key, (where, tape) in names.items():
        length = None if mass is None else mass.tape_lengths.get(key)
        text = (
            "not estimated" if length is None else f"{length:.1f} m (+10 % = {length * 1.1:.1f} m)"
        )
        note = f"{length / ctx.gores:.2f} m per gore" if key == "vertical" and length else ""
        rows.append([where, f"{tape.tape_class}, {tape.width * 1000:.0f} mm", text, note])
    for p in ctx.primitives:
        rim = sum(a.length for a in p.attachment)
        rows.append(
            [
                f"{p.primitive.name} rim",
                d.tapes.hole.tape_class,
                f"{rim:.2f} m",
                "footprint line on the envelope",
            ]
        )
        for h in p.feed_holes:
            rows.append(
                [
                    f"{p.primitive.name} feed hole gore {h.gore} panel {h.row}",
                    d.tapes.hole.tape_class,
                    f"{2 * math.pi * h.radius:.2f} m",
                    f"O{2 * h.radius * 1000:.0f} mm finished",
                ]
            )
    return rows


def write_sewing_schedule(ctx: PackContext, path: Path) -> Path:
    """``<slug>-sewing-schedule.html``."""
    from envelopelab.export.shop import build_order

    specs = seam_specs(ctx)
    tapes = tape_schedule(ctx)
    order = [[str(k), step, text] for k, (step, text) in enumerate(build_order(ctx), start=1)]
    seams = sewing_schedule(ctx.sheets, ctx.pairs, ctx.gores)
    g = ctx.design.gores
    sub = f"{ctx.gores} gores x {len(ctx.rows)} rows" + (
        f" - mouth O{g.mouth_diameter:.3f} m, parachute hole O{g.parachute_hole_diameter:.3f} m, "
        f"seal overlap {g.seal_overlap * 1000:.0f} mm"
        if g
        else ""
    )
    body = (
        "<h2>Seam specifications</h2>"
        + _table(["Seam", "Type", "Allowance", "Stitch"], specs, set())
        + "<h2>Webbing / tape schedule</h2>"
        + _table(["Location", "Material", "Length", "Notes"], tapes, set())
        + "<h2>Assembly sequence</h2>"
        + _table(["Step", "Stage", "Work"], order, {0})
        + f"<h2>{html.escape(seams.title)}</h2>"
        + _table(seams.columns, seams.rows, {0, 4, 5, 6})
    )
    path.write_text(_page(f"Sewing schedule - {ctx.design.meta.name}", sub, body), encoding="utf-8")
    return path
