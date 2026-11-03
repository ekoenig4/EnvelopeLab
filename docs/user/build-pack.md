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
| `00-cover.pdf` | Start here: what the pack is, where it comes from (version, git commit, design hash, time), the safety notice, **every value tagged *assumed*** (check these against datasheets before building), the structural result, and the list of files |
| `<name>-panels-A-B.pdf`, `<name>-panel-D.pdf`, … | Cutting the envelope: one panel per page at 1:1, two rows to a file; a row that carries a special shape on its own sheet with every gore's marks (labelled by gore) |
| `<name>-panels-grouped.pdf` | The paired panel files in one, for printing in one go |
| `<name>-parachute-patterns.pdf`, `<name>-<shape>-patterns.pdf` | Cutting the parachute and each special shape's skin pieces (one per page) |
| `cad/` | One DXF per piece (mm) and `index.json`, for CAD programs and the automatic checks |
| `cut-list.pdf` / `.csv` | Planning the fabric: pieces, cut counts, areas, fabric totals, tape lengths and thread |
| `sewing-schedule.pdf` / `.csv` | Sewing: every seam in order with both edge lengths, how often it is sewn and a box to tick |
| `rigging.pdf` / `.csv` | Making the lines: lengths, limit loads, strengths with their source, factors of safety (**FAILS** when below the requirement) |
| `spec-summary.pdf` / `.json` | The design at a glance: size, volume, lift, lift margin, mass budget, materials |
| `3d-view.html` | Looking at it: open it in any browser, offline |
| `index.json` | Programs: the machine-readable list of every file and seam |

**Before cutting**, print every 1:1 file at 100 % (never *fit to page*) and measure both
calibration lines on every page (across and along): each must measure what its label
says. Solid = cut, dotted = sew (finished), red = feature marks, blue = finished sizes.

## The 3D view page

`3d-view.html` shows what the application's 3D view shows for the run chosen there:

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
