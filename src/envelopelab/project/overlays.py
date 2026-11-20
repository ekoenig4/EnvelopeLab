r"""Overlays: flat appliqué patches sewn on top of the envelope (ADR-0056).

An overlay is a flat piece of cloth (a circle, an ellipse, a rectangle, a polygon or an
outline imported from a DXF or SVG file) sewn on top of the envelope panels, anywhere on
the envelope and across seams. It is not inflated or simulated: it adds cloth, a cut
piece and marking lines, nothing else.

Geometry
--------
The outline is given in *cloth coordinates* :math:`(a, b)`, m: :math:`a` across the
cloth (towards the next gore), :math:`b` up the load tape, centred on the overlay's
placement (gore :math:`k`, tape position :math:`s_0`, fraction ``across`` from the gore
centreline, gore position :math:`g_0 = k - \tfrac12 + \text{across}`) and turned by
``turn_deg`` (anticlockwise). A point of the outline lies on the envelope at

.. math:: s = s_0 + b, \qquad g = g_0 + \frac{a}{2\,h(s)},

where :math:`h(s)` is the flat half width of a panel at tape position :math:`s` (lobe
rows: the gore's flat half width :math:`w(s)`; flat-chord rows: the half width of the cut
trapezoid, linear between its bottom and top). Across the cloth of the panels laid side
by side a distance :math:`a` is therefore exactly :math:`a` m of cloth, and in each host
panel's pattern coordinates (``x`` across from the gore centreline, ``y`` up from the
row's bottom seam; flat-chord rows: along the row's rise) the outline is drawn at

.. math:: x = (2 f - 1)\,h(s), \qquad f = g - (k_h - 1), \qquad y = s - s_{bottom},

for host gore :math:`k_h`. The cut piece is the outline as given (its finished line) with
the hem turned under round it.

Assumptions and valid range
---------------------------
The envelope is doubly curved and a flat patch cannot lie on it exactly. The mapping above
keeps lengths across the cloth and up the tape; it shears a patch whose centre is off the
gore centreline (``x`` shifts with :math:`h(s)`), and adjacent flat panels meet at an
angle at their seam. :func:`overlay_layout` reports the difference between the outline's
length on the piece and the length marked on the panels (worked in as ease); a large
difference means the patch is too big for the local curvature (source: assumed, a fabric
patch gives about 1 % without puckering). The outline must lie between the mouth and the
crown and span less than the whole circumference. Reference: the gore-map development of
:mod:`envelopelab.project.placement_map` (ADR-0044), which this extends to finite patches.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from envelopelab.project.shapes import ShapePlacement

if TYPE_CHECKING:
    from envelopelab.features.primitives import EnvelopeSurface
    from envelopelab.project.gore_design import DesignFinding
    from envelopelab.project.placement_map import GoreMap
    from envelopelab.solvers.membrane import FloatArray

OutlineKind = Literal["circle", "ellipse", "rectangle", "polygon", "outline"]
OUTLINE_KINDS: tuple[OutlineKind, ...] = ("circle", "ellipse", "rectangle", "polygon", "outline")
#: Longest segment of an outline once densified, m (display and marking accuracy; source:
#: assumed).
SEGMENT = 0.02
#: Default hem turned under round an appliqué, m (source: assumed, a 12 mm single fold).
DEFAULT_HEM = 0.012
#: Difference between the outline's length on the piece and on the panels above which a
#: warning is given, as a fraction of the outline (source: assumed, fabric give ~1 %).
EASE_WARNING = 0.01
#: Tier key of an overlay's single piece in the panel colours (``PanelColours.shapes``).
OVERLAY_PIECE = ("A", 1)


class OverlaySpec(BaseModel):
    """One appliqué patch (module docstring). Lengths in m, angles in degrees.

    Attributes
    ----------
    name : str
        Unique among special shapes and overlays.
    placement : ShapePlacement
        Where its centre lies: gore (from 1), tape position (m) and fraction across the
        gore (``lean`` is not used).
    outline : {"circle", "ellipse", "rectangle", "polygon", "outline"}
        Kind of outline.
    width, height : float
        Size across and up the tape, m (a circle: ``width`` is its diameter; an imported
        outline is scaled to fit the box, keeping its proportions).
    turn_deg : float
        Turn of the outline, anticlockwise seen from outside, degrees.
    points : list of (float, float)
        Corners of a polygon (m, about its centre) or the imported outline (any units).
    smooth : bool
        A polygon is drawn through its corners as a smooth closed curve.
    source : str
        File an outline was imported from (for information).
    hem : float
        Cloth turned under round the outline, m (the cut piece is that much larger).
    fabric : str or None
        Fabric of the patch (None: as the panel under its centre).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_\- ]+$")
    placement: ShapePlacement
    outline: OutlineKind = "circle"
    width: float = Field(default=1.0, gt=0.0)
    height: float = Field(default=1.0, gt=0.0)
    turn_deg: float = Field(default=0.0, ge=-180.0, le=180.0)
    points: list[tuple[float, float]] = Field(default_factory=list)
    smooth: bool = False
    source: str = ""
    hem: float = Field(default=DEFAULT_HEM, ge=0.0)
    fabric: str | None = None

    @model_validator(mode="after")
    def _points(self) -> OverlaySpec:
        if self.outline in ("polygon", "outline") and len(self.points) < 3:
            raise ValueError(f"overlay {self.name}: a {self.outline} needs at least 3 points")
        return self


def _closed_spline(points: FloatArray, per_segment: int = 12) -> FloatArray:
    """A closed uniform Catmull-Rom curve through ``points`` (m)."""
    p = np.asarray(points, dtype=np.float64)
    n = len(p)
    t = np.linspace(0.0, 1.0, per_segment, endpoint=False)[:, None]
    out = []
    for i in range(n):
        p0, p1, p2, p3 = p[i - 1], p[i], p[(i + 1) % n], p[(i + 2) % n]
        out.append(
            0.5
            * (
                2 * p1
                + (-p0 + p2) * t
                + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t**2
                + (-p0 + 3 * p1 - 3 * p2 + p3) * t**3
            )
        )
    curve: FloatArray = np.vstack(out)
    return curve


def _signed_area(p: FloatArray) -> float:
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _self_intersects(p: FloatArray) -> bool:
    n = len(p)
    a, b = p, np.roll(p, -1, axis=0)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            d1, d2 = b[i] - a[i], b[j] - a[j]
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) < 1e-15:
                continue
            r = a[j] - a[i]
            t = (r[0] * d2[1] - r[1] * d2[0]) / den
            u = (r[0] * d1[1] - r[1] * d1[0]) / den
            if 0.0 < t < 1.0 and 0.0 < u < 1.0:
                return True
    return False


def densify(points: FloatArray, step: float = SEGMENT) -> FloatArray:
    """A closed polygon (m) with no edge longer than ``step`` (m)."""
    p = np.asarray(points, dtype=np.float64)
    out = []
    for a, b in zip(p, np.roll(p, -1, axis=0), strict=True):
        n = max(1, math.ceil(float(np.linalg.norm(b - a)) / step))
        out.append(a + (b - a) * np.arange(n)[:, None] / n)
    dense: FloatArray = np.vstack(out)
    return dense


def outline_points(spec: OverlaySpec) -> FloatArray:
    """The finished outline in cloth coordinates about the centre, m, anticlockwise, not
    densified (module docstring).

    Raises
    ------
    ValueError
        For an outline that crosses itself or has no area.
    """
    w, h = spec.width, spec.height
    if spec.outline == "circle":
        t = np.linspace(0.0, 2 * math.pi, 96, endpoint=False)
        p = 0.5 * w * np.column_stack([np.cos(t), np.sin(t)])
    elif spec.outline == "ellipse":
        t = np.linspace(0.0, 2 * math.pi, 96, endpoint=False)
        p = 0.5 * np.column_stack([w * np.cos(t), h * np.sin(t)])
    elif spec.outline == "rectangle":
        p = 0.5 * np.array([[-w, -h], [w, -h], [w, h], [-w, h]], dtype=np.float64)
    else:
        p = np.asarray(spec.points, dtype=np.float64)
        if spec.outline == "outline":
            # Imported: centred on its box and scaled to fit width x height.
            lo, hi = p.min(axis=0), p.max(axis=0)
            span = np.maximum(hi - lo, 1e-12)
            p = (p - 0.5 * (lo + hi)) * min(w / span[0], h / span[1])
        elif spec.smooth:
            p = _closed_spline(p)
    # A self-crossing outline first: its signed area may be zero (a bow tie).
    if spec.outline in ("polygon", "outline") and _self_intersects(p):
        raise ValueError(f"overlay {spec.name}: the outline crosses itself")
    if _signed_area(p) < 0.0:
        p = p[::-1]
    if abs(_signed_area(p)) < 1e-6:
        raise ValueError(f"overlay {spec.name}: the outline has no area")
    c, s = math.cos(math.radians(spec.turn_deg)), math.sin(math.radians(spec.turn_deg))
    turned: FloatArray = p @ np.array([[c, s], [-s, c]])
    return turned


def cloth_half_width(surface: EnvelopeSurface, s: FloatArray) -> FloatArray:
    """Flat half width :math:`h(s)` of a panel at tape positions ``s`` (m), m (module
    docstring; flat-chord rows: linear between the trapezoid's bottom and top)."""
    s = np.atleast_1d(np.asarray(s, dtype=np.float64))
    out = np.asarray(surface.half_width(s), dtype=np.float64).copy()
    rows = surface.row_index(s)
    for i, band in enumerate(surface.rows):
        if band.rise is None:
            continue
        on = rows == i
        t = (s[on] - band.s_bottom) / (band.s_top - band.s_bottom)
        out[on] = band.half_bottom + t * (band.half_top - band.half_bottom)
    return out


def panel_xy(surface: EnvelopeSurface, row: int, f: FloatArray, s: FloatArray) -> FloatArray:
    """Pattern coordinates (m) in the panel of row ``row`` of points at fraction ``f``
    across their gore (0 at its left seam) and tape position ``s`` (m)."""
    band = surface.rows[row]
    s = np.asarray(s, dtype=np.float64)
    x = (2.0 * np.asarray(f, dtype=np.float64) - 1.0) * cloth_half_width(surface, s)
    if band.rise is None:
        y = s - band.s_bottom
    else:
        y = (s - band.s_bottom) / (band.s_top - band.s_bottom) * band.rise
    out: FloatArray = np.column_stack([x, y])
    return out


@dataclass
class OverlayRun:
    """The part of an overlay's outline that lies in one envelope panel.

    Attributes
    ----------
    gore : int
        Host gore, from 1.
    row : str
        Host row label.
    plan : ndarray, shape (n, 2)
        The run in cloth coordinates (the cut piece's frame), m.
    panel : ndarray, shape (n, 2)
        The run in the host panel's pattern coordinates, m.
    gs : ndarray, shape (n, 2)
        The run as gore positions and tape positions (m).
    """

    gore: int
    row: str
    plan: FloatArray
    panel: FloatArray
    gs: FloatArray


@dataclass
class OverlayLayout:
    """An overlay laid on the envelope.

    Attributes
    ----------
    spec : OverlaySpec
    outline : ndarray, shape (n, 2)
        Finished outline in cloth coordinates, densified, anticlockwise, m.
    gs : ndarray, shape (n, 2)
        The outline as gore positions (unwrapped; gore k spans k-1 to k) and tape
        positions, m.
    runs : list of OverlayRun
        The outline split at every seam it crosses, in order round it.
    crossings : list of (ndarray, int, str, int, str)
        Where the outline crosses a seam: cloth point (m) and the panels (gore, row) on
        each side; numbered from 1 in this order as match marks.
    perimeter : float
        Length of the finished outline, m.
    marked : float
        Length of the marking lines on the panels, m.
    covered : list of (int, str)
        Panels the overlay lies over (gore, row), every gore from 1.
    """

    spec: OverlaySpec
    outline: FloatArray
    gs: FloatArray
    runs: list[OverlayRun] = field(default_factory=list)
    crossings: list[tuple[FloatArray, int, str, int, str]] = field(default_factory=list)
    perimeter: float = 0.0
    marked: float = 0.0
    covered: list[tuple[int, str]] = field(default_factory=list)

    @property
    def ease(self) -> float:
        """Outline length on the piece less the length marked on the panels, m."""
        return self.perimeter - self.marked

    def warnings(self) -> list[str]:
        """What the builder should know (empty: nothing)."""
        if self.perimeter > 0 and abs(self.ease) > EASE_WARNING * self.perimeter:
            return [
                f"overlay {self.spec.name}: its outline is {self.ease * 1000:+.0f} mm longer "
                f"on the piece than marked on the panels ({abs(self.ease) / self.perimeter:.1%}"
                "): the envelope is too curved there for a flat patch this size; work the "
                "ease in between the match marks or make it smaller"
            ]
        return []


def _gore_label(g: float, gores: int) -> int:
    return int(math.floor(g)) % gores + 1


def overlay_layout(spec: OverlaySpec, surface: EnvelopeSurface) -> OverlayLayout:
    """Lay an overlay on the envelope (module docstring).

    Parameters
    ----------
    spec : OverlaySpec
        The overlay.
    surface : EnvelopeSurface
        The envelope (:func:`envelopelab.project.shapes.envelope_surface`), m.

    Returns
    -------
    OverlayLayout

    Raises
    ------
    ValueError
        When the outline crosses itself, runs past the mouth or the crown, or spans the
        whole circumference.
    """
    n = surface.gore_count
    length = float(surface.profile.meridian_length)
    outline = densify(outline_points(spec))
    pl = spec.placement
    s = pl.tape_position + outline[:, 1]
    if s.min() <= 0.0 or s.max() >= length:
        raise ValueError(
            f"overlay {spec.name}: it runs past the {'mouth' if s.min() <= 0 else 'crown'}; "
            "move it or make it smaller"
        )
    g0 = pl.gore - 0.5 + pl.across
    g = g0 + outline[:, 0] / (2.0 * cloth_half_width(surface, s))
    if g.max() - g.min() >= n:
        raise ValueError(f"overlay {spec.name}: it is wider than the whole envelope")
    gs = np.column_stack([g, s])
    bounds = np.array([r.s_bottom for r in surface.rows[1:]])
    labels = [r.label for r in surface.rows]

    # Split every segment where it crosses a gore seam (integer g) or a row seam.
    pts_plan, pts_gs = [outline[0]], [gs[0]]
    cuts: list[int] = []  # indices into the point list where a seam is crossed
    m = len(outline)
    for i in range(m):
        a, b = gs[i], gs[(i + 1) % m]
        pa, pb = outline[i], outline[(i + 1) % m]
        # Half-open: a point exactly on a seam belongs to the panel above or after it, so
        # an outline vertex on a seam still splits the outline there.
        ts = []
        lo, hi = sorted((a[0], b[0]))
        for k in range(math.floor(lo), math.floor(hi) + 1):
            if (a[0] >= k) != (b[0] >= k):
                ts.append((k - a[0]) / (b[0] - a[0]))
        for sb in bounds:
            if (a[1] >= sb) != (b[1] >= sb):
                ts.append((sb - a[1]) / (b[1] - a[1]))
        for t in sorted(ts):
            pts_plan.append(pa + t * (pb - pa))
            pts_gs.append(a + t * (b - a))
            cuts.append(len(pts_plan) - 1)
        if i < m - 1:
            pts_plan.append(pb)
            pts_gs.append(b)
    plan_all = np.asarray(pts_plan)
    gs_all = np.asarray(pts_gs)
    total = len(plan_all)

    def panel_of(i: int, j: int) -> tuple[int, int]:
        mid = 0.5 * (gs_all[i % total] + gs_all[j % total])
        row = int(np.searchsorted(bounds, mid[1], side="right"))
        return int(math.floor(mid[0])), row

    layout = OverlayLayout(spec, outline, gs)
    layout.perimeter = float(np.sum(np.linalg.norm(np.roll(outline, -1, axis=0) - outline, axis=1)))
    if not cuts:
        k, row = panel_of(0, 1)
        sequences = [list(range(total)) + [0]]
        starts = [(k, row)]
    else:
        sequences = []
        starts = []
        for c, start in enumerate(cuts):
            end = cuts[(c + 1) % len(cuts)]
            idx = (
                list(range(start, end + 1))
                if end > start
                else [
                    *range(start, total),
                    *range(0, end + 1),
                ]
            )
            sequences.append(idx)
            starts.append(panel_of(idx[0], idx[1]))
    for idx, (k, row) in zip(sequences, starts, strict=True):
        run_gs = gs_all[idx]
        f = run_gs[:, 0] - k
        xy = panel_xy(surface, row, f, run_gs[:, 1])
        layout.runs.append(OverlayRun(k % n + 1, labels[row], plan_all[idx], xy, run_gs))
    layout.marked = float(
        sum(np.sum(np.linalg.norm(np.diff(r.panel, axis=0), axis=1)) for r in layout.runs)
    )
    for c, at in enumerate(cuts):
        before = layout.runs[c - 1]
        after = layout.runs[c]
        layout.crossings.append((plan_all[at], before.gore, before.row, after.gore, after.row))
    # Panels covered: every panel a run lies in, and those inside the outline.
    covered = {(r.gore, r.row) for r in layout.runs}
    for k in range(math.floor(g.min()), math.ceil(g.max())):
        for i, band in enumerate(surface.rows):
            centre = np.array([k + 0.5, 0.5 * (band.s_bottom + band.s_top)])
            if _inside(gs, centre):
                covered.add((k % n + 1, labels[i]))
    layout.covered = sorted(covered, key=lambda p: (labels.index(p[1]), p[0]))
    return layout


def _inside(poly: FloatArray, point: FloatArray) -> bool:
    """Point-in-polygon (even-odd rule)."""
    x, y = float(point[0]), float(point[1])
    px, py = poly[:, 0], poly[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    hit = ((py > y) != (qy > y)) & (
        x < (qx - px) * (y - py) / np.where(qy == py, 1e-30, qy - py) + px
    )
    return bool(np.count_nonzero(hit) % 2)


def clip_strip(poly: FloatArray, lo: float, hi: float) -> FloatArray:
    """The part of a closed polygon with ``lo <= x <= hi`` (Sutherland-Hodgman)."""
    out = np.asarray(poly, dtype=np.float64)
    for edge, keep in ((lo, 1.0), (hi, -1.0)):
        if not len(out):
            break
        nxt = []
        for a, b in zip(out, np.roll(out, -1, axis=0), strict=True):
            a_in, b_in = keep * (a[0] - edge) >= 0.0, keep * (b[0] - edge) >= 0.0
            if a_in:
                nxt.append(a)
            if a_in != b_in:
                t = (edge - a[0]) / (b[0] - a[0])
                nxt.append(a + t * (b - a))
        out = np.asarray(nxt, dtype=np.float64).reshape(-1, 2)
    return out


def gore_pieces(layout: OverlayLayout, gores: int) -> list[tuple[int, FloatArray]]:
    """The overlay's area split by gore: (gore from 1, polygon as gore and tape
    positions with the gore position taken within ``[gore - 1, gore]``)."""
    g = layout.gs[:, 0]
    out = []
    for k in range(math.floor(g.min()), math.ceil(g.max())):
        part = clip_strip(layout.gs, float(k), float(k + 1))
        if len(part) >= 3:
            label = k % gores + 1
            out.append((label, part - np.array([k - (label - 1), 0.0])))
    return out


def map_polygons(layout: OverlayLayout, m: GoreMap) -> list[tuple[int, FloatArray]]:
    """The overlay's area on the gore map (:mod:`envelopelab.project.placement_map`), one
    closed polygon per gore it covers: (gore from 1, polygon in map metres, last point
    repeated). A point at gore position :math:`g` in gore :math:`k` and tape position
    :math:`s` is drawn at :math:`x = (k - \tfrac12) W + 2 (g - k + \tfrac12) w(s)`."""
    out = []
    for gore, part in gore_pieces(layout, m.gores):
        half = np.asarray(m.half_width(part[:, 1]), dtype=np.float64)
        x = (gore - 0.5) * m.column + 2.0 * (part[:, 0] - (gore - 1) - 0.5) * half
        poly = np.column_stack([x, part[:, 1]])
        out.append((gore, np.vstack([poly, poly[:1]])))
    return out


def overlay_mesh(
    layout: OverlayLayout,
    surface: EnvelopeSurface,
    points_at: Callable[[FloatArray, FloatArray], FloatArray],
    grid: float = 0.05,
) -> tuple[FloatArray, np.ndarray]:
    """A triangle mesh of the overlay for drawing (m).

    The cloth outline and its interior sampled every ``grid`` m (at least 1/40 of its
    size) are triangulated (Delaunay), the triangles outside the outline dropped, and
    every point mapped to the envelope (module docstring) and then to 3D by
    ``points_at(g, s)`` (gore positions and tape positions, m, to points (n, 3), m).
    """
    from scipy.spatial import Delaunay

    outline = layout.outline
    lo, hi = outline.min(axis=0), outline.max(axis=0)
    step = max(grid, float(max(hi - lo)) / 40.0)
    xx, yy = np.meshgrid(
        np.arange(lo[0] + step / 2, hi[0], step), np.arange(lo[1] + step / 2, hi[1], step)
    )
    inner = np.column_stack([xx.ravel(), yy.ravel()])
    inner = inner[[_inside(outline, p) for p in inner]] if len(inner) else inner
    plan = np.vstack([outline, inner.reshape(-1, 2)])
    tri = Delaunay(plan).simplices
    keep = np.array([_inside(outline, c) for c in plan[tri].mean(axis=1)], dtype=bool)
    pl = layout.spec.placement
    s = pl.tape_position + plan[:, 1]
    g = pl.gore - 0.5 + pl.across + plan[:, 0] / (2.0 * cloth_half_width(surface, s))
    points = np.asarray(points_at(g, s), dtype=np.float64)
    return points, np.asarray(tri[keep], dtype=np.int64)


def overlay_findings(
    overlays: Sequence[OverlaySpec], surface: EnvelopeSurface
) -> list[DesignFinding]:
    """Validation findings of the overlays: an error for one that cannot be laid on the
    envelope, a warning for one too large for the local curvature
    (:meth:`OverlayLayout.warnings`). Target ``shape:<name>`` (selects it)."""
    from envelopelab.project.gore_design import DesignFinding

    out = []
    for spec in overlays:
        try:
            layout = overlay_layout(spec, surface)
        except ValueError as exc:
            out.append(DesignFinding("overlay", "error", str(exc), f"shape:{spec.name}"))
            continue
        out += [
            DesignFinding("overlay_fit", "warning", text, f"shape:{spec.name}")
            for text in layout.warnings()
        ]
    return out


def overlay_names(overlays: Sequence[OverlaySpec]) -> list[str]:
    """Names of the overlays."""
    return [o.name for o in overlays]


def default_overlay(name: str, gore: int, tape_position: float) -> OverlaySpec:
    """A 1 m circle centred on gore ``gore`` at ``tape_position`` m."""
    return OverlaySpec(name=name, placement=ShapePlacement(gore=gore, tape_position=tape_position))


__all__ = [
    "DEFAULT_HEM",
    "EASE_WARNING",
    "OUTLINE_KINDS",
    "OVERLAY_PIECE",
    "OutlineKind",
    "OverlayLayout",
    "OverlayRun",
    "OverlaySpec",
    "clip_strip",
    "cloth_half_width",
    "default_overlay",
    "densify",
    "gore_pieces",
    "map_polygons",
    "outline_points",
    "overlay_findings",
    "overlay_layout",
    "overlay_mesh",
    "overlay_names",
    "panel_xy",
]
