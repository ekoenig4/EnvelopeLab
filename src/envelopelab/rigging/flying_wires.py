r"""Flying wires: from the mouth load tapes to the basket's burner frame.

The N vertical load tapes end at the mouth ring (radius :math:`r_m`, height :math:`z_m`).
They are gathered in :math:`w` equal groups of :math:`g = N/w` consecutive tapes; each
group meets at a carabiner :math:`P_j` a height :math:`d` below the mouth (the crow's
foot), and one flying wire runs from each carabiner to the nearest of the burner-frame
attachment points :math:`F_i` (radius :math:`R_f`, a height :math:`H_f` below the mouth).

Geometry
--------
* Seam azimuths :math:`\varphi_k = 2\pi k/N` (see :mod:`envelopelab.rigging.common`);
  group :math:`j` holds seams :math:`jg+1 .. (j+1)g`.
* Carabiner: azimuth of the group's mean direction, radius of its centroid
  :math:`r_c = r_m \sin(\pi g/N) / (g \sin(\pi/N))`, height :math:`z_m - d`.
* Frame point :math:`i`: azimuth :math:`\alpha_0 + 2\pi i/n_f`, radius :math:`R_f`,
  height :math:`z_m - H_f`.

Statics
-------
The suspended weight is :math:`W = m_{payload}\,g` (basket, burner, fuel and occupants)
and the limit load :math:`n_{LF} W`. Each wire takes an equal share of the vertical load,
and each leg of a crow's foot an equal share of its wire's vertical component:

.. math::
    T_j = \frac{n_{LF} W}{w \cos\theta_j}, \qquad
    t_k = \frac{T_j \cos\theta_j}{g\,\cos\beta_k}

with :math:`\theta_j` and :math:`\beta_k` the angles of wire and leg from the vertical.

Assumptions and valid range: rigid, level burner frame; static load case scaled by the
limit load factor; straight, inextensible wires and legs; the carabiner position is
prescribed by ``crows_foot_drop`` (horizontal equilibrium at the carabiner is not
enforced, so leg loads are an estimate); the envelope's own weight is carried by the
fabric and does not load the wires.

References
----------
.. [CFR31] 14 CFR Part 31, *Airworthiness standards: manned free balloons*, §31.23
   (flight load factor), §31.25 (factor of safety), §31.27 (strength).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from envelopelab.rigging.common import FloatArray, point, seam_azimuth


@dataclass(frozen=True)
class WireGeometry:
    """Flying-wire layout (module docstring).

    Attributes
    ----------
    group_size : int
        Load tapes per wire, :math:`g`.
    seams : list of list of int
        Seam numbers of each wire's crow's foot.
    carabiners : ndarray, shape (w, 3)
        Carabiner points, m.
    frame_points : ndarray, shape (n_f, 3)
        Frame attachment points, m.
    wire_frame_point : list of int
        Frame point index of each wire.
    wire_lengths, wire_angles : ndarray, shape (w,)
        Wire lengths (m) and angles from the vertical (rad).
    leg_lengths, leg_angles : ndarray, shape (N,)
        Crow's-foot leg length (m) and angle from the vertical (rad), per seam 1..N.
    """

    group_size: int
    seams: list[list[int]]
    carabiners: FloatArray
    frame_points: FloatArray
    wire_frame_point: list[int]
    wire_lengths: FloatArray
    wire_angles: FloatArray
    leg_lengths: FloatArray
    leg_angles: FloatArray


def _angle_from_vertical(vector: FloatArray) -> float:
    return math.atan2(float(np.hypot(vector[0], vector[1])), float(vector[2]))


def wire_geometry(
    gore_count: int,
    mouth_radius: float,
    mouth_height: float,
    count: int,
    frame_points: int,
    frame_radius: float,
    frame_drop: float,
    frame_azimuth_deg: float,
    crows_foot_drop: float,
) -> WireGeometry:
    """Layout of the flying wires (module docstring).

    Parameters
    ----------
    gore_count : int
        N (a multiple of ``count``).
    mouth_radius, mouth_height : float
        m.
    count : int
        Wires w.
    frame_points : int
        Frame attachment points.
    frame_radius, frame_drop : float
        m.
    frame_azimuth_deg : float
        Azimuth of the first frame point, degrees.
    crows_foot_drop : float
        m.

    Returns
    -------
    WireGeometry

    Raises
    ------
    ValueError
        When N is not a multiple of the wire count, the frame is not below the
        carabiners, or a crow's foot of several tapes has no drop.
    """
    if count < 1 or gore_count % count:
        raise ValueError(f"gore count {gore_count} is not a multiple of {count} flying wires")
    if frame_drop <= crows_foot_drop:
        raise ValueError("the burner frame must hang below the carabiners")
    g = gore_count // count
    if g > 1 and crows_foot_drop <= 0.0:
        raise ValueError(f"{g} load tapes per wire need a crow's foot drop above 0")
    seams = [[j * g + i + 1 for i in range(g)] for j in range(count)]
    step = 2.0 * math.pi / gore_count
    r_c = mouth_radius * (math.sin(math.pi * g / gore_count) / (g * math.sin(math.pi / gore_count)))
    z_c = mouth_height - crows_foot_drop
    alpha0 = math.radians(frame_azimuth_deg)
    frames = np.array(
        [
            point(
                frame_radius, alpha0 + 2.0 * math.pi * i / frame_points, mouth_height - frame_drop
            )
            for i in range(frame_points)
        ]
    )
    carabiners = []
    wire_frame: list[int] = []
    lengths, angles = [], []
    leg_lengths = np.zeros(gore_count)
    leg_angles = np.zeros(gore_count)
    for group in seams:
        phi = step * (group[0] + group[-1]) / 2.0
        cara = point(r_c, phi, z_c)
        carabiners.append(cara)
        # nearest frame point by azimuth difference
        diffs = [
            abs(math.remainder(phi - (alpha0 + 2.0 * math.pi * i / frame_points), 2.0 * math.pi))
            for i in range(frame_points)
        ]
        i_best = int(np.argmin(diffs))
        wire_frame.append(i_best)
        vec = cara - frames[i_best]
        lengths.append(float(np.linalg.norm(vec)))
        angles.append(_angle_from_vertical(vec))
        for seam in group:
            top = point(mouth_radius, seam_azimuth(seam, gore_count), mouth_height)
            leg = top - cara
            length = float(np.linalg.norm(leg))
            # One tape per wire and no drop: the tape ends at the carabiner (no leg).
            if length > 1e-9:
                leg_lengths[seam - 1] = length
                leg_angles[seam - 1] = _angle_from_vertical(leg)
    return WireGeometry(
        group_size=g,
        seams=seams,
        carabiners=np.array(carabiners),
        frame_points=frames,
        wire_frame_point=wire_frame,
        wire_lengths=np.array(lengths),
        wire_angles=np.array(angles),
        leg_lengths=leg_lengths,
        leg_angles=leg_angles,
    )


def wire_tensions(geometry: WireGeometry, limit_weight: float) -> tuple[FloatArray, FloatArray]:
    r"""Wire and leg tensions under the limit suspended weight (module docstring).

    Parameters
    ----------
    geometry : WireGeometry
        Layout.
    limit_weight : float
        :math:`n_{LF} W`, N.

    Returns
    -------
    (ndarray, ndarray)
        Tension per wire (w,) and per crow's-foot leg (N,), N. A leg of zero length
        (one tape per wire, no drop) carries the wire's tension.
    """
    w = len(geometry.wire_lengths)
    vertical = limit_weight / w
    wires = vertical / np.cos(geometry.wire_angles)
    legs = np.zeros_like(geometry.leg_lengths)
    for j, group in enumerate(geometry.seams):
        share = vertical / len(group)
        for seam in group:
            if geometry.leg_lengths[seam - 1] == 0.0:
                legs[seam - 1] = wires[j]
            else:
                legs[seam - 1] = share / math.cos(geometry.leg_angles[seam - 1])
    return wires, legs
