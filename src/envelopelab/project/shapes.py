"""Special shapes stored in a project: the data of every dome, tube, revolved and mesh shape.

A project's design state holds a list of shape specifications next to the design
document (project format version 2, ADR-0020). Each one is plain data (metres, degrees)
that :func:`to_primitive` turns into a primitive of :mod:`envelopelab.features.primitives`
and :func:`shape_design` places on the design's envelope. The specifications are part of
the undoable design state, of snapshots and versions, and of the ``shapes`` input group of
the dependency graph.
"""

from __future__ import annotations

import dataclasses
import math
from typing import TYPE_CHECKING, Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from envelopelab.project.symmetry import MirrorLink, SymmetryAxis

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.features.primitives import EnvelopeSurface, Primitive, PrimitiveDesign
    from envelopelab.project.model import PatternSet
    from envelopelab.solvers.membrane import FloatArray

__all__ = ["MirrorLink", "SymmetryAxis"]

ShapeKind = Literal["dome", "tube", "revolved", "mesh"]
SHAPE_KINDS: tuple[ShapeKind, ...] = ("dome", "tube", "revolved", "mesh")
#: A dragged base point stays this far inside the ends of the load tape, m (source:
#: assumed; a placement needs 0 < tape position < tape length).
DRAG_MARGIN = 1e-3
#: Least finished width of a panel's top where it is sewn to the cap, m (source: assumed:
#: a top edge this wide can still be sewn and taped by hand).
CAP_PANEL_TOP_WIDTH = 0.10
#: An automatic cap's diameter is at most this fraction of the shape's base diameter
#: (source: assumed; keeps the cap on the top of small shapes).
CAP_MAX_FRACTION = 0.5
#: Most horizontal splits of a shape (one tier letter each, A to Z).
MAX_SPLITS = 25


class ShapePlacement(BaseModel):
    """Where a shape sits on the envelope (see ``envelopelab.features.primitives.Placement``).

    Attributes
    ----------
    gore : int
        Gore number of the base point, from 1.
    tape_position : float
        Tape arc length of the base point from the mouth, m.
    across : float
        Fraction of the gore width from its centreline, in [-0.5, 0.5].
    lean_deg : float
        Lean of the axis from the envelope normal, deg.
    lean_toward_deg : float
        Direction of the lean, deg (0 up the tape, 90 towards the next gore).
    """

    model_config = ConfigDict(extra="forbid")

    gore: int = Field(ge=1)
    tape_position: float = Field(gt=0.0)
    across: float = Field(default=0.0, ge=-0.5, le=0.5)
    lean_deg: float = Field(default=0.0, ge=0.0, le=75.0)
    lean_toward_deg: float = 0.0


class FeedHole(BaseModel):
    """A feed hole cut in the envelope inside a shape's footprint.

    Attributes
    ----------
    gore : int
        Gore number of the hole's centre, from 1.
    tape_position : float
        Tape arc length of the centre from the mouth, m.
    across : float
        Fraction of the gore width from its centreline, in [-0.5, 0.5].
    radius : float
        Finished radius, m.
    """

    model_config = ConfigDict(extra="forbid")

    gore: int = Field(ge=1)
    tape_position: float = Field(gt=0.0)
    across: float = Field(default=0.0, ge=-0.5, le=0.5)
    radius: float = Field(gt=0.0)


class _ShapeBase(BaseModel):
    """Fields every shape has.

    Attributes
    ----------
    name : str
        Shape name (piece labels and file names start with it; unique in a project).
    placement : ShapePlacement
        Base point and lean.
    marks_per_piece : int
        Match marks per skin piece.
    feed_hole_radius : float or None
        Radius of the hole cut in the envelope under the base point to fill the shape, m
        (None: no centred hole).
    feed_holes : list of FeedHole
        More feed holes anywhere inside the footprint. A shape without any feed hole
        cannot be simulated as a fed chamber.
    seam_allowance : float
        Seam allowance round the skin pieces, m.
    fabric : str or None
        Fabric id of the skin (None: the fabric of the envelope row it sits on).
    cap_diameter : float or None
        Diameter of the cap the tops of the skin pieces are sewn round, m, where they
        would otherwise meet in a point (a dome, a revolved profile ending on the axis, a
        pointed tube, a mesh). None: automatic (:func:`cap_diameter`); 0: no cap, the
        pieces meet in a point.
    seam_offset_deg : float
        Turn of every seam round the shape's axis, deg: the first gore or panel is
        centred this far round from the direction up the tape (0), towards the next gore
        (90). Where the panels meet.
    panel_widths : list of float
        Relative width of every gore or panel round the axis, one per piece, piece 1
        first (empty: all equal). ``[2, 1, 1]`` makes piece 1 half the shape.
    splits : list of float
        Horizontal splits: where every gore or panel is cut across, as fractions of the
        profile's length from the base circle to the tip, increasing in (0, 1). The tiers
        are sewn edge to edge; their pieces are labelled ``A`` (at the rim), ``B``, ...
        Not for mesh shapes.
    crown_seam_offset_deg : float or None
        Where the seams meet the cap (or the tip) round the axis: the seam turn there, deg,
        as ``seam_offset_deg`` at the rim (None: the same as at the rim). The seams turn
        smoothly from the rim to the crown (ADR-0049). Not for mesh shapes.
    crown_panel_widths : list of float
        Relative widths of the gores or panels at the crown (empty: as at the rim).
    cap_shift : float
        Move the cap off the tip: its centre this far down the skin from the tip, m (0:
        centred). It must still cover the tip. Domes and revolved shapes with a cap.
    cap_direction_deg : float
        Direction round the axis the cap moves towards, deg (0 up the tape, 90 towards
        the next gore, as the seam turn).
    cap_across, cap_up : float
        Where the panels meet (the cap's centre), seen from above the shape, as fractions
        of its widest radius from the tip: across (towards the next gore) and up (up the
        tape), each -1 to 1 with ``cap_across² + cap_up² <= 1`` (0, 0: the tip). They move
        with the shape when it is resized (ADR-0052); use them or ``cap_shift``, not both.
    group : str or None
        Name of the object the shape belongs to (several shapes with the same group are
        moved, mirrored and exported together, :mod:`envelopelab.project.shape_groups`;
        None: on its own).
    mirror : MirrorLink or None
        For a mirror twin: the shape it mirrors and the symmetry axis it is mirrored
        across (:mod:`envelopelab.project.symmetry`); the twin is kept the mirror image
        of that shape after every edit. None: an ordinary shape.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_\- ]+$")
    placement: ShapePlacement
    marks_per_piece: int = Field(default=2, ge=1, le=8)
    feed_hole_radius: float | None = Field(default=None, gt=0.0)
    feed_holes: list[FeedHole] = Field(default_factory=list)
    seam_allowance: float = Field(default=0.0125, ge=0.0)
    fabric: str | None = None
    cap_diameter: float | None = Field(default=None, ge=0.0)
    seam_offset_deg: float = Field(default=0.0, ge=-180.0, le=180.0)
    panel_widths: list[float] = Field(default_factory=list)
    splits: list[float] = Field(default_factory=list, max_length=MAX_SPLITS)
    crown_seam_offset_deg: float | None = Field(default=None, ge=-180.0, le=180.0)
    crown_panel_widths: list[float] = Field(default_factory=list)
    cap_shift: float = Field(default=0.0, ge=0.0)
    cap_direction_deg: float = Field(default=0.0, ge=-180.0, le=180.0)
    cap_across: float = Field(default=0.0, ge=-1.0, le=1.0)
    cap_up: float = Field(default=0.0, ge=-1.0, le=1.0)
    group: str | None = Field(
        default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_\- ]+$"
    )
    mirror: MirrorLink | None = None

    @model_validator(mode="after")
    def _layout(self) -> _ShapeBase:
        count = piece_count(self)  # type: ignore[arg-type]
        if self.panel_widths and len(self.panel_widths) != count:
            raise ValueError(
                f"panel_widths: {len(self.panel_widths)} widths for {count} gores or panels"
            )
        if any(not w > 0.0 for w in self.panel_widths):
            raise ValueError("panel_widths: every width must be positive")
        if any(not 0.0 < f < 1.0 for f in self.splits) or any(
            b <= a for a, b in zip(self.splits, self.splits[1:], strict=False)
        ):
            raise ValueError("splits: fractions must increase within (0, 1)")
        if self.splits and getattr(self, "kind", None) == "mesh":
            raise ValueError("splits: a mesh shape's panels cannot be split across")
        if self.crown_panel_widths and len(self.crown_panel_widths) != count:
            raise ValueError(
                f"crown_panel_widths: {len(self.crown_panel_widths)} widths for {count} gores "
                "or panels"
            )
        if any(not w > 0.0 for w in self.crown_panel_widths):
            raise ValueError("crown_panel_widths: every width must be positive")
        if getattr(self, "kind", None) == "mesh" and (
            self.crown_seam_offset_deg is not None or self.crown_panel_widths or self.cap_shift
        ):
            raise ValueError("a mesh shape's seams and cap cannot be moved at the crown")
        if self.cap_shift and getattr(self, "kind", None) == "tube":
            raise ValueError("cap_shift: a tube's tip disc cannot be moved off its axis")
        relative = bool(self.cap_across or self.cap_up)
        if relative:
            if getattr(self, "kind", None) in ("tube", "mesh"):
                raise ValueError("cap_across, cap_up: only a dome's or revolved shape's cap moves")
            if self.cap_shift:
                raise ValueError(
                    "cap_across, cap_up: set where the panels meet either as fractions or "
                    "with cap_shift, not both"
                )
            if math.hypot(self.cap_across, self.cap_up) > 1.0 + 1e-9:
                raise ValueError(
                    "cap_across, cap_up: the meeting point must lie inside the shape seen "
                    "from above (across² + up² at most 1)"
                )
        return self


class DomeShape(_ShapeBase):
    """Half-spheroid dome: base radius and height, m; number of skin gores."""

    kind: Literal["dome"] = "dome"
    base_radius: float = Field(gt=0.0)
    height: float = Field(gt=0.0)
    gores: int = Field(default=16, ge=3, le=64)


class TubeShape(_ShapeBase):
    """Straight frustum with a flat tip disc: radii and length, m; number of panels."""

    kind: Literal["tube"] = "tube"
    base_radius: float = Field(gt=0.0)
    tip_radius: float = Field(ge=0.0)
    length: float = Field(gt=0.0)
    panels: int = Field(default=4, ge=1, le=64)


class RevolvedShape(_ShapeBase):
    """Profile ``(rho, zeta)`` points (m) revolved about the axis; number of skin gores."""

    kind: Literal["revolved"] = "revolved"
    profile: list[tuple[float, float]] = Field(min_length=2)
    gores: int = Field(default=12, ge=3, le=64)
    smooth: bool = True


class MeshShape(_ShapeBase):
    """Closed triangle mesh (m, z out of the envelope) cut into panels.

    The vertices and triangles are stored in the project, so it does not depend on the
    file they came from (``source`` only records its name).
    """

    kind: Literal["mesh"] = "mesh"
    vertices: list[tuple[float, float, float]] = Field(min_length=4)
    triangles: list[tuple[int, int, int]] = Field(min_length=4)
    source: str = ""
    panels: int = Field(default=12, ge=2, le=64)


ShapeSpec = Annotated[
    DomeShape | TubeShape | RevolvedShape | MeshShape, Field(discriminator="kind")
]


def _meeting_point(spec: ShapeSpec, prim: Any) -> Primitive:
    """``prim`` with its cap moved where ``spec``'s relative meeting point says
    (``cap_across``, ``cap_up``; :func:`~envelopelab.features.primitives.
    meeting_point_shift` on the pointed meridian); unchanged without one."""
    from envelopelab.features.primitives import meeting_point_shift

    if not (spec.cap_across or spec.cap_up):
        out: Primitive = prim
        return out
    rho, zeta = dataclasses.replace(prim, cap_radius=0.0).meridian()
    shift, direction = meeting_point_shift(rho, zeta, spec.cap_across, spec.cap_up)
    moved: Primitive = dataclasses.replace(prim, cap_shift=shift, cap_direction=direction)
    return moved


def meeting_point(spec: ShapeSpec) -> tuple[float, float]:
    """Where ``spec``'s panels meet, seen from above, as plan fractions (across, up) of
    its widest radius (ADR-0052): the relative values when set, else converted from
    ``cap_shift``/``cap_direction_deg`` (0, 0 for a tube or mesh shape)."""
    from envelopelab.features.primitives import meeting_point_plan

    if spec.cap_across or spec.cap_up:
        return float(spec.cap_across), float(spec.cap_up)
    if not spec.cap_shift or not isinstance(spec, DomeShape | RevolvedShape):
        return 0.0, 0.0
    prim: Any = to_primitive(spec)
    rho, zeta = dataclasses.replace(prim, cap_radius=0.0).meridian()
    return meeting_point_plan(rho, zeta, spec.cap_shift, math.radians(spec.cap_direction_deg))


def to_primitive(spec: ShapeSpec) -> Primitive:
    """The primitive of :mod:`envelopelab.features.primitives` a specification describes."""
    from envelopelab.features.primitives import (
        Dome,
        FreeformShape,
        Placement,
        Revolved,
        Tube,
    )
    from envelopelab.io.reference_mesh import ReferenceMesh

    pl = spec.placement
    placement = Placement(pl.gore, pl.tape_position, pl.across, pl.lean_deg, pl.lean_toward_deg)
    marks = spec.marks_per_piece
    rc = 0.5 * cap_diameter(spec)
    layout = {
        "seam_offset": math.radians(spec.seam_offset_deg),
        "panel_widths": tuple(float(w) for w in spec.panel_widths),
    }
    # Where the panels meet at the crown (not for mesh shapes, ADR-0049).
    crown: dict[str, object] = {
        "crown_offset": None
        if spec.crown_seam_offset_deg is None
        else math.radians(spec.crown_seam_offset_deg),
        "crown_widths": tuple(float(w) for w in spec.crown_panel_widths),
    }
    cap: dict[str, Any] = {
        "cap_shift": float(spec.cap_shift),
        "cap_direction": math.radians(spec.cap_direction_deg),
    }
    splits = tuple(float(f) for f in spec.splits)
    if isinstance(spec, DomeShape):
        return _meeting_point(
            spec,
            Dome(
                spec.name,
                placement,
                spec.base_radius,
                spec.height,
                spec.gores,
                marks,
                rc,
                splits=splits,
                **layout,  # type: ignore[arg-type]
                **crown,  # type: ignore[arg-type]
                **cap,
            ),
        )
    if isinstance(spec, TubeShape):
        if rc > 0.0:  # a pointed tube cut off where it is as wide as the cap
            length = spec.length * (1.0 - rc / spec.base_radius)
            return Tube(
                spec.name,
                placement,
                spec.base_radius,
                rc,
                length,
                spec.panels,
                marks,
                splits=splits,
                **layout,  # type: ignore[arg-type]
                **crown,  # type: ignore[arg-type]
            )
        return Tube(
            spec.name,
            placement,
            spec.base_radius,
            spec.tip_radius,
            spec.length,
            spec.panels,
            marks,
            splits=splits,
            **layout,  # type: ignore[arg-type]
            **crown,  # type: ignore[arg-type]
        )
    if isinstance(spec, RevolvedShape):
        return _meeting_point(
            spec,
            Revolved(
                spec.name,
                placement,
                tuple((float(r), float(z)) for r, z in spec.profile),
                spec.gores,
                spec.smooth,
                marks,
                rc,
                splits=splits,
                **layout,  # type: ignore[arg-type]
                **crown,  # type: ignore[arg-type]
                **cap,
            ),
        )
    mesh = ReferenceMesh(
        np.asarray(spec.vertices, dtype=np.float64),
        np.asarray(spec.triangles, dtype=np.int64),
        spec.source,
    )
    return FreeformShape(spec.name, placement, mesh, spec.panels, marks, rc, **layout)  # type: ignore[arg-type]


def piece_count(spec: ShapeSpec) -> int:
    """Number of gores or panels round a shape's axis."""
    if isinstance(spec, DomeShape | RevolvedShape):
        return spec.gores
    return spec.panels


def pointed(spec: ShapeSpec) -> bool:
    """True when a shape's skin pieces would meet in a point (so a cap can close it)."""
    if isinstance(spec, TubeShape):
        return spec.tip_radius <= 0.0
    if isinstance(spec, RevolvedShape):
        return float(spec.profile[-1][0]) <= 0.0
    return True


def auto_cap_diameter(spec: ShapeSpec) -> float:
    r"""Automatic cap diameter of a pointed shape, m.

    Every one of the M pieces' tops is at least :data:`CAP_PANEL_TOP_WIDTH` wide, so
    :math:`d = M\,w_{top}/\pi` for equal pieces, and
    :math:`d = w_{top} \sum w / (\pi \min w)` for pieces of relative widths :math:`w`
    (the narrowest top is then :math:`w_{top}`), but at most :data:`CAP_MAX_FRACTION` of
    the base diameter (both assumed). Rounded to 1 mm.
    """
    if spec.panel_widths:
        w = spec.panel_widths
        d = CAP_PANEL_TOP_WIDTH * sum(w) / (math.pi * min(w))
    else:
        d = piece_count(spec) * CAP_PANEL_TOP_WIDTH / math.pi
    d = min(d, CAP_MAX_FRACTION * 2.0 * base_radius(spec))
    return round(d, 3)


def cap_diameter(spec: ShapeSpec) -> float:
    """Diameter of the cap that closes a shape's top, m (0: none).

    ``spec.cap_diameter`` when set, otherwise :func:`auto_cap_diameter`; always 0 for a
    shape that does not come to a point (a tube with a tip disc, a profile ending off the
    axis).
    """
    if not pointed(spec):
        return 0.0
    if spec.cap_diameter is not None:
        return float(spec.cap_diameter)
    return auto_cap_diameter(spec)


def shape_design(
    spec: ShapeSpec, surface: EnvelopeSurface, seam_clearance: float | None = None
) -> PrimitiveDesign:
    """Place a shape on an envelope and derive its attachment and cutting pattern.

    ``seam_clearance`` is the least distance from a feed hole's edge to a seam of its
    envelope panel, m (:func:`feed_hole_clearance`; None: the library default).

    Raises
    ------
    PrimitiveError
        When the shape does not fit (the message says why).
    """
    from envelopelab.features.primitives import FEED_HOLE_SEAM_CLEARANCE, design_primitive

    return design_primitive(
        to_primitive(spec),
        surface,
        seam_allowance=spec.seam_allowance,
        feed_hole_radius=spec.feed_hole_radius,
        feed_holes=[
            (h.tape_position, surface.theta_at(h.gore, h.across), h.radius) for h in spec.feed_holes
        ],
        seam_clearance=FEED_HOLE_SEAM_CLEARANCE if seam_clearance is None else seam_clearance,
    )


def shape_preview(spec: ShapeSpec, surface: EnvelopeSurface) -> PrimitiveDesign:
    """A shape's skin on the envelope for drawing while it is edited
    (:func:`envelopelab.features.primitives.preview_primitive`; not a design result).

    Raises
    ------
    PrimitiveError
        When the shape does not fit, or it has no fast preview (a mesh shape).
    """
    from envelopelab.features.primitives import preview_primitive

    return preview_primitive(to_primitive(spec), surface)


def feed_hole_clearance(design: DesignDocument, patterns: PatternSet) -> float:
    r"""Least distance from a feed hole's finished edge to a seam of its panel, m.

    The hole's hem band (the hole tape's width) and the widest seam allowance of the rows
    (the fell beside the seam) must fit side by side:
    :math:`c = w_{hole\,tape} + \max_{rows} a_{row}` (source: design values; the rule is
    assumed).
    """
    from envelopelab.project.gore_design import row_allowance

    rows = [r.letter for r in design.gores.panel_rows] if design.gores is not None else []
    allowance = max((row_allowance(design, patterns, r) for r in rows), default=0.0)
    return float(design.tapes.hole.width + allowance)


def clear_feed_holes(
    spec: ShapeSpec,
    surface: EnvelopeSurface,
    clearance: float,
    placed: PrimitiveDesign | None = None,
) -> tuple[ShapeSpec, list[str]]:
    """Move a shape's extra feed holes clear of the seams of their panels.

    Every extra feed hole closer than ``clearance`` to a seam moves to the nearest position
    in its panel that is clear of the seams and inside the footprint
    (:func:`envelopelab.features.primitives.clear_feed_hole`). The hole under the base
    point moves with the shape, so it is only reported. ``placed`` is the shape already
    placed on ``surface`` from ``spec`` (placed here when None).

    Returns
    -------
    (ShapeSpec, list of str)
        The shape with its holes moved (unchanged when none needed moving), and what was
        done or could not be done.
    """
    from envelopelab.features.primitives import clear_feed_hole, feed_hole_seam_clearance

    if placed is None:
        placed = shape_design(spec, surface, clearance)
    notes: list[str] = []
    holes = list(spec.feed_holes)
    for i, (hole, mark) in enumerate(zip(spec.feed_holes, placed.extra_feed_holes, strict=True)):
        if feed_hole_seam_clearance(surface, mark.row, mark.centre_xy, mark.radius) >= clearance:
            continue
        theta = surface.theta_at(hole.gore, hole.across)
        found = clear_feed_hole(placed, hole.tape_position, theta, hole.radius, clearance)
        where = f"{spec.name}: feed hole in gore {mark.gore} row {mark.row}"
        if found is None:
            notes.append(f"{where} cannot be moved clear of the seams inside its panel")
            continue
        s, th = found
        g = float(surface.gore_position(np.array([th]))[0])
        gore = int(math.floor(g)) % surface.gore_count + 1
        across = round(g - math.floor(g) - 0.5, 4)
        holes[i] = hole.model_copy(
            update={"gore": gore, "tape_position": round(s, 4), "across": across}
        )
        notes.append(
            f"{where} moved clear of the seams (tape position {hole.tape_position:.3f} "
            f"-> {s:.3f} m, across {hole.across:+.3f} -> {across:+.3f})"
        )
    if spec.feed_hole_radius is not None and placed.feed_hole is not None:
        centre = placed.feed_hole
        c = feed_hole_seam_clearance(surface, centre.row, centre.centre_xy, centre.radius)
        if c < clearance:
            notes.append(
                f"{spec.name}: the feed hole under the base point is {c * 1000:.0f} mm from a "
                "seam; move the shape or make that hole smaller"
            )
    return spec.model_copy(update={"feed_holes": holes}), notes


def envelope_surface(
    design: DesignDocument, patterns: PatternSet, rows: list[Any] | None = None
) -> EnvelopeSurface:
    """The envelope shapes are placed on (the design's load-tape surface); ``rows``: its
    panel rows when already made."""
    from envelopelab.features.primitives import EnvelopeSurface

    return EnvelopeSurface.from_design(design, patterns, rows)


def default_shape(kind: ShapeKind, design: DesignDocument, name: str) -> ShapeSpec:
    """A sensible new shape of ``kind`` for a design (sized from its envelope).

    The base sits on gore 1, a third of the way up the tape from the mouth; sizes are a
    small fraction of the envelope's largest radius.

    Raises
    ------
    ValueError
        For a mesh (it needs a file) or a design without gores.
    """
    from envelopelab.project.gore_design import design_profile

    if design.gores is None:
        raise ValueError("special shapes are placed on a standard-gore design")
    profile = design_profile(design)
    radius = float(profile.r.max())
    placement = ShapePlacement(gore=1, tape_position=round(0.45 * profile.meridian_length, 3))
    size = round(max(0.06 * radius, 0.05), 3)
    if kind == "dome":
        return DomeShape(name=name, placement=placement, base_radius=size, height=size)
    if kind == "tube":
        return TubeShape(
            name=name,
            placement=placement,
            base_radius=size,
            tip_radius=round(0.4 * size, 3),
            length=round(2.5 * size, 3),
        )
    if kind == "revolved":
        a = size
        profile_pts = [
            (round(a * math.cos(t), 4), round(1.2 * a * math.sin(t), 4))
            for t in np.linspace(0.0, 0.5 * math.pi, 7)[:-1]
        ] + [(0.0, round(1.2 * a, 4))]
        return RevolvedShape(name=name, placement=placement, profile=profile_pts)
    raise ValueError("a mesh shape is made from a mesh file (import_mesh_shape)")


def mesh_shape(
    name: str,
    vertices: np.ndarray,
    triangles: np.ndarray,
    placement: ShapePlacement,
    source: str = "",
    panels: int = 12,
) -> MeshShape:
    """A mesh shape from vertex (m, z out of the envelope) and triangle arrays."""
    return MeshShape(
        name=name,
        placement=placement,
        vertices=[tuple(float(c) for c in v) for v in np.asarray(vertices)],  # type: ignore[misc]
        triangles=[tuple(int(i) for i in t) for t in np.asarray(triangles)],  # type: ignore[misc]
        source=source,
        panels=panels,
    )


def host_row(placed: PrimitiveDesign) -> str:
    """Label of the envelope row the shape's base point sits in."""
    for row in placed.surface.rows:
        if row.s_bottom <= placed.base_s <= row.s_top:
            return row.label
    return placed.surface.rows[-1].label


def shape_fabrics(
    spec: ShapeSpec, design: DesignDocument, patterns: PatternSet, placed: PrimitiveDesign
) -> tuple[str, str]:
    """Fabric ids of the envelope under the shape and of the shape's skin.

    The envelope fabric is the one of the row the base point sits in; the skin uses
    ``spec.fabric`` or, when that is None, the same fabric.
    """
    from envelopelab.project.gore_design import row_zone

    zone = row_zone(design, patterns, host_row(placed))
    host = design.zones.get(zone) or next(iter(design.zones.values()), "")
    return host, spec.fabric or host


def placement_at(
    surface: EnvelopeSurface, point: FloatArray, current: ShapePlacement
) -> ShapePlacement:
    """The placement whose base point is the envelope point nearest ``point``.

    Used to drag a shape over the envelope: gore, tape position and position across the
    gore follow the point; the lean of ``current`` is kept.

    Parameters
    ----------
    surface : EnvelopeSurface
        Envelope (:func:`envelope_surface`).
    point : ndarray, shape (3,)
        A point on or near the envelope, m (e.g. picked on the 3D view's design surface).
    current : ShapePlacement
        Placement being changed (its lean is kept).

    Returns
    -------
    ShapePlacement
        Gore from 1, tape position (m) kept 1 mm inside the tape's ends, across in
        [-0.5, 0.5], rounded to 0.1 mm and 1e-4 of the gore width.
    """
    s, theta, _ = surface.locate(np.asarray(point, dtype=np.float64).reshape(1, 3))
    length = float(surface.profile.meridian_length)
    tape = min(max(float(s[0]), DRAG_MARGIN), length - DRAG_MARGIN)
    g = float(surface.gore_position(theta)[0])
    cell = min(int(math.floor(g)), surface.gore_count - 1)
    across = min(max(g - cell - 0.5, -0.5), 0.5)
    return current.model_copy(
        update={"gore": cell + 1, "tape_position": round(tape, 4), "across": round(across, 4)}
    )


def base_radius(spec: ShapeSpec) -> float:
    """Radius of the circle a shape stands on, m (for a mesh: its largest radius)."""
    if isinstance(spec, DomeShape | TubeShape):
        return float(spec.base_radius)
    if isinstance(spec, RevolvedShape):
        return float(spec.profile[0][0])
    v = np.asarray(spec.vertices, dtype=np.float64)
    return float(np.hypot(v[:, 0], v[:, 1]).max())


def footprint_preview(
    surface: EnvelopeSurface, placement: ShapePlacement, radius: float, samples: int = 64
) -> FloatArray:
    """Approximate footprint ring of a shape at ``placement``, on the envelope, m.

    A circle of ``radius`` round the base point in the tangent plane, moved onto the
    envelope surface. It ignores the lean and the shape's own footprint search
    (:func:`shape_design`), so it is only a drag preview, never a pattern.

    Parameters
    ----------
    surface : EnvelopeSurface
        Envelope.
    placement : ShapePlacement
        Base point (lean ignored).
    radius : float
        Circle radius, m (:func:`base_radius`).
    samples : int
        Points round the ring.

    Returns
    -------
    ndarray, shape (samples + 1, 3)
        Closed ring (first point repeated), m.
    """
    s0 = placement.tape_position
    theta0 = surface.theta_at(placement.gore, placement.across)
    centre = surface.point(np.array([s0]), np.array([theta0]))[0]
    e_hoop, e_up, _ = surface.frame(s0, theta0)
    a = np.linspace(0.0, 2.0 * math.pi, samples + 1)
    ring = centre + radius * (np.outer(np.cos(a), e_hoop) + np.outer(np.sin(a), e_up))
    s, theta, _ = surface.locate(ring)
    length = float(surface.profile.meridian_length)
    out: FloatArray = surface.point(np.clip(s, 0.0, length), theta)
    return out


def display_offset(design: DesignDocument, placed: PrimitiveDesign) -> FloatArray:
    """Shift that puts a placed shape on the display surface, m, shape (3,).

    Shapes are placed and simulated on the surface of revolution through the tapes
    (:class:`~envelopelab.features.primitives.EnvelopeSurface`). The 3D view draws the
    envelope with its lobes or raised crests (:func:`~envelopelab.project.gore_design.
    display_surface`), so each shape is moved by the gap at its base point to sit on it.
    Display only: no shape geometry or result changes.
    """
    from envelopelab.project.gore_design import display_points

    s = np.array([placed.base_s])
    theta = np.array([placed.base_theta])
    on_display = display_points(design, s, theta)[0]
    on_revolution = placed.surface.point(s, theta)[0]
    return np.asarray(on_display - on_revolution, dtype=np.float64)


def feed_hole_rings(
    design: DesignDocument, placed: PrimitiveDesign, points: int = 33
) -> list[FloatArray]:
    """Every feed hole of a placed shape as a ring on the display surface, m.

    A hole's centre is given in the chart round the base point (hoop arc, tape arc,
    ``FeedHoleMark.chart_xy``); its circle is drawn in that chart, which is the envelope
    near the base point to first order.
    """
    from envelopelab.project.gore_design import display_points

    r0, _ = placed.surface.radius_height(np.array([placed.base_s]))
    radius = max(float(r0[0]), 1e-9)
    t = np.linspace(0.0, 2.0 * math.pi, points)
    rings = []
    for hole in placed.feed_holes:
        cx, cy = hole.chart_xy
        s = placed.base_s + cy + hole.radius * np.sin(t)
        theta = placed.base_theta + (cx + hole.radius * np.cos(t)) / radius
        rings.append(display_points(design, s, theta))
    return rings
