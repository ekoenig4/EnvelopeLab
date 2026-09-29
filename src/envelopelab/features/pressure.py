r"""Pressure communication between the main envelope and a pressure-fed appendage.

A ram-air pod, blister or tube that is fed through holes in the envelope fills with
envelope gas. With the envelope's differential pressure
:math:`\Delta p_{env}(z) = (\rho_{amb} - \rho_{int})\,g\,\max(z - z_{mouth}, 0)` sampled at
the feed holes, the appendage pressure is

.. math::
    p_{ref} = (1 - k)\,\frac{\sum_i A_i\,\Delta p_{env}(z_i)}{\sum_i A_i}, \qquad
    z_{ref} = \frac{\sum_i A_i z_i}{\sum_i A_i}, \qquad
    p_c(z) = p_{ref} + (\rho_{amb} - \rho_{int})\,g\,(z - z_{ref})

where :math:`A_i` and :math:`z_i` are the open area and centre height of feed hole
:math:`i` and :math:`k` is the *pressure-loss factor*: the fraction of the differential
pressure lost through the holes and by leakage through the skin and seams in steady
flight. The gas in the appendage is envelope gas, so its pressure varies with height at
the envelope's gradient.

Assumptions
-----------
* Quasi-static: the appendage is full and the flow through the holes is small, so the
  static pressure inside is uniform apart from the hydrostatic gradient. Filling,
  flapping and external aerodynamics (dynamic pressure from wind or climb, turbulent
  flow round the appendage) are outside the model.
* The loss factor is **assumed** (source tag ``assumed``): no measurement or datasheet
  supports a value. The default :data:`DEFAULT_LOSS_FACTOR` is 0 (fully communicating,
  the upper bound of the appendage pressure). Use the sensitivity sweep of the Reality
  Check report to see how much the shape depends on it.
* Feed-hole heights are taken at the reference geometry (the model's initial shape); a
  hole that moves by :math:`\delta z` changes the pressure by :math:`\rho g\,\delta z`,
  a few Pa per metre.
* An appendage with no feed hole, or one that is set independently (a sealed blister
  or a sensitivity study), takes its pressure from :func:`independent_chamber`.

Valid range: :math:`0 \le k < 1`; feed holes above the mouth (holes below the mouth see
zero differential pressure and cannot inflate the appendage).

References
----------
.. [Idelchik] I. E. Idelchik, *Handbook of Hydraulic Resistance*, 3rd ed., Begell House
   (1996), ch. 4 (orifice loss coefficients, for a loss factor derived from flow).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from envelopelab.materials.membrane import SourceTag
from envelopelab.solvers.model import OperatingConditions, PressureChamber

#: Default pressure-loss factor (fully communicating), dimensionless, source ``assumed``.
DEFAULT_LOSS_FACTOR = 0.0


@dataclass(frozen=True)
class FeedHole:
    """An opening that feeds an appendage from the envelope.

    Attributes
    ----------
    name : str
        Opening name.
    centre_height : float
        Height of the hole centre in model coordinates, m.
    area : float
        Open area, m^2.
    """

    name: str
    centre_height: float
    area: float

    def __post_init__(self) -> None:
        if self.area <= 0.0:
            raise ValueError(f"feed hole {self.name}: area must be positive")


@dataclass(frozen=True)
class FeedPressure:
    """Envelope pressure sampled at the feed holes and the resulting appendage pressure.

    Attributes
    ----------
    samples : list of (str, float, float)
        (hole name, centre height m, envelope differential pressure Pa) per hole.
    mean_envelope_pressure : float
        Area-weighted envelope pressure at the holes, Pa.
    reference_height : float
        Area-weighted hole height, m.
    loss_factor : float
        :math:`k`, dimensionless (source ``assumed``).
    chamber : PressureChamber
        The appendage chamber.
    """

    samples: list[tuple[str, float, float]]
    mean_envelope_pressure: float
    reference_height: float
    loss_factor: float
    chamber: PressureChamber

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dictionary with units."""
        return {
            "feed_holes": [
                {"name": n, "centre_height_m": z, "envelope_pressure_pa": p}
                for n, z, p in self.samples
            ],
            "mean_envelope_pressure_pa": self.mean_envelope_pressure,
            "reference_height_m": self.reference_height,
            "loss_factor": self.loss_factor,
            "loss_factor_source": "assumed",
            "chamber": self.chamber.as_dict(),
        }


def fed_chamber(
    name: str,
    conditions: OperatingConditions,
    holes: Sequence[FeedHole],
    loss_factor: float = DEFAULT_LOSS_FACTOR,
) -> FeedPressure:
    """Chamber pressure of an appendage fed from the envelope through ``holes``.

    Parameters
    ----------
    name : str
        Chamber (feature) name.
    conditions : OperatingConditions
        Envelope load case (densities, gravity, mouth height).
    holes : sequence of FeedHole
        Feed holes (heights m, areas m^2).
    loss_factor : float
        Pressure-loss factor :math:`k` in [0, 1), dimensionless, source ``assumed``.

    Returns
    -------
    FeedPressure
        Sampled envelope pressures (Pa) and the chamber (Pa, m, Pa/m).

    Raises
    ------
    ValueError
        Without holes, for :math:`k` outside [0, 1), or when every hole is at or below
        the mouth (no differential pressure to fill the appendage).
    """
    if not holes:
        raise ValueError(f"{name}: a fed chamber needs at least one feed hole")
    if not 0.0 <= loss_factor < 1.0:
        raise ValueError(f"{name}: loss factor must be in [0, 1), got {loss_factor}")
    heights = np.array([h.centre_height for h in holes])
    areas = np.array([h.area for h in holes])
    dp = conditions.pressure(heights)
    if float(dp.max()) <= 0.0:
        raise ValueError(f"{name}: every feed hole is at or below the mouth")
    mean_p = float((areas * dp).sum() / areas.sum())
    z_ref = float((areas * heights).sum() / areas.sum())
    chamber = PressureChamber(
        name=name,
        reference_pressure=(1.0 - loss_factor) * mean_p,
        reference_height=z_ref,
        gradient=conditions.pressure_gradient,
        source="assumed",
        description=(
            f"fed through {len(holes)} hole(s); envelope pressure {mean_p:.3f} Pa at "
            f"z = {z_ref:.3f} m, loss factor {loss_factor:g} (assumed)"
        ),
    )
    return FeedPressure(
        samples=[(h.name, h.centre_height, float(p)) for h, p in zip(holes, dp, strict=True)],
        mean_envelope_pressure=mean_p,
        reference_height=z_ref,
        loss_factor=loss_factor,
        chamber=chamber,
    )


def independent_chamber(
    name: str,
    reference_pressure: float,
    reference_height: float,
    gradient: float,
    source: SourceTag = "assumed",
) -> PressureChamber:
    """Chamber with a pressure set directly (sealed blister, sensitivity study).

    Parameters
    ----------
    name : str
        Chamber name.
    reference_pressure : float
        Differential pressure at ``reference_height``, Pa.
    reference_height : float
        m.
    gradient : float
        :math:`(\\rho_{amb} - \\rho_{gas}) g` of the chamber gas, Pa/m (0 for a uniform
        pressure).
    source : {"datasheet", "measured", "assumed"}
        Provenance of the value.

    Returns
    -------
    PressureChamber
        The chamber.
    """
    return PressureChamber(
        name=name,
        reference_pressure=reference_pressure,
        reference_height=reference_height,
        gradient=gradient,
        source=source,
        description=f"set independently: {reference_pressure:.3f} Pa at z = "
        f"{reference_height:.3f} m, gradient {gradient:.4f} Pa/m ({source})",
    )
