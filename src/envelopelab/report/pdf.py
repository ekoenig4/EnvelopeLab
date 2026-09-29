"""Minimal vector PDF writer for reports (text, lines, filled polygons).

Writes PDF 1.4 with the standard Helvetica fonts (no embedding) and FlateDecode page
streams (``zlib`` from the standard library), so reports need no extra dependency. Only
what the Reality Check report uses is supported: pages of a fixed size, text lines,
filled and stroked polygons and rectangles in RGB. Coordinates are points (1/72 in) with
the origin at the bottom left of the page.

Reference: Adobe, *PDF Reference*, 6th ed. (version 1.7), 2006, ch. 3 (file structure),
ch. 4 (graphics), ch. 5 (text, standard 14 fonts).
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from pathlib import Path

#: A4 landscape, points.
A4_LANDSCAPE = (842.0, 595.0)
RGB = tuple[float, float, float]


def _escape(text: str) -> str:
    safe = text.encode("latin-1", errors="replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class PdfCanvas:
    """Builds a multi-page PDF document.

    Parameters
    ----------
    size : (float, float)
        Page width and height, points.
    """

    def __init__(self, size: tuple[float, float] = A4_LANDSCAPE) -> None:
        self.width, self.height = size
        self.pages: list[list[str]] = []
        self.new_page()

    def new_page(self) -> None:
        """Start a new page."""
        self.pages.append([])

    @property
    def _ops(self) -> list[str]:
        return self.pages[-1]

    def text(
        self,
        x: float,
        y: float,
        text: str,
        size: float = 9.0,
        bold: bool = False,
        color: RGB = (0, 0, 0),
    ) -> None:
        """Draw one line of text with its baseline at ``(x, y)``."""
        font = "F2" if bold else "F1"
        r, g, b = color
        self._ops.append(
            f"BT {r:.3f} {g:.3f} {b:.3f} rg /{font} {size:.2f} Tf {x:.2f} {y:.2f} Td "
            f"({_escape(text)}) Tj ET"
        )

    def polygon(
        self,
        points: Sequence[tuple[float, float]],
        fill: RGB | None = None,
        stroke: RGB | None = None,
        width: float = 0.5,
    ) -> None:
        """Draw a closed polygon, filled and/or stroked."""
        if len(points) < 2:
            return
        path = [f"{points[0][0]:.2f} {points[0][1]:.2f} m"]
        path += [f"{x:.2f} {y:.2f} l" for x, y in points[1:]]
        path.append("h")
        ops = []
        if fill is not None:
            ops.append("{:.3f} {:.3f} {:.3f} rg".format(*fill))
        if stroke is not None:
            ops.append("{:.3f} {:.3f} {:.3f} RG {:.2f} w".format(*stroke, width))
        op = "B" if fill is not None and stroke is not None else ("f" if fill is not None else "S")
        self._ops.append(" ".join(ops + path + [op]))

    def line(
        self, x0: float, y0: float, x1: float, y1: float, color: RGB = (0, 0, 0), width: float = 0.5
    ) -> None:
        """Draw a straight line."""
        self._ops.append(
            "{:.3f} {:.3f} {:.3f} RG {:.2f} w {:.2f} {:.2f} m {:.2f} {:.2f} l S".format(
                *color, width, x0, y0, x1, y1
            )
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: RGB | None = None,
        stroke: RGB | None = None,
    ) -> None:
        """Draw a rectangle."""
        self.polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], fill, stroke)

    def to_bytes(self) -> bytes:
        """The complete PDF file."""
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font1 = add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        )
        font2 = add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )
        pages_id = len(objects) + 1 + 2 * len(self.pages)
        page_ids = []
        for ops in self.pages:
            stream = zlib.compress("\n".join(ops).encode("latin-1", errors="replace"))
            content = add(
                f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode()
                + stream
                + b"\nendstream"
            )
            page_ids.append(
                add(
                    (
                        f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {self.width:.0f} "
                        f"{self.height:.0f}] /Resources << /Font << /F1 {font1} 0 R "
                        f"/F2 {font2} 0 R >> "
                        f">> /Contents {content} 0 R >>"
                    ).encode()
                )
            )
        kids = " ".join(f"{p} 0 R" for p in page_ids)
        assert add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()) == pages_id
        catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for k, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{k} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n".encode()
        out += f"startxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)

    def save(self, path: str | Path) -> Path:
        """Write the PDF file."""
        p = Path(path)
        p.write_bytes(self.to_bytes())
        return p
