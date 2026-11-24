# Lift charts and equilibrium

Modules: `envelopelab.lift_chart` (the equilibrium) and `envelopelab.export.lift_chart`
(the build-pack charts). All quantities are SI internally (m, K, Pa, kg, N); the charts
print °C, m and kg.

## Equilibrium

A balloon floats in static equilibrium when its gross lift carries exactly its own mass
and its load:

\[
V\,(\rho_{amb} - \rho_{int}) = m_{fixed} + m_{load},
\qquad
\rho_{amb} = \frac{p}{R_d\,T_{amb}}, \quad \rho_{int} = \frac{p}{R_d\,T_{mean}}
\]

* \(V\): envelope volume, m³ (the design's lofted volume in the build pack);
* \(p\): ISA static pressure at the pressure altitude, Pa (`atmosphere.isa`);
* \(T_{amb}\): ambient air temperature **at that altitude**, K;
* \(T_{mean}\): volume-mean gas temperature inside the envelope, K;
* \(m_{fixed}\): envelope and rigging mass, kg (`GoreOutputs.envelope_mass + rigging_mass`);
* \(m_{load}\): everything else (basket, burners, fuel, occupants), kg.

## Top (crown) temperature and mean temperature

Pilots read the crown temperature, and the fabric limit applies there. The gas below the
crown is cooler, and the lift depends on the mean. EnvelopeLab uses a fixed offset:

\[
T_{mean} = T_{top} - \Delta T_{top\to mean}
\]

`DEFAULT_TOP_TO_MEAN` is 20 K, tagged **assumed**. It is a generic engineering value, not
a measurement. A larger offset predicts less lift and a hotter crown for the same load,
so a generous offset errs on the safe side. Replace it with a value measured on your
envelope, for example from the crown sensor compared with temperatures logged at several
heights.

## The four variables

Any three of top temperature, ambient temperature, altitude and load fix the fourth.

| Function | Given | Solves | Method |
|---|---|---|---|
| `equilibrium_load` | altitude, ambient, top | load | closed form, \(m_{load} = V(\rho_{amb}-\rho_{int}) - m_{fixed}\) |
| `equilibrium_top_temperature` | altitude, ambient, load | top temperature | closed form, below |
| `equilibrium_altitude` | ISA deviation, top, load | altitude (ceiling) | scan in 100 m steps, then Brent's method |

The top temperature for a load is

\[
\frac{1}{T_{mean}} = \frac{1}{T_{amb}} - \frac{R_d\,(m_{fixed}+m_{load})}{p\,V},
\qquad T_{top} = T_{mean} + \Delta T_{top\to mean}.
\]

When the right-hand side is \(\le 0\), the mass exceeds the mass of the displaced air,
\(V\rho_{amb}\), and no temperature lifts it. The point is then `no_equilibrium`.

For the ceiling the ambient temperature follows the ISA shifted by a deviation,
\(T_{amb}(h) = T_{ISA}(h) + \Delta T_{ISA}\). In the troposphere
\(\rho_{amb} \propto T^{4.256}\) and \(p \propto T^{5.256}\), so at a fixed mean gas
temperature

\[
\frac{d}{dT}\left(\rho_{amb} - \rho_{int}\right) > 0
\iff T_{amb} < \frac{4.256}{5.256}\,T_{mean} \approx 0.81\,T_{mean}.
\]

On a very hot day (\(T_{amb} > 0.81\,T_{mean}\), e.g. above about 29 °C with a 100 °C mean)
lift grows slightly with height near the ground. The ceiling is therefore defined as the
**lowest** altitude above the start where the spare lift turns negative. It is found by
scanning rather than by assuming lift falls with height. This is why the ISA+30 curve of
the ceiling chart is nearly vertical near sea level.

## Status of each point

Points are never dropped. Each one carries a status:

| Status | Meaning |
|---|---|
| `ok` | Equilibrium within the top-temperature limit |
| `above_limit` | The top temperature exceeds the limit. **Not a permitted state.** It is shaded red on the charts |
| `no_equilibrium` | No temperature lifts the mass, the load is negative (the envelope cannot lift itself), or the balloon cannot lift the load at the start altitude |
| `beyond_range` | Still spare lift at 11 000 m, the top of the search |

## Top-temperature limit

The limit is the lowest `max_service_temperature` among the fabrics of the design's
zones, with that fabric's source tag. A fabric not in the library gets the generic
120 °C, tagged **assumed** (`project.simulation.membrane_for_fabric`).

## Assumptions and valid range

* Static equilibrium: still air, no climb or descent, no drag or added mass.
* Uniform densities over the envelope height (< 0.4 % change over 30 m).
* Dry ideal-gas air inside and out. Humidity and combustion products are not modelled.
  Humid ambient air is lighter, so on a humid day the real lift is slightly lower.
* Internal pressure equals ambient (open mouth). The overpressure of a few tens of Pa
  changes density by < 0.05 %.
* A constant top-to-mean offset. Real stratification depends on the burner pattern,
  porosity and heat loss.
* A fixed volume: the design's lofted volume, not a solved inflated shape.
* Valid for −5 000 m to 11 000 m and 200 K to 420 K.

## Benchmarks

See [Lift-chart benchmarks](../validation/lift-chart-benchmarks.md): load, top temperature
and ceiling against hand calculations written out in closed form.

## References

* ISO 2533:1975, *Standard Atmosphere*.
* FAA, *Balloon Flying Handbook*, FAA-H-8083-11 (aerostatics; flight-manual loading charts).
* Archimedes' principle; see [Atmosphere](atmosphere.md) for the densities and gross lift.
