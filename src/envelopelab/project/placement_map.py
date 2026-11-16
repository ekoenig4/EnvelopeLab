r"""Where special shapes sit on the balloon: a gore map and a coarse 3D sketch (ADR-0044).

The Special shapes panel shows every shape, its footprint, feed holes and the symmetry
axes on two drawings next to the editor, so positions typed as numbers can be seen.

Gore map
--------
The gores are laid side by side as they are cut, each at its true flat width: gore
:math:`k` (from 0) is the column centred on :math:`x_k = (k + \tfrac12)\,W`, with
:math:`W = 2 w_{max} (1 + c)` (:math:`w_{max}` the largest flat half width of a gore,
:math:`c` = :data:`COLUMN_GAP` a gap between columns), and its outline runs
:math:`x = x_k \pm w(s)` up the load tape :math:`y = s` (m from the mouth). A point at
gore position :math:`g` (gore widths from the first seam) and tape position :math:`s` is
drawn at

.. math:: x = x_k + 2\left(g - k - \tfrac12\right) w(s), \qquad y = s,
          \qquad k = \lfloor g \rfloor \bmod N,

so a point keeps its place across its gore, as on the cut panel (lobe gores: exactly the
panel's :math:`x`; flat-chord rows: the same across-fraction on the gore's half width,
which ignores their seam bows). A footprint that crosses a seam is drawn in both gores,
broken at the seam. :func:`map_to_placement` is the inverse, used to drag a shape on the
map.

3D sketch
---------
:func:`envelope_sketch` is the display surface (:func:`envelopelab.project.gore_design.
display_points`) on a coarse grid, its gore seams and row seams as lines, for a quick
software-drawn view; the panel adds the shapes as designed and the symmetry axes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from envelopelab.features.primitives import EnvelopeSurface, PrimitiveDesign
    from envelopelab.project.shapes import ShapePlacement
    from envelopelab.project.symmetry import SymmetryAxis
    from envelopelab.solvers.membrane import FloatArray, IntArray

#: Gap between the gore columns of the map, as a fraction of a gore's widest width
#: (display only).
COLUMN_GAP = 0.06
#: Samples up the tape of every gore outline and axis line of the map.
MAP_SAMPLES = 97


@dataclass
class GoreMap:
    """The gores laid side by side (module docstring), m.

    Attributes
    ----------
    gores : int
        Number of gores N.
    length : float
        Load-tape length from the mouth to the crown, m.
    column : float
        Column width :math:`W`, m.
    outlines : list of ndarray, shape (n, 2)
        Every gore's closed outline, gore 1 first.
    rows : list of (str, float, float)
        Row label and tape positions of its bottom and top seams, m.
    """

    gores: int
    length: float
    column: float
    outlines: list[FloatArray] = field(default_factory=list)
    rows: list[tuple[str, float, float]] = field(default_factory=list)
    _surface: Any = field(default=None, repr=False)

    def half_width(self, s: FloatArray) -> FloatArray:
        """Flat half width of a gore at tape positions ``s`` (m), m."""
        out: FloatArray = np.asarray(self._surface.half_width(np.asarray(s, float)))
        return out

    def points(self, g: FloatArray, s: FloatArray) -> FloatArray:
        """Map points of gore positions ``g`` and tape positions ``s`` (m), m."""
        g = np.mod(np.asarray(g, float), self.gores)
        s = np.clip(np.asarray(s, float), 0.0, self.length)
        k = np.minimum(np.floor(g), self.gores - 1)
        x = (k + 0.5) * self.column + 2.0 * (g - k - 0.5) * self.half_width(s)
        return np.column_stack([x, s])

    def polylines(self, g: FloatArray, s: FloatArray, closed: bool = False) -> list[FloatArray]:
        """A curve given by gore and tape positions as map polylines, broken where it
        crosses a seam into the next gore."""
        g, s = np.asarray(g, float), np.asarray(s, float)
        if closed and len(g):
            # Start where the loop enters a gore, so each gore's part is one piece.
            cell0 = np.floor(np.mod(g, self.gores)).astype(np.int64)
            change = np.flatnonzero(cell0 != np.roll(cell0, 1))
            if len(change):
                g, s = np.roll(g, -int(change[0])), np.roll(s, -int(change[0]))
            g, s = np.append(g, g[:1]), np.append(s, s[:1])
        cell = np.floor(np.mod(g, self.gores)).astype(np.int64)
        pts = self.points(g, s)
        out, start = [], 0
        for i in range(1, len(g) + 1):
            if i == len(g) or cell[i] != cell[start]:
                if i - start > 1:
                    out.append(pts[start:i])
                start = i
        return out


def gore_map(surface: EnvelopeSurface) -> GoreMap:
    """The gore map of an envelope (module docstring)."""
    length = float(surface.profile.meridian_length)
    s = np.linspace(0.0, length, MAP_SAMPLES)
    half = np.asarray(surface.half_width(s), float)
    column = 2.0 * float(half.max()) * (1.0 + COLUMN_GAP)
    n = surface.gore_count
    m = GoreMap(n, length, column, _surface=surface)
    for k in range(n):
        xc = (k + 0.5) * column
        m.outlines.append(
            np.vstack([np.column_stack([xc + half, s]), np.column_stack([xc - half, s])[::-1]])
        )
    m.rows = [(r.label, float(r.s_bottom), float(r.s_top)) for r in surface.rows]
    return m


def gore_position(placement: ShapePlacement) -> float:
    """Gore position (gore widths from the first seam) of a placement's base point."""
    return placement.gore - 0.5 + placement.across


def footprint_lines(m: GoreMap, placed: PrimitiveDesign) -> list[FloatArray]:
    """A placed shape's footprint on the map (broken at seams), m."""
    g = np.asarray(placed.surface.gore_position(placed.footprint_theta), float)
    return m.polylines(g, placed.footprint_s, closed=True)


def ring_lines(m: GoreMap, g: float, s: float, radius: float, points: int = 49) -> list[FloatArray]:
    """A circle of ``radius`` (m) round the point at gore position ``g``, tape position
    ``s`` (m), drawn on the map (feed holes): in the tangent plane, the hoop direction
    taken at the circle's height, m."""
    a = np.linspace(0.0, 2.0 * math.pi, points)
    ss = s + radius * np.sin(a)
    w = np.maximum(m.half_width(np.clip(ss, 0.0, m.length)), 1e-9)
    gg = g + radius * np.cos(a) / (2.0 * w)
    return m.polylines(gg, ss)


def axis_line(m: GoreMap, axis: SymmetryAxis) -> FloatArray:
    """A symmetry axis on the map, from the mouth to the crown, m."""
    s = np.linspace(0.0, m.length, MAP_SAMPLES)
    return m.points(np.full(MAP_SAMPLES, axis.line), s)


def gore_position_at(m: GoreMap, x: float, y: float) -> float | None:
    """Gore position (gore widths from the first seam) of map point ``(x, y)`` (m): the
    inverse of :meth:`GoreMap.points`, clamped to the gore's seams; None off the map."""
    if not (0.0 <= y <= m.length and 0.0 <= x <= m.gores * m.column):
        return None
    k = int(min(max(math.floor(x / m.column), 0), m.gores - 1))
    w = max(float(m.half_width(np.array([y]))[0]), 1e-9)
    across = min(max((x - (k + 0.5) * m.column) / (2.0 * w), -0.5), 0.5)
    return k + 0.5 + across


def snap(g: float, step: float = 0.5) -> float:
    """``g`` (gore widths) to the nearest multiple of ``step``: with 0.5, the nearest
    gore centreline or seam."""
    return round(g / step) * step


def azimuth_position(point: FloatArray, gores: int) -> float:
    """Gore position of a 3D point's azimuth round the envelope axis (z), in [0, N)."""
    theta = math.atan2(float(point[1]), float(point[0])) % (2.0 * math.pi)
    return theta / (2.0 * math.pi / gores)


def mirrored_lines(m: GoreMap, g: FloatArray, s: FloatArray, line: float) -> list[FloatArray]:
    """A closed curve given by gore and tape positions, mirrored across the axis at gore
    position ``line`` (:math:`g' = 2 g_m - g`), as map polylines: where a mirror twin's
    footprint would lie."""
    return m.polylines(2.0 * line - np.asarray(g, float), s, closed=True)


def reflect(points: FloatArray, line: float, gores: int) -> FloatArray:
    r"""3D points (envelope frame, z up the axis) mirrored in the meridian plane at gore
    position ``line``: azimuth :math:`\theta_m = 2\pi g_m / N`,
    :math:`x' = x \cos 2\theta_m + y \sin 2\theta_m`,
    :math:`y' = x \sin 2\theta_m - y \cos 2\theta_m`, :math:`z' = z`."""
    a = 2.0 * (2.0 * math.pi * line / gores)
    p = np.asarray(points, float)
    c, s = math.cos(a), math.sin(a)
    out: FloatArray = np.column_stack(
        [c * p[:, 0] + s * p[:, 1], s * p[:, 0] - c * p[:, 1], p[:, 2]]
    )
    return out


def map_to_placement(m: GoreMap, x: float, y: float, current: ShapePlacement) -> ShapePlacement:
    """The placement whose base point is drawn at map point ``(x, y)`` (m): gore from
    the column, tape position ``y`` (kept 1 mm inside the tape) and the fraction across
    the gore, clamped to [-0.5, 0.5]; the lean of ``current`` is kept."""
    from envelopelab.project.shapes import DRAG_MARGIN

    k = int(min(max(math.floor(x / m.column), 0), m.gores - 1))
    s = min(max(float(y), DRAG_MARGIN), m.length - DRAG_MARGIN)
    w = max(float(m.half_width(np.array([s]))[0]), 1e-9)
    across = min(max((x - (k + 0.5) * m.column) / (2.0 * w), -0.5), 0.5)
    return current.model_copy(
        update={"gore": k + 1, "tape_position": round(s, 4), "across": round(across, 4)}
    )


def nudged(m: GoreMap, placement: ShapePlacement, d_hoop: float, d_tape: float) -> ShapePlacement:
    r"""``placement`` moved ``d_hoop`` m round the envelope (positive towards higher
    gores) and ``d_tape`` m up the tape, as on the flat gore: the base point moves
    :math:`\Delta g = \Delta_{hoop} / (2 w(s))` gore widths (:math:`w` the flat half
    width at its tape position), into the next gore when it passes a seam, and stays 1 mm
    inside the ends of the tape. The lean is kept."""
    from envelopelab.project.shapes import DRAG_MARGIN

    s = float(placement.tape_position)
    w = max(float(m.half_width(np.array([s]))[0]), 1e-9)
    g = (gore_position(placement) + d_hoop / (2.0 * w)) % m.gores
    cell = min(int(math.floor(g)), m.gores - 1)
    s = min(max(s + d_tape, DRAG_MARGIN), m.length - DRAG_MARGIN)
    return placement.model_copy(
        update={
            "gore": cell + 1,
            "tape_position": round(s, 4),
            "across": round(min(max(g - cell - 0.5, -0.5), 0.5), 4),
        }
    )


@dataclass
class Sketch:
    """A coarse 3D envelope for the panel's sketch, m (envelope frame, z up).

    Attributes
    ----------
    points : ndarray, shape (n, 3)
        Grid points.
    triangles : ndarray of int, shape (t, 3)
        Triangles, normals pointing out.
    seams : list of ndarray
        Gore seams (mouth to crown) and row seams (round the envelope).
    """

    points: FloatArray
    triangles: IntArray
    seams: list[FloatArray]


def envelope_sketch(design: Any, per_gore: int = 4, rings: int = 30) -> Sketch:
    """The display surface on a coarse grid with its seams (module docstring)."""
    from envelopelab.project.gore_design import design_profile, display_points, panel_rows
    from envelopelab.project.model import PatternSet

    n = design.gores.count
    length = float(design_profile(design).meridian_length)
    s = np.linspace(0.0, length, rings)
    cols = n * per_gore
    theta = 2.0 * math.pi * np.arange(cols) / cols
    ss, tt = np.meshgrid(s, theta, indexing="ij")
    pts = display_points(design, ss.ravel(), tt.ravel())
    tri = []
    for i in range(rings - 1):
        for j in range(cols):
            a, b = i * cols + j, i * cols + (j + 1) % cols
            c, d = a + cols, b + cols
            tri += [(a, b, d), (a, d, c)]
    seams = []
    dense = np.linspace(0.0, length, 61)
    for k in range(n):
        seams.append(display_points(design, dense, np.full(len(dense), 2.0 * math.pi * k / n)))
    around = np.linspace(0.0, 2.0 * math.pi, n * 12 + 1)
    try:
        tops = [r.s_top for r in panel_rows(design, PatternSet())][:-1]
    except ValueError:
        tops = []
    for top in tops:
        seams.append(display_points(design, np.full(len(around), top), around))
    return Sketch(np.asarray(pts, float), np.asarray(tri, dtype=np.int64), seams)
