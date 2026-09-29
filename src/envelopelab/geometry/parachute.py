r"""Flat parachute (crown valve) pattern pieces: radial gores and a centre disc.

The parachute closes the crown hole of a gore envelope from inside. It is modelled here
as a **flat circular canopy** of finished radius :math:`R` made of :math:`N` identical
gores sewn along radial seams to each other and, at their inner ends, to a circular centre
disc of finished radius :math:`r_c`. Each finished gore is an annular sector of angle

.. math:: \theta = \frac{2\pi}{N}

between the radii :math:`r_c` and :math:`R`, with straight radial sides and circular-arc
ends. Its seam lengths and finished area are

.. math::
    L_\text{radial} = R - r_c, \qquad
    L_\text{rim} = \theta R, \qquad
    L_\text{inner} = \theta r_c, \qquad
    A_\text{gore} = \frac{\theta}{2}\left(R^2 - r_c^2\right),

so the :math:`N` inner arcs add up to the disc circumference :math:`2\pi r_c` and the
finished canopy area is :math:`N A_\text{gore} + \pi r_c^2 = \pi R^2`.

Coordinates and units
---------------------
Lengths in m, areas in m^2. A gore is drawn with its centreline on the :math:`y` axis, the
finished rim arc through the origin and the centre of the parachute at :math:`(0, R)`
(the rim is the ``bottom`` edge, the inner arc the ``top`` edge, as for envelope panels
whose top points towards the crown). The disc is centred on the origin.

Assumptions
-----------
* Flat canopy: no fullness or doming is designed into the gores; fabric stretch is
  neglected. Designs with a shaped parachute use a manual outline override.
* Arcs are sampled as polygons with at most :data:`MAX_SEGMENT_ANGLE_DEG` per segment:
  the chord error is below 5e-6 relative for arc lengths and 2e-5 for areas.
* Valid for :math:`N \ge 3` and :math:`0 < r_c < R`.

References
----------
.. [Poynter] D. Poynter, *Parachute Recovery Systems Design Manual*, Para Publishing
   (1991), flat circular canopies and gore layout.
.. [Struik] D. J. Struik, *Lectures on Classical Differential Geometry*, 2nd ed., Dover
   (1988), arc length and area of plane curves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from envelopelab.geometry.polygon import (
    FloatArray,
    offset_polygon,
    orient_ccw,
    polyline_length,
    signed_area,
    split_edges,
)

#: Largest angle of one polygon segment of a sampled arc, deg.
MAX_SEGMENT_ANGLE_DEG = 0.5


def arc_segments_for(n_gores: int) -> int:
    """Polygon segments per gore arc for :data:`MAX_SEGMENT_ANGLE_DEG` (even, at least 8).

    An even count puts a vertex on the gore centreline, at the origin of the rim.
    """
    segments = max(8, math.ceil(360.0 / n_gores / MAX_SEGMENT_ANGLE_DEG))
    return segments + segments % 2


def _check(radius: float, centre_radius: float, n_gores: int) -> None:
    if n_gores < 3:
        raise ValueError("a parachute needs at least 3 gores")
    if not 0.0 < centre_radius < radius:
        raise ValueError("the centre disc radius must be between 0 and the parachute radius")


def gore_outline(
    radius: float,
    centre_radius: float,
    n_gores: int,
    arc_segments: int | None = None,
) -> FloatArray:
    r"""Finished outline of one flat parachute gore (an annular sector).

    Parameters
    ----------
    radius : float
        Finished parachute radius :math:`R`, m.
    centre_radius : float
        Finished centre-disc radius :math:`r_c`, m.
    n_gores : int
        Number of gores :math:`N` (>= 3).
    arc_segments : int, optional
        Polygon segments per arc; default :func:`arc_segments_for`.

    Returns
    -------
    ndarray, shape (2 * (arc_segments + 1), 2)
        Counter-clockwise outline, m: the rim arc through the origin, the inner arc at
        distance :math:`R - r_c` above it (see the module docstring for the frame).

    Raises
    ------
    ValueError
        For :math:`N < 3` or :math:`r_c \notin (0, R)`.
    """
    _check(radius, centre_radius, n_gores)
    segments = arc_segments or arc_segments_for(n_gores)
    half = math.pi / n_gores
    phi = np.linspace(-half, half, segments + 1)
    # A point at distance rho from the parachute centre (0, R), angle phi from the -y axis.
    rim = np.column_stack((radius * np.sin(phi), radius - radius * np.cos(phi)))
    inner = np.column_stack((centre_radius * np.sin(phi), radius - centre_radius * np.cos(phi)))
    return orient_ccw(np.vstack((rim, inner[::-1])))


def centre_outline(
    centre_radius: float,
    n_gores: int,
    arc_segments: int | None = None,
) -> FloatArray:
    """Finished outline of the centre disc, m (counter-clockwise, centred on the origin).

    The disc has ``n_gores * arc_segments`` vertices, so every gore's inner arc meets it on
    a matching set of points.

    Parameters
    ----------
    centre_radius : float
        Finished disc radius, m (> 0).
    n_gores : int
        Number of parachute gores (>= 3).
    arc_segments : int, optional
        Polygon segments per gore arc; default :func:`arc_segments_for`.

    Returns
    -------
    ndarray, shape (n_gores * arc_segments, 2)
        Outline, m.
    """
    if centre_radius <= 0.0 or n_gores < 3:
        raise ValueError("the centre disc needs a positive radius and at least 3 gores")
    segments = arc_segments or arc_segments_for(n_gores)
    t = np.linspace(0.0, 2.0 * math.pi, n_gores * segments, endpoint=False)
    return np.column_stack((centre_radius * np.cos(t), centre_radius * np.sin(t)))


@dataclass(frozen=True)
class ParachutePieces:
    """Finished and cut pieces of a parachute (one gore shape and the centre disc).

    Attributes
    ----------
    n_gores : int
        Number of gores N.
    gore_finished, gore_cut : ndarray, shape (n, 2)
        Finished and cut outline of one gore, m, counter-clockwise.
    centre_finished, centre_cut : ndarray, shape (m, 2)
        Finished and cut outline of the centre disc, m, counter-clockwise.
    """

    n_gores: int
    gore_finished: FloatArray
    gore_cut: FloatArray
    centre_finished: FloatArray
    centre_cut: FloatArray

    @property
    def gore_edges(self) -> dict[str, float]:
        """Finished gore edge lengths, m: ``bottom`` (rim), ``top``, ``left``, ``right``."""
        return gore_edge_lengths(self.gore_finished)

    @property
    def centre_circumference(self) -> float:
        """Finished centre-disc circumference, m."""
        return polyline_length(self.centre_finished, closed=True)

    @property
    def finished_area(self) -> float:
        """Finished parachute area (all gores and the disc), m^2."""
        return self.n_gores * abs(signed_area(self.gore_finished)) + abs(
            signed_area(self.centre_finished)
        )

    @property
    def cut_area(self) -> float:
        """Cut fabric area including seam allowances (all gores and the disc), m^2."""
        return self.n_gores * abs(signed_area(self.gore_cut)) + abs(signed_area(self.centre_cut))

    @property
    def radial_seam_length(self) -> float:
        """Total finished radial seam length (N seams, one per gore side pair), m."""
        edges = self.gore_edges
        return self.n_gores * 0.5 * (edges["left"] + edges["right"])

    @property
    def rim_length(self) -> float:
        """Finished rim length of the whole parachute, m."""
        return self.n_gores * self.gore_edges["bottom"]


def gore_edge_lengths(outline: FloatArray) -> dict[str, float]:
    """Finished edge lengths of a parachute gore outline, m.

    Corners are found as for imported pattern pieces
    (:func:`envelopelab.geometry.polygon.split_edges`); the outline must have four corners.
    The rim is the edge through the lowest point, the inner end the edge opposite it and
    the sides are told apart by their mean :math:`x` (normal-based side names do not work
    for wide gores, :math:`N < 4`).

    Parameters
    ----------
    outline : ndarray, shape (n, 2)
        Finished gore outline, m, rim at the bottom.

    Returns
    -------
    dict of str to float
        ``bottom`` (rim), ``top`` (inner end), ``left`` and ``right`` (radial sides), m.

    Raises
    ------
    ValueError
        When the outline does not have four corners.
    """
    edges = split_edges(orient_ccw(np.asarray(outline, dtype=np.float64)))
    if len(edges) != 4:
        raise ValueError(
            f"a parachute gore needs four corners (rim, two radial sides, inner end); "
            f"found {len(edges)} edge(s)"
        )
    rim = min(range(4), key=lambda i: float(edges[i].points[:, 1].min()))
    inner = (rim + 2) % 4
    a, b = (rim + 1) % 4, (rim + 3) % 4
    left, right = sorted((a, b), key=lambda i: float(edges[i].points[:, 0].mean()))
    return {
        "bottom": edges[rim].length,
        "top": edges[inner].length,
        "left": edges[left].length,
        "right": edges[right].length,
    }


def parachute_pieces(
    diameter: float,
    centre_diameter: float,
    n_gores: int,
    allowance: float,
    arc_segments: int | None = None,
) -> ParachutePieces:
    """Generated finished and cut pieces of a flat parachute.

    Parameters
    ----------
    diameter : float
        Finished parachute diameter :math:`2R`, m.
    centre_diameter : float
        Finished centre-disc diameter :math:`2r_c`, m.
    n_gores : int
        Number of gores (>= 3).
    allowance : float
        Seam allowance added all round each piece, m (>= 0).
    arc_segments : int, optional
        Polygon segments per gore arc; default :func:`arc_segments_for`.

    Returns
    -------
    ParachutePieces
        Outlines in m.
    """
    if allowance < 0.0:
        raise ValueError("the seam allowance must not be negative")
    gore = gore_outline(diameter / 2.0, centre_diameter / 2.0, n_gores, arc_segments)
    disc = centre_outline(centre_diameter / 2.0, n_gores, arc_segments)
    return ParachutePieces(
        n_gores=n_gores,
        gore_finished=gore,
        gore_cut=offset_polygon(gore, allowance) if allowance > 0 else gore.copy(),
        centre_finished=disc,
        centre_cut=offset_polygon(disc, allowance) if allowance > 0 else disc.copy(),
    )
