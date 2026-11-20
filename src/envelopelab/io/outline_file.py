"""Closed outlines from DXF and SVG files, for crown caps (ADR-0054).

:func:`read_outline` returns the largest closed outline of a drawing as points in the
file's own drawing units, x to the right and y up. The crown scales it to the cap's size
(:func:`envelopelab.features.crown.scaled`), so the units do not matter.

* **DXF** (read with ezdxf): closed LWPOLYLINE and POLYLINE (bulges become arcs), SPLINE
  (closed or ending where it starts), CIRCLE and ELLIPSE, in model space.
* **SVG** (read here, no further dependency): ``polygon``, ``polyline``, ``rect``,
  ``circle``, ``ellipse`` and ``path`` (commands M, L, H, V, C, S, Q, T and Z, absolute and
  relative; elliptical arcs A are not read). Element ``transform`` attributes are not
  applied (the outline is scaled and turned afterwards); SVG's y axis points down and is
  turned up here.

The *largest* outline is the one enclosing the most area.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from envelopelab.solvers.membrane import FloatArray

#: Points per curve segment (Bezier, arc, spline span), source: assumed.
CURVE_SAMPLES = 24


class OutlineFileError(ValueError):
    """A file without a usable closed outline (the message says why)."""


def _area(points: FloatArray) -> float:
    p = np.asarray(points, float)
    return 0.5 * abs(float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])))


def _largest(loops: list[FloatArray], source: str) -> FloatArray:
    loops = [np.asarray(lp, float) for lp in loops if len(lp) >= 3]
    loops = [lp[:-1] if np.allclose(lp[0], lp[-1]) else lp for lp in loops]
    loops = [lp for lp in loops if len(lp) >= 3 and _area(lp) > 0.0]
    if not loops:
        raise OutlineFileError(f"{source}: no closed outline found")
    best: FloatArray = max(loops, key=_area)
    return best


def read_outline(path: str | Path) -> FloatArray:
    """The largest closed outline of a DXF or SVG drawing (module docstring).

    Parameters
    ----------
    path : str or Path
        ``.dxf`` or ``.svg`` file.

    Returns
    -------
    ndarray, shape (n, 2)
        Outline points in the drawing's units, y up, last point not repeated.

    Raises
    ------
    OutlineFileError
        For another file type, an unreadable file or one without a closed outline.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        return _largest(_dxf_loops(path), path.name)
    if suffix == ".svg":
        return _largest(_svg_loops(path), path.name)
    raise OutlineFileError(f"{path.name}: read a .dxf or .svg file")


# -- DXF ---------------------------------------------------------------------------------


def _dxf_loops(path: Path) -> list[FloatArray]:
    from ezdxf import path as dxf_path
    from ezdxf.filemanagement import readfile
    from ezdxf.lldxf.const import DXFError

    try:
        doc = readfile(str(path))
    except (OSError, DXFError) as exc:
        raise OutlineFileError(f"{path.name}: {exc}") from exc
    loops: list[FloatArray] = []
    for entity in doc.modelspace():
        kind = entity.dxftype()
        if kind not in ("LWPOLYLINE", "POLYLINE", "SPLINE", "CIRCLE", "ELLIPSE"):
            continue
        try:
            outline = dxf_path.make_path(entity)
        except (TypeError, ValueError):
            continue
        ctrl = np.array([(v.x, v.y) for v in outline.control_vertices()], float)
        if len(ctrl) < 2:
            continue
        # Curves flattened to 0.1 % of the entity's size.
        tolerance = max(1e-3 * float(np.ptp(ctrl, axis=0).max()), 1e-12)
        points = np.array([(v.x, v.y) for v in outline.flattening(distance=tolerance)], float)
        if len(points) < 3:
            continue
        closed = kind in ("CIRCLE", "ELLIPSE") or bool(getattr(entity, "closed", False))
        if kind == "POLYLINE":
            closed = closed or bool(getattr(entity, "is_closed", False))
        size = float(np.ptp(points, axis=0).max())
        if closed or np.linalg.norm(points[0] - points[-1]) <= 1e-6 * max(size, 1e-12):
            loops.append(points)
    return loops


def _flatten_curve(points: list[FloatArray]) -> FloatArray:
    """Points along a cubic or quadratic Bezier (control points, first included)."""
    t = np.linspace(0.0, 1.0, CURVE_SAMPLES + 1)[1:, None]
    p = [np.asarray(q, float) for q in points]
    if len(p) == 3:
        out: FloatArray = (1 - t) ** 2 * p[0] + 2 * (1 - t) * t * p[1] + t**2 * p[2]
        return out
    out = (
        (1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * p[1] + 3 * (1 - t) * t**2 * p[2] + t**3 * p[3]
    )
    return out


_TOKENS = re.compile(r"[MmLlHhVvCcSsQqTtZzAa]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _path_loops(d: str, source: str) -> list[FloatArray]:
    """Closed sub-paths of an SVG path ``d`` attribute (module docstring)."""
    tokens = _TOKENS.findall(d)
    loops: list[FloatArray] = []
    current: list[FloatArray] = []
    pos = np.zeros(2)
    start = np.zeros(2)
    last_ctrl: FloatArray | None = None
    last_cmd = ""
    i = 0
    cmd = ""

    def number() -> float:
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]
            i += 1
        elif not cmd:
            raise OutlineFileError(f"{source}: a path must start with a command")
        rel = cmd.islower()
        c = cmd.upper()
        base = pos if rel else np.zeros(2)
        if c == "Z":
            if len(current) >= 3:
                loops.append(np.array(current))
            current, pos = [], start.copy()
            last_ctrl, last_cmd = None, "Z"
            cmd = ""
            continue
        if c == "A":
            raise OutlineFileError(
                f"{source}: elliptical arcs (A) in paths are not read; convert them to curves"
            )
        if c == "M":
            if len(current) >= 3 and np.allclose(current[0], current[-1]):
                loops.append(np.array(current))
            pos = base + np.array([number(), number()])
            start = pos.copy()
            current = [pos.copy()]
            cmd = "l" if rel else "L"  # further pairs are lines
            last_ctrl, last_cmd = None, "M"
            continue
        if c == "L":
            pos = base + np.array([number(), number()])
            current.append(pos.copy())
        elif c == "H":
            pos = np.array([(pos[0] if rel else 0.0) + number(), pos[1]])
            current.append(pos.copy())
        elif c == "V":
            pos = np.array([pos[0], (pos[1] if rel else 0.0) + number()])
            current.append(pos.copy())
        elif c in ("C", "S"):
            if c == "C":
                c1 = base + np.array([number(), number()])
            else:
                c1 = 2 * pos - last_ctrl if last_ctrl is not None and last_cmd in "CS" else pos
            c2 = base + np.array([number(), number()])
            end = base + np.array([number(), number()])
            current.extend(_flatten_curve([pos, c1, c2, end]))
            pos, last_ctrl = end, c2
            last_cmd = c
            continue
        elif c in ("Q", "T"):
            if c == "Q":
                c1 = base + np.array([number(), number()])
            else:
                c1 = 2 * pos - last_ctrl if last_ctrl is not None and last_cmd in "QT" else pos
            end = base + np.array([number(), number()])
            current.extend(_flatten_curve([pos, c1, end]))
            pos, last_ctrl = end, c1
            last_cmd = c
            continue
        last_ctrl, last_cmd = None, c
    if len(current) >= 3 and np.allclose(current[0], current[-1]):
        loops.append(np.array(current))
    return loops


def _numbers(text: str | None) -> list[float]:
    return [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", text or "")]


def _svg_loops(path: Path) -> list[FloatArray]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise OutlineFileError(f"{path.name}: {exc}") from exc
    loops: list[FloatArray] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        get = element.attrib.get
        if tag in ("polygon", "polyline"):
            v = _numbers(get("points"))
            pts = np.array(v[: len(v) // 2 * 2], float).reshape(-1, 2)
            if tag == "polygon" or (len(pts) > 2 and np.allclose(pts[0], pts[-1])):
                loops.append(pts)
        elif tag == "rect":
            x, y = float(get("x", 0)), float(get("y", 0))
            w, h = float(get("width", 0)), float(get("height", 0))
            loops.append(np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]))
        elif tag in ("circle", "ellipse"):
            cx, cy = float(get("cx", 0)), float(get("cy", 0))
            rx = float(get("r", 0)) if tag == "circle" else float(get("rx", 0))
            ry = float(get("r", 0)) if tag == "circle" else float(get("ry", 0))
            t = np.linspace(0.0, 2.0 * math.pi, 4 * CURVE_SAMPLES, endpoint=False)
            loops.append(np.column_stack([cx + rx * np.cos(t), cy + ry * np.sin(t)]))
        elif tag == "path":
            loops += _path_loops(get("d", ""), path.name)
    # SVG's y axis points down: turn it up.
    return [np.column_stack([lp[:, 0], -lp[:, 1]]) for lp in loops]
