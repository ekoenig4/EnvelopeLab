"""Special shapes stored in a project: the data of every dome, tube, revolved and mesh shape.

A project's design state holds a list of shape specifications next to the design
document (project format version 2, ADR-0020). Each one is plain data (metres, degrees)
that :func:`to_primitive` turns into a primitive of :mod:`envelopelab.features.primitives`
and :func:`shape_design` places on the design's envelope. The specifications are part of
the undoable design state, of snapshots and versions, and of the ``shapes`` input group of
the dependency graph.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.features.primitives import EnvelopeSurface, Primitive, PrimitiveDesign
    from envelopelab.project.model import PatternSet

ShapeKind = Literal["dome", "tube", "revolved", "mesh"]
SHAPE_KINDS: tuple[ShapeKind, ...] = ("dome", "tube", "revolved", "mesh")


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
        Radius of the hole cut in the envelope to fill the shape, m (None: no hole; the
        shape cannot then be simulated as a fed chamber).
    seam_allowance : float
        Seam allowance round the skin pieces, m.
    fabric : str or None
        Fabric id of the skin (None: the fabric of the envelope row it sits on).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_\- ]+$")
    placement: ShapePlacement
    marks_per_piece: int = Field(default=2, ge=1, le=8)
    feed_hole_radius: float | None = Field(default=None, gt=0.0)
    seam_allowance: float = Field(default=0.0125, ge=0.0)
    fabric: str | None = None


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
    if isinstance(spec, DomeShape):
        return Dome(spec.name, placement, spec.base_radius, spec.height, spec.gores, marks)
    if isinstance(spec, TubeShape):
        return Tube(
            spec.name, placement, spec.base_radius, spec.tip_radius, spec.length, spec.panels, marks
        )
    if isinstance(spec, RevolvedShape):
        return Revolved(
            spec.name,
            placement,
            tuple((float(r), float(z)) for r, z in spec.profile),
            spec.gores,
            spec.smooth,
            marks,
        )
    mesh = ReferenceMesh(
        np.asarray(spec.vertices, dtype=np.float64),
        np.asarray(spec.triangles, dtype=np.int64),
        spec.source,
    )
    return FreeformShape(spec.name, placement, mesh, spec.panels, marks)


def shape_design(spec: ShapeSpec, surface: EnvelopeSurface) -> PrimitiveDesign:
    """Place a shape on an envelope and derive its attachment and cutting pattern.

    Raises
    ------
    PrimitiveError
        When the shape does not fit (the message says why).
    """
    from envelopelab.features.primitives import design_primitive

    return design_primitive(
        to_primitive(spec),
        surface,
        seam_allowance=spec.seam_allowance,
        feed_hole_radius=spec.feed_hole_radius,
    )


def envelope_surface(design: DesignDocument, patterns: PatternSet) -> EnvelopeSurface:
    """The envelope shapes are placed on (the design's load-tape surface)."""
    from envelopelab.features.primitives import EnvelopeSurface

    return EnvelopeSurface.from_design(design, patterns)


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
