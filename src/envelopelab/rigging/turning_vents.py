r"""Turning vents: jet thrust, torque, air loss and heat loss of an open side vent.

A turning vent is a vertical seam left open over some rows (a slit of length
:math:`\ell` along the tape, from meridian distance :math:`s_0` to :math:`s_1`). Pulled
open to a gap width :math:`w`, it lets hot air out tangentially; the reaction turns the
balloon. With the hydrostatic differential pressure
:math:`\Delta p(z) = (\rho_{amb} - \rho_{int})\,g\,(z - z_{mouth})` and the orifice
equation (jet speed :math:`v = \sqrt{2\Delta p/\rho_{int}}`, discharge coefficient
:math:`C_d`):

.. math::
    \dot m = \int_{s_0}^{s_1} C_d\, w \sqrt{2 \rho_{int} \Delta p}\;ds, \qquad
    F = \int_{s_0}^{s_1} 2 C_d\, w\, \Delta p\;ds, \qquad
    \tau = \pm\int_{s_0}^{s_1} r(s)\, 2 C_d\, w\, \Delta p\;ds

(the jet momentum flux :math:`\dot m v`, with :math:`C_d` applied to the jet area and a
velocity coefficient of 1), and the heat carried away
:math:`\dot Q = \dot m\, c_p (T_{int} - T_{amb})`. The torque sign is + for a
counter-clockwise rotation seen from above.

Assumptions and valid range: quasi-steady jet from a thin-walled slot with a uniform gap
width, directed tangentially; no external wind; densities uniform; the envelope shape is
the design profile (the vent does not deform it). Valid while :math:`\Delta p > 0` over
the slot (the slot is above the mouth).

References
----------
.. [White] F. M. White, *Fluid Mechanics*, McGraw-Hill, ch. 3 (momentum flux) and
   ch. 6 (orifice discharge, :math:`C_d \approx 0.61` for a sharp-edged slot).
.. [Incropera] F. P. Incropera et al., *Fundamentals of Heat and Mass Transfer*, Table A.4
   (air, :math:`c_p = 1007` J/(kg K) at 300 K).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from envelopelab.atmosphere import G0, PhysicalConstant
from envelopelab.geometry.gore import MeridianProfile

#: Specific heat of air at constant pressure (300 K).
CP_AIR = PhysicalConstant(
    1007.0, "J/(kg K)", "datasheet", "Incropera, Fundamentals of Heat and Mass Transfer, Table A.4"
)
#: Integration samples along the slot.
SLOT_SAMPLES = 401


@dataclass(frozen=True)
class VentJet:
    """Outflow of one open turning vent (module docstring).

    Attributes
    ----------
    slot_length : float
        :math:`\\ell = s_1 - s_0`, m.
    area : float
        Open area :math:`w \\ell`, m^2.
    mean_radius, mean_height : float
        Radius and height of the slot midpoint, m.
    mass_flow : float
        kg/s.
    thrust : float
        N.
    torque : float
        N m (+ counter-clockwise from above).
    heat_loss : float
        W.
    """

    slot_length: float
    area: float
    mean_radius: float
    mean_height: float
    mass_flow: float
    thrust: float
    torque: float
    heat_loss: float


def vent_jet(
    profile: MeridianProfile,
    s0: float,
    s1: float,
    width: float,
    discharge_coefficient: float,
    ambient_density: float,
    internal_density: float,
    ambient_temperature: float,
    internal_temperature: float,
    counterclockwise: bool,
    gravity: float = G0.value,
) -> VentJet:
    """Jet of one open turning vent (module docstring).

    Parameters
    ----------
    profile : MeridianProfile
        Envelope meridian, mouth first, m.
    s0, s1 : float
        Slot ends along the tape, m (``0 <= s0 < s1 <= L``).
    width : float
        Open gap width, m.
    discharge_coefficient : float
        :math:`C_d`, dimensionless.
    ambient_density, internal_density : float
        kg/m^3.
    ambient_temperature, internal_temperature : float
        K.
    counterclockwise : bool
        Rotation the vent produces, seen from above.
    gravity : float
        m/s^2.

    Returns
    -------
    VentJet
    """
    if not 0.0 <= s0 < s1 <= profile.meridian_length + 1e-9:
        raise ValueError("vent slot must lie on the meridian")
    s = np.linspace(s0, s1, SLOT_SAMPLES)
    r = profile.radius_at(s)
    z = profile.height_at(s)
    z_mouth = float(profile.height_at(0.0))
    dp = np.clip((ambient_density - internal_density) * gravity * (z - z_mouth), 0.0, None)
    cd = discharge_coefficient
    mass_flow = float(np.trapezoid(cd * width * np.sqrt(2.0 * internal_density * dp), s))
    force_density = 2.0 * cd * width * dp
    thrust = float(np.trapezoid(force_density, s))
    torque = float(np.trapezoid(r * force_density, s)) * (1.0 if counterclockwise else -1.0)
    mid = 0.5 * (s0 + s1)
    return VentJet(
        slot_length=s1 - s0,
        area=width * (s1 - s0),
        mean_radius=float(profile.radius_at(mid)),
        mean_height=float(profile.height_at(mid)),
        mass_flow=mass_flow,
        thrust=thrust,
        torque=torque,
        heat_loss=mass_flow * CP_AIR.value * (internal_temperature - ambient_temperature),
    )


def side_force(thrusts: list[float], azimuths: list[float], counterclockwise: list[bool]) -> float:
    r"""Magnitude of the net horizontal force of several vent jets, N.

    The reaction on the balloon of a vent at azimuth :math:`\varphi` producing a
    counter-clockwise rotation points along :math:`e_\varphi = (-\sin\varphi, \cos\varphi)`.
    """
    fx = fy = 0.0
    for f, phi, ccw in zip(thrusts, azimuths, counterclockwise, strict=True):
        sign = 1.0 if ccw else -1.0
        fx += -sign * f * math.sin(phi)
        fy += sign * f * math.cos(phi)
    return math.hypot(fx, fy)
