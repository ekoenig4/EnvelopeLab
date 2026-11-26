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

A model pack is made from the scaled inputs (ADR-0063, :func:`scale_inputs`): the design
(:func:`scale_design`), row annotations, overlays and special shapes (each designed again
on the scaled envelope, :func:`scale_primitive_design`), so every sheet and document is
made at model size by the same code as the full-size pack. Values that do not scale
geometrically are printed :data:`NOT_APPLICABLE`; the lift charts are left out.

Fitting the paper
-----------------
Each piece is printed whole on one sheet of the chosen paper (US Letter 8.5 x 11 in by
default, or a custom size, or only a maximum width: :class:`PaperSize`), inside a
printer margin on every side. A piece fits when its cut outline,
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
from typing import TYPE_CHECKING, Any

import numpy as np

from envelopelab.export.build_pack import BuildPackError, Sheet
from envelopelab.export.templates import turn_points
from envelopelab.geometry.polygon import offset_polygon
from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.features.primitives import EnvelopeSurface, Primitive, PrimitiveDesign
    from envelopelab.project.model import PatternSet
    from envelopelab.project.overlays import OverlaySpec

INCH = 0.0254  # m (exact, by definition)


@dataclass(frozen=True)
class PaperSize:
    """The sheet (or strip) every piece of a model is printed on.

    Attributes
    ----------
    name : str
        Display name (e.g. "US Letter (8.5 x 11 in)").
    width : float
        Width across the printer, m.
    height : float or None
        Height, m; None: any length (a roll or a strip of paper only ``width`` wide,
        each page as long as its piece).
    """

    name: str
    width: float
    height: float | None

    def __post_init__(self) -> None:
        if not (self.width > 0.0 and math.isfinite(self.width)):
            raise BuildPackError("the print width must be a positive length")
        if self.height is not None and not (self.height > 0.0 and math.isfinite(self.height)):
            raise BuildPackError("the print height must be a positive length")

    @property
    def unbounded(self) -> bool:
        """True when only the width is set (any length)."""
        return self.height is None

    @classmethod
    def custom(cls, width: float, height: float | None = None) -> PaperSize:
        """A print size set by the builder: ``width`` by ``height`` m, or only a maximum
        ``width`` (m) when ``height`` is None."""
        if height is None:
            return cls(f"max width {width * 1000:.0f} mm, any length", width, None)
        return cls(f"custom {width * 1000:.0f} x {height * 1000:.0f} mm", width, height)


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
        short = min(self.paper.width, self.paper.height or math.inf)
        if self.margin < 0.0 or 2.0 * self.margin >= short:
            raise BuildPackError("the paper margin must leave room on the sheet")
        if self.seam_allowance is not None and self.seam_allowance < 0.0:
            raise BuildPackError("the model seam allowance must not be negative")

    @property
    def factor(self) -> float:
        """Scale factor :math:`k = 1/n`, dimensionless."""
        return 1.0 / self.denominator

    @property
    def printable(self) -> tuple[float, float]:
        """Printable width and height of the sheet as given, m (height ``inf`` when only
        the width is set)."""
        h = self.paper.height
        return (
            self.paper.width - 2.0 * self.margin,
            math.inf if h is None else h - 2.0 * self.margin,
        )

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
    portrait = np.minimum(pw / w, ph / h)
    if not math.isfinite(ph):  # a strip of one width: the width runs across it
        return portrait, np.zeros_like(portrait)
    return portrait, np.minimum(ph / w, pw / h)


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
        for landscape in (False,) if not math.isfinite(ph) else (False, True):
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


# --------------------------------------------------------------------------------------
# Scaling the design: every length of the inputs times k, so every sheet and document of
# the pack is made at model size by the same code as the full-size pack.
# --------------------------------------------------------------------------------------

#: Printed wherever a document would give a value that does not scale geometrically
#: (weights, loads, strengths, factors of safety, lift, flow; ADR-0063).
NOT_APPLICABLE = "n/a (scale model)"


def _allowance(model: ScaleModel, full: float) -> float:
    """A seam allowance (m) at model size: the model's fixed one, else ``full`` scaled."""
    return model.seam_allowance if model.seam_allowance is not None else full * model.factor


def model_name(name: str, model: ScaleModel) -> str:
    """The name of a design's scale model, e.g. ``generic model 1-20`` (a file-name safe
    form of 1:20)."""
    return f"{name} model 1-{model.denominator:g}"


def scale_design(design: DesignDocument, model: ScaleModel) -> DesignDocument:
    """A standard-gore design with every length multiplied by the model's factor :math:`k`
    (m): the meridian, rows and seam bows, openings, tapes' widths, seam allowances (or
    the model's fixed allowance), rigging and parachute lengths, the scoop and the
    turning vents' openings. Dimensionless values (lofts, tapers, bulges, angles, counts)
    are kept; physical values that do not scale geometrically (strengths, masses,
    operating conditions, load factors) are kept as they are and must not be shown for
    the model (:data:`NOT_APPLICABLE`). The design is renamed :func:`model_name`.
    """
    from envelopelab.design.model import DesignDocument

    if design.gores is None:
        raise BuildPackError("a scale model needs a standard-gore design")
    k = model.factor
    raw = design.model_dump(mode="json", by_alias=True)
    raw["meta"]["name"] = model_name(design.meta.name, model)
    g = raw["gores"]
    for p in g["meridian_profile_control_points"]:
        p["x"] *= k
        p["y"] *= k
    for row in g["panel_rows"]:
        row["finished_height"] *= k
        for key in ("bow_bottom", "bow_top"):
            if row.get(key) is not None:
                row[key] *= k
    for key in ("mouth_diameter", "crown_ring", "parachute_hole_diameter", "seal_overlap"):
        g[key] *= k
    for tape in ("vertical", "horizontal", "rim", "hole"):
        raw["tapes"][tape]["width"] *= k
    for seam in raw["seam_types"]:
        seam["allowance"] = _allowance(model, seam["allowance"])
    rig = raw["rigging"]
    if rig.get("red_line") is not None:
        rig["red_line"]["spare_length"] *= k
    if rig.get("flying_wires") is not None:
        for key in ("frame_radius", "frame_drop", "crows_foot_drop"):
            rig["flying_wires"][key] *= k
    chute = raw.get("parachute")
    if chute is not None:
        for key in ("shroud_attachment", "centralizing_depth"):
            chute[key] *= k
        for key in ("centre_ring_diameter", "centre_panel_diameter"):
            if chute.get(key) is not None:
                chute[key] *= k
    if raw.get("scoop") is not None:
        raw["scoop"]["height"] *= k
    for vent in raw["turning_vents"]:
        vent["opening_width"] *= k
    return DesignDocument.model_validate(raw)


def scale_patterns(patterns: PatternSet, model: ScaleModel) -> PatternSet:
    """Row annotations at model size: seam allowances (or the model's fixed one), tape
    paths, feature locations and manual outlines times :math:`k` (m)."""
    from envelopelab.project.model import PatternSet

    k = model.factor
    raw = patterns.model_dump(mode="json")
    for row in raw["rows"].values():
        if row.get("seam_allowance") is not None:
            row["seam_allowance"] = _allowance(model, row["seam_allowance"])
        elif model.seam_allowance is not None:
            row["seam_allowance"] = model.seam_allowance
        for path in row.get("tape_paths", []):
            path["points"] = [[x * k, y * k] for x, y in path["points"]]
        for loc in row.get("feature_locations", []):
            loc["x"] *= k
            loc["y"] *= k
            loc["radius"] *= k
        if row.get("manual_outline") is not None:
            pts = row["manual_outline"]["points"]
            row["manual_outline"]["points"] = [[x * k, y * k] for x, y in pts]
    return PatternSet.model_validate(raw)


def scale_overlay(spec: OverlaySpec, model: ScaleModel) -> OverlaySpec:
    """An overlay at model size: its position up the tape, size, polygon corners and hem
    (or the model's fixed allowance) times :math:`k` (m)."""
    k = model.factor
    placement = spec.placement.model_copy(
        update={"tape_position": spec.placement.tape_position * k}
    )
    return spec.model_copy(
        update={
            "placement": placement,
            "width": spec.width * k,
            "height": spec.height * k,
            "points": [(x * k, y * k) for x, y in spec.points],
            "hem": _allowance(model, spec.hem),
        }
    )


def scale_primitive(primitive: Primitive, factor: float) -> Primitive:
    """A special-shape primitive with every length times ``factor`` (dimensionless): its
    position up the tape, radii, heights, lengths, profile, mesh, cap radius and shift,
    seam centre and crown outline. Angles, counts and relative widths are kept."""
    from envelopelab.features.primitives import Dome, FreeformShape, Revolved, Tube
    from envelopelab.io.reference_mesh import ReferenceMesh

    k = float(factor)
    pl = primitive.placement
    changes: dict[str, Any] = {"placement": replace(pl, tape_position=pl.tape_position * k)}
    crown = getattr(primitive, "crown", None)
    if crown is not None:
        changes["crown"] = replace(
            crown,
            size=crown.size * k,
            width=crown.width * k,
            length=crown.length * k,
            points=tuple((x * k, y * k) for x, y in crown.points),
        )
    if isinstance(primitive, Dome):
        changes |= {
            "base_radius": primitive.base_radius * k,
            "height": primitive.height * k,
            "cap_radius": primitive.cap_radius * k,
            "cap_shift": primitive.cap_shift * k,
        }
    elif isinstance(primitive, Tube):
        changes |= {
            "base_radius": primitive.base_radius * k,
            "tip_radius": primitive.tip_radius * k,
            "length": primitive.length * k,
        }
    elif isinstance(primitive, Revolved):
        changes |= {
            "profile": tuple((r * k, z * k) for r, z in primitive.profile),
            "cap_radius": primitive.cap_radius * k,
            "cap_shift": primitive.cap_shift * k,
        }
    elif isinstance(primitive, FreeformShape):
        mesh = primitive.mesh
        changes |= {
            "mesh": ReferenceMesh(
                np.asarray(mesh.vertices, dtype=np.float64) * k, mesh.triangles, mesh.source
            ),
            "cap_radius": primitive.cap_radius * k,
            "seam_centre": (primitive.seam_centre[0] * k, primitive.seam_centre[1] * k),
        }
    else:  # pragma: no cover - every kind is handled above
        raise BuildPackError(f"cannot scale a {type(primitive).__name__}")
    return replace(primitive, **changes)


def scale_primitive_design(
    design: PrimitiveDesign, surface: EnvelopeSurface, model: ScaleModel
) -> PrimitiveDesign:
    """A placed special shape designed again at model size on the scaled envelope
    ``surface``: the primitive scaled (:func:`scale_primitive`) and its design inputs
    (seam allowance, feed holes, check tolerance, feed-hole clearance) scaled with it,
    the seam allowance being the model's fixed one when it has one.

    Raises
    ------
    BuildPackError
        For a preview (no design inputs recorded).
    PrimitiveError
        When the scaled shape cannot be placed (as the full-size one could).
    """
    from envelopelab.features.primitives import design_primitive

    inputs = design.inputs
    if inputs is None:
        raise BuildPackError(f"{design.primitive.name}: a preview cannot be scaled")
    k = model.factor
    return design_primitive(
        scale_primitive(design.primitive, k),
        surface,
        seam_allowance=_allowance(model, inputs.seam_allowance),
        feed_hole_radius=None if inputs.feed_hole_radius is None else inputs.feed_hole_radius * k,
        tolerance=inputs.tolerance * k,
        samples=inputs.samples,
        feed_holes=[(s * k, theta, r * k) for s, theta, r in inputs.feed_holes],
        seam_clearance=inputs.seam_clearance * k,
    )


@dataclass
class ModelInputs:
    """Everything a build pack is made from, at model size (:func:`scale_inputs`)."""

    design: DesignDocument
    primitives: list[PrimitiveDesign]
    patterns: PatternSet
    overlays: list[OverlaySpec]


def scale_inputs(
    design: DesignDocument,
    primitives: Sequence[PrimitiveDesign],
    patterns: PatternSet | None,
    overlays: Sequence[OverlaySpec],
    model: ScaleModel,
) -> ModelInputs:
    """The design, its placed shapes, row annotations and overlays at model size."""
    from envelopelab.features.primitives import EnvelopeSurface
    from envelopelab.project.model import PatternSet

    scaled = scale_design(design, model)
    surface = EnvelopeSurface.from_design(scaled)
    return ModelInputs(
        scaled,
        [scale_primitive_design(p, surface, model) for p in primitives],
        scale_patterns(patterns if patterns is not None else PatternSet(), model),
        [scale_overlay(o, model) for o in overlays],
    )


@dataclass(frozen=True)
class ModelSummary:
    r"""The main sizes of a scale model, from the full-size design's.

    Attributes
    ----------
    volume : float
        Envelope volume, :math:`k^3 V`, m^3.
    height : float
        Envelope height, :math:`k H`, m.
    max_diameter : float
        Widest diameter, :math:`k D`, m.
    """

    volume: float
    height: float
    max_diameter: float


def model_summary(
    volume: float, height: float, max_diameter: float, model: ScaleModel
) -> ModelSummary:
    r"""The scale model's volume (:math:`V_m = k^3 V`, m^3), height and widest diameter
    (:math:`k\,L`, m) from the full-size ``volume`` (m^3), ``height`` and
    ``max_diameter`` (m): geometric similarity (module docstring)."""
    k = model.factor
    return ModelSummary(volume * k**3, height * k, max_diameter * k)
