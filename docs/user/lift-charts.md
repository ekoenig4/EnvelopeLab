# Lift charts

The lift charts show the **equilibrium points** of your envelope: the load it floats,
the top (crown) temperature that load needs, and how high it can go. They cover a range
of top temperatures, ambient temperatures, altitudes and loads.

!!! warning "Design aid, not a flight manual"
    The charts are static equilibrium values from the design. They are not a certified
    loading chart. Points above the top-temperature limit are shaded red and marked
    `above_limit`. Check every value tagged *assumed* before relying on the charts.

## The Lift charts mode

The **Lift charts** tab of the main window (Ctrl+8) shows the charts of the design you
are editing, next to the settings of the curves they draw:

* **Curves** (left): the settings of [Choosing the curves](#choosing-the-curves). The
  charts redraw as you type. A setting is saved to the project when you pause, as one
  undo step, so *Edit ▸ Undo* puts the previous curves back in the form and the charts.
  While an entry does not read, the charts keep the last good curves and the reason
  is shown in red.
* **Inputs and assumptions** (left, below): the volume, envelope and rigging mass,
  top-temperature limit and top-to-mean offset the charts use, each with its source tag,
  and the safety notice.
* **Charts** (right), one sub-tab each: **Maximum load**, **Gross lift** (one chart per
  altitude), **Stratification** (the assumed temperature profile and its pressure), **Top temperature** (one chart per altitude, up to four) and **Ceiling**.
  These are the pages of the PDF below, drawn on screen with the same data. The region
  above the top-temperature limit is shaded red and labelled *not permitted*.
* **Theory** (last sub-tab): how the charts are calculated, the equations, constants and
  assumptions, with this design's own values (volume, masses, the ISA pressure at each
  altitude, the offset and its source). The same text is the last page of the PDF;
  [Lift charts and equilibrium](../theory/lift-charts.md) explains it in full.
* **Export PDF…** writes these charts as a PDF, with every equilibrium point in a CSV
  file beside it.

The charts follow every edit of the design (profile, fabrics, rigging, payload). When
the envelope mass cannot be estimated, the tab says why instead of drawing.

## Getting the charts

*File ▸ Export build pack…*, tick **Lift charts** (ticked by default). The pack then
contains:

* `<name>-lift-chart.pdf`, six A4 landscape pages (five with a fixed offset); after the
  gross-lift page comes the **stratification** page (temperature and pressure by height):
    1. **Maximum load at the top-temperature limit** vs ambient temperature, one curve
       per pressure altitude (by default 0, 1 000, 2 000 and 3 000 m). Go up from the ambient
       temperature at that altitude to the curve and read the most load that floats with
       the crown at the limit. The inputs and their source tags are listed below the chart.
    2. **Gross lift** vs crown temperature, one chart per altitude, one curve per
       ambient temperature: the classic lift chart of builders' spreadsheets, read with
       your crown sensor. The dashed lines are the envelope + rigging mass and that plus
       the design load: where a curve crosses one, the balloon floats. The red line is the
       crown limit; beyond it is shaded and the curves end there. Behind each point the
       lift uses the mean gas temperature that crown temperature gives (see *Mean or crown
       temperature* below).
    3. **Top temperature needed** vs load, one panel per altitude, one curve per ambient
       temperature (by default −10 to 30 °C). The red dashed line is the limit. The shaded region
       above it is not permitted. The dotted line marks the design's payload.
    4. **Equilibrium altitude (ceiling)** vs load, with the crown at the limit, one curve
       per ISA deviation (by default −15, 0, +15 and +30 K).
  Every chart has metric and English units: kg with an lb scale, °C with a °F scale,
  m with ft. The legends, the limit line and the design load give both.
* `<name>-lift-chart.csv` (SI and °C only): every equilibrium point of the grid, with columns
  `solved_for, altitude_m, isa_offset_K, ambient_C, top_C, mean_C, load_kg,
  gross_lift_N, status`.

## Choosing the curves

The **Lift charts** tab, *Design ▸ Lift charts…* or **Curves and units…** beside
*Lift charts* in the export dialog set the curves for this project. They are saved with the project and undone
with *Edit ▸ Undo* like any edit.

| Setting | What it does | Allowed |
|---|---|---|
| **Units** | Type in metric (m, °C, kg) or English (ft, °F, lb). Switching converts what is typed. The choice is remembered. | |
| **Altitudes** | Pressure altitudes: one curve each on the loading chart and one panel each on the temperature page | 1 to 4, −5 000 m to 11 000 m |
| **Ambient temperatures** | One curve each on the temperature page | 1 to 6, −50 °C to 60 °C |
| **ISA deviations** | One curve each on the ceiling chart (0 is a standard day) | 1 to 6, −50 K to 50 K |
| **Load axis up to** | The end of the load axis. *Automatic* uses the most the balloon lifts | above 0 |
| **Lowest top temperature** | The first crown temperature tabulated in the CSV (then every 10 °C to the limit) | 0 °C to 200 °C |
| **Mean temperature** | *From envelope shape* (default): an assumed linear profile weighted by the design's volume; or *Fixed offset* | |
| **Mouth temperature rise** | Shape model: the mouth's rise above ambient as a share of the crown's, with its source and a note (lower is more conservative) | 0 to 100 % |
| **Minimum top minus mean** / **Top minus mean temperature** | The floor of the shape model, or the fixed offset, with its source (*assumed*, *measured* or *datasheet*) and a note | 0 to 100 K |

Type lists separated by commas, semicolons or spaces. Thousands separators are fine:
`0, 5,000, 10,000` reads as three altitudes. Anything that doesn't read, or is out of
range, is explained under the fields, and **OK** stays disabled until it is fixed.
**Preview…** opens the charts for what is typed, before you save it.
**Restore defaults** brings back the default curves and the *assumed* 20 K offset.

When you have measured your envelope's crown-to-mean offset, enter it and set the source
to *measured*. The charts print the value with its source tag.

## Mean or crown temperature

Lift depends on the **mean** temperature of the air in the whole envelope; your crown
sensor reads the **top**, which is hotter. By default EnvelopeLab works the mean out
**from your envelope's shape**: it assumes the air warms evenly from the mouth (half as
far above ambient as the crown, *assumed*) to the crown, and weights each layer by the
volume the design puts there. The result is never less than the *Minimum top minus mean*
(20 K / 36 °F, *assumed*) below the crown, so it is at least as conservative as before.
Choose *Fixed offset* under *Mean temperature* to use exactly that offset instead.

The **Stratification** tab shows the assumed temperature at each height for each ambient
temperature, the mean it gives, the height below which half the volume lies, and the
pressure difference that profile produces next to a uniform envelope's. A lower *Mouth
temperature rise* is more conservative; an offset of 0 is the least conservative choice.
These profiles are assumptions, not measurements: with a crown sensor and one sensor
partway down you can measure the offset and enter it as *measured*. Every chart is read with the crown temperature.

A lift spreadsheet that takes one "envelope temperature" (for example the Balloon
Builders Journal's) assumes the whole envelope is at that temperature, so that number is
the mean. Do not enter the crown reading there: with a 20 K difference it overstates the
lift by 13 % to 29 % for a 92 000 ft³ envelope. With an offset of 0, EnvelopeLab's gross
lift matches such a spreadsheet (within 0.3 %, from the spreadsheet's rounded constants).

## What goes in

| Input | From | Source tag |
|---|---|---|
| Envelope volume | the design's lofted profile (as drawn) | geometry |
| Envelope + rigging mass | the mass estimate (Shape mode outputs) | the fabric, tape and line values |
| Top-temperature limit | lowest service temperature of the design's fabrics | the fabric's tag; 120 °C *assumed* when not in the library |
| Mean temperature | top − the offset of *Design ▸ Lift charts…* (20 K by default) | the offset's tag: *assumed* by default |

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
