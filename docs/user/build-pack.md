# Exporting a build pack

A build pack is a folder with everything needed to cut, sew and rig the balloon: the
cutting patterns at 1:1, the documents to work from, and a 3D view to look at. Export it
with **File ▸ Export build pack…** (or **Export build pack…** in the Special shapes
panel); the pack format is described in [Build pack](../formats/build-pack.md).

## The export dialog

* **Folder**: where the pack is written (created if needed; files of the same names are
  replaced). The last folder is remembered.
* **Roll width**: the width of your fabric roll (default 60 in). Every 1:1 page is as
  large as its piece with one side no longer than the roll: the row height runs across
  the bolt and the gore width along the roll. A piece larger than the roll both ways is
  split into numbered bands across the roll.
* **Include**: the documents (all ticked by default). The cutting sheets are always
  written.

The pack is not written while a special shape is being placed or cannot be placed, so
it never leaves a shape out without saying so.

## What is in the pack

| File | Use it for |
|---|---|
| `<name>-00-BUILD-PACK-INDEX.pdf` | Start here (three A3 sheets): the key dimensions in metric and English, the features, the shop limits the pack is built to (bolt width, cutting table, largest piece), how to print; the index of every file (`REF` to read, `1:1` to print at actual size, `CAD`); and the build order, each step naming the sheet to work from |
| `<name>-spec-summary.pdf` | The design at a glance, metric and English: size, volume, mouth, parachute hole and overlap, line lengths, lift and lift margin, configuration, rigging factors of safety, and **every value tagged *assumed*** (check these against datasheets before building) |
| `<name>-build-log.pdf` | Sign-off sheets for the floor: panel cutting, each special shape, the turning vents, and the parachute, rigging and final inspection |
| `<name>-panels-A-B.pdf`, `<name>-panel-D.pdf`, … | Cutting the envelope: one panel per page at 1:1, two rows to a file; a row that carries a special shape on its own sheet with every gore's marks (labelled by gore) |
| `<name>-panels-grouped.pdf` | The paired panel files in one, for printing in one go |
| `<name>-parachute-patterns.pdf`, `<name>-<shape>-patterns.pdf` | Cutting the parachute and each special shape's skin pieces (one per page) |
| `<name>-panels.dxf`, `<name>-panel-templates.dxf`, `<name>-appendage-patterns.dxf` (+ PNG previews) | CAD: the whole envelope developed with its features, the panels on a grid, and the appendage and parachute pieces, in mm |
| `cad/` | One DXF per piece (mm) and `index.json`, for CAD programs and the automatic checks |
| `<name>-layout-diagram.html` | The whole envelope as a gore x row grid in its fabric colours, with every feature located |
| `<name>-panel-map.html` / `.csv` | Which panel of which gore carries which feature |
| `<name>-gore-layout.pdf` | Every gore drawn to scale with its features, then one page per gore |
| `<name>-panel-dimensions.html` / `.csv` | Finished and cut size of every panel, how it lies on the bolt and the table, the spare, and the fabric totals |
| `<name>-panel-loft.html` / `.csv` | Every panel's width at 0, 25, 50, 75 and 100 % of its height, for checking cut panels |
| `<name>-sewing-schedule.html` | Sewing: seam specifications, the tape schedule (with 10 % waste), the assembly sequence and every seam in order with both edge lengths and a box to tick |
| `<name>-<shape>.pdf`, `<name>-<shape>-build.pdf` | Each special shape: its specification, skin cut list, match marks and feed holes; and its build procedure, step by step, with lines for your own notes |
| `<name>-turning-vents.pdf`, `<name>-vent-panels.pdf` | The turning vents (when there are any): placement, opening, thrust and torque, control lines; and the panels that carry them |
| `<name>-parachute.pdf`, `<name>-scoop.pdf` | Making the lines: parachute data and every rigging length; the scoop and the flying wires, each wire's length; factors of safety (**FAILS** when below the requirement) |
| `<name>-3d.html` | Looking at it: open it in any browser, offline |


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
**Side**, **Top** and **Isometric** set the view; the layer list turns parts on and off.
The page needs WebGL (every current browser has it) and nothing else: it can be sent by
e-mail or opened from a USB stick.

Without a run (or with only the sheets exported from a script) the page shows the design
and its rigging, with the banner *Design only*.

## Checking a pack

`scripts/check_build_pack.py` (run by `scripts/verify.py`) exports a sample pack with
every document and checks it; `envelopelab.export.qa.check_pack(folder)` checks any pack
from its files alone (calibration lines, units, page width, headers, sewn edge lengths,
the index, and the documents).
