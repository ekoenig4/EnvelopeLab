r"""Parachute (deflation port): shape, flat panels, shroud and centralising lines, opening.

The parachute is a round fabric valve inside the crown. Internal pressure presses it
against the envelope around the crown opening (radius :math:`r_h`, height :math:`z_t`,
the top of the meridian profile) over the *seal overlap* :math:`o`, measured along the
fabric. Shroud lines run from its edge down to the vertical load tapes; centralising
lines run from its edge to a confluence on the axis, where the red line is attached.
Everything is solved in one meridian plane (axisymmetry).

Seated shape
------------
* Edge :math:`E`: the envelope point at meridian distance :math:`s_E = L - o` from the
  mouth, :math:`E = (r(s_E), z(s_E))`.
* Parachute meridian: the envelope meridian from :math:`E` up to the rim
  :math:`R = (r_h, z_t)`, then a spherical cap over the hole with rise
  :math:`h = b\,2r_h` (billow :math:`b`); sphere radius
  :math:`\rho = (r_h^2 + h^2)/(2h)`. The flat panels are the gores of this surface of
  revolution (:func:`envelopelab.geometry.gore.split_rows`, small-bulge width, one panel
  row from the edge to the apex).
* Shroud attachment :math:`A`: the load-tape point at :math:`s_A = s_E - a`
  (:math:`a` = ``shroud_attachment``); shroud length :math:`L_s = |E - A|`.
* Confluence :math:`C = (0, z_t - d)` (:math:`d` = ``centralizing_depth``); centralising
  line length :math:`L_c = |E - C|`.

Load
----
The pressure over the overlap annulus is carried by contact with the envelope; the
pressure over the hole is carried by parachute fabric tension to the edge and so by the
shroud lines. With the hydrostatic differential pressure at the cap apex (the largest
over the cap; conservative),

.. math::
    F = \Delta p(z_t + h)\,\pi r_h^2, \qquad
    T_s = \frac{n_{LF} F}{n\,\sin\alpha}, \qquad
    \sin\alpha = \frac{z_E - z_A}{L_s}

for :math:`n` shroud lines and limit load factor :math:`n_{LF}`.

Opening kinematics
------------------
Pulling the red line by :math:`\delta` lowers the confluence to :math:`z_C - \delta`.
With taut, inextensible lines the edge moves on the circle of radius :math:`L_s` about
:math:`A`, :math:`E(\psi) = A + L_s(\cos\psi, \sin\psi)`, and the confluence stays
:math:`L_c` from it: :math:`z_C(\psi) = z_E(\psi) - \sqrt{L_c^2 - r_E(\psi)^2}`. The
reported travels are

* *seal open*: the edge is further from the rim than the overlap, :math:`|E - R| \ge o`,
  so the overlap fabric can no longer lie against the rim;
* *full open*: in addition the annular gap between the edge ring and the envelope wall,
  :math:`A_g = 2\pi r_E\, d_w(E)` (:math:`d_w` = distance from :math:`E` to the envelope
  meridian), equals the hole area :math:`\pi r_h^2`.

Assumptions and valid range: axisymmetric, seated parachute; lines straight and
inextensible; parachute fabric slack, pressure and friction ignored in the kinematics
(the travels are geometric estimates, not a deflation-rate prediction); the red-line
pull force is not computed. The envelope simulation still closes the crown with an
unmeshed cap that loads the crown ring (see ``docs/theory/rigging.md``).

References
----------
.. [FAA] FAA-H-8083-11B, *Balloon Flying Handbook*, Federal Aviation Administration,
   ch. 2 (envelope, parachute top, red line, centralising lines).
.. [White] F. M. White, *Fluid Mechanics*, McGraw-Hill, ch. 2 (hydrostatics).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from envelopelab.geometry.gore import (
    GoreWidthModel,
    MeridianProfile,
    PanelRow,
    SeamAllowance,
    split_rows,
)

FloatArray = np.ndarray
#: Samples of the cap arc and of the opening path.
CAP_SAMPLES = 181
PATH_SAMPLES = 1201
#: Label of the parachute panel piece.
PANEL_LABEL = "P"


@dataclass(frozen=True)
class ParachuteGeometry:
    """Seated parachute and its lines (module docstring).

    Attributes
    ----------
    hole_radius, rim_height : float
        :math:`r_h`, :math:`z_t`, m.
    edge_s, edge_radius, edge_height : float
        :math:`s_E`, :math:`r_E`, :math:`z_E`, m.
    attachment_s, attachment_radius, attachment_height : float
        :math:`s_A`, :math:`r_A`, :math:`z_A`, m.
    cap_rise : float
        :math:`h`, m.
    apex_radius : float
        Centre-ring radius where the panels end (0: none), m.
    confluence_height : float
        :math:`z_C`, m.
    shroud_length, centralizing_length : float
        :math:`L_s`, :math:`L_c`, m.
    profile : MeridianProfile
        Parachute meridian from the edge (s = 0) to the apex, m.
    """

    hole_radius: float
    rim_height: float
    edge_s: float
    edge_radius: float
    edge_height: float
    attachment_s: float
    attachment_radius: float
    attachment_height: float
    cap_rise: float
    apex_radius: float
    confluence_height: float
    shroud_length: float
    centralizing_length: float
    profile: MeridianProfile

    @property
    def diameter(self) -> float:
        """Projected diameter of the seated parachute, :math:`2 r_E`, m."""
        return 2.0 * self.edge_radius

    @property
    def meridian_length(self) -> float:
        """Parachute fabric length from edge to apex, m."""
        return self.profile.meridian_length

    @property
    def area(self) -> float:
        """Parachute fabric area (finished), m^2."""
        return self.profile.area

    @property
    def hole_area(self) -> float:
        """:math:`\\pi r_h^2`, m^2."""
        return math.pi * self.hole_radius**2


#: Rise below which the cap is flat, m (a sphere radius that large overflows).
FLAT_RISE = 1e-6


def cap_radius(hole_radius: float, rise: float) -> float:
    """Sphere radius of a cap, :math:`\rho = (r_h^2 + h^2)/(2h)`, m (inf when flat)."""
    return math.inf if rise < FLAT_RISE else (hole_radius**2 + rise**2) / (2.0 * rise)


def cap_points(
    hole_radius: float, rim_height: float, rise: float, apex_radius: float = 0.0
) -> tuple[FloatArray, FloatArray]:
    r"""Meridian of a spherical cap from the rim to the apex (or a centre ring), m.

    Parameters
    ----------
    hole_radius : float
        :math:`r_h > 0`, m.
    rim_height : float
        :math:`z_t`, m.
    rise : float
        :math:`h \ge 0` of the full cap (below 1 um: flat disc), m.
    apex_radius : float
        Radius of the centre ring where the cap ends, :math:`0 \le a < r_h`, m.

    Returns
    -------
    (ndarray, ndarray)
        Radii from :math:`r_h` to :math:`a` and heights from :math:`z_t` up, m.
    """
    if hole_radius <= 0.0 or rise < 0.0:
        raise ValueError("hole radius must be positive and rise non-negative")
    if not 0.0 <= apex_radius < hole_radius:
        raise ValueError(
            f"centre ring radius {apex_radius:.3f} m must be below the hole radius "
            f"{hole_radius:.3f} m"
        )
    rho = cap_radius(hole_radius, rise)
    if math.isinf(rho):
        r = np.linspace(hole_radius, apex_radius, CAP_SAMPLES)
        return r, np.full_like(r, rim_height)
    zc = rim_height + rise - rho
    theta_rim = math.atan2(hole_radius, rim_height - zc)
    theta = np.linspace(theta_rim, math.asin(apex_radius / rho), CAP_SAMPLES)
    return rho * np.sin(theta), zc + rho * np.cos(theta)


def _point_at(profile: MeridianProfile, s: float) -> tuple[float, float]:
    return float(profile.radius_at(s)), float(profile.height_at(s))


def seated_geometry(
    envelope: MeridianProfile,
    seal_overlap: float,
    billow: float,
    shroud_attachment: float,
    centralizing_depth: float,
    apex_radius: float = 0.0,
) -> ParachuteGeometry:
    """Seated parachute geometry on an envelope profile (module docstring).

    Parameters
    ----------
    envelope : MeridianProfile
        Envelope meridian, mouth first, m; its top radius is the hole radius.
    seal_overlap : float
        Overlap along the fabric, m (> 0).
    billow : float
        Cap rise over hole diameter, dimensionless.
    shroud_attachment : float
        Distance along the load tape from the edge down to the shroud attachment, m.
    centralizing_depth : float
        Confluence depth below the rim, m.
    apex_radius : float
        Radius of the parachute centre ring (0: none), m.

    Returns
    -------
    ParachuteGeometry

    Raises
    ------
    ValueError
        When the overlap or the attachment do not fit on the meridian, or the top
        opening is closed.
    """
    length = envelope.meridian_length
    r_h, z_t = _point_at(envelope, length)
    if r_h <= 0.0:
        raise ValueError("the envelope has no crown opening (top radius 0)")
    if not 0.0 < seal_overlap < length:
        raise ValueError(f"seal overlap {seal_overlap:.3f} m does not fit on the meridian")
    s_e = length - seal_overlap
    s_a = s_e - shroud_attachment
    if s_a < 0.0:
        raise ValueError(
            f"shroud attachment {shroud_attachment:.3f} m below the parachute edge is "
            "beyond the mouth"
        )
    r_e, z_e = _point_at(envelope, s_e)
    r_a, z_a = _point_at(envelope, s_a)
    rise = billow * 2.0 * r_h
    s_top = envelope.s[envelope.s > s_e]
    seg_r = np.concatenate(([r_e], envelope.radius_at(s_top)))
    seg_z = np.concatenate(([z_e], envelope.height_at(s_top)))
    cr, cz = cap_points(r_h, z_t, rise, apex_radius)
    keep = np.hypot(seg_r - r_h, seg_z - z_t) > 1e-9
    profile = MeridianProfile.from_points(
        np.concatenate((seg_r[keep], cr)), np.concatenate((seg_z[keep], cz))
    )
    z_c = z_t - centralizing_depth
    return ParachuteGeometry(
        hole_radius=r_h,
        rim_height=z_t,
        edge_s=s_e,
        edge_radius=r_e,
        edge_height=z_e,
        attachment_s=s_a,
        attachment_radius=r_a,
        attachment_height=z_a,
        cap_rise=rise,
        apex_radius=apex_radius,
        confluence_height=z_c,
        shroud_length=math.hypot(r_e - r_a, z_e - z_a),
        centralizing_length=math.hypot(r_e, z_e - z_c),
        profile=profile,
    )


def parachute_panel(geometry: ParachuteGeometry, panel_count: int, allowance: float) -> PanelRow:
    """Flat pattern of one parachute panel (edge at the bottom, apex at the top).

    Parameters
    ----------
    geometry : ParachuteGeometry
        Seated parachute.
    panel_count : int
        Radial panels, >= 3.
    allowance : float
        Seam allowance on every edge, m.

    Returns
    -------
    PanelRow
        Label :data:`PANEL_LABEL`; finished and cut outlines in m.
    """
    profile = geometry.profile
    return split_rows(
        profile,
        GoreWidthModel(n_gores=panel_count, form="small_bulge"),
        [profile.meridian_length],
        labels=[PANEL_LABEL],
        allowance=SeamAllowance(side=allowance, bottom=allowance, top=allowance),
    )[0]


def crown_force(
    geometry: ParachuteGeometry, pressure_gradient: float, mouth_height: float
) -> float:
    r"""Vertical pressure force the shroud lines carry, N.

    .. math:: F = \frac{d\Delta p}{dz}\,(z_t + h - z_{mouth})\,\pi r_h^2

    Parameters
    ----------
    geometry : ParachuteGeometry
        Seated parachute.
    pressure_gradient : float
        :math:`(\rho_{amb} - \rho_{int}) g`, Pa/m.
    mouth_height : float
        Height of the zero-pressure mouth, m.
    """
    dp = pressure_gradient * (geometry.rim_height + geometry.cap_rise - mouth_height)
    return max(dp, 0.0) * geometry.hole_area


def shroud_tension(geometry: ParachuteGeometry, force: float, count: int) -> float:
    r"""Tension of each shroud line under a vertical force ``force`` (N), N.

    .. math:: T_s = F / (n \sin\alpha)

    Raises
    ------
    ValueError
        When the attachment is not below the edge (the lines cannot hold the parachute
        down).
    """
    drop = geometry.edge_height - geometry.attachment_height
    if drop <= 0.0:
        raise ValueError("shroud attachment is not below the parachute edge")
    return force / (count * drop / geometry.shroud_length)


@dataclass(frozen=True)
class OpeningResult:
    """Red-line travel to open the parachute (module docstring).

    Attributes
    ----------
    seal_open_travel : float, optional
        Pull at which the seal breaks, m (None: not reachable).
    full_open_travel : float, optional
        Pull at which the edge gap equals the hole area, m (None: not reachable).
    max_travel : float
        Pull at which the lines become straight or the edge reaches the axis, m.
    confluence_height_full : float, optional
        Confluence height at full opening, m.
    path_travel, path_edge_radius, path_edge_height, path_gap_area : ndarray
        The opening path, m and m^2 (gap area 0 while the seal holds).
    """

    seal_open_travel: float | None
    full_open_travel: float | None
    max_travel: float
    confluence_height_full: float | None
    path_travel: FloatArray
    path_edge_radius: FloatArray
    path_edge_height: FloatArray
    path_gap_area: FloatArray


def wall_distance(envelope: MeridianProfile, r: FloatArray, z: FloatArray) -> FloatArray:
    """Distance from meridian-plane points to the envelope meridian polyline, m."""
    pr = np.asarray(r, dtype=np.float64).reshape(-1, 1)
    pz = np.asarray(z, dtype=np.float64).reshape(-1, 1)
    ar, az = envelope.r[:-1], envelope.z[:-1]
    dr, dz = np.diff(envelope.r), np.diff(envelope.z)
    t = np.clip(((pr - ar) * dr + (pz - az) * dz) / (dr**2 + dz**2), 0.0, 1.0)
    d = np.hypot(pr - (ar + t * dr), pz - (az + t * dz))
    return np.asarray(d.min(axis=1)).reshape(np.shape(r))


def opening(
    geometry: ParachuteGeometry, envelope: MeridianProfile, seal_overlap: float
) -> OpeningResult:
    """Red-line travel for a seal-open and a full-open parachute (module docstring).

    Parameters
    ----------
    geometry : ParachuteGeometry
        Seated parachute.
    envelope : MeridianProfile
        Envelope meridian, m.
    seal_overlap : float
        Overlap along the fabric, m.
    """
    g = geometry
    ra, za, ls, lc = (
        g.attachment_radius,
        g.attachment_height,
        g.shroud_length,
        g.centralizing_length,
    )
    rh, zt = g.hole_radius, g.rim_height
    psi0 = math.atan2(g.edge_height - za, g.edge_radius - ra)

    def edge(psi: float | FloatArray) -> tuple[FloatArray, FloatArray]:
        return ra + ls * np.cos(psi), za + ls * np.sin(psi)

    def travel(psi: float | FloatArray) -> FloatArray:
        r, z = edge(psi)
        return g.confluence_height - (z - np.sqrt(np.clip(lc**2 - r**2, 0.0, None)))

    def seal_margin(psi: float | FloatArray) -> FloatArray:
        r, z = edge(psi)
        return np.hypot(r - rh, z - zt) - seal_overlap

    # Only the wall the edge can reach matters for the gap distance.
    near = np.hypot(envelope.r - ra, envelope.z - za) <= 2.0 * ls + seal_overlap
    near[:-1] |= near[1:]
    near[1:] |= near[:-1]
    wall = (
        MeridianProfile.from_points(envelope.r[near], envelope.z[near])
        if near.sum() >= 2
        else envelope
    )

    def gap(psi: float | FloatArray) -> FloatArray:
        r, z = edge(psi)
        return np.asarray(2.0 * math.pi * r * wall_distance(wall, r, z))

    psi = np.linspace(psi0, psi0 + 1.5 * math.pi, PATH_SAMPLES)
    r, z = edge(psi)
    delta = travel(psi)
    ok = (r >= 0.0) & (r <= lc) & np.concatenate(([True], np.diff(delta) > 0.0))
    stop = len(psi) if bool(np.all(ok)) else max(int(np.argmin(ok)), 1)
    psi, r, z, delta = psi[:stop], r[:stop], z[:stop], delta[:stop]
    margin = seal_margin(psi)
    area = np.zeros_like(margin)
    open_ = margin >= 0.0
    area[open_] = gap(psi[open_])

    def crossing(values: FloatArray, func: Callable[[float], float], lo: float) -> float | None:
        # First sample at or after ``lo`` where ``values`` >= 0, refined between samples.
        idx = np.nonzero((values >= 0.0) & (psi >= lo))[0]
        if not len(idx):
            return None
        k = int(idx[0])
        a = max(float(psi[k - 1]), lo) if k > 0 else float(psi[0])
        if k == 0 or func(a) >= 0.0:
            return a if k > 0 else float(psi[0])
        return float(brentq(func, a, float(psi[k]), xtol=1e-12))

    psi_seal = crossing(margin, lambda p: float(seal_margin(p)), float(psi[0]))
    psi_full = None
    if psi_seal is not None:
        psi_full = crossing(area - g.hole_area, lambda p: float(gap(p)) - g.hole_area, psi_seal)
    seal = None if psi_seal is None else float(travel(psi_seal))
    full = None if psi_full is None else float(travel(psi_full))
    return OpeningResult(
        seal_open_travel=seal,
        full_open_travel=full,
        max_travel=float(delta[-1]),
        confluence_height_full=None if full is None else g.confluence_height - full,
        path_travel=delta,
        path_edge_radius=r,
        path_edge_height=z,
        path_gap_area=area,
    )
