r"""Hoop loads of the crown ring (rim of the crown opening) and the parachute centre ring.

Both rings are thin circular rings loaded by an axisymmetric radial line load
:math:`q` (N/m, outward positive), whose hoop force is :math:`H = q\,a` for a ring of
radius :math:`a` (tension positive).

Crown ring
----------
The ring at the rim of the crown opening (radius :math:`r_h`) is pulled by the envelope
fabric along the meridian tangent. If the rim carries a vertical force :math:`F`, the
meridional resultant there is :math:`n_m = F / (2\pi r_h \sin\beta)` with :math:`\beta`
the angle of the meridian above the horizontal at the rim, so the outward line load is
:math:`q = n_m \cos\beta` and

.. math:: H_{crown} = \frac{F}{2\pi \tan\beta}.

The design uses :math:`F = \Delta p(z_t + h)\,\pi r_h^2`, the full pressure force over the
hole: this is the load path of the envelope simulation's cap closure and an **upper bound**
for a parachute design, whose shroud lines take most of that force to the load tapes
lower down. A meridian that turns inward below the rim gives compression (buckling of the
ring is not checked; a warning says so); a horizontal meridian at the rim cannot hold the
ring (error).

Centre ring
-----------
The parachute cap is a pressurised spherical membrane of radius :math:`\rho`, with the
isotropic stress resultant :math:`n = p\rho/2` (the AGENTS.md sphere benchmark). At the
centre ring (radius :math:`a`) the membrane pulls outward with :math:`q = n` (the cap is
almost horizontal there), so

.. math:: H_{centre} = \frac{p\,\rho\,a}{2}.

A flat parachute (billow 0) has :math:`\rho \to \infty` and cannot carry pressure as a
membrane; its centre-ring load is not assessed (warning). The crown-line load (ground
handling) is not computed.

Assumptions: thin rings, axisymmetric loads, static pressure at the cap apex, limit load
factor applied as for the lines. References: S. Timoshenko, J. Gere, *Theory of Elastic
Stability* (rings under radial load); W. C. Young, R. Budynas, *Roark's Formulas for
Stress and Strain*, ch. 9 (circular rings) and ch. 13 (membrane stresses in spheres).
"""

from __future__ import annotations

import math

from envelopelab.geometry.gore import MeridianProfile


def rim_angle(envelope: MeridianProfile) -> float:
    """Angle of the meridian above the horizontal at the top (rim), rad.

    Positive when the meridian rises toward the axis (a normal crown). The tangent is the
    second-order one-sided difference of the last three profile samples (a one-sided
    first-order difference lags by half a sample).
    """
    r, z = envelope.r[-3:], envelope.z[-3:]
    if len(r) < 3:
        dr, dz = float(r[-1] - r[0]), float(z[-1] - z[0])
    else:
        dr = float(3.0 * r[2] - 4.0 * r[1] + r[0])
        dz = float(3.0 * z[2] - 4.0 * z[1] + z[0])
    return math.atan2(dz, -dr)


def crown_ring_hoop(force: float, envelope: MeridianProfile) -> float | None:
    """Hoop force of the crown ring, :math:`F / (2\\pi\\tan\\beta)`, N (module docstring).

    Parameters
    ----------
    force : float
        Vertical force on the rim, N.
    envelope : MeridianProfile
        Envelope meridian, m.

    Returns
    -------
    float or None
        Tension positive; None when the meridian is (nearly) horizontal or points down
        at the rim, so that the rim cannot carry a vertical force.
    """
    beta = rim_angle(envelope)
    if math.sin(beta) <= 1e-6:
        return None
    return force / (2.0 * math.pi * math.tan(beta))


def centre_ring_hoop(pressure: float, cap_radius: float, ring_radius: float) -> float | None:
    """Hoop force of the parachute centre ring, :math:`p\\rho a/2`, N.

    Parameters
    ----------
    pressure : float
        Differential pressure on the cap, Pa.
    cap_radius : float
        Sphere radius of the cap, m (inf for a flat parachute).
    ring_radius : float
        m.

    Returns
    -------
    float or None
        Tension; None for a flat parachute (not assessed).
    """
    if math.isinf(cap_radius):
        return None
    return pressure * cap_radius * ring_radius / 2.0
