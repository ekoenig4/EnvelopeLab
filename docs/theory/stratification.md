# Gas temperature stratification (level 1)

Module: `envelopelab.stratification`. Used by the lift charts
([Lift charts and equilibrium](lift-charts.md)) to relate the crown temperature to the mean
gas temperature; see ADR-0060. All quantities are SI (m, K, Pa).

## Why the shape matters

The gas in a hot-air envelope is hottest at the crown and coolest at the mouth: the burner
plume rises to the crown, and the fabric cools the gas beside it, which sinks along the
walls (a stably stratified "filling box", Baines & Turner 1969). Lift is the volume
integral of the density difference,

\[
\frac{L}{g} = \int_V \bigl(\rho_{amb} - \rho(h)\bigr)\,dV,
\qquad \rho = \frac{p}{R_d T},
\]

so the temperature that gives the same lift as the real profile is the **volume-weighted
harmonic mean**

\[
\frac{1}{T_{eff}} = \frac{1}{V}\int_V \frac{dV}{T(h)}.
\]

Where the volume lies in height decides how much of the gas is hot: an envelope with much
of its volume high up (a teardrop) has a mean close to the crown temperature; one with its
volume low (a squat or cone-down shape) a mean further below it. The design gives this
distribution exactly; the temperature profile itself has to be modelled or measured.

## Level 1: assumed profile, real shape

Height \(h\) is measured up from the mouth; \(H\) is the crown height above it.

**Volume by height.** Each segment of the design's meridian profile, from
\((r_1, z_1)\) to \((r_2, z_2)\), sweeps a frustum

\[
dV = \frac{\pi}{3}\,(r_1^2 + r_1 r_2 + r_2^2)\,(z_2 - z_1),
\]

split over height bins (400 by default) in proportion to the height it covers in each
(the area \(\pi r^2\) is integrated exactly along the segment). The distribution is scaled
to the design's lofted volume, so the gore bulge counts in the same proportion at every
height.

**Temperature profile.** Linear from mouth to crown:

\[
T(h) = T_{amb} + (T_{top} - T_{amb})\left[\varphi + (1 - \varphi)\frac{h}{H}\right]
\]

\(\varphi\) is the temperature rise above ambient at the mouth as a fraction of the rise at
the crown: **50 %, tagged assumed** (`DEFAULT_MOUTH_EXCESS`), editable per project
(*Lift charts ▸ Mouth temperature rise*). \(\varphi = 100\,\%\) is a uniform envelope;
a lower \(\varphi\) is a cooler lower envelope: less lift, more conservative.

**Mean and floor.** The mean used is never less than a floor below the crown (the
project's *Minimum top minus mean*, 20 K by default, tagged assumed):

\[
T_{mean} = \min\bigl(T_{eff}(T_{top}, T_{amb}),\ T_{top} - \Delta T_{min}\bigr).
\]

When the floor applies, the profile shown is the linear one with a lower mouth rise
\(\varphi' < \varphi\), solved so that its \(T_{eff}\) is exactly
\(T_{top} - \Delta T_{min}\): the floor cools the lower envelope, never the crown. (If even
\(\varphi' = 0\), a mouth at ambient, cannot reach the floor, the mean is the floor's and
the profile drawn is the one with \(\varphi' = 0\).)

**Inverse.** The mean rises monotonically with the crown temperature, so the crown
temperature for a mean (needed by the top-temperature chart) is found by Brent's method;
the bracket doubles from 1 000 K until it holds the root.

The offset depends on the ambient temperature (a warmer day, a smaller rise, a smaller
offset), so the lift charts evaluate it at each condition, and the ceiling at each
altitude of its search.

## Pressure consistent with the profile

The internal-minus-ambient pressure follows from hydrostatics with the open mouth as zero:

\[
\Delta p(h) = g\int_0^{h}\bigl(\rho_{amb} - \rho(h')\bigr)\,dh'
= \frac{g\,p}{R_d}\left[\frac{h}{T_{amb}} - \frac{H}{b}\,\ln\frac{a + b\,h/H}{a}\right],
\]

with \(a = T(0)\) and \(b = T(H) - T(0)\) (for \(b = 0\) it is the uniform
\((\rho_{amb} - \rho)\,g\,h\)). It grows faster near the hot crown than a uniform
envelope's; the *Stratification* chart compares the two at the same mean. The structural
(inflation) solver still uses a uniform internal temperature, i.e. a constant gradient:
that gradient is a consequence of the uniform-temperature assumption, so it carries no
information about the temperature profile.

## Assumptions and valid range

* The profile's *form* (linear in height) and \(\varphi\) are assumed, not predicted:
  the real profile depends on the burner duty, heat loss through the fabric, porosity,
  sun and wind. A heat-balance model (plume entrainment, wall loss per slice; "level 2")
  would predict them; a crown and a mid-height sensor would measure them.
* Each horizontal layer is at one temperature (no plume core, no wall boundary layer).
* The static pressure is the same inside and out over the envelope height.
* The lofted-to-revolved volume ratio is the same at every height.
* \(0 \le \varphi \le 1\), \(T_{top} > T_{amb}\).

## Benchmarks

[Lift-chart benchmarks](../validation/lift-chart-benchmarks.md), *Stratification* rows: a
cylinder against the closed form \(T_{eff} = b/\ln(1 + b/a)\), a sphere against adaptive
quadrature, the crown pressure against trapezoidal integration, and the floor.

## References

* W. D. Baines and J. S. Turner, "Turbulent buoyant convection from a source in a confined
  region", *J. Fluid Mech.* 37 (1969) 51–80.
* B. R. Morton, G. I. Taylor and J. S. Turner, "Turbulent gravitational convection from
  maintained and instantaneous sources", *Proc. R. Soc. A* 234 (1956) 1–23 (plume theory,
  for a future heat-balance model).
* Pappus's centroid theorem; Archimedes' principle; ISO 2533:1975.
