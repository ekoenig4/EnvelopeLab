# Lift charts and equilibrium

Modules: `envelopelab.lift_chart` (the equilibrium), `envelopelab.export.lift_chart`
(the charts, and `theory_sections`, the theory text the application's *Lift charts ▸
Theory* tab and the last page of the PDF show with the values of the open design) and
`envelopelab.validation.lift_chart` (the benchmarks). All quantities are SI internally
(m, K, Pa, kg, N); the charts print °C, m and kg with °F, ft and lb scales.

## 1. Gross lift

A hot-air balloon is lifted by the weight of the air it displaces minus the weight of the
hot air inside it (Archimedes' principle):

\[
L = V\,(\rho_{amb} - \rho_{int})\,g
\]

* \(L\): **gross lift**, N: everything the balloon can carry, *its own envelope and
  rigging included*. Gross lift is not payload.
* \(V\): envelope volume, m³ (the design's lofted volume; see *Assumptions*);
* \(g\): standard gravity, 9.806 65 m/s² (`atmosphere.G0`). Lift is quoted as a mass,
  \(L/g\) in kg (or lb), which is the mass it holds up at standard gravity.

The mouth is open, so inside and outside are at the same static pressure \(p\) (the
hydrostatic overpressure of a few tens of Pa changes the density by < 0.05 %). Both gases
follow the ideal-gas law, \(\rho = p/(R_d T)\), so

\[
\frac{L}{g} = \frac{p\,V}{R_d}\left(\frac{1}{T_{amb}} - \frac{1}{T_{mean}}\right)
\]

with absolute temperatures. This is the whole lift model: every chart evaluates it.

## 2. Which temperature: mean, top and "envelope temperature"

The gas in an envelope is stratified: hottest at the crown, coolest near the mouth. The
density in the lift equation is the volume average, so the temperature in it is the
**volume-mean gas temperature** \(T_{mean}\). Two other temperatures matter:

* the **top (crown) temperature** \(T_{top}\): what the pilot's crown sensor reads, and
  where the fabric limit applies (the hottest fabric);
* an **"envelope temperature"** entered in a spreadsheet that assumes one uniform
  temperature for the whole envelope. In the lift equation that temperature can only be
  the mean.

EnvelopeLab relates top and mean in one of two ways (*Lift charts ▸ Mean temperature*,
ADR-0060):

* **From the envelope's shape** (the default, level 1;
  [Gas temperature stratification](stratification.md)): the gas temperature is assumed to
  rise linearly from the mouth (50 % of the crown's rise above ambient, *assumed*) to the
  crown, and the mean is its volume-weighted harmonic mean over the design's volume
  distribution, never less than a floor below the crown:
  \[
  T_{mean} = \min\bigl(T_{eff}(T_{top}, T_{amb}),\ T_{top} - \Delta T_{min}\bigr).
  \]
  The offset then depends on the envelope's shape and on the ambient temperature.
* **Fixed offset**:
  \[
  T_{mean} = T_{top} - \Delta T_{top\to mean}.
  \]

`DEFAULT_TOP_TO_MEAN` is 20 K (36 °F), tagged **assumed**: a generic engineering value,
not a measurement. It is the floor of the shape model and the offset of the fixed model.
Each project can set its own value and source tag; measure it on the envelope (crown
sensor vs temperatures logged at several heights) and tag it **measured**. A larger offset
(or a cooler mouth) predicts less lift and a hotter crown for the same load, so it errs on
the safe side. **An offset of 0 is the least conservative choice**: it reproduces a
uniform-temperature spreadsheet exactly, overstating lift and understating the crown
temperature of a real, stratified envelope.

The distinction changes the numbers a lot. For a 92 000 ft³ envelope (2 605 m³), with a
fixed 20 K offset (the shape model typically gives more):

| Ambient, altitude | Temperature read | Uniform envelope at that temperature | Crown at that temperature, mean 20 K lower | Difference |
|---|---|---|---|---|
| 40 °F, 300 ft | 200 °F | 1 752 lb | 1 436 lb | −18 % |
| 40 °F, 300 ft | 250 °F | 2 138 lb | 1 866 lb | −13 % |
| 90 °F, 6 000 ft | 200 °F | 887 lb | 631 lb | −29 % |
| 90 °F, 6 000 ft | 250 °F | 1 199 lb | 979 lb | −18 % |

Reading the crown sensor into a uniform-temperature chart therefore overstates the lift
(by the amount the crown is hotter than the mean). EnvelopeLab reads **every chart against
the crown (top) temperature**, the one the pilot measures; each point's lift uses the mean
that crown temperature gives (section above). The gross-lift chart therefore has the same
form as those spreadsheet charts but with the crown on its horizontal axis; with a fixed
offset of 0 the two are identical.

## 3. Atmosphere

* **Pressure**: International Standard Atmosphere (ISO 2533) at the pressure altitude
  \(h\) (`atmosphere.isa`). Below 11 km
  \[
  p = p_0\left(1 - \frac{L_0 h}{T_0}\right)^{g_0/(L_0 R_d)},\quad
  p_0 = 101\,325\ \mathrm{Pa},\ T_0 = 288.15\ \mathrm{K},\ L_0 = 0.0065\ \mathrm{K/m},\
  \frac{g_0}{L_0 R_d} = 5.25588
  \]
  (in US units: 2116.22 lbf/ft², 0.001 981 2 K/ft). A flight altitude in feet MSL on a
  standard-pressure day is this pressure altitude.
* **Ambient temperature**: the air temperature *at the flight altitude*, as given; it is
  not derived from the lapse rate, so ambient temperature and altitude are independent
  axes. The ceiling chart is the exception: there the ambient temperature follows the ISA
  shifted by a deviation, \(T_{amb}(h) = T_{ISA}(h) + \Delta T_{ISA}\).

## 4. Constants and units

| Quantity | SI value | US value | Source |
|---|---|---|---|
| Gas constant of dry air \(R_d\) | 287.052 87 J/(kg K) | 53.352 ft lbf/(lb °R) | datasheet, ISO 2533 |
| Standard gravity \(g_0\) | 9.806 65 m/s² | 32.174 ft/s² | datasheet, ISO 2533 |
| Sea-level pressure \(p_0\) | 101 325 Pa | 2116.22 lbf/ft² | datasheet, ISO 2533 |
| Absolute temperature | K = °C + 273.15 | °R = °F + 459.67 | definition |
| Mass, length | — | 1 lb = 0.453 592 37 kg, 1 ft = 0.3048 m | definition (1959) |

## 5. Equilibrium: the four variables

The balloon floats when the gross lift carries exactly its mass and its load:

\[
\frac{L}{g} = m_{fixed} + m_{load}
\]

\(m_{fixed}\): envelope and rigging mass, kg (`GoreOutputs.envelope_mass + rigging_mass`);
\(m_{load}\): everything else (basket, burners, fuel, occupants), kg. Any three of top
temperature, ambient temperature, altitude and load fix the fourth.

| Function | Given | Solves | Method |
|---|---|---|---|
| `lift_mass` | altitude, ambient, mean temperature | gross lift \(L/g\) | closed form (section 1) |
| `equilibrium_load` | altitude, ambient, top | load | closed form, \(m_{load} = L/g - m_{fixed}\) |
| `equilibrium_top_temperature` | altitude, ambient, load | top temperature | closed form, below |
| `equilibrium_altitude` | ISA deviation, top, load | altitude (ceiling) | scan in 100 m steps, then Brent's method |

The top temperature for a load is

\[
\frac{1}{T_{mean}} = \frac{1}{T_{amb}} - \frac{R_d\,(m_{fixed}+m_{load})}{p\,V},
\qquad T_{top} = T_{mean} + \Delta T_{top\to mean}.
\]

When the right-hand side is \(\le 0\), the mass exceeds the mass of the displaced air,
\(V\rho_{amb}\), and no temperature lifts it. The point is then `no_equilibrium`.

For the ceiling, in the troposphere \(\rho_{amb} \propto T^{4.256}\) and
\(p \propto T^{5.256}\), so at a fixed mean gas temperature

\[
\frac{d}{dT}\left(\rho_{amb} - \rho_{int}\right) > 0
\iff T_{amb} < \frac{4.256}{5.256}\,T_{mean} \approx 0.81\,T_{mean}.
\]

On a very hot day (\(T_{amb} > 0.81\,T_{mean}\), e.g. above about 29 °C with a 100 °C mean)
lift grows slightly with height near the ground. The ceiling is therefore the **lowest**
altitude above the start where the spare lift turns negative, found by scanning rather
than by assuming lift falls with height. This is why the ISA+30 curve of the ceiling chart
is nearly vertical near sea level.

## 6. The charts

| Chart (PDF page, *Lift charts* sub-tab) | x | y | Curves | Temperature read against |
|---|---|---|---|---|
| Maximum load | ambient temperature at altitude | load at the limit | one per altitude | top, at its limit |
| Gross lift | crown temperature | gross lift \(L/g\) | one per ambient, one panel per altitude | top; red line at the limit |
| Stratification | gas temperature / pressure difference | height above the mouth | one per ambient (temperature); stratified vs uniform (pressure) | top, at its limit (shape model only) |
| Top temperature | load | top temperature needed | one per ambient, one panel per altitude | top |
| Ceiling | load | equilibrium altitude | one per ISA deviation | top, at its limit |
| Theory | — | — | the text of this page's sections 1–5 with the design's own values | — |

On the gross-lift chart the dashed lines are the envelope + rigging mass and that plus the
design load: where a curve crosses a line, the balloon floats with that load. The region
beyond the red line (crown above its limit) is shaded and every curve ends at it. On the top-temperature chart the
region above the limit is shaded. Each chart also has the US scale of each axis.

## 7. Comparison with builders' lift spreadsheets

The *Envelope lifting capacity* spreadsheet of the Balloon Builders Journal (issue 8),
used for example with the 92 000 ft³ Smalley pattern, computes the gross lift in pounds:

\[
L\,[\mathrm{lb}] = \frac{V\,p}{R}\left(\frac{1}{T_{amb}} - \frac{1}{T_{env}}\right),\qquad
p\,[\mathrm{lbf/ft^2}] = 2116\left(\frac{288.15}{288.15 - 0.00198\,h}\right)^{-5.25587}
\]

with \(V\) in ft³, \(h\) in ft MSL, \(R = 53.34\) ft lbf/(lb °R), °R = °F + 459 and one
envelope temperature \(T_{env}\), plotted against \(T_{env}\) (130–280 °F) for chosen
pairs of ambient temperature and altitude.

| Item | Spreadsheet | EnvelopeLab | Effect on the spreadsheet's lift |
|---|---|---|---|
| Lift equation | Archimedes, ideal gas, inside at ambient pressure | the same | — |
| Pressure | ISA, \(p_0 = 2116\) lbf/ft², lapse 0.00198 K/ft | ISA, 2116.22 lbf/ft², 0.001 981 2 K/ft | ±0.01 % |
| Gas constant | 53.34 ft lbf/(lb °R) | 53.352 (287.052 87 J/(kg K)) | +0.02 % |
| Absolute temperature | °F + 459 | °F + 459.67 | **+0.24 %** |
| Ambient temperature | at the flight altitude, as given | the same (except the ceiling chart) | — |
| Envelope temperature | one uniform temperature | mean gas temperature; top = mean + offset | see section 2 |
| Output | gross lift only | gross lift, load at the limit, top temperature needed, ceiling | — |
| Fabric limit | not shown | crown limit from the fabric's service temperature, shaded | — |

With exact constants the two agree to 1e-4 (the spreadsheet's \(T_{env}\) being the
mean gas temperature); as published the spreadsheet is 0.23–0.27 % higher, almost all from
°F + 459. Both are tested in [Lift-chart benchmarks](../validation/lift-chart-benchmarks.md).
The substantive difference is section 2: the spreadsheet's envelope temperature is a mean
temperature, so it must not be read off the crown sensor.

## 8. Status of each point

Points are never dropped. Each one carries a status:

| Status | Meaning |
|---|---|
| `ok` | Equilibrium within the top-temperature limit |
| `above_limit` | The top temperature exceeds the limit. **Not a permitted state.** It is shaded red on the charts |
| `no_equilibrium` | No temperature lifts the mass, the load is negative (the envelope cannot lift itself), or the balloon cannot lift the load at the start altitude |
| `beyond_range` | Still spare lift at 11 000 m, the top of the search |

## 9. Top-temperature limit

The limit is the lowest `max_service_temperature` among the fabrics of the design's
zones, with that fabric's source tag. A fabric not in the library gets the generic
120 °C, tagged **assumed** (`project.simulation.membrane_for_fabric`).

## 10. Assumptions and valid range

* Static equilibrium: still air, no climb or descent, no drag or added mass.
* Uniform densities over the envelope height (< 0.4 % change over 30 m).
* Dry ideal-gas air inside and out. Humidity and combustion products are not modelled.
  Humid ambient air is lighter, so on a humid day the real lift is slightly lower.
* Internal pressure equals ambient (open mouth).
* The top-to-mean relation: an assumed linear profile over the design's volume (default)
  or a constant offset. Real stratification depends on the burner pattern, porosity, heat
  loss, sun and wind ([Gas temperature stratification](stratification.md)).
* A fixed volume: the design's lofted volume, not a solved inflated shape.
* Valid for −5 000 m to 11 000 m and 200 K to 420 K.

## Benchmarks

See [Lift-chart benchmarks](../validation/lift-chart-benchmarks.md): load, top temperature
and ceiling against hand calculations written out in closed form, and gross lift against
the builders' spreadsheet formula (as published and with exact constants).

## References

* ISO 2533:1975, *Standard Atmosphere*.
* NIST SP 811, *Guide for the Use of the International System of Units* (lb, ft, °R).
* FAA, *Balloon Flying Handbook*, FAA-H-8083-11 (aerostatics; flight-manual loading charts).
* Balloon Builders Journal, issue 8: *Envelope lifting capacity* spreadsheet.
* Archimedes' principle; see [Atmosphere](atmosphere.md) for the densities and gross lift.
