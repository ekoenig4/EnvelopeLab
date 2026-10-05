r"""Parametric special-shape primitives on a standard-gore envelope.

A primitive (a dome, a tube or a revolved profile) is placed on the envelope designed by
the gore editor; a shape modelled as a mesh is placed the same way
(:class:`FreeformShape`, :mod:`envelopelab.features.freeform`).
This module derives everything a builder needs to make it from that placement alone:

* the **footprint**: the line where the primitive's skin meets the envelope, and its
  run across every host panel (gore and row) in that panel's own pattern coordinates,
  so it can be marked on the cut panels (:class:`AttachmentLine`);
* numbered **match marks** on the footprint and on the skin's rim (:class:`MatchMark`);
* the **cutting pattern** of the skin: finished and cut outlines of every gore or panel
  (:class:`CutPiece`);
* **checks** on that pattern: rim length against the footprint, the two sides of every
  skin seam, flattening distortion (:class:`DesignCheck`);
* an :class:`~envelopelab.features.builder.AppendageSpec` whose skin rests in the as-cut
  panel shapes (:func:`primitive_appendage`), so the preview solver and CalculiX predict
  how the sewn feature takes shape under pressure.

Envelope surface
----------------
The host is the surface of revolution of the design's meridian (the load-tape line)
:math:`(r(s), z(s))`, :math:`s` the tape arc length from the mouth:

.. math:: \mathbf{X}(s, \theta) = (r\cos\theta,\ r\sin\theta,\ z), \qquad
          \mathbf{n} = (z'\cos\theta,\ z'\sin\theta,\ -r')

Gore :math:`k` (numbered from 1) spans :math:`\theta \in [(k-1), k)\,2\pi/N`. A point at
fraction :math:`\tau \in [-\tfrac12, \tfrac12]` across gore :math:`k` from its centreline
sits at :math:`x = 2\tau w(s)`, :math:`y = s - s_{row}` in the panel pattern of that
gore's row, with :math:`w(s)` the flat gore half-width of the design's width model. This
is exact on the centreline and on the load tapes; across a lobe of a lofted gore the
mark is placed proportionally to the flat width (the lobe bulge between tapes is not
part of the host surface here).

Primitive skin
--------------
Each primitive has an axis :math:`\mathbf{a}` through the base point
:math:`\mathbf{P}_0 = \mathbf{X}(s_0, \theta_0)`, the outward normal tilted by the lean
:math:`\lambda` towards the azimuth :math:`\psi` in the tangent plane
(:math:`\psi = 0` up the tape towards the crown, :math:`90^\circ` towards the next gore):

.. math:: \mathbf{a} = \cos\lambda\,\mathbf{n} + \sin\lambda
          (\cos\psi\,\mathbf{e}_s + \sin\psi\,\mathbf{e}_\theta)

and a meridian :math:`(\rho(\sigma), \zeta(\sigma))` revolved about it, :math:`\sigma` its
arc length from the base circle (:math:`\zeta = 0`) to the tip. Around the axis, the angle
:math:`\phi` starts at :math:`\mathbf{b}_1` (the up-tape direction made normal to
:math:`\mathbf{a}`) and turns towards :math:`\mathbf{b}_2 = \mathbf{a}\times\mathbf{b}_1`:

.. math:: \mathbf{S}(\sigma, \phi) = \mathbf{P}_0 + \rho(\sigma)(\cos\phi\,\mathbf{b}_1
          + \sin\phi\,\mathbf{b}_2) + \zeta(\sigma)\,\mathbf{a}

* **Dome**: a half spheroid of base radius :math:`a` and height :math:`h`,
  :math:`\rho = a\cos\omega,\ \zeta = h\sin\omega`; a blister, lobe or ear.
* **Tube**: a straight frustum from base radius :math:`r_b` to tip radius :math:`r_t`
  over the axial length :math:`L`, closed by a flat tip disc; a horn, nose or mast.
* **Revolved**: any meridian given as points (spline or straight segments), closed by an
  apex or a flat tip disc; a nose, bulb, onion, ball or flared horn. Its gores are
  flattened like a dome's.

Below the base circle each skin meridian is continued along its base tangent (a dome's
wall drops straight down the axis, a tube's generator continues; a profile that flares
outward at its base drops straight down the axis too) until it meets the envelope; the
footprint point on meridian :math:`\phi` is the last crossing of
:math:`\mathbf{S}(\cdot, \phi)` from inside to outside the envelope (signed distance to
the meridian curve, bisection to :data:`ROOT_TOLERANCE`). The skin therefore always
reaches the envelope, also when a leaned base circle dips below it.

Cutting pattern
---------------
The skin is divided by meridians :math:`\phi_j = 2\pi j/M - \pi/M` into :math:`M` pieces
(piece 1 is centred on :math:`\phi = 0`). Writing each meridian from its footprint point
to the tip with :math:`t \in [0, 1]`:

* **Tube panels are exact developments.** A cone of half-angle :math:`\gamma`
  (:math:`\sin\gamma = (r_b - r_t)/\ell`) unrolls about its apex with polar radius equal to
  the slant distance from the apex and polar angle :math:`\alpha = \phi\sin\gamma`; a
  cylinder unrolls to :math:`x = r_b\phi`. Every length and angle is kept.
* **Dome gores are classic gores with true-length seams.** The gore centreline is laid
  straight with its true length, :math:`y(t)`, and every parallel :math:`t` = const
  straight across it with its true arc length from the centreline, :math:`x(t, \phi)`
  [Pagon]_. That makes the flat seam edges longer than the seams of the doubly curved
  gore, so the gore is then sheared and stretched along its length,

  .. math:: x' = x + \kappa y, \qquad y' = (1 + \alpha)\,y,

  with :math:`\alpha, \kappa` chosen so that both seam edges have their true 3D length:
  the two sides of every skin seam match, the rim stays straight and the apex stays one
  point. The cloth that cannot follow a doubly curved surface ends up spread over the
  gore; the ``area distortion`` check reports it, and more gores reduce it (about
  :math:`1/M^2`).

Valid range
-----------
The footprint must stay on the convex part of the envelope between the mouth and the
crown, and be star-shaped about the base point (every skin meridian crosses the
envelope once on its way out); bases larger than about a quarter of the local envelope
radius, or leans that make the skin touch the envelope again, are rejected.

References
----------
.. [Struik] D. J. Struik, *Lectures on Classical Differential Geometry*, 2nd ed., Dover
   (1988), sec. 2-1 and 2-8 (surfaces of revolution; developable cones and cylinders).
.. [Pagon] W. W. Pagon, "Gore patterns for balloons and airship envelopes", in
   *Scientific Ballooning Handbook*, NCAR TN-99 (1975), sec. 7 (gore flattening by
   centreline and parallel arc lengths).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from scipy.spatial import cKDTree

from envelopelab.features.builder import (
    AppendageSpec,
    ChartHole,
    DesignedSkin,
    FeatureBuildError,
    HostSurface,
    HostTape,
    PressureSpec,
    RimTapeSpec,
    _mesh_disc,
)
from envelopelab.geometry.gore import (
    GoreWidthModel,
    MeridianProfile,
    gore_half_widths,
    polygon_area,
)
from envelopelab.geometry.polygon import offset_polygon, points_in_polygon
from envelopelab.io.reference_mesh import ReferenceMesh
from envelopelab.materials.membrane import TapeMaterial
from envelopelab.solvers.membrane import FloatArray, IntArray

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.project.model import PatternSet

PrimitiveKind = Literal["dome", "tube", "revolved", "mesh"]
CheckSeverity = Literal["info", "warning", "error"]

ROOT_TOLERANCE = 1e-7
"""Bisection tolerance of a footprint point along its skin meridian, m (source: assumed)."""

FOOTPRINT_GRID = 241
"""Path samples per skin meridian that bracket the footprint crossing before bisection
(about 1 % of the path; a second crossing finer than that is not detected)."""

MARK_EASE_SAMPLES = 48
"""Integration steps per match-mark interval when measuring the attachment ease
(:func:`_mark_ease`; a few mm per step for usual mark spacings)."""

DEFAULT_TOLERANCE = 0.003
"""Default length tolerance of the pattern checks, m (AGENTS.md sewn-edge default, 3 mm;
source: assumed)."""

AREA_DISTORTION_LIMIT = 0.01
"""Largest relative difference between a piece's flat and 3D area before the pattern is
flagged (dimensionless; source: assumed)."""


SEAM_FLATTENING_LIMIT = 0.02
"""Largest relative difference between a flat seam edge and the designed seam before the
pattern is flagged (dimensionless; source: assumed)."""


_Entry = tuple[tuple[Any, ...], float, float]
"""A boundary node of a cut piece: (shared-node key, t, phi)."""


class PrimitiveError(ValueError):
    """A primitive that cannot be placed or flattened on its envelope."""


# --------------------------------------------------------------------------------------
# Envelope surface
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RowBand:
    """A horizontal panel row: label and finished tape positions (m) of its seams."""

    label: str
    s_bottom: float
    s_top: float


class EnvelopeSurface:
    """The standard-gore envelope as a surface of revolution (see module docstring).

    Parameters
    ----------
    profile : MeridianProfile
        Load-tape meridian, m (dense polyline).
    gore_count : int
        Number of gores N.
    width_model : GoreWidthModel, optional
        Flat gore width model (default: small bulge with ``gore_count`` gores).
    rows : sequence of RowBand, optional
        Panel rows from the mouth up (default: one row ``"A"`` over the whole tape).
    """

    def __init__(
        self,
        profile: MeridianProfile,
        gore_count: int,
        width_model: GoreWidthModel | None = None,
        rows: Sequence[RowBand] = (),
    ) -> None:
        if gore_count < 3:
            raise PrimitiveError("an envelope needs at least 3 gores")
        self.profile = profile
        self.gore_count = int(gore_count)
        self.width_model = width_model or GoreWidthModel(n_gores=gore_count)
        length = profile.meridian_length
        self.rows: tuple[RowBand, ...] = tuple(rows) or (RowBand("A", 0.0, length),)
        s, r, z = profile.s, profile.r, profile.z
        dr, dz = np.gradient(r, s), np.gradient(z, s)
        norm = np.hypot(dr, dz)
        self._dr, self._dz = dr / norm, dz / norm
        self._tree = cKDTree(np.column_stack([r, z]))
        seg = np.column_stack([np.diff(r), np.diff(z)])
        self._seg_len = np.hypot(seg[:, 0], seg[:, 1])
        self._seg_dir = seg / self._seg_len[:, None]

    @classmethod
    def from_design(
        cls, design: DesignDocument, patterns: PatternSet | None = None
    ) -> EnvelopeSurface:
        """Envelope of a standard-gore design (profile, gore count, loft and rows).

        Parameters
        ----------
        design : DesignDocument
            Standard-gore design, m.
        patterns : PatternSet, optional
            Row annotations (allowance overrides do not move the finished rows).

        Returns
        -------
        EnvelopeSurface
            Surface with the design's panel rows.
        """
        from envelopelab.project.gore_design import (
            design_profile,
            design_width_model,
            panel_rows,
        )
        from envelopelab.project.model import PatternSet

        if design.gores is None:
            raise PrimitiveError("primitives are placed on a standard-gore design")
        profile = design_profile(design)
        rows = panel_rows(design, patterns or PatternSet(), profile)
        return cls(
            profile,
            design.gores.count,
            design_width_model(design),
            [RowBand(r.label, r.s_bottom, r.s_top) for r in rows],
        )

    @property
    def gore_angle(self) -> float:
        """Azimuth spanned by one gore, rad."""
        return 2.0 * math.pi / self.gore_count

    def radius_height(self, s: FloatArray) -> tuple[FloatArray, FloatArray]:
        """Tape radius and height at tape positions ``s`` (m), m."""
        p = self.profile
        return np.interp(s, p.s, p.r), np.interp(s, p.s, p.z)

    def point(self, s: FloatArray, theta: FloatArray) -> FloatArray:
        """3D points :math:`\\mathbf{X}(s, \\theta)` (m, rad), m, shape (n, 3)."""
        s, theta = np.broadcast_arrays(np.asarray(s, float), np.asarray(theta, float))
        r, z = self.radius_height(s.ravel())
        th = theta.ravel()
        return np.column_stack([r * np.cos(th), r * np.sin(th), z])

    def frame(self, s: float, theta: float) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Unit hoop tangent, up-tape tangent and outward normal at one point."""
        dr = float(np.interp(s, self.profile.s, self._dr))
        dz = float(np.interp(s, self.profile.s, self._dz))
        c, si = math.cos(theta), math.sin(theta)
        e_hoop = np.array([-si, c, 0.0])
        e_up = np.array([dr * c, dr * si, dz])
        e_up /= np.linalg.norm(e_up)
        normal = np.cross(e_hoop, e_up)
        return e_hoop, e_up, normal / np.linalg.norm(normal)

    def locate(self, points: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Closest tape position, azimuth and signed distance of 3D points.

        Parameters
        ----------
        points : ndarray, shape (n, 3)
            Points, m.

        Returns
        -------
        s : ndarray
            Tape position of the closest surface point, m.
        theta : ndarray
            Azimuth, rad, in :math:`[0, 2\\pi)`.
        distance : ndarray
            Signed distance from the surface, m, positive outside the envelope.
        """
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        q = np.column_stack([np.hypot(p[:, 0], p[:, 1]), p[:, 2]])
        theta = np.mod(np.arctan2(p[:, 1], p[:, 0]), 2.0 * math.pi)
        _, k = self._tree.query(q)
        n_seg = len(self._seg_len)
        best_d = np.full(len(q), np.inf)
        best_s = np.zeros(len(q))
        best_sd = np.zeros(len(q))
        prof = self.profile
        for offset in (-1, 0):
            i = np.clip(k + offset, 0, n_seg - 1)
            a = np.column_stack([prof.r[i], prof.z[i]])
            d = self._seg_dir[i]
            t = np.clip(np.einsum("ij,ij->i", q - a, d), 0.0, self._seg_len[i])
            proj = a + t[:, None] * d
            rel = q - proj
            dist = np.hypot(rel[:, 0], rel[:, 1])
            # Outward normal of a mouth-to-crown segment (dr, dz) is (dz, -dr).
            sd = rel[:, 0] * d[:, 1] - rel[:, 1] * d[:, 0]
            better = dist < best_d
            best_d = np.where(better, dist, best_d)
            best_s = np.where(better, prof.s[i] + t, best_s)
            best_sd = np.where(better, np.where(np.abs(sd) > 0, sd, dist), best_sd)
        return best_s, theta, best_sd

    def signed_distance(self, points: FloatArray) -> FloatArray:
        """Signed distance of 3D points from the envelope, m (positive outside)."""
        return self.locate(points)[2]

    def theta_at(self, gore: int, across: float = 0.0) -> float:
        """Azimuth of a point ``across`` (fraction from the centreline) in a gore, rad."""
        return (gore - 0.5 + across) * self.gore_angle

    def gore_position(self, theta: FloatArray) -> FloatArray:
        """Azimuth in gore widths from seam 0, in :math:`[0, N)` (gore k spans [k-1, k))."""
        out: FloatArray = np.mod(np.asarray(theta, float) / self.gore_angle, self.gore_count)
        return out

    def half_width(self, s: FloatArray) -> FloatArray:
        """Flat gore half-width at tape positions ``s`` (m), m."""
        return gore_half_widths(self.profile, self.width_model, np.atleast_1d(s))[1]

    def row_index(self, s: FloatArray) -> IntArray:
        """Index of the row containing each tape position (m)."""
        tops = np.array([r.s_top for r in self.rows[:-1]])
        out: IntArray = np.searchsorted(tops, np.atleast_1d(s), side="right")
        return out


# --------------------------------------------------------------------------------------
# Primitive definitions
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    """Where a primitive sits on the envelope and how its axis leans.

    Attributes
    ----------
    gore : int
        Gore number of the base point, from 1.
    tape_position : float
        Tape arc length of the base point from the mouth, m.
    across : float
        Fraction of the gore width from its centreline, in [-0.5, 0.5] (0: centreline,
        +-0.5: the load tapes either side).
    lean_deg : float
        Lean of the axis from the envelope normal, deg, in [0, 75].
    lean_toward_deg : float
        Direction of the lean in the tangent plane, deg: 0 up the tape (towards the
        crown), 90 towards the next gore, 180 towards the mouth.
    """

    gore: int
    tape_position: float
    across: float = 0.0
    lean_deg: float = 0.0
    lean_toward_deg: float = 0.0


@dataclass(frozen=True)
class Dome:
    """A half-spheroid blister, lobe or ear (see module docstring).

    Attributes
    ----------
    name : str
        Feature name (piece labels start with it).
    placement : Placement
        Base point and lean.
    base_radius : float
        Radius :math:`a` of the base circle, m.
    height : float
        Height :math:`h` of the dome above its base circle along the axis, m.
    gores : int
        Number of skin gores M (>= 3).
    marks_per_piece : int
        Match marks per gore on the rim (>= 1).
    """

    name: str
    placement: Placement
    base_radius: float
    height: float
    gores: int = 8
    marks_per_piece: int = 2

    kind: PrimitiveKind = field(default="dome", init=False)

    @property
    def pieces(self) -> int:
        """Number of skin pieces round the axis."""
        return self.gores

    @property
    def closed_tip(self) -> bool:
        """False: the gores meet in a point at the apex."""
        return False

    @property
    def tip_radius(self) -> float:
        """Radius of the tip circle, m (0: an apex)."""
        return 0.0

    @property
    def tip_height(self) -> float:
        """Height of the tip above the base circle along the axis, m."""
        return self.height

    def meridian(self, count: int = 2001) -> tuple[FloatArray, FloatArray]:
        """Dense skin meridian :math:`(\\rho, \\zeta)` from the base circle to the tip, m."""
        w = np.linspace(0.0, 0.5 * math.pi, count)
        return self.base_radius * np.cos(w), self.height * np.sin(w)

    def validate(self) -> None:
        """Raise :class:`PrimitiveError` for out-of-range values."""
        _check_common(self.name, self.placement, self.marks_per_piece)
        if self.base_radius <= 0.0 or self.height <= 0.0:
            raise PrimitiveError(f"{self.name}: dome radius and height must be positive")
        if self.gores < 3:
            raise PrimitiveError(f"{self.name}: a dome needs at least 3 gores")


@dataclass(frozen=True)
class Tube:
    """A straight frustum (horn, nose, mast) closed by a flat tip disc.

    Attributes
    ----------
    name : str
        Feature name.
    placement : Placement
        Base point and lean.
    base_radius, tip_radius : float
        Radii :math:`r_b \\ge r_t \\ge 0` of the base and tip circles, m (``tip_radius``
        0: a pointed horn without a tip disc).
    length : float
        Axial length :math:`L` from the base circle to the tip, m.
    panels : int
        Number of skin panels M (>= 1).
    marks_per_piece : int
        Match marks per panel on the rim (>= 1).
    """

    name: str
    placement: Placement
    base_radius: float
    tip_radius: float
    length: float
    panels: int = 4
    marks_per_piece: int = 2

    kind: PrimitiveKind = field(default="tube", init=False)

    @property
    def pieces(self) -> int:
        """Number of skin pieces round the axis (the tip disc is extra)."""
        return self.panels

    @property
    def closed_tip(self) -> bool:
        """True when a flat disc closes the tip."""
        return self.tip_radius > 0.0

    @property
    def tip_height(self) -> float:
        """Height of the tip above the base circle along the axis, m."""
        return self.length

    def meridian(self, count: int = 2001) -> tuple[FloatArray, FloatArray]:
        """Skin meridian from the base circle to the tip, m (a straight generator)."""
        f = np.linspace(0.0, 1.0, count)
        return (
            self.base_radius + f * (self.tip_radius - self.base_radius),
            f * self.length,
        )

    def validate(self) -> None:
        """Raise :class:`PrimitiveError` for out-of-range values."""
        _check_common(self.name, self.placement, self.marks_per_piece)
        if self.base_radius <= 0.0 or self.length <= 0.0:
            raise PrimitiveError(f"{self.name}: tube radius and length must be positive")
        if not 0.0 <= self.tip_radius <= self.base_radius:
            raise PrimitiveError(f"{self.name}: tip radius must be between 0 and the base radius")
        if self.panels < 1:
            raise PrimitiveError(f"{self.name}: a tube needs at least one panel")


@dataclass(frozen=True)
class Revolved:
    r"""Any profile revolved about the axis: nose, bulb, onion, ball, flared horn.

    Attributes
    ----------
    name : str
        Feature name.
    placement : Placement
        Base point and lean.
    profile : tuple of (float, float)
        Meridian points :math:`(\rho, \zeta)` from the base circle (:math:`\zeta = 0`,
        :math:`\rho > 0`) to the tip, m: distance from the axis and height along it. The
        last point on the axis (:math:`\rho = 0`) closes the shape in an apex; otherwise
        a flat disc of the last radius closes it.
    gores : int
        Number of skin gores M (>= 3).
    smooth : bool
        Interpolate the points with a cubic spline (otherwise straight segments).
    marks_per_piece : int
        Match marks per gore on the rim (>= 1).
    """

    name: str
    placement: Placement
    profile: tuple[tuple[float, float], ...]
    gores: int = 12
    smooth: bool = True
    marks_per_piece: int = 2

    kind: PrimitiveKind = field(default="revolved", init=False)

    @property
    def pieces(self) -> int:
        """Number of skin pieces round the axis (a tip disc is extra)."""
        return self.gores

    @property
    def tip_radius(self) -> float:
        """Radius of the tip circle, m (0: an apex)."""
        return float(self.profile[-1][0])

    @property
    def closed_tip(self) -> bool:
        """True when a flat disc closes the tip."""
        return self.tip_radius > 0.0

    @property
    def tip_height(self) -> float:
        """Height of the tip above the base circle along the axis, m."""
        return float(self.profile[-1][1])

    def meridian(self, count: int = 2001) -> tuple[FloatArray, FloatArray]:
        """Dense skin meridian from the base circle to the tip, m."""
        pts = np.asarray(self.profile, dtype=np.float64)
        chord = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        t = np.linspace(0.0, chord[-1], count)
        if self.smooth and len(pts) > 2:
            from scipy.interpolate import CubicSpline

            rho = CubicSpline(chord, pts[:, 0])(t)
            zeta = CubicSpline(chord, pts[:, 1])(t)
            return np.clip(rho, 0.0, None), zeta
        return np.interp(t, chord, pts[:, 0]), np.interp(t, chord, pts[:, 1])

    def validate(self) -> None:
        """Raise :class:`PrimitiveError` for out-of-range values."""
        _check_common(self.name, self.placement, self.marks_per_piece)
        pts = np.asarray(self.profile, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 2:
            raise PrimitiveError(f"{self.name}: a profile needs at least two (rho, zeta) points")
        if pts[0, 1] != 0.0 or pts[0, 0] <= 0.0:
            raise PrimitiveError(f"{self.name}: the profile must start at zeta = 0 with rho > 0")
        if np.any(pts[:-1, 0] <= 0.0) or pts[-1, 0] < 0.0:
            raise PrimitiveError(f"{self.name}: only the last profile point may lie on the axis")
        if np.any(np.linalg.norm(np.diff(pts, axis=0), axis=1) <= 0.0):
            raise PrimitiveError(f"{self.name}: profile points must be distinct")
        if self.gores < 3:
            raise PrimitiveError(f"{self.name}: a revolved shape needs at least 3 gores")
        rho, _ = self.meridian()
        if np.any(rho[:-1] <= 0.0):
            raise PrimitiveError(f"{self.name}: the smoothed profile crosses the axis")


@dataclass(frozen=True)
class FreeformShape:
    """Any shape modelled as a triangle mesh (e.g. in Blender); see
    :mod:`envelopelab.features.freeform`.

    Attributes
    ----------
    name : str
        Feature name.
    placement : Placement
        Base point and lean of the mesh's frame.
    mesh : ReferenceMesh
        Closed triangle mesh in its own frame, m: :math:`z` along the axis out of the
        envelope, :math:`x` up the tape, origin at the base point; sunk a little below
        :math:`z = 0` so it reaches into the envelope
        (:func:`envelopelab.io.blender.read_shape_mesh`).
    panels : int
        Number of skin panels M (>= 2), cut along half-planes through the axis.
    marks_per_piece : int
        Match marks per panel on the rim (>= 1).
    """

    name: str
    placement: Placement
    mesh: ReferenceMesh = field(repr=False)
    panels: int = 6
    marks_per_piece: int = 2

    kind: PrimitiveKind = field(default="mesh", init=False)

    @property
    def pieces(self) -> int:
        """Number of skin panels."""
        return self.panels

    @property
    def closed_tip(self) -> bool:
        """False: the panels meet at the pole where the axis leaves the mesh."""
        return False

    @property
    def tip_radius(self) -> float:
        """0: the panels meet in a point."""
        return 0.0

    @property
    def tip_height(self) -> float:
        """Highest point of the mesh along the axis, m."""
        return float(np.asarray(self.mesh.vertices)[:, 2].max())

    def validate(self) -> None:
        """Raise :class:`PrimitiveError` for out-of-range values."""
        _check_common(self.name, self.placement, self.marks_per_piece)
        if len(self.mesh.triangles) < 4:
            raise PrimitiveError(f"{self.name}: the mesh has too few triangles")
        if self.panels < 2:
            raise PrimitiveError(f"{self.name}: a free-form shape needs at least 2 panels")


Primitive = Dome | Tube | Revolved | FreeformShape
RevolvedPrimitive = Dome | Tube | Revolved


def _check_common(name: str, placement: Placement, marks: int) -> None:
    if not -0.5 <= placement.across <= 0.5:
        raise PrimitiveError(f"{name}: 'across' must be within [-0.5, 0.5]")
    if not 0.0 <= placement.lean_deg <= 75.0:
        raise PrimitiveError(f"{name}: lean must be within [0, 75] deg")
    if marks < 1:
        raise PrimitiveError(f"{name}: at least one match mark per piece")


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AttachmentLine:
    """The footprint's run across one host panel, in that panel's pattern coordinates.

    Attributes
    ----------
    gore : int
        Host gore number, from 1.
    row : str
        Host row label.
    points : ndarray, shape (n, 2)
        Finished-pattern coordinates, m: ``x`` across from the gore centreline, ``y`` up
        from the row's finished bottom seam line.
    """

    gore: int
    row: str
    points: FloatArray = field(repr=False)

    @property
    def length(self) -> float:
        """Length of the run on the flat panel, m."""
        return float(np.linalg.norm(np.diff(self.points, axis=0), axis=1).sum())


@dataclass(frozen=True)
class MatchMark:
    """A numbered mark on the footprint and the matching mark on the skin rim.

    Attributes
    ----------
    number : int
        Mark number, from 1 at the top of the feature (:math:`\\phi = 0`).
    phi_deg : float
        Angle round the axis, deg.
    gore, row : int, str
        Host panel carrying the mark.
    host_xy : tuple of float
        Mark in the host panel's pattern coordinates, m.
    piece : str
        Skin piece carrying the mark on its rim.
    piece_xy : tuple of float
        Mark in the skin piece's pattern coordinates, m.
    """

    number: int
    phi_deg: float
    gore: int
    row: str
    host_xy: tuple[float, float]
    piece: str
    piece_xy: tuple[float, float]


@dataclass(frozen=True)
class FeedHoleMark:
    """A hole cut in the envelope under the feature (centre in panel coordinates, m)."""

    gore: int
    row: str
    centre_xy: tuple[float, float]
    radius: float


@dataclass(frozen=True)
class CutPiece:
    """One piece of the skin's cutting pattern.

    Attributes
    ----------
    label : str
        Piece label (``<name>-G1`` dome gores, ``<name>-P1`` tube panels,
        ``<name>-TIP`` tip disc).
    finished : ndarray, shape (n, 2)
        Finished (sewn-line) outline, m, counter-clockwise, ``y`` up the piece.
    cut : ndarray, shape (m, 2)
        Cut outline including the seam allowance, m.
    rim : ndarray, shape (k, 2) or None
        Edge sewn to the envelope along the footprint, m.
    edges : dict of str to ndarray
        Other finished edges (``left``, ``right``, ``top``), m.
    surface_area : float
        Area of the piece on the designed 3D shape, m^2.
    cut_count : int
        Pieces to cut.
    """

    label: str
    finished: FloatArray = field(repr=False)
    cut: FloatArray = field(repr=False)
    rim: FloatArray | None = field(repr=False)
    edges: dict[str, FloatArray] = field(repr=False)
    surface_area: float
    cut_count: int = 1

    @property
    def flat_area(self) -> float:
        """Finished flat area, m^2."""
        return polygon_area(self.finished)

    @property
    def size(self) -> tuple[float, float]:
        """Finished width and height of the piece, m."""
        span = self.finished.max(axis=0) - self.finished.min(axis=0)
        return float(span[0]), float(span[1])


@dataclass(frozen=True)
class DesignCheck:
    """A check on the derived pattern.

    Attributes
    ----------
    name : str
        Check name.
    value : float
        Measured value (``unit``).
    limit : float
        Limit the value is compared with (``unit``).
    unit : str
        Unit of value and limit.
    severity : {"info", "warning", "error"}
        ``info`` passed or informative; ``warning`` and ``error`` need attention.
    message : str
        What was measured and what to do.
    """

    name: str
    value: float
    limit: float
    unit: str
    severity: CheckSeverity
    message: str

    @property
    def passed(self) -> bool:
        """True for informative checks and passed limits."""
        return self.severity == "info"


@dataclass
class PrimitiveDesign:
    """Everything derived from one primitive on its envelope (SI units).

    Attributes
    ----------
    primitive : Dome, Tube or Revolved
        Input.
    surface : EnvelopeSurface
        Host envelope.
    base_s, base_theta : float
        Tape position (m) and azimuth (rad) of the base point.
    base_point, axis, b1, b2 : ndarray, shape (3,)
        Base point (m) and the unit axis frame.
    footprint_phi : ndarray
        Angles of the footprint samples round the axis, rad, increasing from 0.
    footprint_points : ndarray, shape (n, 3)
        Footprint on the envelope, m.
    footprint_s, footprint_theta : ndarray
        Tape position (m) and azimuth (rad) of each footprint sample.
    pieces : list of CutPiece
        Skin cutting pattern.
    attachment : list of AttachmentLine
        Footprint runs on the host panels.
    marks : list of MatchMark
        Numbered match marks.
    feed_hole : FeedHoleMark or None
        Hole cut in the envelope under the feature.
    checks : list of DesignCheck
        Pattern checks.
    mark_ease : ndarray
        Skin rim length minus marked attachment-line length (on the flat envelope
        panels) between match mark ``j`` and the next one, m (see :func:`_mark_ease`).
    """

    primitive: Primitive
    surface: EnvelopeSurface
    base_s: float
    base_theta: float
    base_point: FloatArray
    axis: FloatArray
    b1: FloatArray
    b2: FloatArray
    footprint_phi: FloatArray
    footprint_points: FloatArray
    footprint_s: FloatArray
    footprint_theta: FloatArray
    pieces: list[CutPiece]
    attachment: list[AttachmentLine]
    marks: list[MatchMark]
    feed_hole: FeedHoleMark | None
    checks: list[DesignCheck]
    _skin: Any = field(repr=False)
    mark_ease: FloatArray = field(default_factory=lambda: np.zeros(0), repr=False)

    @property
    def footprint_length(self) -> float:
        """Length of the footprint line on the envelope, m."""
        p = self.footprint_points
        return float(np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1).sum())

    @property
    def designed_height(self) -> float:
        """Largest height of the designed skin above the envelope, m."""
        return float(self._skin.max_height())

    @property
    def ok(self) -> bool:
        """True when no check is a warning or an error."""
        return all(c.passed for c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready summary with units in the keys."""
        p = self.primitive
        return {
            "name": p.name,
            "kind": p.kind,
            "base": {
                "gore": p.placement.gore,
                "across": p.placement.across,
                "tape_position_m": self.base_s,
                "lean_deg": p.placement.lean_deg,
                "lean_toward_deg": p.placement.lean_toward_deg,
            },
            "footprint_length_m": self.footprint_length,
            "designed_height_m": self.designed_height,
            "pieces": [
                {
                    "label": c.label,
                    "cut_count": c.cut_count,
                    "finished_width_m": c.size[0],
                    "finished_height_m": c.size[1],
                    "flat_area_m2": c.flat_area,
                    "surface_area_m2": c.surface_area,
                    "finished_outline_m": c.finished.tolist(),
                    "cut_outline_m": c.cut.tolist(),
                }
                for c in self.pieces
            ],
            "attachment": [
                {"gore": a.gore, "row": a.row, "points_m": a.points.tolist()}
                for a in self.attachment
            ],
            "match_marks": [
                {
                    "number": m.number,
                    "phi_deg": m.phi_deg,
                    "gore": m.gore,
                    "row": m.row,
                    "host_xy_m": list(m.host_xy),
                    "piece": m.piece,
                    "piece_xy_m": list(m.piece_xy),
                }
                for m in self.marks
            ],
            "feed_hole": None
            if self.feed_hole is None
            else {
                "gore": self.feed_hole.gore,
                "row": self.feed_hole.row,
                "centre_xy_m": list(self.feed_hole.centre_xy),
                "radius_m": self.feed_hole.radius,
            },
            "mark_ease_m": self.mark_ease.tolist(),
            "checks": [
                {
                    "name": c.name,
                    "value": c.value,
                    "limit": c.limit,
                    "unit": c.unit,
                    "severity": c.severity,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


# --------------------------------------------------------------------------------------
# Skin geometry
# --------------------------------------------------------------------------------------


class _Skin:
    """Skin surface :math:`\\mathbf{S}(t, \\phi)` from the footprint (t=0) to the tip (t=1)."""

    def __init__(
        self,
        primitive: RevolvedPrimitive,
        surface: EnvelopeSurface,
        base: FloatArray,
        axis: FloatArray,
        b1: FloatArray,
        b2: FloatArray,
        samples: int,
    ) -> None:
        self.primitive = primitive
        self.surface = surface
        self.base, self.axis, self.b1, self.b2 = base, axis, b1, b2
        rho, zeta = primitive.meridian()
        sigma = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(rho), np.diff(zeta)))])
        self.rho_m, self.zeta_m, self.sigma = rho, zeta, sigma
        self.total = float(sigma[-1])
        tangent = np.array([rho[1] - rho[0], zeta[1] - zeta[0]])
        tangent /= np.linalg.norm(tangent)
        # A profile flaring outward at its base would run into the axis if continued
        # backwards; its wall drops straight down the axis instead.
        self.base_tangent = tangent if tangent[0] <= 0.0 else np.array([0.0, 1.0])
        self.phi = np.linspace(0.0, 2.0 * math.pi, samples, endpoint=False)
        self.u0 = self._footprint(self.phi)

    # Path along one skin meridian: u < 0 on the continuation below the base circle.
    def _rz(self, u: FloatArray) -> tuple[FloatArray, FloatArray]:
        below = u < 0.0
        rho = np.where(
            below,
            self.rho_m[0] + u * self.base_tangent[0],
            np.interp(u, self.sigma, self.rho_m),
        )
        zeta = np.where(below, u * self.base_tangent[1], np.interp(u, self.sigma, self.zeta_m))
        return rho, zeta

    def at_u(self, u: FloatArray, phi: FloatArray) -> FloatArray:
        """3D points at path positions ``u`` (m) on meridians ``phi`` (rad)."""
        u, phi = np.broadcast_arrays(np.asarray(u, float), np.asarray(phi, float))
        rho, zeta = self._rz(u.ravel())
        ph = phi.ravel()
        radial = np.cos(ph)[:, None] * self.b1 + np.sin(ph)[:, None] * self.b2
        out: FloatArray = self.base + rho[:, None] * radial + zeta[:, None] * self.axis
        return out

    def _footprint(self, phi: FloatArray) -> FloatArray:
        name = self.primitive.name
        reach = 2.0 * max(float(self.rho_m[0]), self.total)
        # The grid only brackets the crossing (and detects a second one); bisection then
        # finds it to ROOT_TOLERANCE, so a coarse grid gives the same footprint.
        u = np.linspace(-reach, self.total, FOOTPRINT_GRID)
        uu, pp = np.meshgrid(u, phi)
        sd = self.surface.signed_distance(self.at_u(uu, pp)).reshape(uu.shape)
        if np.any(sd[:, 0] >= 0.0):
            raise PrimitiveError(
                f"{name}: the skin does not reach the envelope; the base is too large for "
                "the local envelope curvature"
            )
        if np.any(sd[:, -1] <= 0.0):
            raise PrimitiveError(f"{name}: the tip lies inside the envelope; reduce the lean")
        inside = sd < 0.0
        last = inside.shape[1] - 1 - np.argmax(inside[:, ::-1], axis=1)
        crossings = np.sum(np.diff(inside.astype(np.int8), axis=1) != 0, axis=1)
        if np.any(crossings > 1):
            raise PrimitiveError(
                f"{name}: the skin touches the envelope again; reduce the lean or the size"
            )
        lo, hi = u[last], u[last + 1]
        while float(np.max(hi - lo)) > ROOT_TOLERANCE:
            mid = 0.5 * (lo + hi)
            out = self.surface.signed_distance(self.at_u(mid, phi)) > 0.0
            hi = np.where(out, mid, hi)
            lo = np.where(out, lo, mid)
        u0: FloatArray = 0.5 * (lo + hi)
        if np.any(u0 >= self.total):
            raise PrimitiveError(f"{name}: the footprint reaches the tip")
        return u0

    def u0_at(self, phi: FloatArray) -> FloatArray:
        """Footprint path position on meridians ``phi`` (rad), m (periodic interpolation)."""
        out: FloatArray = np.interp(
            np.mod(phi, 2.0 * math.pi), self.phi, self.u0, period=2.0 * math.pi
        )
        return out

    def u_of(self, t: FloatArray, phi: FloatArray) -> FloatArray:
        """Path position of skin parameter ``t`` in [0, 1] on meridians ``phi``, m."""
        u0 = self.u0_at(phi)
        out: FloatArray = u0 + np.asarray(t, float) * (self.total - u0)
        return out

    def at(self, t: FloatArray, phi: FloatArray) -> FloatArray:
        """3D skin points at parameters ``(t, phi)``, m."""
        t, phi = np.broadcast_arrays(np.asarray(t, float), np.asarray(phi, float))
        return self.at_u(self.u_of(t.ravel(), phi.ravel()), phi.ravel())

    def rim_points(self, phi: FloatArray) -> FloatArray:
        """Footprint points at angles ``phi`` round the axis (rad), m."""
        phi = np.asarray(phi, float)
        return self.at(np.zeros(len(phi)), phi)

    def factory(self, design: PrimitiveDesign, host: HostSurface) -> _SkinFactory:
        """Skin factory of the sub-model (see :func:`primitive_appendage`)."""
        return _SkinFactory(design, host)

    def max_height(self) -> float:
        t, ph = np.meshgrid(np.linspace(0.0, 1.0, 81), self.phi[::4])
        return float(self.surface.signed_distance(self.at(t, ph)).max())


class _Piece:
    """Development of one skin piece between meridians ``phi_a < phi_b``."""

    def __init__(self, skin: _Skin, phi_a: float, phi_b: float) -> None:
        self.skin = skin
        self.phi_a, self.phi_b = phi_a, phi_b
        self.phi_c = 0.5 * (phi_a + phi_b)

    def flat(self, t: FloatArray, phi: FloatArray) -> FloatArray:
        raise NotImplementedError

    def inverse(self, xy: FloatArray) -> tuple[FloatArray, FloatArray]:
        raise NotImplementedError


class _GorePiece(_Piece):
    """Classic gore flattening with sewn-edge equalisation (see module docstring)."""

    def __init__(self, skin: _Skin, phi_a: float, phi_b: float, n_t: int = 161, n_w: int = 49):
        super().__init__(skin, phi_a, phi_b)
        self.t = np.linspace(0.0, 1.0, n_t)
        self.ph = np.linspace(phi_a, phi_b, n_w)
        tt, pp = np.meshgrid(self.t, self.ph, indexing="ij")
        self._params_grid = np.column_stack([tt.ravel(), pp.ravel()])
        grid = skin.at(tt, pp).reshape(n_t, n_w, 3)
        centre = skin.at(self.t, np.full(n_t, self.phi_c))
        y = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(centre, axis=0), axis=1))])
        arc = np.concatenate(
            [np.zeros((n_t, 1)), np.cumsum(np.linalg.norm(np.diff(grid, axis=1), axis=2), axis=1)],
            axis=1,
        )
        mid = np.array([np.interp(self.phi_c, self.ph, a) for a in arc])
        self.classic = np.stack(
            [arc - mid[:, None], np.broadcast_to(y[:, None], arc.shape)], axis=2
        )
        self.seam_3d = (_length(grid[:, 0]), _length(grid[:, -1]))
        self.stretch = (0.0, 0.0)
        self._set(self.classic)

    def _set(self, xy: FloatArray) -> None:
        from scipy.interpolate import RegularGridInterpolator

        self.xy = xy
        self._forward = RegularGridInterpolator(
            (self.t, self.ph), xy, bounds_error=False, fill_value=None
        )
        flat_pts = xy.reshape(-1, 2)
        _, first = np.unique(np.round(flat_pts, 10), axis=0, return_index=True)
        self._pts, self._params = flat_pts[first], self._params_grid[first]

    def edge_lengths(self) -> tuple[float, float]:
        """Flat lengths of the left and right seam edges, m."""
        return _length(self.xy[:, 0]), _length(self.xy[:, -1])

    def equalise(self, left: float, right: float) -> None:
        r"""Shear and stretch the gore to the given seam edge lengths (m).

        :math:`x' = x + \kappa y,\ y' = (1 + \alpha) y`: the shear lengthens one edge and
        shortens the other (area unchanged), the stretch changes both. The rim stays on
        :math:`y = 0` and the apex stays one point. :math:`\alpha, \kappa` are found by
        Newton iteration on the two edge lengths.
        """
        x, y = self.classic[..., 0], self.classic[..., 1]

        def warp(c: FloatArray) -> FloatArray:
            return np.stack([x + c[1] * y, y * (1.0 + c[0])], axis=2)

        def lengths(c: FloatArray) -> FloatArray:
            w = warp(c)
            return np.array([_length(w[:, 0]), _length(w[:, -1])]) - (left, right)

        c = np.zeros(2)
        for _ in range(20):
            f = lengths(c)
            if float(np.abs(f).max()) < 1e-10:
                break
            jac = np.column_stack(
                [
                    (lengths(c + h) - f) / 1e-7
                    for h in (np.array([1e-7, 0.0]), np.array([0.0, 1e-7]))
                ]
            )
            c = c - np.linalg.solve(jac, f)
        self.stretch = (float(c[0]), float(c[1]))
        self._set(warp(c))

    def flat(self, t: FloatArray, phi: FloatArray) -> FloatArray:
        t, phi = np.broadcast_arrays(np.asarray(t, float), np.asarray(phi, float))
        out: FloatArray = self._forward(np.column_stack([t.ravel(), phi.ravel()]))
        return out

    def inverse(self, xy: FloatArray) -> tuple[FloatArray, FloatArray]:
        from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

        val = LinearNDInterpolator(self._pts, self._params)(xy)
        bad = np.isnan(val).any(axis=1)
        if bad.any():
            val[bad] = NearestNDInterpolator(self._pts, self._params)(xy[bad])
        return val[:, 0], val[:, 1]


class _ConePiece(_Piece):
    """Exact development of a frustum (or cylinder) panel about its apex."""

    def __init__(self, skin: _Skin, phi_a: float, phi_b: float) -> None:
        super().__init__(skin, phi_a, phi_b)
        r_b, r_t = float(skin.rho_m[0]), float(skin.rho_m[-1])
        slant = skin.total
        self.sin_g = (r_b - r_t) / slant
        self.cyl = self.sin_g < 1e-9
        self.d_base = 0.0 if self.cyl else r_b / self.sin_g
        self.radius = r_b
        self.shift = 0.0
        rim = self.flat(np.zeros(181), np.linspace(phi_a, phi_b, 181))
        self.shift = float(rim[:, 1].min())

    def flat(self, t: FloatArray, phi: FloatArray) -> FloatArray:
        t, phi = np.broadcast_arrays(np.asarray(t, float), np.asarray(phi, float))
        t, phi = t.ravel(), phi.ravel()
        u = self.skin.u_of(t, phi)
        if self.cyl:
            return np.column_stack([self.radius * (phi - self.phi_c), u - self.shift])
        d = self.d_base - u
        a = (phi - self.phi_c) * self.sin_g
        return np.column_stack([d * np.sin(a), self.d_base - d * np.cos(a) - self.shift])

    def inverse(self, xy: FloatArray) -> tuple[FloatArray, FloatArray]:
        if self.cyl:
            phi = self.phi_c + xy[:, 0] / self.radius
            u = xy[:, 1] + self.shift
        else:
            yy = self.d_base - (xy[:, 1] + self.shift)
            d = np.hypot(xy[:, 0], yy)
            phi = self.phi_c + np.arctan2(xy[:, 0], yy) / self.sin_g
            u = self.d_base - d
        u0 = self.skin.u0_at(phi)
        t = (u - u0) / (self.skin.total - u0)
        return np.clip(t, 0.0, 1.0), phi


# --------------------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------------------


def _axis_frame(
    surface: EnvelopeSurface, placement: Placement, s0: float, theta0: float
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    e_hoop, e_up, normal = surface.frame(s0, theta0)
    lam = math.radians(placement.lean_deg)
    psi = math.radians(placement.lean_toward_deg)
    axis = math.cos(lam) * normal + math.sin(lam) * (math.cos(psi) * e_up + math.sin(psi) * e_hoop)
    axis /= np.linalg.norm(axis)
    b1 = e_up - (e_up @ axis) * axis
    if np.linalg.norm(b1) < 1e-6:  # axis along the tape: start from the hoop direction
        b1 = e_hoop - (e_hoop @ axis) * axis
    b1 /= np.linalg.norm(b1)
    b2 = np.cross(axis, b1)
    return surface.point(np.array([s0]), np.array([theta0]))[0], axis, b1, b2


def _seams(primitive: Primitive) -> FloatArray:
    m = primitive.pieces
    out: FloatArray = 2.0 * math.pi * np.arange(m + 1) / m - math.pi / m
    return out


def _developable(primitive: Primitive) -> bool:
    """True for a straight frustum (a tube, or a revolved profile of one segment)."""
    if isinstance(primitive, Tube):
        return True
    if isinstance(primitive, Revolved) and len(primitive.profile) == 2:
        r_b, r_t = primitive.profile[0][0], primitive.profile[1][0]
        return r_b >= r_t
    return False


def _pieces(skin: _Skin, primitive: Primitive) -> list[_Piece]:
    seams = _seams(primitive)
    pairs = list(zip(seams[:-1], seams[1:], strict=True))
    if _developable(primitive):
        return [_ConePiece(skin, float(a), float(b)) for a, b in pairs]
    gores = [_GorePiece(skin, float(a), float(b)) for a, b in pairs]
    # Both sides of every skin seam are laid at the seam's true 3D length.
    for g in gores:
        g.equalise(*g.seam_3d)
    return list(gores)


def _piece_label(primitive: Primitive, k: int) -> str:
    return f"{primitive.name}-{'G' if primitive.kind in ('dome', 'revolved') else 'P'}{k + 1}"


def _outline(piece: _Piece, n: int = 97) -> tuple[FloatArray, dict[str, FloatArray]]:
    t = np.linspace(0.0, 1.0, n)
    ph = np.linspace(piece.phi_a, piece.phi_b, n)
    rim = piece.flat(np.zeros(n), ph)
    right = piece.flat(t, np.full(n, piece.phi_b))
    top = piece.flat(np.ones(n), ph[::-1])
    left = piece.flat(t[::-1], np.full(n, piece.phi_a))
    edges = {"rim": rim, "right": right, "top": top, "left": left}
    ring = np.vstack([rim[:-1], right[:-1], top[:-1], left[:-1]])
    # A pointed tip (dome apex, horn point) is a single vertex.
    keep = np.ones(len(ring), bool)
    keep[1:] = np.linalg.norm(np.diff(ring, axis=0), axis=1) > 1e-9
    return ring[keep], edges


def _surface_area(skin: _Skin, piece: _Piece, n: int = 121) -> float:
    tt, pp = np.meshgrid(np.linspace(0, 1, n), np.linspace(piece.phi_a, piece.phi_b, n))
    g = skin.at(tt, pp).reshape(n, n, 3)
    a = g[1:, :-1] - g[:-1, :-1]
    b = g[:-1, 1:] - g[:-1, :-1]
    c = g[1:, 1:] - g[1:, :-1]
    d = g[1:, 1:] - g[:-1, 1:]
    return float(
        0.5 * np.linalg.norm(np.cross(a, b), axis=2).sum()
        + 0.5 * np.linalg.norm(np.cross(c, d), axis=2).sum()
    )


def _length(points: FloatArray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _panel_xy(
    surface: EnvelopeSurface, s: FloatArray, g: FloatArray, cell: int, row: int
) -> FloatArray:
    across = g - cell - 0.5
    x = 2.0 * across * surface.half_width(s)
    return np.column_stack([x, s - surface.rows[row].s_bottom])


def _mark_ease(
    surface: EnvelopeSurface,
    g_centre: float,
    mark_phi: FloatArray,
    rim_point: Callable[[FloatArray], FloatArray],
    rim_flat: Callable[[FloatArray], tuple[IntArray, FloatArray]],
    corners: FloatArray | None = None,
    samples: int = MARK_EASE_SAMPLES,
) -> FloatArray:
    r"""Skin rim length minus marked attachment-line length between match marks.

    Both edges of the attachment seam are cut cloth: the skin rim on its pieces and the
    footprint line marked on the flat envelope panels. Flattening the envelope gores
    makes the marked line slightly longer or shorter than the footprint on the designed
    surface, which the rim matches, so the two sides differ by an *ease* that the
    builder works in between match marks. For mark interval :math:`j`

    .. math::

        e_j = \int_{\phi_j}^{\phi_{j+1}} \left|\frac{d\mathbf{r}}{d\phi}\right| d\phi
            - \int_{\phi_j}^{\phi_{j+1}} \left|\frac{d\mathbf{h}}{d\phi}\right| d\phi,

    with :math:`\mathbf{r}(\phi)` the rim on its flat skin piece and
    :math:`\mathbf{h}(\phi)` the footprint point in its envelope panel's pattern
    coordinates, summed over ``samples`` steps per interval plus the ``corners`` of a
    polyline rim (so a free-form rim's chords are followed exactly). A step that crosses
    from one piece or panel to the next uses its 3D length (both sides are sewn there,
    and the step is a few mm).

    Parameters
    ----------
    surface : EnvelopeSurface
        Envelope.
    g_centre : float
        Gore position of the base point, gore widths (fixes the panel numbering).
    mark_phi : ndarray
        Increasing mark angles round the axis in :math:`[0, 2\pi)`, rad.
    rim_point : callable
        Angles (rad) to 3D rim points, m.
    rim_flat : callable
        Angles (rad) to (piece index, flat rim point in that piece, m).
    corners : ndarray, optional
        Angles of the rim's polyline vertices, rad (for a free-form rim).
    samples : int
        Uniform steps per mark interval.

    Returns
    -------
    ndarray
        :math:`e_j` per mark interval, m (positive: the rim is longer).
    """
    n = len(mark_phi)
    nxt = np.append(mark_phi[1:], mark_phi[0] + 2.0 * math.pi)
    extra = np.zeros(0) if corners is None else np.mod(np.asarray(corners, float), 2.0 * math.pi)
    parts, owner = [], []
    for j in range(n):
        a, b = float(mark_phi[j]), float(nxt[j])
        inside = np.concatenate([extra, extra + 2.0 * math.pi])
        grid = np.unique(
            np.concatenate([np.linspace(a, b, samples + 1), inside[(inside > a) & (inside < b)]])
        )
        parts.append(grid)
        owner.append(np.full(len(grid) - 1, j))
    phi = np.concatenate(parts)
    interval = np.concatenate(owner)
    # Steps between consecutive samples of the same interval (not across intervals).
    ends = np.cumsum([len(g) for g in parts])
    step = np.ones(len(phi) - 1, dtype=bool)
    step[ends[:-1] - 1] = False
    p3 = rim_point(phi)
    piece, rim_xy = rim_flat(phi)
    s, theta, _ = surface.locate(p3)
    n_g = surface.gore_count
    g = surface.gore_position(theta)
    g = g_centre + np.mod(g - g_centre + 0.5 * n_g, n_g) - 0.5 * n_g
    cell = np.floor(g).astype(np.int64)
    row = surface.row_index(s)
    host_xy = np.zeros((len(phi), 2))
    panel = cell * (len(surface.rows) + 1) + row
    for key in np.unique(panel):
        sel = panel == key
        c, r = int(cell[sel][0]), int(row[sel][0])
        host_xy[sel] = _panel_xy(surface, s[sel], g[sel], c, r)
    d3 = np.linalg.norm(np.diff(p3, axis=0), axis=1)

    def length(group: IntArray, xy: FloatArray) -> FloatArray:
        d_flat = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        d = np.where(group[1:] == group[:-1], d_flat, d3)[step]
        out: FloatArray = np.bincount(interval, weights=d, minlength=n).astype(np.float64)
        return out

    ease: FloatArray = length(piece, rim_xy) - length(panel, host_xy)
    return ease


def _attachment(
    surface: EnvelopeSurface, s: FloatArray, theta: FloatArray, g_centre: float
) -> list[AttachmentLine]:
    n_g = surface.gore_count
    g = surface.gore_position(theta)
    g = g_centre + np.mod(g - g_centre + 0.5 * n_g, n_g) - 0.5 * n_g
    tops = [r.s_top for r in surface.rows[:-1]]
    pts = [(float(s[0]), float(g[0]))]
    closed_s, closed_g = np.append(s, s[0]), np.append(g, g[0])
    for i in range(len(s)):
        (s_a, g_a), (s_b, g_b) = (closed_s[i], closed_g[i]), (closed_s[i + 1], closed_g[i + 1])
        cuts: list[float] = []
        for k in range(math.floor(min(g_a, g_b)) + 1, math.ceil(max(g_a, g_b))):
            if g_a != g_b:
                cuts.append((k - g_a) / (g_b - g_a))
        for top in tops:
            if (s_a - top) * (s_b - top) < 0.0:
                cuts.append((top - s_a) / (s_b - s_a))
        for f in sorted(c for c in cuts if 0.0 < c < 1.0):
            pts.append((s_a + f * (s_b - s_a), g_a + f * (g_b - g_a)))
        pts.append((float(s_b), float(g_b)))
    arr = np.array(pts)
    mid_s = 0.5 * (arr[:-1, 0] + arr[1:, 0])
    mid_g = 0.5 * (arr[:-1, 1] + arr[1:, 1])
    keys = list(
        zip(np.floor(mid_g).astype(int).tolist(), surface.row_index(mid_s).tolist(), strict=True)
    )
    runs: list[tuple[tuple[int, int], list[int]]] = []
    for i, key in enumerate(keys):
        if runs and runs[-1][0] == key:
            runs[-1][1].append(i + 1)
        else:
            runs.append((key, [i, i + 1]))
    if len(runs) > 1 and runs[0][0] == runs[-1][0]:
        key, idx = runs.pop()
        runs[0] = (key, idx[:-1] + runs[0][1])
    out = []
    for (cell, row), idx in runs:
        sel = arr[idx]
        out.append(
            AttachmentLine(
                gore=cell % n_g + 1,
                row=surface.rows[row].label,
                points=_panel_xy(surface, sel[:, 0], sel[:, 1], cell, row),
            )
        )
    return out


def _host_location(
    surface: EnvelopeSurface, s: float, theta: float, g_centre: float
) -> tuple[int, str, tuple[float, float]]:
    n_g = surface.gore_count
    g = float(surface.gore_position(np.array([theta]))[0])
    g = g_centre + ((g - g_centre + 0.5 * n_g) % n_g) - 0.5 * n_g
    cell = math.floor(g)
    row = int(surface.row_index(np.array([s]))[0])
    xy = _panel_xy(surface, np.array([s]), np.array([g]), cell, row)[0]
    return cell % n_g + 1, surface.rows[row].label, (float(xy[0]), float(xy[1]))


def design_primitive(
    primitive: Primitive,
    surface: EnvelopeSurface,
    seam_allowance: float = 0.0125,
    feed_hole_radius: float | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    samples: int = 720,
) -> PrimitiveDesign:
    """Place a primitive on the envelope and derive its attachment and cutting pattern.

    Parameters
    ----------
    primitive : Dome, Tube or Revolved
        Feature definition, m and deg.
    surface : EnvelopeSurface
        Host envelope (:meth:`EnvelopeSurface.from_design`).
    seam_allowance : float
        Seam allowance added round every skin piece, m.
    feed_hole_radius : float, optional
        Radius of a hole cut in the envelope under the feature to feed it, m.
    tolerance : float
        Length tolerance of the pattern checks, m.
    samples : int
        Footprint samples round the axis.

    Returns
    -------
    PrimitiveDesign
        Footprint, attachment lines, match marks, cutting pattern and checks.

    Raises
    ------
    PrimitiveError
        When the primitive cannot be placed (outside the envelope, touching it again,
        base too large for the local curvature).
    """
    primitive.validate()
    pl = primitive.placement
    if not 1 <= pl.gore <= surface.gore_count:
        raise PrimitiveError(f"{primitive.name}: gore must be within 1..{surface.gore_count}")
    length = surface.profile.meridian_length
    if not 0.0 < pl.tape_position < length:
        raise PrimitiveError(f"{primitive.name}: tape position must be within (0, {length:.3f}) m")
    s0, theta0 = pl.tape_position, surface.theta_at(pl.gore, pl.across)
    base, axis, b1, b2 = _axis_frame(surface, pl, s0, theta0)
    if isinstance(primitive, FreeformShape):
        return _design_freeform(
            primitive,
            surface,
            s0,
            theta0,
            base,
            axis,
            b1,
            b2,
            seam_allowance,
            feed_hole_radius,
            tolerance,
        )
    skin = _Skin(primitive, surface, base, axis, b1, b2, samples)
    fp = skin.at(np.zeros(samples), skin.phi)
    fp_s, fp_theta, _ = surface.locate(fp)
    g_centre = pl.gore - 0.5 + pl.across

    pieces = _pieces(skin, primitive)
    cut: list[CutPiece] = []
    for k, piece in enumerate(pieces):
        finished, edges = _outline(piece)
        cut.append(
            CutPiece(
                label=_piece_label(primitive, k),
                finished=finished,
                cut=offset_polygon(finished, seam_allowance) if seam_allowance > 0 else finished,
                rim=edges.pop("rim"),
                edges=edges,
                surface_area=_surface_area(skin, piece),
            )
        )
    if primitive.closed_tip:
        ang = np.linspace(0.0, 2.0 * math.pi, 192, endpoint=False)
        disc = primitive.tip_radius * np.column_stack([np.cos(ang), np.sin(ang)])
        cut.append(
            CutPiece(
                label=f"{primitive.name}-TIP",
                finished=disc,
                cut=offset_polygon(disc, seam_allowance) if seam_allowance > 0 else disc,
                rim=None,
                edges={"top": np.vstack([disc, disc[:1]])},
                surface_area=math.pi * primitive.tip_radius**2,
            )
        )

    marks = []
    count = primitive.pieces * primitive.marks_per_piece
    seams = _seams(primitive)
    for j in range(count):
        phi = 2.0 * math.pi * j / count
        k = min(int((phi - seams[0]) // (2.0 * math.pi / primitive.pieces)), len(pieces) - 1)
        if phi > pieces[k].phi_b:  # the last piece reaches past 2 pi - pi/M
            phi -= 2.0 * math.pi
        point = skin.at(np.zeros(1), np.array([phi]))
        s_m, th_m, _ = surface.locate(point)
        gore, row, host_xy = _host_location(surface, float(s_m[0]), float(th_m[0]), g_centre)
        pxy = pieces[k].flat(np.zeros(1), np.array([phi]))[0]
        marks.append(
            MatchMark(
                number=j + 1,
                phi_deg=math.degrees(phi % (2.0 * math.pi)),
                gore=gore,
                row=row,
                host_xy=host_xy,
                piece=_piece_label(primitive, k),
                piece_xy=(float(pxy[0]), float(pxy[1])),
            )
        )

    feed = None
    if feed_hole_radius is not None:
        if feed_hole_radius <= 0.0:
            raise PrimitiveError(f"{primitive.name}: feed hole radius must be positive")
        gore, row, centre = _host_location(surface, s0, theta0, g_centre)
        feed = FeedHoleMark(gore, row, centre, feed_hole_radius)

    design = PrimitiveDesign(
        primitive=primitive,
        surface=surface,
        base_s=s0,
        base_theta=theta0,
        base_point=base,
        axis=axis,
        b1=b1,
        b2=b2,
        footprint_phi=skin.phi,
        footprint_points=fp,
        footprint_s=fp_s,
        footprint_theta=fp_theta,
        pieces=cut,
        attachment=_attachment(surface, fp_s, fp_theta, g_centre),
        marks=marks,
        feed_hole=feed,
        checks=[],
        _skin=skin,
    )
    phi_0 = pieces[0].phi_a
    bounds = np.array([p.phi_b for p in pieces])

    def rim_flat(phi: FloatArray) -> tuple[IntArray, FloatArray]:
        pm = phi_0 + np.mod(phi - phi_0, 2.0 * math.pi)
        k = np.minimum(np.searchsorted(bounds, pm), len(pieces) - 1)
        xy = np.zeros((len(pm), 2))
        for kk in np.unique(k):
            sel = k == kk
            xy[sel] = pieces[int(kk)].flat(np.zeros(int(sel.sum())), pm[sel])
        return k, xy

    design.mark_ease = _mark_ease(
        surface,
        g_centre,
        2.0 * math.pi * np.arange(count) / count,
        lambda phi: skin.at(np.zeros(len(phi)), phi),
        rim_flat,
    )
    design.checks = _checks(design, pieces, tolerance)
    return design


def _checks(design: PrimitiveDesign, pieces: list[_Piece], tol: float) -> list[DesignCheck]:
    p, skin, surface = design.primitive, design._skin, design.surface
    out: list[DesignCheck] = []

    def check(
        name: str, value: float, limit: float, unit: str, bad: CheckSeverity, msg: str
    ) -> None:
        out.append(DesignCheck(name, value, limit, unit, "info" if value <= limit else bad, msg))

    length = surface.profile.meridian_length
    s_lo, s_hi = float(design.footprint_s.min()), float(design.footprint_s.max())
    clearance = min(s_lo, length - s_hi)
    out.append(
        DesignCheck(
            "footprint between mouth and crown",
            clearance,
            0.0,
            "m",
            "info" if clearance > 0.0 else "error",
            f"footprint spans tape positions {s_lo:.3f}-{s_hi:.3f} m of {length:.3f} m",
        )
    )
    rim = sum(_length(c.rim) for c in design.pieces if c.rim is not None)
    check(
        "rim length",
        abs(rim - design.footprint_length),
        tol,
        "m",
        "error",
        f"skin rim {rim:.4f} m against footprint {design.footprint_length:.4f} m",
    )
    if len(design.mark_ease):
        line = sum(a.length for a in design.attachment)
        worst = float(np.abs(design.mark_ease).max())
        check(
            "attachment ease",
            worst,
            tol,
            "m",
            "error",
            "largest difference between the skin rim and the line marked on the flat "
            f"envelope panels between two match marks ({worst * 1000:.1f} mm; in total rim "
            f"{rim:.4f} m against marked line {line:.4f} m, {(rim - line) * 1000:+.1f} mm "
            f"eased over {len(design.mark_ease)} mark intervals; more match marks per piece "
            "spread it further)",
        )
    m = len(pieces)
    worst_pair, worst_flat = 0.0, 0.0
    t = np.linspace(0.0, 1.0, 241)
    for j in range(m if m > 1 else 0):
        a, b = design.pieces[j], design.pieces[(j + 1) % m]
        worst_pair = max(worst_pair, abs(_length(a.edges["right"]) - _length(b.edges["left"])))
        phi = pieces[j].phi_b
        seam3d = (
            skin.seam_length(j + 1)
            if isinstance(p, FreeformShape)
            else _length(skin.at(t, np.full(len(t), phi)))
        )
        worst_flat = max(
            worst_flat,
            abs(_length(a.edges["right"]) / seam3d - 1.0),
            abs(_length(b.edges["left"]) / seam3d - 1.0),
        )
    if m == 1:  # a single tube panel is sewn to itself along one seam
        c = design.pieces[0]
        worst_pair = abs(_length(c.edges["right"]) - _length(c.edges["left"]))
    check(
        "skin seam match",
        worst_pair,
        tol,
        "m",
        "error",
        "largest length difference between the two sides of a skin seam",
    )
    check(
        "seam flattening",
        worst_flat,
        SEAM_FLATTENING_LIMIT,
        "-",
        "warning",
        "largest relative difference between a flat seam edge and the designed 3D seam "
        + (
            "(flattening a doubly curved piece changes its seams, so the sewn dome is "
            "fuller than designed; more gores reduce it, the simulation predicts it)"
            if not _developable(p)
            else "(frustum panels are exact developments)"
        ),
    )
    distortion = max(
        abs(c.flat_area / c.surface_area - 1.0) for c in design.pieces if c.surface_area > 0
    )
    check(
        "area distortion",
        distortion,
        AREA_DISTORTION_LIMIT,
        "-",
        "warning",
        "largest relative difference between a piece's flat and designed area",
    )
    crossed = sorted({a.gore for a in design.attachment})
    rows = sorted({a.row for a in design.attachment})
    out.append(
        DesignCheck(
            "host panels",
            float(len(design.attachment)),
            0.0,
            "-",
            "info",
            f"footprint crosses gores {crossed} and rows {rows}; mark it on every listed "
            "panel before assembly",
        )
    )
    if design.feed_hole is not None:
        hole = design.feed_hole
        e_hoop, e_up, _ = surface.frame(design.base_s, design.base_theta)
        rel = design.footprint_points - design.base_point
        loop = np.column_stack([rel @ e_hoop, rel @ e_up])
        ang = np.linspace(0.0, 2.0 * math.pi, 64, endpoint=False)
        ring = hole.radius * np.column_stack([np.cos(ang), np.sin(ang)])
        inside = bool(points_in_polygon(ring, loop).all())
        out.append(
            DesignCheck(
                "feed hole inside footprint",
                0.0 if inside else 1.0,
                0.0,
                "-",
                "info" if inside else "error",
                f"feed hole of radius {hole.radius:.3f} m at the base point",
            )
        )
    return out


# --------------------------------------------------------------------------------------
# Analysis model
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EnvelopeHost(HostSurface):
    r"""The true envelope round a primitive, in the host chart and frame of the builder.

    The chart is :math:`u = r(s)\,\Delta\theta` (true hoop arc), :math:`v = s - s_0`
    (true meridian arc); the frame puts the base point at :math:`(0, 0, z_0)` with the
    hoop direction along :math:`+y` (:class:`~envelopelab.features.builder.HostSurface`).
    The inherited radii are the local values at the base point and only set the
    far-field prestress of the patch (:func:`~envelopelab.features.builder.shell_prestress`).
    """

    design: PrimitiveDesign | None = field(default=None, compare=False, repr=False)

    def _d(self) -> PrimitiveDesign:
        assert self.design is not None
        return self.design

    def _rotation(self) -> FloatArray:
        c, si = math.cos(-self._d().base_theta), math.sin(-self._d().base_theta)
        return np.array([[c, -si, 0.0], [si, c, 0.0], [0.0, 0.0, 1.0]])

    def hoop_radius_at(self, v: float) -> float:
        """Distance of the parallel at chart height ``v`` (m) from the axis, m."""
        d = self._d()
        return float(d.surface.radius_height(np.array([d.base_s + v]))[0][0])

    def map(self, uv: FloatArray) -> FloatArray:
        """3D positions of chart points (m), shape (n, 3)."""
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        return _to_host_frame(self._d(), _from_chart(self._d(), uv))

    def _theta_s(self, uv: FloatArray) -> tuple[FloatArray, FloatArray]:
        d = self._d()
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        s = d.base_s + uv[:, 1]
        r, _ = d.surface.radius_height(s)
        return d.base_theta + uv[:, 0] / r, s

    def normal(self, uv: FloatArray) -> FloatArray:
        """Outward unit normals at chart points, shape (n, 3)."""
        d = self._d()
        theta, s = self._theta_s(uv)
        dr = np.interp(s, d.surface.profile.s, d.surface._dr)
        dz = np.interp(s, d.surface.profile.s, d.surface._dz)
        n = np.column_stack([dz * np.cos(theta), dz * np.sin(theta), -dr])
        out: FloatArray = (n / np.linalg.norm(n, axis=1)[:, None]) @ self._rotation().T
        return out

    def tangent_u(self, uv: FloatArray) -> FloatArray:
        """Unit hoop tangents at chart points, shape (n, 3)."""
        theta, _ = self._theta_s(uv)
        t = np.column_stack([-np.sin(theta), np.cos(theta), np.zeros(len(theta))])
        out: FloatArray = t @ self._rotation().T
        return out

    def height_above(self, points: FloatArray) -> FloatArray:
        """Signed distance of 3D points (host frame) from the envelope, m."""
        d = self._d()
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3).copy()
        r0, _ = d.surface.radius_height(np.array([d.base_s]))
        p[:, 0] += float(r0[0])
        return d.surface.signed_distance(p @ self._rotation())


def host_surface_at(design: PrimitiveDesign, window: float = 0.25) -> EnvelopeHost:
    r"""Host of a primitive's sub-model: the true envelope round the base point.

    The local radii (for the far-field prestress only) are :math:`R_1`, the meridian
    radius of curvature from the tangent-angle change over ``base_s +- window``, and
    :math:`R_2 = r/\cos\beta`.

    Parameters
    ----------
    design : PrimitiveDesign
        Placed primitive.
    window : float
        Half the tape length over which :math:`R_1` is measured, m.

    Returns
    -------
    EnvelopeHost
        Host with its chart origin at the base point.
    """
    surface, s0 = design.surface, design.base_s
    prof = surface.profile
    lo, hi = max(0.0, s0 - window), min(prof.meridian_length, s0 + window)
    dr = np.interp([lo, s0, hi], prof.s, surface._dr)
    dz = np.interp([lo, s0, hi], prof.s, surface._dz)
    ang = np.unwrap(np.arctan2(dz, dr))
    curvature = float(ang[2] - ang[0]) / max(hi - lo, 1e-12)
    if curvature <= 1e-9:
        raise PrimitiveError(
            f"{design.primitive.name}: the envelope is not convex round the feature"
        )
    beta = math.atan2(-float(dr[1]), float(dz[1]))
    r0, z0 = surface.radius_height(np.array([s0]))
    return EnvelopeHost(
        meridian_radius=1.0 / curvature,
        hoop_radius=float(r0[0]) / math.cos(beta),
        normal_elevation=beta,
        centre_height=float(z0[0]),
        source="design envelope (surface of revolution of the load-tape meridian)",
        design=design,
    )


def _chart(design: PrimitiveDesign, s: FloatArray, theta: FloatArray) -> FloatArray:
    r"""Host-chart coordinates of envelope points (tape position m, azimuth rad), m.

    :math:`v = s - s_0` is the true meridian arc and :math:`u = r(s)\,\Delta\theta` the
    true hoop arc, so lengths on the envelope carry over to the host patch.
    """
    v = np.asarray(s, float) - design.base_s
    dth = np.mod(np.asarray(theta, float) - design.base_theta + math.pi, 2.0 * math.pi) - math.pi
    r, _ = design.surface.radius_height(np.asarray(s, float))
    return np.column_stack([r * dth, v])


def _from_chart(design: PrimitiveDesign, chart: FloatArray) -> FloatArray:
    """Envelope points (m) of host-chart coordinates (inverse of :func:`_chart`)."""
    s = design.base_s + chart[:, 1]
    r, _ = design.surface.radius_height(s)
    return design.surface.point(s, design.base_theta + chart[:, 0] / r)


def _to_host_frame(design: PrimitiveDesign, points: FloatArray) -> FloatArray:
    c, si = math.cos(-design.base_theta), math.sin(-design.base_theta)
    rot = np.array([[c, -si, 0.0], [si, c, 0.0], [0.0, 0.0, 1.0]])
    out: FloatArray = points @ rot.T
    r0, _ = design.surface.radius_height(np.array([design.base_s]))
    out[:, 0] -= float(r0[0])
    return out


def _chord_rest(skin: _Skin, rest: FloatArray, par: FloatArray, samples: int = 9) -> FloatArray:
    r"""Rest triangles of flat facets standing in for curved cloth.

    A triangle's sides are chords of the designed surface while the cut cloth between
    its corners follows the surface, so each flat side length is scaled by
    chord / arc of the same path on the designed surface. That keeps the pattern's
    own strain (flat against designed) and removes the faceting excess
    :math:`pprox (\kappa h)^2/24` that would otherwise read as slack cloth; the factor
    tends to 1 as the mesh is refined.

    Parameters
    ----------
    skin : _Skin
        Designed skin.
    rest : ndarray, shape (m, 3, 2)
        Flat corner coordinates, m.
    par : ndarray, shape (m, 3, 2)
        Corner parameters :math:`(t, \phi)`.
    samples : int
        Points along each side for its arc length.

    Returns
    -------
    ndarray, shape (m, 3, 2)
        Corrected rest triangles, m (corner 0 and the direction of side 01 kept).
    """
    f = np.linspace(0.0, 1.0, samples)
    lengths = np.empty((len(rest), 3))
    for k, (a, b) in enumerate(((0, 1), (1, 2), (2, 0))):
        pa, pb = par[:, a], par[:, b]
        path = pa[:, None, :] + f[None, :, None] * (pb - pa)[:, None, :]
        pts = skin.at(path[..., 0].ravel(), path[..., 1].ravel()).reshape(len(rest), samples, 3)
        arc = np.linalg.norm(np.diff(pts, axis=1), axis=2).sum(axis=1)
        chord = np.linalg.norm(pts[:, -1] - pts[:, 0], axis=1)
        flat = np.linalg.norm(rest[:, b] - rest[:, a], axis=1)
        lengths[:, k] = flat * np.divide(chord, arc, out=np.ones_like(arc), where=arc > 1e-12)
    l01, l12, l20 = lengths.T
    out = rest.copy()
    e = rest[:, 1] - rest[:, 0]
    e /= np.linalg.norm(e, axis=1)[:, None]
    n = np.column_stack([-e[:, 1], e[:, 0]])
    x2 = (l01**2 + l20**2 - l12**2) / (2.0 * l01)
    y2 = np.sqrt(np.clip(l20**2 - x2**2, 0.0, None))
    ok = (l01 + l12 > l20) & (l12 + l20 > l01) & (l20 + l01 > l12)
    out[ok, 1] = rest[ok, 0] + l01[ok, None] * e[ok]
    out[ok, 2] = rest[ok, 0] + x2[ok, None] * e[ok] + y2[ok, None] * n[ok]
    return out


@dataclass
class _SkinFactory:
    """Meshes the as-cut pieces round the conformed footprint loop (see the builder).

    Every piece is triangulated in its own flat pattern coordinates, so the triangles'
    rest shapes are the cut cloth. Seam, rim, tip and apex nodes are shared between the
    pieces that meet there; interior nodes are placed on the designed shape through the
    inverse of the piece's development.
    """

    design: PrimitiveDesign
    host: HostSurface

    def _seam_ts(self, phi: float, size: float) -> FloatArray:
        dense = np.linspace(0.0, 1.0, 401)
        pts = self.design._skin.at(dense, np.full(len(dense), phi))
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        count = max(2, int(math.ceil(arc[-1] / size)))
        out: FloatArray = np.interp(np.linspace(0.0, arc[-1], count + 1), arc, dense)
        return out

    def __call__(self, rim_chart: FloatArray, size: float) -> DesignedSkin:
        design, skin = self.design, self.design._skin
        prim = design.primitive
        pieces = _pieces(skin, prim)
        m = len(pieces)
        seams = _seams(prim)
        width = 2.0 * math.pi / m
        notes: list[str] = []
        rel = _from_chart(design, rim_chart) - design.base_point
        radial = rel - np.outer(rel @ design.axis, design.axis)
        phi_rel = np.mod(np.arctan2(rel @ design.b2, rel @ design.b1) - seams[0], 2.0 * math.pi)
        # The footprint node on every skin seam (the nearest one where conforming the
        # footprint to a host tape crossing moved it).
        seam_node: list[int] = []
        for j in range(m):
            gap = np.abs(np.mod(phi_rel - j * width + math.pi, 2.0 * math.pi) - math.pi)
            k = int(np.argmin(gap))
            off = float(gap[k] * np.linalg.norm(radial[k]))
            if off > 1e-6:
                notes.append(
                    f"skin seam {j + 1} meets the footprint {off * 1000:.0f} mm from its "
                    "design position (a host tape crosses nearby)"
                )
            seam_node.append(k)
        if len(set(seam_node)) != m:
            raise FeatureBuildError(f"{prim.name}: skin seams too close for the mesh size")
        for j, k in enumerate(seam_node):
            phi_rel[k] = j * width
        seam_set = set(seam_node)

        closed = prim.closed_tip
        per = 0
        tip_phi: FloatArray = np.zeros(0)
        if closed:
            per = max(1, int(math.ceil(prim.tip_radius * width / size)))
            tip_phi = seams[0] + width * np.arange(m * per) / per
        seam_t = [self._seam_ts(float(seams[j]), size) for j in range(m)]

        keys: dict[tuple[Any, ...], int] = {}
        positions: list[FloatArray] = []
        tris: list[IntArray] = []
        rests: list[FloatArray] = []
        grains: list[FloatArray] = []
        seam_edges: dict[str, IntArray] = {}

        params: list[tuple[float, float]] = []

        def node(key: tuple[Any, ...], t: float, phi: float) -> int:
            if key not in keys:
                keys[key] = len(positions)
                positions.append(skin.at(np.array([t]), np.array([phi]))[0])
                params.append((t, phi))
            return keys[key]

        for k, piece in enumerate(pieces):
            j_b = (k + 1) % m
            inner = sorted(
                (
                    i
                    for i in range(len(rim_chart))
                    if i not in seam_set and k * width <= phi_rel[i] < (k + 1) * width
                ),
                key=lambda i: float(phi_rel[i]),
            )
            rim: list[_Entry] = [(("rim", seam_node[k]), 0.0, piece.phi_a)]
            rim += [(("rim", i), 0.0, float(seams[0] + phi_rel[i])) for i in inner]
            rim.append((("rim", seam_node[j_b]), 0.0, piece.phi_b))
            right: list[_Entry] = [
                (("seam", j_b, q), float(t), piece.phi_b)
                for q, t in enumerate(seam_t[j_b][1:-1], 1)
            ]
            top: list[_Entry]
            if closed:
                top = [(("tip", (k + 1) * per % (m * per)), 1.0, piece.phi_b)]
                top += [
                    (("tip", k * per + i), 1.0, float(tip_phi[k * per + i]))
                    for i in reversed(range(per))
                ]
            else:
                top = [(("apex",), 1.0, piece.phi_c)]
            left: list[_Entry] = [
                (("seam", k, q), float(t), piece.phi_a)
                for q, t in reversed(list(enumerate(seam_t[k][1:-1], 1)))
            ]
            boundary = rim + right + top + left
            flat_b = np.array(
                [piece.flat(np.array([t]), np.array([ph]))[0] for _, t, ph in boundary]
            )
            xy, tri = _mesh_disc(flat_b, size)
            dist, hit = cKDTree(xy).query(flat_b)
            scale = max(1.0, float(np.ptp(flat_b)))
            if np.any(dist > 1e-6 * scale) or len(set(hit.tolist())) != len(hit):
                raise FeatureBuildError(f"{prim.name}: piece {k + 1} boundary was not kept")
            local = np.full(len(xy), -1, dtype=np.int64)
            for (key, t, ph), h in zip(boundary, hit, strict=True):
                local[h] = node(key, t, ph)
            free = np.flatnonzero(local < 0)
            if len(free):
                t_f, ph_f = piece.inverse(xy[free])
                local[free] = len(positions) + np.arange(len(free))
                positions.extend(skin.at(t_f, ph_f))
                params.extend(zip(t_f.tolist(), ph_f.tolist(), strict=True))
            # Node parameters as this piece sees them (the apex angle is the piece's).
            par = np.array([params[g] for g in local])
            for (key, _, ph), h in zip(boundary, hit, strict=True):
                if key[0] == "apex":
                    par[h] = (1.0, ph)
            tris.append(local[tri])
            rests.append(_chord_rest(skin, xy[tri], par[tri]))
            grains.append(np.tile([0.0, 1.0], (len(tri), 1)))
            chain = [keys[e[0]] for e in [rim[-1], *right, top[0]]]
            if m > 1 or k == 0:
                seam_edges[f"{prim.name}:seam {j_b + 1}"] = np.column_stack([chain[:-1], chain[1:]])
        if closed:
            ring = prim.tip_radius * np.column_stack([np.cos(tip_phi), np.sin(tip_phi)])
            xy, tri = _mesh_disc(ring, size)
            _, hit = cKDTree(xy).query(ring)
            local = np.full(len(xy), -1, dtype=np.int64)
            for i, h in enumerate(hit):
                local[h] = node(("tip", i), 1.0, float(tip_phi[i]))
            free = np.flatnonzero(local < 0)
            centre = design.base_point + prim.tip_height * design.axis
            local[free] = len(positions) + np.arange(len(free))
            positions.extend(
                centre + np.outer(xy[free, 0], design.b1) + np.outer(xy[free, 1], design.b2)
            )
            tris.append(local[tri])
            rests.append(xy[tri])
            grains.append(np.tile([1.0, 0.0], (len(tri), 1)))
            ids = local[hit]
            seam_edges[f"{prim.name}:tip seam"] = np.column_stack([ids, np.roll(ids, -1)])
        rim_index = np.array([keys[("rim", i)] for i in range(len(rim_chart))], dtype=np.int64)
        return DesignedSkin(
            positions=_to_host_frame(design, np.array(positions)),
            triangles=np.concatenate(tris),
            rest_uv=np.concatenate(rests),
            grain=np.concatenate(grains),
            rim_index=rim_index,
            seams=seam_edges,
            notes=notes,
        )


def primitive_appendage(
    design: PrimitiveDesign,
    mesh_size: float = 0.15,
    margin: float | None = None,
    load_tape: TapeMaterial | None = None,
    row_tape: TapeMaterial | None = None,
    rim_tape: TapeMaterial | None = None,
    hem_tape: TapeMaterial | None = None,
    pressure: PressureSpec | None = None,
    host_zone: str = "host",
    skin_zone: str = "skin",
) -> AppendageSpec:
    """Sub-model specification of a placed primitive with its as-cut skin.

    The skin rests in the flat shapes of its cut pieces (:class:`CutPiece`, finished
    lines), sewn along their seams and to the envelope along the footprint; the host is
    a patch of the envelope round the footprint with its load tapes (gore seams) and,
    optionally, horizontal row tapes. Build it with
    :func:`~envelopelab.features.builder.build_appendage` and solve it like any other
    appendage.

    Parameters
    ----------
    design : PrimitiveDesign
        Placed primitive (:func:`design_primitive`).
    mesh_size : float
        Target element size, m.
    margin : float, optional
        Host patch margin round the footprint, m (default half the footprint's larger
        side).
    load_tape, row_tape, rim_tape, hem_tape : TapeMaterial, optional
        Vertical load tapes, horizontal row tapes, the tape round the footprint and the
        feed-hole hem; ``None`` leaves that tape out.
    pressure : PressureSpec, optional
        Chamber pressure; default ``fed`` (loss factor 0.1, assumed) through the design's
        feed hole.
    host_zone, skin_zone : str
        Material zones of the envelope patch and the skin.

    Returns
    -------
    AppendageSpec
        Specification with ``skin_mode="designed"``.
    """
    prim = design.primitive
    skin = design._skin
    # Footprint nodes: every skin seam plus an even subdivision of each piece's rim.
    seams = _seams(prim)
    phis: list[float] = []
    for a, b in zip(seams[:-1], seams[1:], strict=True):
        arc = _length(skin.rim_points(np.linspace(a, b, 65)))
        count = max(2, int(math.ceil(arc / mesh_size)))
        phis += list(np.linspace(a, b, count, endpoint=False))
    phi = np.array(phis)
    s, theta, _ = design.surface.locate(skin.rim_points(phi))
    host = host_surface_at(design)
    chart = _chart(design, s, theta)
    lo, hi = chart.min(axis=0), chart.max(axis=0)
    margin = margin if margin is not None else 0.5 * float((hi - lo).max())
    rect = (lo[0] - margin, lo[1] - margin, hi[0] + margin, hi[1] + margin)
    tapes: list[HostTape] = []
    if load_tape is not None:
        # Load tape k runs along the seam between gores k and k + 1 (seam 0: N and 1).
        v = np.linspace(rect[1], rect[3], 41)
        surface = design.surface
        for k in range(surface.gore_count):
            th = k * surface.gore_angle
            dth = (th - design.base_theta + math.pi) % (2.0 * math.pi) - math.pi
            if abs(dth) > 0.5 * math.pi:
                continue
            line = _chart(design, design.base_s + v, np.full(len(v), th))
            inside = (line[:, 0] > rect[0]) & (line[:, 0] < rect[2])
            if inside.sum() >= 2:
                tapes.append(HostTape(f"load tape {k}", line[inside], load_tape))
    if row_tape is not None:
        for band in design.surface.rows[:-1]:
            v_k = band.s_top - design.base_s
            if rect[1] < v_k < rect[3]:
                u = np.linspace(rect[0], rect[2], 41)
                tapes.append(
                    HostTape(
                        f"row seam {band.label}", np.column_stack([u, np.full(41, v_k)]), row_tape
                    )
                )
    holes = []
    if design.feed_hole is not None:
        holes.append(ChartHole("feed", (0.0, 0.0), design.feed_hole.radius, hem_tape))
    if pressure is None:
        if not holes:
            raise PrimitiveError(
                f"{prim.name}: a fed feature needs a feed hole (feed_hole_radius) or an "
                "explicit pressure specification"
            )
        pressure = PressureSpec("fed", 0.1)
    return AppendageSpec(
        name=prim.name,
        footprint=chart,
        skin_mode="designed",
        skin_mesh=skin.factory(design, host),
        match_points=prim.pieces * prim.marks_per_piece,
        match_start=(0.0, 1.0),
        host=host,
        margin=margin,
        mesh_size=mesh_size,
        host_zone=host_zone,
        skin_zone=skin_zone,
        rim_tape=RimTapeSpec(rim_tape) if rim_tape is not None else None,
        host_tapes=tapes,
        holes=holes,
        pressure=pressure,
        intended={"projected_height_m": design.designed_height},
    )


def _design_freeform(
    shape: FreeformShape,
    surface: EnvelopeSurface,
    s0: float,
    theta0: float,
    base: FloatArray,
    axis: FloatArray,
    b1: FloatArray,
    b2: FloatArray,
    seam_allowance: float,
    feed_hole_radius: float | None,
    tolerance: float,
) -> PrimitiveDesign:
    """:func:`design_primitive` for a free-form mesh shape."""
    from envelopelab.features.freeform import (
        EDGE_STRAIN_LIMIT,
        build_mesh_skin,
        cut_outline,
        panel_outline,
    )

    try:
        skin = build_mesh_skin(shape, surface, base, axis, b1, b2)
    except FeatureBuildError as exc:
        raise PrimitiveError(str(exc)) from exc
    order = np.argsort(np.mod(skin.rim_phi, 2.0 * math.pi))
    fp = skin.x[skin.rim_loop][order]
    fp_phi = np.mod(skin.rim_phi, 2.0 * math.pi)[order]
    fp_s, fp_theta, _ = surface.locate(fp)
    g_centre = shape.placement.gore - 0.5 + shape.placement.across
    pieces: list[CutPiece] = []
    strain = 0.0
    for k, panel in enumerate(skin.panels):
        finished, edges = panel_outline(panel)
        e3 = panel.x[panel.tri]
        ef = panel.flat[panel.tri]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            l3 = np.linalg.norm(e3[:, a] - e3[:, b], axis=1)
            lf = np.linalg.norm(ef[:, a] - ef[:, b], axis=1)
            strain = max(strain, float(np.abs(lf / l3 - 1.0).max()))
        area = 0.5 * float(
            np.linalg.norm(np.cross(e3[:, 1] - e3[:, 0], e3[:, 2] - e3[:, 0]), axis=1).sum()
        )
        pieces.append(
            CutPiece(
                label=_piece_label(shape, k),
                finished=finished,
                cut=cut_outline(finished, seam_allowance),
                rim=edges.pop("rim"),
                edges=edges,
                surface_area=area,
            )
        )
    marks = []
    count = shape.pieces * shape.marks_per_piece
    for j in range(count):
        phi = 2.0 * math.pi * j / count
        point = skin.rim_points(np.array([phi]))
        s_m, th_m, _ = surface.locate(point)
        gore, row, host_xy = _host_location(surface, float(s_m[0]), float(th_m[0]), g_centre)
        k = skin.panel_of(phi)
        pxy = skin.rim_flat(k, np.array([phi]))[0]
        marks.append(
            MatchMark(
                number=j + 1,
                phi_deg=math.degrees(phi),
                gore=gore,
                row=row,
                host_xy=host_xy,
                piece=_piece_label(shape, k),
                piece_xy=(float(pxy[0]), float(pxy[1])),
            )
        )
    feed = None
    if feed_hole_radius is not None:
        if feed_hole_radius <= 0.0:
            raise PrimitiveError(f"{shape.name}: feed hole radius must be positive")
        gore, row, centre = _host_location(surface, s0, theta0, g_centre)
        feed = FeedHoleMark(gore, row, centre, feed_hole_radius)
    design = PrimitiveDesign(
        primitive=shape,
        surface=surface,
        base_s=s0,
        base_theta=theta0,
        base_point=base,
        axis=axis,
        b1=b1,
        b2=b2,
        footprint_phi=fp_phi,
        footprint_points=fp,
        footprint_s=fp_s,
        footprint_theta=fp_theta,
        pieces=pieces,
        attachment=_attachment(surface, fp_s, fp_theta, g_centre),
        marks=marks,
        feed_hole=feed,
        checks=[],
        _skin=skin,
    )

    def rim_flat(phi: FloatArray) -> tuple[IntArray, FloatArray]:
        k = np.array([skin.panel_of(float(p)) for p in phi], dtype=np.int64)
        xy = np.zeros((len(phi), 2))
        for kk in np.unique(k):
            sel = k == kk
            xy[sel] = skin.rim_flat(int(kk), phi[sel])
        return k, xy

    design.mark_ease = _mark_ease(
        surface,
        g_centre,
        2.0 * math.pi * np.arange(count) / count,
        skin.rim_points,
        rim_flat,
        corners=skin.rim_phi,
    )
    checks = _checks(design, skin.panels, tolerance)  # type: ignore[arg-type]
    checks.append(
        DesignCheck(
            "edge strain",
            strain,
            EDGE_STRAIN_LIMIT,
            "-",
            "info" if strain <= EDGE_STRAIN_LIMIT else "warning",
            "largest relative difference between a flat triangle side and the same side "
            "on the mesh (use more panels to reduce it)",
        )
    )
    design.checks = checks
    return design
