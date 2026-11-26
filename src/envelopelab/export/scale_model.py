r"""Scale-model build packs: every pattern piece at 1:n, each on one sheet of paper.

A scale model is cut from the same flat patterns as the full-size envelope with every
length multiplied by the scale factor :math:`k = 1/n`:

.. math:: \mathbf{x}_\text{model} = k\,\mathbf{x}_\text{full}, \qquad
          L_\text{model} = k L, \quad A_\text{model} = k^2 A, \quad V_\text{model} = k^3 V

so the sewn model is geometrically similar to the design (ADR-0062). Finished outlines,
edges, match marks, footprint lines, feed holes and planned seam ease all scale by
:math:`k`. The seam allowance either scales with the piece (an exact 1:n copy of the cut
outline) or is set to a fixed width at model size (:attr:`ScaleModel.seam_allowance`),
because a 25 mm allowance at 1:20 is a 1.25 mm strip nobody can glue or sew.

Fitting the paper
-----------------
Each piece is printed whole on one sheet of the chosen paper (US Letter 8.5 x 11 in by
default), inside a printer margin on every side. A piece fits when its cut outline,
turned by some angle :math:`\theta`, has a bounding box :math:`a(\theta) \times
b(\theta)` with :math:`a \le W, b \le H` or :math:`a \le H, b \le W` (portrait or
landscape), :math:`W \times H` the printable area. The turns tried are upright, a quarter
turn, every hull-edge direction of the outline (where the minimum-area bounding
rectangle lies [Freeman]_) and every whole degree. :func:`fit_scale` finds the largest
:math:`k` at which every piece fits (bisection: the fit is monotone in :math:`k`) and
returns the scale denominator :math:`n = 1/k`, rounded up to a whole number by default,
so ``1:n`` is the largest model whose pieces all fit.

Assumptions and valid range: geometric similarity only. A model in paper, tissue or thin
film is **not** dynamically or structurally similar to the full-size envelope: lift
scales with :math:`k^3` while skin mass scales with :math:`k^2` (times the model
material's areal mass), and stresses and wrinkling do not scale. A model shows the
shape of the patterns as built; it is not evidence of the full-size envelope's strength
or airworthiness.

References
----------
.. [Freeman] H. Freeman and R. Shapira, "Determining the minimum-area encasing rectangle
   for an arbitrary closed curve", Comm. ACM 18(7), 409-413 (1975).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from envelopelab.export.build_pack import BuildPackError, SeamPair, Sheet
from envelopelab.export.templates import turn_points
from envelopelab.geometry.polygon import offset_polygon
from envelopelab.solvers.membrane import FloatArray

INCH = 0.0254  # m (exact, by definition)


@dataclass(frozen=True)
class PaperSize:
    """A sheet of paper, portrait.

    Attributes
    ----------
    name : str
        Display name (e.g. "US Letter (8.5 x 11 in)").
    width : float
        Short side, m.
    height : float
        Long side, m.
    """

    name: str
    width: float
    height: float

    def __post_init__(self) -> None:
        if not 0.0 < self.width <= self.height:
            raise BuildPackError("paper width must be positive and no longer than its height")


#: Standard paper sizes (ANSI/ASME Y14.1 and ISO 216; exact by definition).
PAPER_SIZES: dict[str, PaperSize] = {
    "letter": PaperSize("US Letter (8.5 x 11 in)", 8.5 * INCH, 11.0 * INCH),
    "legal": PaperSize("US Legal (8.5 x 14 in)", 8.5 * INCH, 14.0 * INCH),
    "tabloid": PaperSize("Tabloid (11 x 17 in)", 11.0 * INCH, 17.0 * INCH),
    "a4": PaperSize("A4 (210 x 297 mm)", 0.210, 0.297),
    "a3": PaperSize("A3 (297 x 420 mm)", 0.297, 0.420),
}

#: Printer margin left blank on every side, m (0.5 in; home printers need about 0.25 in;
#: source: assumed).
DEFAULT_PAPER_MARGIN = 0.5 * INCH

#: Turns tried on every piece besides its hull-edge directions, deg.
_GRID_TURNS = np.arange(0.0, 180.0, 1.0)


@dataclass(frozen=True)
class ScaleModel:
    """How a scale-model pack is made.

    Attributes
    ----------
    denominator : float
        Scale denominator :math:`n` of 1:n (> 0; 1 is full size), dimensionless.
    paper : PaperSize
        Paper every piece is printed on, one piece per sheet.
    margin : float
        Blank border on every side of the sheet, m (>= 0).
    seam_allowance : float or None
        Seam (or glue-tab) allowance round every cut piece at model size, m; None scales
        the design's allowance with the piece (an exact 1:n copy of the cut outline).
    """

    denominator: float
    paper: PaperSize = PAPER_SIZES["letter"]
    margin: float = DEFAULT_PAPER_MARGIN
    seam_allowance: float | None = None

    def __post_init__(self) -> None:
        if not (self.denominator > 0.0 and math.isfinite(self.denominator)):
            raise BuildPackError("the scale denominator must be a positive number")
        if self.margin < 0.0 or 2.0 * self.margin >= self.paper.width:
            raise BuildPackError("the paper margin must leave room on the sheet")
        if self.seam_allowance is not None and self.seam_allowance < 0.0:
            raise BuildPackError("the model seam allowance must not be negative")

    @property
    def factor(self) -> float:
        """Scale factor :math:`k = 1/n`, dimensionless."""
        return 1.0 / self.denominator

    @property
    def printable(self) -> tuple[float, float]:
        """Printable width and height of the portrait sheet, m."""
        return (self.paper.width - 2.0 * self.margin, self.paper.height - 2.0 * self.margin)

    def label(self) -> str:
        """The scale as builders write it, e.g. ``1:20`` or ``1:12.5``."""
        return f"1:{self.denominator:g}"


def scale_sheet(sheet: Sheet, factor: float, seam_allowance: float | None = None) -> Sheet:
    """A copy of ``sheet`` with every length multiplied by ``factor``.

    Parameters
    ----------
    sheet : Sheet
        Sheet in m.
    factor : float
        Scale factor :math:`k` (> 0), dimensionless.
    seam_allowance : float, optional
        Allowance of the scaled cut outline, m: the finished outline offset outward by it
        (:func:`envelopelab.geometry.polygon.offset_polygon`). None scales the cut
        outline with the rest.

    Returns
    -------
    Sheet
        The scaled sheet (names, piece, kind, cut count, fabric and colours unchanged).
    """
    if not factor > 0.0:
        raise BuildPackError("the scale factor must be positive")
    k = float(factor)

    def pts(a: FloatArray) -> FloatArray:
        out: FloatArray = np.asarray(a, dtype=np.float64) * k
        return out

    finished = pts(sheet.finished)
    cut = model_cut(sheet, k, seam_allowance)
    return replace(
        sheet,
        finished=finished,
        cut=cut,
        edges={name: pts(e) for name, e in sheet.edges.items()},
        marks=[(x * k, y * k, t) for x, y, t in sheet.marks],
        lines=[pts(ln) for ln in sheet.lines],
        holes=[(x * k, y * k, r * k) for x, y, r in sheet.holes],
        hole_cuts=[(x * k, y * k, r * k) for x, y, r in sheet.hole_cuts],
        ticks=[pts(t) for t in sheet.ticks],
        texts=[(x * k, y * k, t) for x, y, t in sheet.texts],
        notes=list(sheet.notes),
        whole=None if sheet.whole is None else scale_sheet(sheet.whole, factor, seam_allowance),
        colours=[(c, list(w)) for c, w in sheet.colours],
    )


def scale_seam_pair(pair: SeamPair, factor: float) -> SeamPair:
    """``pair`` with its planned ease (m) multiplied by ``factor`` (dimensionless)."""
    return SeamPair(pair.a, pair.b, pair.ease * factor)


def scale_pack(
    sheets: Sequence[Sheet], pairs: Sequence[SeamPair], model: ScaleModel
) -> tuple[list[Sheet], list[SeamPair]]:
    """Every sheet and seam pair of a pack at the model's scale, each sheet noting the
    scale (``SCALE MODEL 1:n``) under its header."""
    k = model.factor
    out = []
    for sheet in sheets:
        scaled = scale_sheet(sheet, k, model.seam_allowance)
        scaled.notes = [f"SCALE MODEL {model.label()} - not a full-size pattern", *scaled.notes]
        out.append(scaled)
    return out, [scale_seam_pair(p, k) for p in pairs]


@dataclass(frozen=True)
class PaperFit:
    """How a piece lies on its sheet of paper.

    Attributes
    ----------
    angle : float
        Turn of the piece on the sheet, deg counter-clockwise.
    landscape : bool
        True when the sheet is turned landscape.
    width, height : float
        The turned cut outline's bounding box, m (across and up the sheet as printed).
    fits : bool
        True when that box lies inside the printable area.
    """

    angle: float
    landscape: bool
    width: float
    height: float
    fits: bool


def _turns(hull: FloatArray) -> FloatArray:
    """Turns to try (deg): upright, a quarter turn, each hull edge laid along the x axis,
    and every whole degree."""
    edges = np.roll(hull, -1, axis=0) - hull
    along = np.mod(-np.degrees(np.arctan2(edges[:, 1], edges[:, 0])), 180.0)
    return np.concatenate([[0.0, 90.0], np.round(along, 6), _GRID_TURNS])


def _hull(points: FloatArray) -> FloatArray:
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return pts
    from scipy.spatial import ConvexHull, QhullError

    try:
        out: FloatArray = pts[ConvexHull(pts).vertices]
    except QhullError:  # collinear outline: its points are its own hull
        return pts
    return out


def _spans(hull: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Turns tried (deg) and the turned hull's bounding-box width and height at each
    (m)."""
    turns = _turns(hull)
    a = np.radians(turns)
    c, s = np.cos(a)[:, None], np.sin(a)[:, None]
    w = np.ptp(c * hull[:, 0] - s * hull[:, 1], axis=1)
    h = np.ptp(s * hull[:, 0] + c * hull[:, 1], axis=1)
    return turns, w, h


def _rooms(
    w: FloatArray, h: FloatArray, printable: tuple[float, float]
) -> tuple[FloatArray, FloatArray]:
    """How many times each turned box would fit, portrait and landscape: the smaller of
    the printable-to-used ratios across and up the sheet (dimensionless)."""
    pw, ph = printable
    tiny = 1e-12
    w = np.maximum(w, tiny)
    h = np.maximum(h, tiny)
    return np.minimum(pw / w, ph / h), np.minimum(ph / w, pw / h)


def paper_fit(cut: FloatArray, printable: tuple[float, float]) -> PaperFit:
    """The turn and sheet orientation that fit cut outline ``cut`` (m) in the printable
    area ``printable`` (portrait width, height; m).

    Upright and a quarter turn, portrait then landscape, are taken first when they fit;
    otherwise the turn with the most room (the largest ratio of printable to used size,
    the smaller of the two directions). When none fits, the fit with the most room is
    returned with ``fits`` False.
    """
    pw, ph = printable
    hull = _hull(cut)
    for angle in (0.0, 90.0):
        w, h = np.ptp(turn_points(hull, angle), axis=0)
        for landscape in (False, True):
            aw, ah = (ph, pw) if landscape else (pw, ph)
            if w <= aw and h <= ah:
                return PaperFit(angle, landscape, float(w), float(h), True)
    turns, ws, hs = _spans(hull)
    room_p, room_l = _rooms(ws, hs, printable)
    best_p, best_l = int(np.argmax(room_p)), int(np.argmax(room_l))
    if room_p[best_p] >= room_l[best_l]:
        i, landscape, room = best_p, False, float(room_p[best_p])
    else:
        i, landscape, room = best_l, True, float(room_l[best_l])
    return PaperFit(float(turns[i]), landscape, float(ws[i]), float(hs[i]), room >= 1.0)


def _largest_factor(points: FloatArray, printable: tuple[float, float]) -> float:
    """The largest factor by which outline ``points`` (m) can be scaled and still fit
    the printable area at one of the turns tried (dimensionless): the bounding box of
    the scaled outline is the scaled box, so it is the most room of any turn."""
    _turns_, w, h = _spans(_hull(points))
    room_p, room_l = _rooms(w, h, printable)
    return float(max(room_p.max(), room_l.max()))


def model_cut(sheet: Sheet, factor: float, seam_allowance: float | None = None) -> FloatArray:
    """The cut outline of ``sheet`` scaled by ``factor`` (m), as :func:`scale_sheet`
    draws it, without scaling the rest of the sheet."""
    if seam_allowance is None:
        out: FloatArray = np.asarray(sheet.cut, dtype=np.float64) * factor
        return out
    finished = np.asarray(sheet.finished, dtype=np.float64) * factor
    return finished if seam_allowance == 0.0 else offset_polygon(finished, seam_allowance)


def piece_scale_limit(sheet: Sheet, model: ScaleModel) -> float:
    r"""The largest scale factor :math:`k` (dimensionless) at which ``sheet`` (full size,
    m) fits on the model's paper.

    With the allowance scaled (``model.seam_allowance`` None) the whole cut outline
    scales, so :math:`k` is the most room of any turn (:func:`paper_fit`), exactly.

    With a fixed allowance :math:`a` the cut outline is the scaled finished outline
    offset by :math:`a`, whose bounding box at turn :math:`\theta` is the scaled box
    grown by :math:`a` on every side (exact for a rounded offset):

    .. math:: k = \max_\theta \min\left(\frac{W - 2a}{w(\theta)},
              \frac{H - 2a}{h(\theta)}\right)

    (and the same landscape). The mitred corners of the drawn offset reach a little
    further, so the exact cut outline is then measured and :math:`k` multiplied by its
    room until it fits: the result always fits, and is the largest to within the mitres.
    """
    printable = model.printable
    a = model.seam_allowance
    if a is None:
        return _largest_factor(np.asarray(sheet.cut, dtype=np.float64), printable)
    if 2.0 * a >= min(printable):
        raise BuildPackError("the model seam allowance alone is wider than the printable area")
    finished = np.asarray(sheet.finished, dtype=np.float64)
    k = _largest_factor(finished, (printable[0] - 2.0 * a, printable[1] - 2.0 * a))
    for _ in range(100):
        room = _largest_factor(model_cut(sheet, k, a), printable)
        if room >= 1.0:
            return k
        # The allowance does not shrink with k, so this step undershoots the fit a
        # little; it converges geometrically.
        k *= room * (1.0 - 1e-9)
    raise BuildPackError(f"no scale found at which {sheet.name} fits the paper")


def fit_scale(
    sheets: Sequence[Sheet],
    model: ScaleModel,
    whole: bool = True,
) -> float:
    """The scale denominator :math:`n` (dimensionless) of the largest 1:n model whose
    every piece fits on the model's paper.

    Parameters
    ----------
    sheets : sequence of Sheet
        Full-size sheets, m.
    model : ScaleModel
        Paper, margin and seam allowance (its own denominator is ignored).
    whole : bool
        Round :math:`n` up to a whole number (``1:20``, not ``1:19.37``).

    Returns
    -------
    float
        :math:`n = 1 / \\min_i k_i`, :math:`k_i` the largest factor at which piece
        :math:`i` fits (:func:`piece_scale_limit`).
    """
    if not sheets:
        raise BuildPackError("no sheets to fit")
    k = min(piece_scale_limit(s, model) for s in sheets)
    if not k > 0.0:
        raise BuildPackError("a piece cannot fit on the paper at any scale")
    n = 1.0 / k
    if whole:
        # Within the bisection's tolerance of a whole number counts as that number.
        n = float(math.ceil(n - 1e-5 * n))
        while not all(
            paper_fit(model_cut(s, 1.0 / n, model.seam_allowance), model.printable).fits
            for s in sheets
        ):
            n += 1.0
    return n


def oversize_pieces(sheets: Sequence[Sheet], model: ScaleModel) -> list[str]:
    """Names of the full-size ``sheets`` whose piece does not fit the paper at the
    model's scale."""
    return [
        s.name
        for s in sheets
        if not paper_fit(model_cut(s, model.factor, model.seam_allowance), model.printable).fits
    ]
