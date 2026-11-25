r"""Temperature stratification of the gas in an envelope (level 1: assumed profile, real
shape).

The gas in a hot-air envelope is hottest at the crown and coolest at the mouth. Lift
depends on the density of the gas averaged over the volume, so the shape of the envelope
(where its volume lies in height) decides which mean temperature a crown temperature
corresponds to. This module takes the shape from the design and *assumes* the form of the
temperature profile; it does not model the heat transfer that sets it.

Model
-----
Height :math:`h` is measured up from the mouth, :math:`H` is the crown height above it and
:math:`f = h/H`. The gas temperature rises linearly from the mouth to the crown:

.. math::
    T(h) = T_{amb} + (T_{top} - T_{amb})\,\bigl[\varphi + (1 - \varphi)\,f\bigr]

with :math:`\varphi` the temperature rise above ambient at the mouth as a fraction of the
rise at the crown (:data:`DEFAULT_MOUTH_EXCESS`, ``assumed``). :math:`\varphi = 1` is a
uniform envelope.

Lift is :math:`L/g = \int (\rho_{amb} - \rho(h))\,dV` with :math:`\rho = p/(R_d T)` at the
common static pressure, so the temperature that gives the same lift as the profile is the
volume-weighted harmonic mean:

.. math::
    \frac{1}{T_{eff}} = \frac{1}{V}\int_V \frac{dV}{T(h)},
    \qquad \Delta T_{top \to mean} = T_{top} - T_{eff}

The volume distribution :math:`dV(h)` comes from the design's meridian profile (Pappus:
each profile segment sweeps a frustum of volume
:math:`\tfrac{\pi}{3}(r_1^2 + r_1 r_2 + r_2^2)(z_2 - z_1)`), scaled to the design's lofted
volume so the gore bulge is included in the same proportion at every height.

The offset used is never below a floor (``minimum_offset``, the project's tagged
top-to-mean offset, 20 K by default): :math:`T_{mean} = \min(T_{eff},\ T_{top} -
\Delta T_{min})`. When the floor applies, the profile shown (and its pressure) is the
linear profile with the mouth excess lowered to :math:`\varphi' < \varphi` so that its
:math:`T_{eff}` is exactly :math:`T_{top} - \Delta T_{min}` (:meth:`StratificationModel.
excess_used`): the floor makes the lower envelope cooler, never the crown.

The same profile gives the differential pressure that is consistent with it (hydrostatic,
open mouth):

.. math::
    \Delta p(h) = g \int_0^{h} \bigl(\rho_{amb} - \rho(h')\bigr)\,dh'
    = \frac{g\,p}{R_d}\left[\frac{h}{T_{amb}}
      - \frac{H}{b}\,\ln\frac{a + b\,h/H}{a}\right]

with :math:`a = T(0)`, :math:`b = T(H) - T(0)` (:math:`b \ne 0`). The structural solver
does not use it yet: it assumes a uniform internal temperature (constant gradient).

Assumptions
-----------
* The *form* of the profile (linear in height) and :math:`\varphi` are assumed; real
  stratification depends on the burner, heat loss, porosity and wind (a heat-balance
  model would predict them; see ``docs/theory/stratification.md``).
* Horizontal layers are at one temperature (no plume core, no wall boundary layer).
* Static pressure is the same inside and out over the envelope (density changes from
  pressure over 30 m are < 0.4 %).
* The lofted-to-revolved volume ratio is the same at every height.

Valid range: :math:`0 \le \varphi \le 1`, :math:`T_{top} > T_{amb}`.

References
----------
* Archimedes' principle and the ideal-gas law (see :mod:`envelopelab.atmosphere`).
* W. D. Baines and J. S. Turner, "Turbulent buoyant convection from a source in a
  confined region", J. Fluid Mech. 37 (1969) 51-80 (stable stratification of a heated
  enclosure: hottest at the top).
* Pappus's centroid theorem (volume of revolution).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.optimize import brentq

from envelopelab.atmosphere import G0, R_DRY_AIR, PhysicalConstant

FloatArray = npt.NDArray[np.float64]

#: Temperature rise above ambient at the mouth as a fraction of the rise at the crown,
#: dimensionless. A generic assumption, not a measurement: it decides how much cooler the
#: lower envelope is. 0.5 puts the mouth gas halfway between ambient and the crown.
DEFAULT_MOUTH_EXCESS = PhysicalConstant(
    0.5,
    "-",
    "assumed",
    "generic: mouth gas halfway between ambient and crown; replace with a measured value",
)
#: Height bins of the volume distribution.
BINS = 400


@dataclass(frozen=True)
class VolumeDistribution:
    """Gas volume of an envelope by height above the mouth.

    Attributes
    ----------
    heights : ndarray
        Bin centres, m above the mouth, increasing, from 0 to ``crown_height``.
    volumes : ndarray
        Volume of each bin, m^3; they add up to ``total``.
    crown_height : float
        Crown above the mouth, m.
    total : float
        Envelope volume, m^3.
    """

    heights: FloatArray
    volumes: FloatArray
    crown_height: float
    total: float

    @classmethod
    def from_profile(
        cls, r: npt.ArrayLike, z: npt.ArrayLike, volume: float | None = None, bins: int = BINS
    ) -> VolumeDistribution:
        r"""Volume by height of the envelope swept by a meridian profile.

        Each segment of the polyline sweeps a frustum of signed volume
        :math:`\tfrac{\pi}{3}(r_1^2 + r_1 r_2 + r_2^2)(z_2 - z_1)`, split over the height
        bins it spans in proportion to the height it covers in each.

        Parameters
        ----------
        r, z : array_like
            Radius and height of the profile from the mouth (first point) to the crown, m.
        volume : float, optional
            Envelope volume to scale to, m^3 (e.g. the lofted volume of the gores);
            default the volume of revolution.
        bins : int
            Number of height bins.

        Returns
        -------
        VolumeDistribution
        """
        rr = np.asarray(r, dtype=np.float64)
        zz = np.asarray(z, dtype=np.float64) - float(np.asarray(z, dtype=np.float64)[0])
        crown = float(zz.max())
        if not crown > 0.0:
            raise ValueError("the crown must lie above the mouth")
        edges = np.linspace(0.0, crown, bins + 1)
        out = np.zeros(bins)
        for k in range(rr.size - 1):
            r1, r2, z1, z2 = rr[k], rr[k + 1], zz[k], zz[k + 1]
            if z1 == z2:
                continue
            # Area pi r(z)^2 is quadratic along the segment; integrate it bin by bin.
            lo, hi = min(z1, z2), max(z1, z2)
            sign = 1.0 if z2 > z1 else -1.0
            first = max(int(np.searchsorted(edges, lo, side="right")) - 1, 0)
            last = min(int(np.searchsorted(edges, hi, side="left")), bins)
            for b in range(first, last):
                a_z, b_z = max(lo, edges[b]), min(hi, edges[b + 1])
                if b_z <= a_z:
                    continue
                ra = r1 + (r2 - r1) * (a_z - z1) / (z2 - z1)
                rb = r1 + (r2 - r1) * (b_z - z1) / (z2 - z1)
                out[b] += sign * math.pi / 3.0 * (ra * ra + ra * rb + rb * rb) * (b_z - a_z)
        revolved = float(out.sum())
        if not revolved > 0.0:
            raise ValueError("the profile encloses no volume")
        total = revolved if volume is None else float(volume)
        return cls(0.5 * (edges[:-1] + edges[1:]), out * (total / revolved), crown, total)

    @property
    def fractions(self) -> FloatArray:
        """Height of each bin as a fraction of the crown height, dimensionless."""
        return self.heights / self.crown_height

    @property
    def weights(self) -> FloatArray:
        """Volume fraction of each bin, dimensionless (sums to 1)."""
        return self.volumes / self.total


@dataclass(frozen=True)
class StratificationModel:
    """Level-1 stratification of one envelope (module docstring).

    Attributes
    ----------
    distribution : VolumeDistribution
        Volume by height, from the design.
    mouth_excess : PhysicalConstant
        :math:`\\varphi`, dimensionless, in [0, 1], with its source tag.
    minimum_offset : PhysicalConstant
        Floor of the top-to-mean offset, K, with its source tag.
    """

    distribution: VolumeDistribution
    mouth_excess: PhysicalConstant = DEFAULT_MOUTH_EXCESS
    minimum_offset: PhysicalConstant = PhysicalConstant(0.0, "K", "assumed", "no floor")

    def __post_init__(self) -> None:
        if not 0.0 <= self.mouth_excess.value <= 1.0:
            raise ValueError("mouth excess must lie in [0, 1]")
        if self.minimum_offset.value < 0.0:
            raise ValueError("minimum offset must be non-negative (K)")

    def temperatures(
        self,
        top_temperature: float,
        ambient_temperature: float,
        heights: npt.ArrayLike,
        excess: float | None = None,
    ) -> FloatArray:
        """Gas temperature at heights above the mouth, K.

        Parameters
        ----------
        top_temperature, ambient_temperature : float
            Crown and ambient temperatures, K.
        heights : array_like
            Heights above the mouth, m (clamped to [0, crown]).
        excess : float, optional
            Mouth excess to use, dimensionless; default the model's
            (:meth:`profile` uses :meth:`excess_used`).
        """
        phi = self.mouth_excess.value if excess is None else excess
        f = np.clip(np.asarray(heights, dtype=np.float64) / self.distribution.crown_height, 0, 1)
        rise = top_temperature - ambient_temperature
        return ambient_temperature + rise * (phi + (1.0 - phi) * f)

    def effective_mean(
        self, top_temperature: float, ambient_temperature: float, excess: float | None = None
    ) -> float:
        """Lift-equivalent mean (volume-weighted harmonic mean) of the profile, K."""
        t = self.temperatures(
            top_temperature, ambient_temperature, self.distribution.heights, excess
        )
        return float(1.0 / np.sum(self.distribution.weights / t))

    def excess_used(self, top_temperature: float, ambient_temperature: float) -> float:
        """Mouth excess of the profile that gives :meth:`mean_from_top`, dimensionless:
        the model's, or lower when the floor applies (module docstring). 0 when even a
        mouth at ambient cannot reach the floor (the mean is then the floor's)."""
        phi = self.mouth_excess.value
        target = top_temperature - self.minimum_offset.value
        if self.effective_mean(top_temperature, ambient_temperature, phi) <= target:
            return phi
        if self.effective_mean(top_temperature, ambient_temperature, 0.0) >= target:
            return 0.0
        return float(
            brentq(
                lambda x: self.effective_mean(top_temperature, ambient_temperature, x) - target,
                0.0,
                phi,
                xtol=1e-10,
            )
        )

    def profile(
        self, top_temperature: float, ambient_temperature: float, heights: npt.ArrayLike
    ) -> FloatArray:
        """Gas temperature the mean of :meth:`mean_from_top` corresponds to, K, at heights
        above the mouth (m): the linear profile with :meth:`excess_used`."""
        return self.temperatures(
            top_temperature,
            ambient_temperature,
            heights,
            self.excess_used(top_temperature, ambient_temperature),
        )

    def mean_from_top(self, top_temperature: float, ambient_temperature: float) -> float:
        r"""Mean gas temperature for a crown temperature, K:
        :math:`\min(T_{eff},\ T_{top} - \Delta T_{min})`."""
        return min(
            self.effective_mean(top_temperature, ambient_temperature),
            top_temperature - self.minimum_offset.value,
        )

    def offset(self, top_temperature: float, ambient_temperature: float) -> float:
        """Top minus mean temperature, K (floor included)."""
        return top_temperature - self.mean_from_top(top_temperature, ambient_temperature)

    def floor_applies(self, top_temperature: float, ambient_temperature: float) -> bool:
        """Whether the floor, not the profile, sets the mean."""
        eff = self.effective_mean(top_temperature, ambient_temperature)
        return top_temperature - self.minimum_offset.value < eff

    def top_from_mean(self, mean_temperature: float, ambient_temperature: float) -> float:
        """Crown temperature whose mean (:meth:`mean_from_top`) is ``mean_temperature``, K.

        The mean rises monotonically with the crown temperature, so the inverse is found
        by Brent's method between the mean itself and a crown far enough above it (the
        bracket doubles from 1 000 K until it holds the root).
        """
        if mean_temperature <= ambient_temperature:
            return mean_temperature + self.minimum_offset.value

        def gap(top: float) -> float:
            return self.mean_from_top(top, ambient_temperature) - mean_temperature

        lo, span = mean_temperature, 1000.0
        if gap(lo) >= 0.0:
            return lo
        # The crown runs ahead of the mean (the lower envelope is cooler), so a very hot
        # mean needs a far hotter crown: widen the bracket until it holds the root.
        while gap(lo + span) < 0.0:
            span *= 2.0
            if span > 1e9:
                raise ValueError("no crown temperature gives this mean temperature")
        return float(brentq(gap, lo, lo + span, xtol=1e-9, rtol=1e-12))

    def pressure_profile(
        self,
        top_temperature: float,
        ambient_temperature: float,
        pressure: float,
        heights: npt.ArrayLike,
        gravity: float = G0.value,
    ) -> FloatArray:
        """Internal-minus-ambient pressure consistent with :meth:`profile` (module
        docstring), Pa, at heights above the mouth (m); 0 at the mouth.

        Parameters
        ----------
        top_temperature, ambient_temperature : float
            K.
        pressure : float
            Ambient static pressure, Pa.
        heights : array_like
            m above the mouth.
        gravity : float, optional
            m/s^2.
        """
        h = np.clip(np.asarray(heights, dtype=np.float64), 0.0, self.distribution.crown_height)
        big_h = self.distribution.crown_height
        a = float(self.profile(top_temperature, ambient_temperature, 0.0))
        b = float(self.profile(top_temperature, ambient_temperature, big_h)) - a
        r = R_DRY_AIR.value
        if abs(b) < 1e-12:
            return gravity * pressure / r * (1.0 / ambient_temperature - 1.0 / a) * h
        return (
            gravity
            * pressure
            / r
            * (h / ambient_temperature - big_h / b * np.log((a + b * h / big_h) / a))
        )
