"""Picture assembly instructions of a build pack, in the manner of flat-pack furniture.

``<slug>-assembly-envelope.pdf`` and one ``<slug>-assembly-<shape>.pdf`` per special
shape: A3 landscape pages of numbered frames, each a drawing made from the pack's own
pieces with as few words as possible: the parts with their counts, what to mark, what
to sew to what (arrows between the edges), the order, and the finished section.
Every outline is drawn from the cutting sheets (to scale within its frame), so the
pictures always match the patterns.

Envelope: parts; mark the panels that carry shapes or feed holes; build one gore from
its rows (bottom row first); join the gores over the load tapes; mouth and crown; the
parachute; the shapes on the envelope; rigging; inspect.

Each special shape: parts; mark its footprint on the envelope panels; join the skin
pieces side by side; the tip piece; the feed holes; sew the rim to the marked line,
matching the numbered marks; the finished shape.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from envelopelab.export.documents import pdf_text
from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.export.build_pack import Sheet
    from envelopelab.export.shop import PackContext
    from envelopelab.features.primitives import PrimitiveDesign
    from envelopelab.report.pdf import PdfCanvas

PAGE = (1190.55, 841.89)  # A3 landscape, points
COLS, ROWS = 3, 2
MARGIN = 30.0
INK = (0.12, 0.16, 0.2)
GREY = (0.55, 0.58, 0.62)
RED = (0.8, 0.1, 0.1)
BLUE = (0.11, 0.37, 0.71)
FILL = (0.93, 0.95, 0.97)

Rect = tuple[float, float, float, float]  # x, y, width, height (points)
Draw = Callable[["PdfCanvas", Rect], None]
RGB = tuple[float, float, float]


class Frames:
    """Numbered frames, six to an A3 page."""

    def __init__(self, title: str, subtitle: str) -> None:
        from envelopelab.report.pdf import PdfCanvas

        self.canvas = PdfCanvas(PAGE)
        self.title, self.subtitle = pdf_text(title), pdf_text(subtitle)
        self.k = 0
        self._head()

    def _head(self) -> None:
        w, h = PAGE
        self.canvas.text(MARGIN, h - MARGIN, self.title, 18, True, INK)
        self.canvas.text(MARGIN, h - MARGIN - 16, self.subtitle, 9, color=GREY)

    def frame(self, caption: str, draw: Draw) -> None:
        """Add a frame: its number, a drawing and a one-line caption."""
        if self.k and self.k % (COLS * ROWS) == 0:
            self.canvas.new_page()
            self._head()
        slot = self.k % (COLS * ROWS)
        self.k += 1
        w, h = PAGE
        fw = (w - 2 * MARGIN - (COLS - 1) * 12) / COLS
        fh = (h - 2 * MARGIN - 40 - (ROWS - 1) * 12) / ROWS
        x = MARGIN + (slot % COLS) * (fw + 12)
        y = h - MARGIN - 40 - (slot // COLS + 1) * fh - (slot // COLS) * 12
        self.canvas.rect(x, y, fw, fh, stroke=(0.8, 0.82, 0.85))
        # The step number in a circle, as in a furniture manual.
        cx, cy = x + 22, y + fh - 22
        ang = np.linspace(0, 2 * math.pi, 37)
        self.canvas.polygon([(cx + 15 * math.cos(a), cy + 15 * math.sin(a)) for a in ang], fill=INK)
        n = str(self.k)
        self.canvas.text(cx - 4.6 * len(n), cy - 6, n, 17, True, (1, 1, 1))
        for j, line in enumerate(_wrap(pdf_text(caption), int((fw - 60) / 5.2))[:2]):
            self.canvas.text(x + 46, y + fh - 20 - 12 * j, line, 10, j == 0, INK)
        draw(self.canvas, (x + 12, y + 12, fw - 24, fh - 62))

    def save(self, path: Path) -> Path:
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


def _fit(
    shapes: Sequence[FloatArray], box: Rect, pad: float = 8.0
) -> Callable[[FloatArray], list[tuple[float, float]]]:
    """A transform that fits all ``shapes`` (m, 2D) in ``box`` (points), uniformly."""
    pts = np.vstack([np.asarray(s, dtype=np.float64) for s in shapes if len(s)])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    x, y, w, h = box
    k = min((w - 2 * pad) / span[0], (h - 2 * pad) / span[1])
    ox = x + (w - k * span[0]) / 2 - k * lo[0]
    oy = y + (h - k * span[1]) / 2 - k * lo[1]

    def tr(a: FloatArray) -> list[tuple[float, float]]:
        a = np.asarray(a, dtype=np.float64).reshape(-1, 2)
        return [(float(ox + k * u), float(oy + k * v)) for u, v in a]

    return tr


def arrow(c: PdfCanvas, a: tuple[float, float], b: tuple[float, float], colour: RGB = BLUE) -> None:
    """An arrow from ``a`` to ``b`` (points)."""
    c.line(a[0], a[1], b[0], b[1], colour, 1.4)
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    for s in (1, -1):
        c.line(b[0], b[1], b[0] - 8 * ux + s * 4.5 * uy, b[1] - 8 * uy - s * 4.5 * ux, colour, 1.4)


def _label(
    c: PdfCanvas,
    at: tuple[float, float],
    text: str,
    size: float = 9,
    colour: RGB = INK,
    bold: bool = False,
) -> None:
    t = pdf_text(text)
    c.text(at[0] - 0.26 * size * len(t), at[1] - size / 3, t, size, bold, colour)


def _centre(points: list[tuple[float, float]]) -> tuple[float, float]:
    a = np.asarray(points)
    return float(a[:, 0].mean()), float(a[:, 1].mean())


# --------------------------------------------------------------------------------------
# Frames
# --------------------------------------------------------------------------------------


def parts_frame(sheets: Sequence[Sheet], label: Callable[[Sheet], str]) -> Draw:
    """All ``sheets`` laid out in a grid, each with its label and cut count."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        n = len(sheets)
        if not n:
            return
        cols = max(1, math.ceil(math.sqrt(n * box[2] / max(box[3], 1.0))))
        rows = math.ceil(n / cols)
        cw, ch = box[2] / cols, box[3] / rows
        size = max(float(np.ptp(s.finished, axis=0).max()) for s in sheets)
        for k, s in enumerate(sheets):
            x = box[0] + (k % cols) * cw
            y = box[1] + box[3] - (k // cols + 1) * ch
            lo = s.finished.min(axis=0)
            pts = (s.finished - lo) / size  # one scale for every part
            tr = _fit([np.array([[0, 0], [1, 1]]), pts], (x, y + 12, cw, ch - 12), 4)
            c.polygon(tr(pts), fill=FILL, stroke=INK, width=0.6)
            _label(c, (x + cw / 2, y + 6), label(s), 7)

    return draw


def marked_frame(rows: dict[str, Sheet], marks: Sequence[Sheet]) -> Draw:
    """One marked panel with its footprint line, feed hole and match marks (red)."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        if not marks:
            return
        m = marks[0]
        row = rows.get(m.name.rsplit("-", 1)[1])
        outline = row.finished if row is not None else m.finished
        tr = _fit([outline], box)
        c.polygon(tr(outline), fill=FILL, stroke=INK, width=0.7)
        for line in m.lines:
            c.polygon(tr(line), stroke=RED, width=1.4, closed=False, dash=(5, 3))
        ang = np.linspace(0, 2 * math.pi, 49)
        for x, y, r in m.holes:
            c.polygon(
                tr(np.column_stack((x + r * np.cos(ang), y + r * np.sin(ang)))),
                stroke=RED,
                width=1.4,
            )
        for x, y, _t in m.marks[:: max(1, len(m.marks) // 6)]:
            ((px, py),) = tr(np.array([[x, y]]))
            c.line(px - 4, py, px + 4, py, RED, 1.0)
            c.line(px, py - 4, px, py + 4, RED, 1.0)
        _label(c, _centre(tr(outline)), m.piece.upper(), 9, RED, True)
        if len(marks) > 1:
            _label(c, (box[0] + box[2] / 2, box[1] + 4), f"+ {len(marks) - 1} more panels", 8, GREY)

    return draw


def gore_stack_frame(rows: Sequence[Sheet], exploded: bool, count: int) -> Draw:
    """The rows of one gore stacked bottom-up (exploded with arrows, or sewn)."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        gap = 0.12 * max(s.finished_size[1] for s in rows) if exploded else 0.0
        shapes, y = [], 0.0
        for s in rows:
            lo = s.finished.min(axis=0)
            shapes.append(s.finished - [0.0, lo[1] - y])
            y += s.finished_size[1] + gap
        tr = _fit(shapes, (box[0], box[1], box[2] * 0.7, box[3]))
        prev = None
        for s, sh in zip(rows, shapes, strict=True):
            pts = tr(sh)
            c.polygon(pts, fill=FILL, stroke=INK, width=0.6)
            cx, cy = _centre(pts)
            _label(c, (cx, cy), s.piece.removeprefix("row "), 7, GREY)
            if exploded and prev is not None:
                top = max(p[1] for p in prev)
                bottom = min(p[1] for p in pts)
                arrow(c, (cx, bottom - 1), (cx, top + 1))
            prev = pts
        _label(c, (box[0] + box[2] * 0.85, box[1] + box[3] / 2), f"x{count}", 22, INK, True)

    return draw


def join_gores_frame(rows: Sequence[Sheet], gores: int) -> Draw:
    """Two gores side by side, arrows towards the shared seam (over the load tape)."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        shapes, y = [], 0.0
        for s in rows:
            lo = s.finished.min(axis=0)
            shapes.append(s.finished - [0.0, lo[1] - y])
            y += s.finished_size[1]
        width = max(float(np.ptp(s[:, 0])) for s in shapes)
        left = [s - [0.6 * width, 0.0] for s in shapes]
        right = [s + [0.6 * width, 0.0] for s in shapes]
        tr = _fit([*left, *right], (box[0], box[1], box[2], box[3] - 10))
        for sh in left + right:
            c.polygon(tr(sh), fill=FILL, stroke=INK, width=0.5)
        mid = y / 2
        (ax, ay), (bx, by) = tr(
            np.array([[-0.6 * width + 0.2 * width, mid], [0.6 * width - 0.2 * width, mid]])
        )
        arrow(c, (ax - 10, ay), ((ax + bx) / 2 - 3, ay))
        arrow(c, (bx + 10, by), ((ax + bx) / 2 + 3, by))
        (sx, s0), (_, s1) = tr(np.array([[0.0, 0.0], [0.0, y]]))
        c.line(sx, s0, sx, s1, BLUE, 2.0)
        _label(
            c,
            (box[0] + box[2] / 2, box[1] + 2),
            f"1 + 2, 2 + 3, ... {gores} + 1: every seam over a load tape",
            8,
            INK,
        )

    return draw


def profile_frame(r: FloatArray, z: FloatArray, mouth: float, hole: float) -> Draw:
    """The envelope's outline (both sides of the profile) with mouth and crown marked."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        right = np.column_stack((r, z))
        left = np.column_stack((-r, z))[::-1]
        outline = np.vstack((right, left))
        tr = _fit([outline], box, 16)
        c.polygon(tr(outline), fill=FILL, stroke=INK, width=0.9)
        (m0, my), (m1, _) = tr(np.array([[-mouth / 2, z.min()], [mouth / 2, z.min()]]))
        c.line(m0, my, m1, my, RED, 2.5)
        (h0, hy), (h1, _) = tr(np.array([[-hole / 2, z.max()], [hole / 2, z.max()]]))
        c.line(h0, hy, h1, hy, RED, 2.5)
        _label(c, ((m0 + m1) / 2, my - 10), "MOUTH: hem over rim tape", 8, RED, True)
        _label(c, ((h0 + h1) / 2, hy + 10), "CROWN: hem over hole tape", 8, RED, True)

    return draw


def parachute_frame(panel: Sheet, centre: Sheet | None, count: int) -> Draw:
    """The parachute from above: radial panels round the centre panel."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        lo = panel.finished.min(axis=0)
        hi = panel.finished.max(axis=0)
        length = float(hi[1] - lo[1])
        inner = 0.0 if centre is None else float(np.ptp(centre.finished[:, 0])) / 2
        shapes = []
        for k in range(count):
            a = 2 * math.pi * k / count
            p = panel.finished - [0.0, lo[1]]
            # The radial panel's bottom at the rim, its top towards the centre.
            rr = inner + length - p[:, 1]
            q = np.column_stack((p[:, 0], rr))
            rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
            shapes.append(q @ rot.T)
        tr = _fit(shapes, box)
        for sh in shapes:
            c.polygon(tr(sh), fill=FILL, stroke=INK, width=0.4)
        if centre is not None:
            c.polygon(
                tr(centre.finished - centre.finished.mean(axis=0)),
                fill=(1, 1, 1),
                stroke=BLUE,
                width=1.2,
            )
        _label(
            c,
            (box[0] + box[2] / 2, box[1] + 2),
            f"{count} radial panels" + (" + centre panel" if centre is not None else ""),
            8,
        )

    return draw


def wire_frame(
    points: FloatArray,
    triangles: np.ndarray,
    colour: tuple[float, float, float] = GREY,
    overlays: Sequence[tuple[FloatArray, tuple[float, float, float]]] = (),
    view: tuple[int, int] = (0, 2),
) -> Draw:
    """A light wireframe projection (x-z by default) of a surface, with 3D polylines
    (m) drawn over it on the same projection: the finished section, a shape's footprint,
    the rigging."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        cols = list(view)
        p2 = np.asarray(points, dtype=np.float64)[:, cols]
        extra = [np.asarray(line, dtype=np.float64)[:, cols] for line, _c in overlays]
        tr = _fit([p2, *extra], box, 12)
        q = np.asarray(tr(p2))
        tris = np.asarray(triangles)
        step = max(1, len(tris) // 1500)  # keep the drawing light
        for t in tris[::step]:
            a, b, d = q[t[0]], q[t[1]], q[t[2]]
            c.polygon([tuple(a), tuple(b), tuple(d)], stroke=colour, width=0.25)
        for line, (_l, col) in zip(extra, overlays, strict=True):
            if len(line) > 1:
                c.polygon(tr(line), stroke=col, width=1.6, closed=False)

    return draw


def text_frame(lines: Sequence[str]) -> Draw:
    """A frame of a few short lines (a check list)."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        y = box[1] + box[3] - 14
        for line in lines:
            for part in _wrap(pdf_text(line), int(box[2] / 5.0)):
                c.text(box[0] + 6, y, part, 9, color=INK)
                y -= 13
            y -= 4

    return draw


# --------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------


def write_envelope_assembly(ctx: PackContext, path: Path) -> Path:
    """``<slug>-assembly-envelope.pdf`` (module docstring)."""
    from envelopelab.project.gore_design import design_profile, display_surface

    d = ctx.design
    g = d.gores
    assert g is not None
    rows = ctx.rows
    by_letter = {s.piece.removeprefix("row "): s for s in rows}
    marks = [s for s in ctx.sheets if s.kind == "marking"]
    doc = Frames(
        f"{d.meta.name} - BASE ENVELOPE ASSEMBLY",
        f"{ctx.gores} gores x {len(rows)} panels - work from the 1:1 panel sheets "
        f"{ctx.file('panel-*.pdf')}",
    )
    doc.frame(
        f"Parts: cut {rows[0].cut_count if rows else 0} of each panel",
        parts_frame(rows, lambda s: f"{s.piece.removeprefix('row ')} x{s.cut_count}"),
    )
    if marks:
        panels = sorted({(m.name.rsplit("-", 1)[1], int(m.piece.split()[1])) for m in marks})
        doc.frame(
            f"Mark {len(panels)} panels for the special shapes (red lines) before sewing",
            marked_frame(by_letter, marks),
        )
    doc.frame(
        f"Build one gore: sew the rows bottom-up, row {rows[0].piece.removeprefix('row ')} first",
        gore_stack_frame(rows, True, ctx.gores),
    )
    doc.frame(
        f"Join the {ctx.gores} gores over the vertical load tapes; close the ring",
        join_gores_frame(rows, ctx.gores),
    )
    profile = design_profile(d)
    s = np.linspace(0.0, profile.meridian_length, 80)
    r = np.array([float(profile.radius_at(v)) for v in s])
    z = np.array([float(profile.height_at(v)) for v in s])
    doc.frame(
        "Hem the mouth and the crown opening",
        profile_frame(r, z, g.mouth_diameter, g.parachute_hole_diameter),
    )
    chute = [s for s in ctx.sheets if s.kind == "parachute panel"]
    if chute:
        centre = next((s for s in chute if s.name == "parachute-centre"), None)
        radial = next(s for s in chute if s.name == "parachute-panel")
        doc.frame(
            "Sew the parachute; set it in the crown with the seal overlap",
            parachute_frame(radial, centre, radial.cut_count),
        )
    surface = display_surface(d)
    for p in ctx.primitives:
        ring = np.asarray(p.footprint_points, dtype=np.float64)
        sheet = ctx.file("assembly-" + _stem(p.primitive.name) + ".pdf")
        doc.frame(
            f"Sew on {p.primitive.name} where marked (see {sheet})",
            wire_frame(
                surface.points, surface.faces, overlays=[(np.vstack((ring, ring[:1])), RED)]
            ),
        )
    rig = None if ctx.outputs is None else ctx.outputs.rigging
    if rig is not None:
        from envelopelab.rigging import rigging_polylines

        lines = [(q, BLUE) for kind in rigging_polylines(d, rig).values() for q in kind]
        doc.frame(
            "Rigging: parachute lines, red line, flying wires (parachute and scoop sheets)",
            wire_frame(surface.points, surface.faces, overlays=lines),
        )
    doc.frame(
        "Inspect and sign off",
        text_frame(
            [
                "Every seam sewn and tape caught in",
                "Mouth and crown hems",
                "Parachute seats on its seal overlap",
                f"Complete {ctx.file('build-log.pdf')}",
            ]
        ),
    )
    return doc.save(path)


def _stem(name: str) -> str:
    from envelopelab.export.templates import piece_name

    return piece_name(name)


def write_shape_assembly(ctx: PackContext, p: PrimitiveDesign, path: Path) -> Path:
    """``<slug>-assembly-<shape>.pdf`` (module docstring)."""
    from envelopelab.features.scene import designed_display

    name = p.primitive.name
    pieces = [s for s in ctx.sheets if s.kind == "skin piece" and s.name.rsplit("-", 1)[0] == name]
    side = [s for s in pieces if "left" in s.edges]
    tips = [s for s in pieces if s not in side]
    marks = [s for s in ctx.sheets if s.kind == "marking" and s.name.split("-mark-")[0] == name]
    rows = {s.piece.removeprefix("row "): s for s in ctx.rows}
    doc = Frames(
        f"{ctx.design.meta.name} - {name.upper()} ASSEMBLY",
        f"{len(pieces)} skin pieces - {len(marks)} envelope panels marked - work from "
        f"{ctx.shape_pieces(name)}",
    )
    doc.frame(f"Parts: {len(pieces)} skin pieces", parts_frame(pieces, lambda s: s.piece))
    if marks:
        doc.frame(
            f"Mark the footprint, ticks and {len(p.marks)} numbered marks on {len(marks)} "
            "envelope panels",
            marked_frame(rows, marks),
        )
    if side:
        doc.frame("Sew the skin pieces side by side, in order, into a ring", _join_pieces(side))
    if tips:
        doc.frame(
            f"Sew every piece's top to the tip piece {tips[0].piece}",
            parts_frame(tips, lambda s: s.piece),
        )
    for h in p.feed_holes:
        doc.frame(
            f"Cut and hem the feed hole in envelope panel {h.row}, gore {h.gore}",
            marked_frame(rows, [m for m in marks if m.holes] or marks),
        )
        break
    doc.frame(
        f"Sew the rim onto the marked line, matching marks 1-{len(p.marks)}", _rim_frame(p, marks)
    )
    shown = designed_display(p)
    doc.frame("Finished", wire_frame(shown.points, shown.triangles, GREY))
    return doc.save(path)


def _join_pieces(pieces: Sequence[Sheet]) -> Draw:
    """The skin pieces in a row with arrows joining each to the next."""

    def draw(c: PdfCanvas, box: Rect) -> None:
        shown = pieces[:6]
        size = max(float(np.ptp(s.finished, axis=0).max()) for s in shown)
        shapes, x = [], 0.0
        for s in shown:
            lo = s.finished.min(axis=0)
            sh = (s.finished - lo) / size
            shapes.append(sh + [x, 0.0])
            x += float(np.ptp(sh[:, 0])) + 0.25
        tr = _fit(shapes, (box[0], box[1] + 14, box[2], box[3] - 14))
        prev = None
        for s, sh in zip(shown, shapes, strict=True):
            pts = tr(sh)
            c.polygon(pts, fill=FILL, stroke=INK, width=0.6)
            _label(c, _centre(pts), s.piece, 7, GREY)
            if prev is not None:
                y = _centre(pts)[1]
                arrow(c, (max(q[0] for q in prev) + 2, y), (min(q[0] for q in pts) - 2, y))
            prev = pts
        more = (
            f"... {pieces[-1].piece}, then {pieces[-1].piece} + {pieces[0].piece}"
            if len(pieces) > 6
            else f"then {pieces[-1].piece} + {pieces[0].piece}"
        )
        _label(c, (box[0] + box[2] / 2, box[1] + 4), more, 8)

    return draw


def _rim_frame(p: PrimitiveDesign, marks: Sequence[Sheet]) -> Draw:
    """The shape's footprint on the envelope (red, seen from outside along the base
    normal) with numbered marks, the skin's rim coming down onto it (arrows)."""
    del marks

    def draw(c: PdfCanvas, box: Rect) -> None:
        ring = np.asarray(p.footprint_points, dtype=np.float64)
        if len(ring) < 3:
            return
        # Seen along the shape's axis: two directions perpendicular to it.
        axis = np.asarray(p.axis, dtype=np.float64)
        axis = axis / (np.linalg.norm(axis) or 1.0)
        up = np.array([0.0, 0.0, 1.0]) - axis * axis[2]
        if np.linalg.norm(up) < 1e-6:
            up = np.array([1.0, 0.0, 0.0]) - axis * axis[0]
        up /= np.linalg.norm(up)
        side = np.cross(axis, up)
        flat = np.column_stack(((ring - ring.mean(axis=0)) @ side, (ring - ring.mean(axis=0)) @ up))
        flat = np.vstack((flat, flat[:1]))
        tr = _fit([flat], (box[0], box[1] + 12, box[2], box[3] * 0.72), 14)
        c.polygon(tr(flat), stroke=RED, width=1.8, closed=False)
        n = len(p.marks)
        for m in p.marks[:: max(1, n // 8)]:
            a = math.radians(m.phi_deg)
            k = int(round(a / (2 * math.pi) * (len(flat) - 1))) % (len(flat) - 1)
            ((px, py),) = tr(flat[k : k + 1])
            c.line(px - 4, py, px + 4, py, RED, 1.0)
            c.line(px, py - 4, px, py + 4, RED, 1.0)
            _label(c, (px, py + 9), str(m.number), 7, RED, True)
        top = box[1] + box[3]
        for frac in (0.25, 0.5, 0.75):
            x = box[0] + frac * box[2]
            arrow(c, (x, top - 4), (x, box[1] + box[3] * 0.78))
        _label(c, (box[0] + box[2] / 2, top - 10), "skin rim", 9, BLUE, True)
        _label(
            c,
            (box[0] + box[2] / 2, box[1] + 4),
            f"{n} numbered marks: mark 1 to mark 1, 2 to 2, ...",
            8,
            RED,
        )

    return draw
