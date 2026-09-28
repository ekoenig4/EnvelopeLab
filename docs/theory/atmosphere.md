# Atmosphere, lift and hydrostatic pressure

Module: `envelopelab.atmosphere`. All quantities are SI (m, K, Pa, kg/m³, N).

## Constants

| Symbol | Value | Unit | Source | Reference |
|---|---|---|---|---|
| \(g_0\) | 9.806 65 | m/s² | datasheet | ISO 2533:1975 |
| \(R_d\) | 287.052 87 | J/(kg K) | datasheet | ISO 2533:1975 |
| \(R_v\) | 461.495 | J/(kg K) | datasheet | CODATA \(R\) / \(M_{H_2O}\) |
| \(p_0\) | 101 325 | Pa | datasheet | ISO 2533:1975 |
| \(T_0\) | 288.15 | K | datasheet | ISO 2533:1975 |
| \(r_0\) | 6 356 766 | m | datasheet | ISO 2533:1975 (geopotential radius) |

Each constant is a `PhysicalConstant(value, unit, source, reference)`.

## International Standard Atmosphere — `isa(h, temperature_offset=0)`

Layers (geopotential altitude \(h\)):

| Base \(h_b\) (m) | \(T_b\) (K) | Lapse \(L\) (K/m) |
|---|---|---|
| 0 | 288.15 | −0.0065 |
| 11 000 | 216.65 | 0 |
| 20 000 | 216.65 | +0.001 |

Within a layer

\[
T = T_b + L\,(h - h_b), \qquad
p = p_b \left(\frac{T}{T_b}\right)^{-g_0/(L R_d)} \;(L \neq 0), \qquad
p = p_b \exp\!\left(-\frac{g_0 (h-h_b)}{R_d T_b}\right) \;(L = 0),
\]

and \(\rho = p/(R_d T)\).

* **Valid range:** −5 000 m to 32 000 m geopotential altitude. Outside it `isa` raises.
* **Geometric altitude:** convert with `geometric_to_geopotential`,
  \(H = r_0 z / (r_0 + z)\) (11 km geometric ≈ 10 981 m geopotential).
* **Non-standard days:** `temperature_offset` \(\Delta T\) shifts temperature at the same
  pressure (pressure-altitude convention), so \(\rho = p_{ISA}(h) / (R_d (T_{ISA} + \Delta T))\).
* **Assumptions:** dry air, hydrostatic equilibrium, constant \(g_0\).

## Ideal-gas density — `gas_density(p, T, relative_humidity=0)`

Dry air (default): \(\rho = p/(R_d T)\).

Optional humidity correction (off by default). With vapour pressure \(e = \varphi\,e_s(T)\)
and the Buck (1981) saturation pressure

\[
e_s = 611.21 \exp\!\left[\left(18.678 - \frac{t}{234.5}\right)\frac{t}{257.14 + t}\right]
\quad (t \text{ in °C}),
\]

\[
\rho = \frac{p - e}{R_d T} + \frac{e}{R_v T}.
\]

Humid air is lighter than dry air (saturated air at 30 °C is ~1.2 % lighter), so using the
dry value for the **ambient** air overstates lift slightly; switch the correction on for hot,
humid days. The internal gas is treated as air: combustion products (CO₂, H₂O) change
\(R\) by well under 1 % and are not modelled. Valid range of \(e_s\): −40 °C to 100 °C.

## Gross lift — `gross_lift(V, rho_amb, rho_int)`

\[
L = V\,(\rho_{amb} - \rho_{int})\,g
\]

Assumes uniform densities over the envelope height: across 30 m the ambient density changes
by ~0.3 %, well inside the uncertainty of the mean internal temperature.

## Hydrostatic differential pressure — `differential_pressure(h, h_mouth, rho_amb, rho_int)`

The mouth is open, so the internal and ambient pressures are equal there. Above the mouth
both columns are hydrostatic, so the net outward pressure on the fabric is

\[
\Delta p(h) = (\rho_{amb} - \rho_{int})\,g\,(h - h_{mouth}),
\qquad \frac{d\,\Delta p}{dh} = (\rho_{amb} - \rho_{int})\,g .
\]

Assumes a static gas with uniform densities. Burner jet, wind and manoeuvre (dynamic) pressure
are not included. Valid for envelope heights up to ~100 m.

## Hand calculation (benchmark)

Ambient 15 °C, internal 100 °C, sea-level pressure:

| Quantity | Hand value |
|---|---|
| \(\rho_{amb} = 101325/(287.05287 \times 288.15)\) | 1.2250 kg/m³ |
| \(\rho_{int} = 101325/(287.05287 \times 373.15)\) | 0.9460 kg/m³ |
| \(\Delta\rho\) | 0.2790 kg/m³ |
| \(d\Delta p/dh = 0.2790 \times 9.80665\) | 2.736 Pa/m (≈ 2.74) |
| \(L\) for 2 610 m³ \(= 2610 \times 0.2790 \times 9.80665\) | 7 142 N (728.3 kgf) |

The computed values are compared against these in
[analytic benchmarks](../validation/analytic-geometry.md) (tolerance 1 %).

## References

* ISO 2533:1975, *Standard Atmosphere* (identical to U.S. Standard Atmosphere 1976 below
  32 km).
* A. L. Buck, "New equations for computing vapor pressure and enhancement factor",
  *J. Appl. Meteorol.* 20 (1981) 1527–1532.
* F. M. White, *Fluid Mechanics*, ch. 2 (hydrostatics).
