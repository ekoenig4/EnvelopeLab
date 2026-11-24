# Lift charts

The lift charts show the **equilibrium points** of your envelope: the load it floats,
the top (crown) temperature that load needs, and how high it can go. They cover a range
of top temperatures, ambient temperatures, altitudes and loads.

!!! warning "Design aid, not a flight manual"
    The charts are static equilibrium values from the design. They are not a certified
    loading chart. Points above the top-temperature limit are shaded red and marked
    `above_limit`. Check every value tagged *assumed* before relying on the charts.

## Getting the charts

*File ▸ Export build pack…*, tick **Lift charts** (ticked by default). The pack then
contains:

* `<name>-lift-chart.pdf`, three A4 landscape pages:
    1. **Maximum load at the top-temperature limit** vs ambient temperature, one curve
       per pressure altitude (0, 1 000, 2 000 and 3 000 m). Go up from the ambient
       temperature at that altitude to the curve and read the most load that floats with
       the crown at the limit. The inputs and their source tags are listed below the chart.
    2. **Top temperature needed** vs load, one panel per altitude, one curve per ambient
       temperature (−10 to 30 °C). The red dashed line is the limit. The shaded region
       above it is not permitted. The dotted line marks the design's payload.
    3. **Equilibrium altitude (ceiling)** vs load, with the crown at the limit, one curve
       per ISA deviation (−15, 0, +15 and +30 K).
  Every chart has metric and English units: kg with an lb scale, °C with a °F scale,
  m with ft. The legends, the limit line and the design load give both.
* `<name>-lift-chart.csv` (SI and °C only): every equilibrium point of the grid, with columns
  `solved_for, altitude_m, isa_offset_K, ambient_C, top_C, mean_C, load_kg,
  gross_lift_N, status`.

## What goes in

| Input | From | Source tag |
|---|---|---|
| Envelope volume | the design's lofted profile (as drawn) | geometry |
| Envelope + rigging mass | the mass estimate (Shape mode outputs) | the fabric, tape and line values |
| Top-temperature limit | lowest service temperature of the design's fabrics | the fabric's tag; 120 °C *assumed* when not in the library |
| Mean temperature | top − 20 K | *assumed*, replace with a measured value |

**Load** means everything carried besides the envelope and rigging: basket, burners,
fuel and occupants.

When the envelope mass cannot be estimated (for example the panel rows do not cover the
profile), the PDF says *NOT PRODUCED* and the CSV holds only its header.

## Using the library directly

```python
from envelopelab.atmosphere import PhysicalConstant, celsius_to_kelvin
from envelopelab.lift_chart import LiftChartInputs, equilibrium_top_temperature

inputs = LiftChartInputs(
    volume=2610.0,  # m^3
    volume_note="measured",
    fixed_mass=210.0,  # kg, envelope + rigging
    fixed_mass_sources=("measured",),
    top_limit=PhysicalConstant(393.15, "K", "datasheet", "fabric datasheet"),
)
point = equilibrium_top_temperature(inputs, 1000.0, celsius_to_kelvin(20.0), 350.0)
print(point.top_temperature - 273.15, point.status)
```

See [Lift charts and equilibrium](../theory/lift-charts.md) for the equations and the
assumptions.
