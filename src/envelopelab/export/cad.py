"""Combined CAD files of a build pack and their PNG previews (ADR-0037).

Besides one DXF per sheet in ``cad/`` (:func:`envelopelab.export.build_pack.write_dxf`),
a pack has three combined drawings at the top level, in millimetres
(``$INSUNITS`` = 4), as in a builder's pack:

* ``<slug>-panels.dxf``: the full 2D development of the envelope: every gore, its rows
  stacked as sewn (layers ``CUT`` and ``SEW``), the special shapes' footprint lines and
  feed holes on the gores that carry them (``FEATURE``), gore numbers and row letters
  (``LABEL``);
* ``<slug>-panel-templates.dxf``: one of each envelope panel on a grid, cut and sewn
  outlines, labelled with its letter and cut count;
* ``<slug>-appendage-patterns.dxf``: every special-shape skin piece and the parachute
  panels on a grid, with their match marks (``MARKS``).

Each has a PNG preview (``<slug>-panels-dxf-preview.png``,
``<slug>-panel-templates-preview.png``, ``<slug>-appendage-patterns-preview.png``) drawn
by a small rasteriser here (lines only, written as PNG with :mod:`zlib`), so no imaging
library is needed. The previews are for looking only; the DXFs are the geometry.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.export.build_pack import Sheet
    from envelopelab.export.shop import PackContext

MM = 1000.0
PREVIEW_WIDTH = 1600  # px
#: Line colours of the previews by layer (RGB).
COLOURS = {
    "CUT": (0, 0, 0),
    "SEW": (120, 120, 120),
    "FEATURE": (200, 30, 30),
    "MARKS": (200, 30, 30),
    "LABEL": (30, 90, 180),
}


class Drawing:
    """Polylines and texts by layer (mm), written as DXF and drawn as PNG."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, FloatArray, bool]] = []
        self.texts: list[tuple[str, float, float, float, str]] = []

    def polyline(self, layer: str, points: FloatArray, closed: bool = False) -> None:
        self.lines.append((layer, np.asarray(points, dtype=np.float64), closed))

    def text(self, layer: str, x: float, y: float, height: float, text: str) -> None:
        self.texts.append((layer, x, y, height, text))

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        pts = np.vstack([p for _l, p, _c in self.lines]) if self.lines else np.zeros((1, 2))
        return pts.min(axis=0), pts.max(axis=0)

    def write_dxf(self, path: Path) -> Path:
        from ezdxf.filemanagement import new as new_dxf

        doc = new_dxf("R2010", setup=False)
        doc.header["$INSUNITS"] = 4  # millimetres
        doc.header["$MEASUREMENT"] = 1
        for layer in sorted({ln[0] for ln in self.lines} | {t[0] for t in self.texts}):
            doc.layers.add(layer)
        msp = doc.modelspace()
        for layer, pts, closed in self.lines:
            msp.add_lwpolyline(
                [(float(x), float(y)) for x, y in pts], close=closed, dxfattribs={"layer": layer}
            )
        for layer, x, y, h, text in self.texts:
            msp.add_text(text, height=h, dxfattribs={"layer": layer, "insert": (x, y)})
        doc.saveas(path)
        return path

    def write_png(self, path: Path, width: int = PREVIEW_WIDTH) -> Path:
        lo, hi = self.bounds()
        span = np.maximum(hi - lo, 1e-9)
        pad = 10
        scale = (width - 2 * pad) / float(span[0])
        height = int(span[1] * scale) + 2 * pad
        height = max(min(height, 4 * width), 50)
        scale = min(scale, (height - 2 * pad) / float(span[1]))
        img = np.full((height, width, 3), 255, dtype=np.uint8)
        for layer, pts, closed in self.lines:
            colour = COLOURS.get(layer, (0, 0, 0))
            q = (pts - lo) * scale + pad
            if closed:
                q = np.vstack((q, q[:1]))
            for a, b in zip(q[:-1], q[1:], strict=True):
                _line(img, a, b, colour)
        return write_png(path, img)


def _line(img: np.ndarray, a: FloatArray, b: FloatArray, colour: tuple[int, int, int]) -> None:
    h, w = img.shape[:2]
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
    xs = np.rint(np.linspace(a[0], b[0], n)).astype(int)
    ys = np.rint(np.linspace(a[1], b[1], n)).astype(int)
    keep = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    img[h - 1 - ys[keep], xs[keep]] = colour


def write_png(path: Path, img: np.ndarray) -> Path:
    """Write an RGB image (uint8, shape (h, w, 3)) as PNG (no imaging library).

    Reference: W3C, *Portable Network Graphics (PNG) Specification*, 2nd ed., 2003.
    """
    h, w = img.shape[:2]
    raw = b"".join(b"\x00" + img[row].tobytes() for row in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
    return path


def _add_sheet(d: Drawing, sheet: Sheet, dx: float, dy: float, marks: bool = True) -> None:
    off = np.array([dx, dy])
    d.polyline("CUT", sheet.cut * MM + off, True)
    d.polyline("SEW", sheet.finished * MM + off, True)
    if marks:
        for x, y, _t in sheet.marks:
            c = np.array([x, y]) * MM + off
            d.polyline("MARKS", np.array([c - (10, 0), c + (10, 0)]))
            d.polyline("MARKS", np.array([c - (0, 10), c + (0, 10)]))


def development(ctx: PackContext) -> Drawing:
    """The full 2D development of the envelope (module docstring), mm."""
    d = Drawing()
    rows = ctx.rows
    if not rows:
        return d
    widest = max(float(np.ptp(s.finished[:, 0])) for s in rows) * MM
    marks: dict[tuple[int, str], list[Sheet]] = {}
    for s in ctx.sheets:
        if s.kind == "marking":
            parts = s.piece.split()
            marks.setdefault((int(parts[1]), parts[-1]), []).append(s)
    for g in range(1, ctx.gores + 1):
        x0 = (g - 1) * widest * 1.1
        y = 0.0
        for s in rows:
            letter = s.piece.removeprefix("row ")
            lo = s.finished.min(axis=0)
            off = np.array([x0, y - lo[1] * MM])
            d.polyline("CUT", s.cut * MM + off, True)
            d.polyline("SEW", s.finished * MM + off, True)
            for m in marks.get((g, letter), []):
                for line in m.lines:
                    d.polyline("FEATURE", line * MM + off)
                for cx, cy, r in m.holes:
                    t = np.linspace(0.0, 2 * np.pi, 49)
                    ring = np.column_stack((cx + r * np.cos(t), cy + r * np.sin(t))) * MM + off
                    d.polyline("FEATURE", ring, True)
            if g == 1:
                d.text("LABEL", x0 - widest * 0.7, y + s.finished_size[1] * MM / 2, 120, letter)
            y += s.finished_size[1] * MM
        d.text("LABEL", x0 - 60, -300, 160, str(g))
    return d


def templates_grid(sheets: Sequence[Sheet], columns: int = 6) -> Drawing:
    """``sheets`` on a grid (cut and sewn outlines, marks, labels), mm."""
    d = Drawing()
    if not sheets:
        return d
    cell_w = max(float(np.ptp(s.cut[:, 0])) for s in sheets) * MM * 1.15
    cell_h = max(float(np.ptp(s.cut[:, 1])) for s in sheets) * MM * 1.25
    for k, s in enumerate(sheets):
        col, row = k % columns, k // columns
        lo = s.cut.min(axis=0) * MM
        dx = col * cell_w - lo[0]
        dy = -row * cell_h - lo[1]
        _add_sheet(d, s, dx, dy)
        label = f"{s.piece.upper()}  CUT {s.cut_count}"
        d.text("LABEL", col * cell_w, -row * cell_h - 150, 90, label)
    return d


def write_cad(ctx: PackContext, out: Path) -> list[tuple[Path, str]]:
    """Write the combined DXFs and their previews; returns (path, description)."""
    files = []
    dev = development(ctx)
    files.append(
        (
            dev.write_dxf(out / ctx.file("panels.dxf")),
            "full 2D envelope development (+ png preview)",
        )
    )
    files.append(
        (
            dev.write_png(out / ctx.file("panels-dxf-preview.png")),
            "preview of the envelope development",
        )
    )
    grid = templates_grid(list(reversed(ctx.rows)))
    files.append(
        (
            grid.write_dxf(out / ctx.file("panel-templates.dxf")),
            f"{len(ctx.rows)} panels on a grid, cut + sew layers",
        )
    )
    files.append(
        (
            grid.write_png(out / ctx.file("panel-templates-preview.png")),
            "preview of the panel templates",
        )
    )
    pieces = [s for s in ctx.sheets if s.kind in ("skin piece", "parachute panel")]
    if pieces:
        app = templates_grid(pieces, columns=8)
        files.append(
            (
                app.write_dxf(out / ctx.file("appendage-patterns.dxf")),
                "special-shape skin pieces and parachute panels",
            )
        )
        files.append(
            (
                app.write_png(out / ctx.file("appendage-patterns-preview.png")),
                "preview of the appendage patterns",
            )
        )
    return files
