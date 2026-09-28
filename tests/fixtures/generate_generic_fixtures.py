"""Generate the generic pattern-import fixtures (DXF files) in tests/fixtures/.

Run from the repository root:

    python tests/fixtures/generate_generic_fixtures.py

The DXF files are committed; this script documents exactly how they were made. Both
fixtures are synthetic designs built with :mod:`envelopelab.geometry.gore`, drawn in mm
with $INSUNITS = 4:

* ``standard_gore/panels.dxf``: 8 gores x 4 rows, CUT and SEW outlines, one label per
  row piece (``PANEL <row> x8``).
* ``special_shape/patterns.dxf``: 6 gores x 3 rows; row B carries a FEATURE circle (the
  finished rim of a hole for a tube appendage), a TAPE line and a GRAIN arrow; plus a
  tube (developed cone frustum) whose base arc is 40 mm longer than the hole rim
  (designed ease) and a cap disc that closes the tube.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from ezdxf.document import Drawing
from ezdxf.filemanagement import new as new_dxf

from envelopelab.geometry.gore import (
    GoreWidthModel,
    MeridianProfile,
    PanelRow,
    SeamAllowance,
    split_rows,
)
from envelopelab.geometry.polygon import FloatArray, offset_polygon

HERE = Path(__file__).resolve().parent
MM = 1000.0
ALLOWANCE = 0.025  # m


def _new_doc() -> Drawing:
    doc = new_dxf("R2010", setup=False)
    doc.header["$INSUNITS"] = 4
    doc.header["$TDCREATE"] = 2460000.0
    doc.header["$TDUPDATE"] = 2460000.0
    for name in ("CUT", "SEW", "FEATURE", "TAPE", "GRAIN", "NOTES"):
        doc.layers.add(name)
    return doc


def _poly(msp: object, points: FloatArray, layer: str, offset: tuple[float, float]) -> None:
    pts = [(float(x * MM + offset[0]), float(y * MM + offset[1])) for x, y in points]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})  # type: ignore[attr-defined]


def _text(msp: object, text: str, at: tuple[float, float], height: float = 60.0) -> None:
    msp.add_text(text, height=height, dxfattribs={"layer": "NOTES", "insert": at})  # type: ignore[attr-defined]


def _rows(n_gores: int, r: list[float], z: list[float], labels: list[str]) -> list[PanelRow]:
    """Equal-height rows covering the whole meridian (heights rounded to 0.1 mm)."""
    profile = MeridianProfile.from_control_points(r, z, samples=161)
    width = GoreWidthModel(n_gores=n_gores, form="small_bulge")
    height = math.floor(profile.meridian_length / len(labels) * 1e4) / 1e4
    heights = [height] * (len(labels) - 1)
    heights.append(profile.meridian_length - sum(heights))
    return split_rows(
        profile,
        width,
        heights,
        labels=labels,
        allowance=SeamAllowance(side=ALLOWANCE, bottom=ALLOWANCE, top=ALLOWANCE),
        corner="miter",
    )


def standard_gore() -> None:
    rows = _rows(8, [1.0, 2.6, 3.0, 2.2, 0.8], [0.0, 2.0, 4.5, 7.0, 8.2], list("ABCD"))
    doc = _new_doc()
    msp = doc.modelspace()
    x = 0.0
    for row in rows:
        width = float(row.cut_outline[:, 0].max() - row.cut_outline[:, 0].min()) * MM
        x += width / 2 + 200.0
        _poly(msp, row.cut_outline, "CUT", (x, 0.0))
        _poly(msp, row.finished_outline, "SEW", (x, 0.0))
        _text(msp, f"PANEL {row.label} x8", (x - 150.0, row.finished_height * MM / 2))
        x += width / 2
    _text(msp, "GENERIC STANDARD GORE FIXTURE 1:1 mm", (0.0, -600.0), 120.0)
    doc.saveas(HERE / "standard_gore" / "panels.dxf")


def _circle(radius: float, n: int = 128) -> FloatArray:
    a = np.linspace(0.0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([radius * np.cos(a), radius * np.sin(a)])


def special_shape() -> None:
    rows = _rows(6, [0.9, 2.2, 2.4, 1.6, 0.7], [0.0, 1.8, 3.8, 5.8, 6.8], list("ABC"))
    doc = _new_doc()
    msp = doc.modelspace()
    x = 0.0
    for row in rows:
        width = float(row.cut_outline[:, 0].max() - row.cut_outline[:, 0].min()) * MM
        x += width / 2 + 200.0
        _poly(msp, row.cut_outline, "CUT", (x, 0.0))
        _poly(msp, row.finished_outline, "SEW", (x, 0.0))
        _text(msp, f"PANEL {row.label} x6", (x - 150.0, 300.0))
        if row.label == "B":
            centre = (x, row.finished_height * MM / 2 + 150.0)
            msp.add_circle(centre, 300.0, dxfattribs={"layer": "FEATURE"})
            msp.add_circle(centre, 275.0, dxfattribs={"layer": "FEATURE"})
            y_tape = 250.0
            half = float(np.interp(y_tape / MM, row.right_edge[:, 1], row.right_edge[:, 0]))
            msp.add_lwpolyline(
                [(x - 0.8 * half * MM, y_tape), (x + 0.8 * half * MM, y_tape)],
                dxfattribs={"layer": "TAPE"},
            )
            msp.add_line((x - 400.0, 150.0), (x + 400.0, 150.0), dxfattribs={"layer": "GRAIN"})
        x += width / 2
    # Tube: developed cone frustum, base radius r_b (hole rim 0.300 m + 40 mm ease), top
    # radius 0.150 m (cap), slant length 1.000 m.
    ease = 0.040
    r_b = 0.300 + ease / (2 * math.pi)
    r_t = 0.150
    slant = 1.0
    rho_b = r_b * slant / (r_b - r_t)
    rho_t = rho_b - slant
    phi = 2 * math.pi * r_b / rho_b
    a = np.linspace(-phi / 2, phi / 2, 65)
    apex = np.array([0.0, rho_b])

    def arc(rho: float, angles: FloatArray) -> FloatArray:
        return apex + rho * np.column_stack([np.sin(angles), -np.cos(angles)])

    tube = np.vstack([arc(rho_b, a), arc(rho_t, a[::-1])])
    tube_offset = (x + 2000.0, 0.0)
    _poly(msp, offset_polygon(tube, ALLOWANCE), "CUT", tube_offset)
    _poly(msp, tube, "SEW", tube_offset)
    _text(msp, "TUBE x1", (tube_offset[0] - 150.0, 500.0))
    cap = _circle(r_t)
    cap_offset = (x + 4000.0, 400.0)
    _poly(msp, offset_polygon(cap, ALLOWANCE), "CUT", cap_offset)
    _poly(msp, cap, "SEW", cap_offset)
    _text(msp, "CAP x1", (cap_offset[0] - 80.0, cap_offset[1]), 40.0)
    doc.saveas(HERE / "special_shape" / "patterns.dxf")


if __name__ == "__main__":
    (HERE / "standard_gore").mkdir(exist_ok=True)
    (HERE / "special_shape").mkdir(exist_ok=True)
    standard_gore()
    special_shape()
