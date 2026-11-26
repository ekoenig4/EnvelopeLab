# Exporting a build pack

A build pack is a folder with everything needed to cut, sew and rig the balloon: the
cutting patterns at 1:1, the documents to work from, and a 3D view to look at. Export it
with **File ▸ Export build pack…** (or **Export build pack…** in the Special shapes
panel); the pack format is described in [Build pack](../formats/build-pack.md).

## The export dialog

* **Folder**: where the pack is written (created if needed; files of the same names are
  replaced). The last folder is remembered.
* **Roll width**: the width of the roll you print on (default 60 in). Every piece has its
  own 1:1 PDF whose one page shows the whole piece. **The page width runs across the
  roll and is never wider than it; the page height runs along the roll, as long as the
  piece needs.** Print every page at 100 % with the page width across the roll, without
  rotating it. To fit, the piece is turned on its page: a quarter turn first (the row
  height across the roll, as panels are cut across the bolt), then upright, then whatever
  turn is narrowest. The bottom margin of every page says so: an arrow across the page,
  *ACROSS THE ROLL: 1440 mm of the 1524 mm roll - piece turned 90 deg*. The UP / warp
  arrow turns with the piece, so lay the paper template on the cloth by that arrow.
  A piece wider than the roll at any turn is never split: its page says so in red, so you
  can join paper or plot it in parts.
  The dialog starts from the **Print roll width** in **Preferences**; with that width
  the Special shapes panel and **Validation / Warnings** already warn about every panel
  larger than the roll before you export.
* **Include**: the documents (all ticked by default). The cutting sheets are always
  written.

The pack is not written while a special shape is being placed or cannot be placed, so
it never leaves a shape out without saying so.

## Scale models on paper

Tick **Scale model** in the export dialog to print a 1:n model of the envelope (and its
special shapes and overlays) at home instead of the full-size pack. Every pattern length
is divided by n, and every piece is printed whole on **one sheet** of the paper you
choose, turned and set portrait or landscape to fit.

* **Scale**: 1 : n. **Fit to paper** sets n to the largest whole number at which every
  piece fits one sheet (for example 1:20 on Letter). The line under the settings says
  whether every piece fits; when some do not, it names them in red. Such pieces are
  still written, on a page enlarged to hold them and marked in red: choose a larger n.
* **Paper**: US Letter (8.5 x 11 in), US Legal, Tabloid (11 x 17 in), A4 or A3.
* **Margin**: the blank border your printer needs on every side (default 12.7 mm,
  0.5 in).
* **Seam allowance**: unticked, the design's allowance is scaled with the piece (an
  exact 1:n copy, often only a millimetre or two); ticked, every piece gets the
  allowance you type (default 5 mm) at model size, enough for glue or a seam.

The pack holds the same files as a full-size pack's patterns, named
`<design> model 1-n` (for example `generic-model-1-20-panel-A.pdf`), and no documents:
those describe the full-size envelope. Every sheet says `SCALE MODEL 1:n - not a
full-size pattern`, and every page's footer gives the scale and paper. **Print at 100 %
(actual size)** and check the calibration lines with a ruler before cutting. The
settings are remembered for the next export.

A model shows the shape of the patterns as they will be sewn. It is not a structural
test: lift scales with n⁻³ and skin weight with n⁻², and stresses do not scale, so a
model says nothing about the full-size envelope's strength
([Scale models](../theory/scale-models.md)).

## What is in the pack

| File | Use it for |
|---|---|
| `<name>-00-BUILD-PACK-INDEX.pdf` | Start here (three A3 sheets): the key dimensions in metric and English, the features, the shop limits the pack is built to (bolt width, cutting table, largest piece), how to print; the index of every file (`REF` to read, `1:1` to print at actual size, `CAD`); and the build order, each step naming the sheet to work from |
| `<name>-spec-summary.pdf` | The design at a glance, metric and English: size, volume, mouth, parachute hole and overlap, line lengths, lift and lift margin, configuration, rigging factors of safety, and **every value tagged *assumed*** (check these against datasheets before building) |
| `<name>-lift-chart.pdf` / `.csv` | [Lift charts](lift-charts.md): the load the balloon floats at the top-temperature limit, the top temperature a load needs, and the ceiling, over ambient temperature and altitude; points above the limit are shaded and marked |
| `<name>-build-log.pdf` | Sign-off sheets for the floor: panel cutting, each special shape, the turning vents, and the parachute, rigging and final inspection |
| `<name>-panel-A.pdf`, `<name>-panel-B.pdf`, … | Cutting the envelope: one PDF per panel, the whole panel at 1:1 on one page |
| `<name>-panel-C-left-half.pdf`, `<name>-panel-C-right-half.pdf`, … | Rows cut as **half gores** (Shape mode, *Panels and print roll*): one PDF per half instead of the panel's; cut each once per gore and sew each pair together along the centre seam first (the sewing schedule lists these seams first) |
| `<name>-panel-H-gore-3.pdf`, … | Marking: one PDF per envelope panel that carries a special shape or a feed hole, with the lines where the shape is sewn on, the numbered marks and the feed holes drawn on it |
| `<name>-assembly-envelope.pdf`, `<name>-assembly-<shape>.pdf` | Building: picture instructions, step by step, for the base envelope and for each special shape |
| `<name>-<shape>-3d.html` | Each special shape in 3D, designed and inflated, with its simulation's metrics |
| `<name>-<shape>-G1.pdf`, … | Cutting each special shape: one PDF per skin piece, the whole piece at 1:1 |
| `<name>-parachute-panel.pdf`, `<name>-parachute-centre.pdf` | Cutting the parachute |
| `<name>-panels.dxf`, `<name>-panel-templates.dxf`, `<name>-appendage-patterns.dxf` (+ PNG previews) | CAD: the whole envelope developed with its features, the panels on a grid, and the appendage and parachute pieces, in mm |
| `cad/` | One DXF per piece (mm) and `index.json`, for CAD programs and the automatic checks |
| `<name>-layout-diagram.html` | The whole envelope as a gore x row grid in its fabric colours, with every feature located |
| `<name>-panel-map.html` / `.csv` | Which panel of which gore carries which feature |
| `<name>-colour-plan.pdf`, `<name>-colour-cloth.csv` | When you have [coloured the panels](panel-colours.md): every gore side by side in its panel colours and each special shape's pieces, then the cloth per colour (pieces, finished and cut area) for ordering fabric |
| `<name>-gore-layout.pdf` | Every gore drawn to scale with its features, then one page per gore |
| `<name>-panel-dimensions.html` / `.csv` | Finished and cut size of every panel, how it lies on the bolt and the table, the spare, and the fabric totals |
| `<name>-panel-loft.html` / `.csv` | Every panel's width at 0, 25, 50, 75 and 100 % of its height, for checking cut panels |
| `<name>-sewing-schedule.html` | Sewing: seam specifications, the tape schedule (with 10 % waste), the assembly sequence and every seam in order with both edge lengths and a box to tick |
| `<name>-<shape>.pdf`, `<name>-<shape>-build.pdf` | Each special shape: its specification, skin cut list, match marks and feed holes; and its build procedure, step by step, with lines for your own notes |
| `<name>-turning-vents.pdf`, `<name>-vent-panels.pdf` | The turning vents (when there are any): placement, opening, thrust and torque, control lines; and the panels that carry them |
| `<name>-parachute.pdf`, `<name>-scoop.pdf` | Making the lines: parachute data and every rigging length; the scoop and the flying wires, each wire's length; factors of safety (**FAILS** when below the requirement) |
| `<name>-3d.html` | Looking at it: open it in any browser, offline |


**Panel colours.** When the design has [panel colours](panel-colours.md), every envelope
panel PDF says under its header how many to cut in each colour and for which gores
(`colours: cut 3 in #c00000 (gores 1, 5, 9), 9 with no colour (gores 2, 3, …)`, with a
swatch per colour), a marking page names the colour of its one panel, and every special
shape's skin piece names its colour. The DXFs carry the same line under their header and
`cad/index.json` lists the colours of every sheet. The 3D view shows the colours.

**Before cutting**, print every 1:1 file at 100 % (never *fit to page*) and measure both
calibration lines on every page (across and along): each must measure what its label
says. Solid = cut, dotted = sew (finished), red = feature marks, blue = finished sizes.

## The 3D view page

`<name>-3d.html` opens in a **realistic look**: the balloon in its fabric colours with
smooth shading, sky and ground, and a basket under the flying wires. It shows what the
application's 3D view shows for the run chosen there:

* the **design surface** (the shape as cut and sewn, in the row fabrics, with its seams
  and gore numbers G1…), the **rigging**, and the special shapes as designed;
* the **result** of the chosen run (the envelope and the shapes solved with it), with the
  *Colour by* list of the application: factor of safety (banded against the
  requirement, everything below it orange and labelled FAIL), resultants, wrinkling,
  displacement and **deviation from design** (drawn on the design surface, red outside
  and blue inside). A result field hides the design surface and the deviation shows it,
  as in the application;
* the same **status banner** as the application: a preview run says it is not verified
  with CalculiX, a stale run is grey and never coloured, an unconverged run says its
  values are not final.

Drag to rotate, shift-drag or right-drag to pan, use the wheel to zoom; **Front**,
**Side**, **Top** and **Isometric** set the view; the parts list turns parts on and off.
The page needs WebGL (every current browser has it) and nothing else: it can be sent by
e-mail or opened from a USB stick.

Without a run (or with only the sheets exported from a script) the page shows the design
and its rigging, with the banner *Design only*. Each special shape has its own page
(`<name>-<shape>-3d.html`) with the same colour modes for its simulation. **Re-run the
preview and the shape simulations before exporting** when you have changed the design:
stale results are drawn grey and never coloured.

## Checking a pack

`scripts/check_build_pack.py` (run by `scripts/verify.py`) exports a sample pack with
every document and checks it; `envelopelab.export.qa.check_pack(folder)` checks any pack
from its files alone (calibration lines, units, page width, headers, sewn edge lengths,
the index, and the documents).
