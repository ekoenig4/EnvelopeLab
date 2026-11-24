"""Fitting a revolved profile to a mesh shape that is round about its axis.

A free-form shape (:class:`envelopelab.features.primitives.FreeformShape`) is a closed
triangle mesh in its own frame: :math:`z` along the axis out of the envelope, origin at
the base point. When the mesh is (nearly) a surface of revolution about that axis, such
as a stalk with a ball on top, it can be replaced by a revolved shape, which is cut into
gores with exact seam lengths, can be split across and is edited by its profile.

Method
------
1. **Top.** The profile ends where the axis leaves the mesh, at height :math:`z_t`: the
   largest :math:`z` of the triangles whose plan view contains the axis.
2. **Sections.** The mesh is cut by planes :math:`z = h` for :data:`SECTIONS` heights
   from the base circle (:math:`h = 0`) to just below :math:`z_t`. Each cut is a set of
   segments; the section's radius is their length-weighted mean distance from the axis,

   .. math:: \\bar\\rho(h) = \\frac{\\sum_j \\ell_j\\, \\tfrac12(\\rho_{j,0} +
             \\rho_{j,1})}{\\sum_j \\ell_j}.

3. **Points.** The curve :math:`(\\bar\\rho(h), h)`, closed by :math:`(0, z_t)`, is
   resampled at ``points`` points equally spaced along its arc length (the base point and
   the tip included).
4. **Deviation.** Every mesh vertex with :math:`z \\ge 0` is compared with the revolved
   surface of the fitted profile: its distance in the meridian plane,
   :math:`(\\sqrt{x^2 + y^2}, z)`, to the drawn profile curve. The largest and RMS
   distances measure both the fit and how far the mesh is from round; they are reported,
   never hidden.

Assumptions and valid range: the axis is the frame's :math:`z` axis through the base
point (how a mesh shape is placed); each section is one loop round the axis. A mesh that
is not round (an ear, a face) or that overhangs (a mushroom cap) gives a large deviation:
:data:`ROUND_TOLERANCE` says when to warn.

References: plane sections of a triangle mesh as in J. O'Rourke, *Computational
Geometry in C*, 2nd ed., Cambridge University Press, 1998; surfaces of revolution and
their meridians as in M. P. do Carmo, *Differential Geometry of Curves and Surfaces*,
Prentice-Hall, 1976.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from envelopelab.features.primitives import Placement, PrimitiveError, Revolved
from envelopelab.geometry.profile_editing import FloatArray

#: Number of section heights cut through the mesh (source: assumed; dense enough that the
#: resampled points follow the mesh, cheap for meshes of thousands of triangles).
SECTIONS = 240
#: A fit whose largest deviation exceeds this fraction of the widest radius is reported
#: as "not round" (source: assumed; 5 % is about what a builder sees by eye).
ROUND_TOLERANCE = 0.05
#: Fewest profile points of a fit (source: assumed; base, one interior point, tip).
MIN_POINTS = 3


@dataclass(frozen=True)
class ProfileFit:
    """A revolved profile fitted to a mesh shape.

    Attributes
    ----------
    profile : tuple of (float, float)
        Profile points :math:`(\\rho, \\zeta)`, m, base first, ending on the axis.
    smooth : bool
        Whether the points are joined by a spline (False when a spline would cross the
        axis; then by straight segments).
    max_deviation : float
        Largest distance of a mesh vertex from the revolved surface, m.
    rms_deviation : float
        Root-mean-square distance of the mesh vertices from it, m.
    deviation_height : float
        Height of the vertex furthest from it, m.
    widest_radius : float
        Largest radius of the fitted profile, m.
    """

    profile: tuple[tuple[float, float], ...]
    smooth: bool
    max_deviation: float
    rms_deviation: float
    deviation_height: float
    widest_radius: float

    @property
    def relative_deviation(self) -> float:
        """Largest deviation over the widest radius, dimensionless."""
        return self.max_deviation / self.widest_radius

    @property
    def round(self) -> bool:
        """Whether the mesh is round about its axis within :data:`ROUND_TOLERANCE`."""
        return self.relative_deviation <= ROUND_TOLERANCE


def axis_top(vertices: FloatArray, triangles: np.ndarray) -> float:
    """Height where the frame's :math:`z` axis leaves the mesh, m.

    Raises
    ------
    ValueError
        When the axis does not pass through the mesh above the base.
    """
    tri = vertices[triangles]
    a, b, c = tri[:, 0, :2], tri[:, 1, :2], tri[:, 2, :2]
    det = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    ok = np.abs(det) > 1e-18
    # Triangles seen edge-on from above cannot contain the axis in plan.
    safe = np.where(ok, det, 1.0)
    u = ((-a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (-a[:, 1])) / safe
    v = ((b[:, 0] - a[:, 0]) * (-a[:, 1]) - (-a[:, 0]) * (b[:, 1] - a[:, 1])) / safe
    inside = ok & (u >= -1e-12) & (v >= -1e-12) & (u + v <= 1.0 + 1e-12)
    if not np.any(inside):
        raise ValueError("the shape's axis does not pass through its mesh")
    z = (1.0 - u - v) * tri[:, 0, 2] + u * tri[:, 1, 2] + v * tri[:, 2, 2]
    top = float(np.max(z[inside]))
    if top <= 0.0:
        raise ValueError("the shape's axis leaves its mesh below the base")
    return top


def section_radius(vertices: FloatArray, triangles: np.ndarray, height: float) -> float:
    """Length-weighted mean radius of the mesh's section by the plane :math:`z` = height,
    m (module docstring, step 2).

    Raises
    ------
    ValueError
        When the plane does not cut the mesh.
    """
    tri = vertices[triangles]
    d = tri[:, :, 2] - height
    points = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        crosses = (d[:, i] < 0.0) != (d[:, j] < 0.0)
        t = np.where(crosses, d[:, i] / np.where(crosses, d[:, i] - d[:, j], 1.0), np.nan)
        points.append(tri[:, i, :2] + t[:, None] * (tri[:, j, :2] - tri[:, i, :2]))
    pts = np.stack(points, axis=1)  # (m, 3 edges, 2)
    cut = np.isfinite(pts[:, :, 0])
    rows = np.flatnonzero(cut.sum(axis=1) == 2)
    if rows.size == 0:
        raise ValueError(f"the mesh has no section at height {height:.3f} m")
    seg = pts[rows][cut[rows]].reshape(-1, 2, 2)
    length = np.linalg.norm(seg[:, 1] - seg[:, 0], axis=1)
    radius = 0.5 * (np.linalg.norm(seg[:, 0], axis=1) + np.linalg.norm(seg[:, 1], axis=1))
    total = float(length.sum())
    if total <= 0.0:
        raise ValueError(f"the mesh has no section at height {height:.3f} m")
    return float(np.dot(length, radius) / total)


def _resample(curve: FloatArray, count: int) -> FloatArray:
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))])
    s = np.linspace(0.0, arc[-1], count)
    out: FloatArray = np.column_stack(
        [np.interp(s, arc, curve[:, 0]), np.interp(s, arc, curve[:, 1])]
    )
    return out


def _revolved(profile: tuple[tuple[float, float], ...], smooth: bool) -> Revolved:
    shape = Revolved("fit", Placement(gore=1, tape_position=1.0), profile, smooth=smooth)
    shape.validate()
    return shape


def fit_profile(vertices: FloatArray, triangles: np.ndarray, points: int = 12) -> ProfileFit:
    """Fit a revolved profile to a mesh shape (module docstring).

    Parameters
    ----------
    vertices : ndarray of shape (n, 3)
        Mesh vertices in the shape's frame, m (:math:`z` along the axis, origin at the
        base point).
    triangles : ndarray of shape (m, 3)
        Vertex indices of each triangle.
    points : int
        Number of profile points, at least :data:`MIN_POINTS`.

    Returns
    -------
    ProfileFit
        The profile and how far the mesh is from it.

    Raises
    ------
    ValueError
        When the axis does not pass through the mesh, a section is missing, or no valid
        profile results.
    """
    if points < MIN_POINTS:
        raise ValueError(f"a fitted profile needs at least {MIN_POINTS} points")
    v = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    t = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    top = axis_top(v, t)
    # Heights avoid the vertices' own z values (a plane through a vertex cuts ambiguously).
    jitter = 1e-9 * top
    heights = np.linspace(0.0, top, SECTIONS, endpoint=False) + jitter
    radii = np.array([section_radius(v, t, float(h)) for h in heights])
    curve = np.vstack([np.column_stack([radii, heights - jitter]), [[0.0, top]]])
    fitted = _resample(curve, points)
    fitted[0, 1] = 0.0
    fitted[-1] = (0.0, top)
    fitted[1:-1, 0] = np.maximum(fitted[1:-1, 0], 1e-3)
    profile = tuple((float(r), float(z)) for r, z in fitted)
    try:
        shape, smooth = _revolved(profile, True), True
    except PrimitiveError:
        try:
            shape, smooth = _revolved(profile, False), False
        except PrimitiveError as exc:
            raise ValueError(f"no valid profile fits this mesh: {exc}") from exc
    rho, zeta = shape.meridian(4001)
    above = v[v[:, 2] >= 0.0]
    meridian = np.column_stack([np.hypot(above[:, 0], above[:, 1]), above[:, 2]])
    dist, _ = cKDTree(np.column_stack([rho, zeta])).query(meridian)
    worst = int(np.argmax(dist))
    return ProfileFit(
        profile=profile,
        smooth=smooth,
        max_deviation=float(dist[worst]),
        rms_deviation=float(np.sqrt(np.mean(dist**2))),
        deviation_height=float(meridian[worst, 1]),
        widest_radius=float(np.max(rho)),
    )
