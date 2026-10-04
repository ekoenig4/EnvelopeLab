# ADR-0016: Build-pack export as DXF sheets, a roll-width PDF and a JSON index

- Status: Accepted
- Date: 2026-10-04

## Context
Builders need the cutting patterns of the envelope and of every special shape at 1:1,
plus the lines to mark on the envelope panels where shapes attach (ADR-0015). AGENTS.md
§6.6 fixes what a build pack must guarantee (calibration lines measured from the
geometry, DXF units, PDF page width equal to the roll width, sewn edge pairs, a complete
index, headers matching the design) and asks for that QA to run in `scripts/verify.py`.

## Decision
* New package `envelopelab.export` (planned in AGENTS.md). `build_pack` writes one DXF
  per sheet (mm, fixed layer names, every finished edge on its own layer), one
  `pattern.pdf` whose pages are as wide as the roll (wide sheets split into strips) and
  an `index.json` (format `envelopelab-build-pack/1`, see `docs/formats/build-pack.md`).
* DXF through ezdxf (already a dependency); the PDF through the project's own minimal
  writer `envelopelab.report.pdf`, which gains per-page sizes and content-stream
  comments (a `%CAL L T` comment marks each calibration line for the QA).
* `envelopelab.export.qa.check_pack` checks a pack from its files alone.
  `scripts/check_build_pack.py` exports a generic sample pack and checks it;
  `scripts/verify.py` runs it.
* Sewn edges are checked against each other, not against the 3D design: the design
  checks of each shape (`rim length`, `skin seam match`) compare with the designed shape.

## Consequences
No new dependency. The Reality Check PDF now writes its page size with two decimals
(`842.00` instead of `842`); its content is unchanged. The footprint run drawn on a
marking sheet is in the envelope panel's pattern coordinates, which are not an isometry
of the envelope away from the gore centreline, so the pack does not pair it with the
skin rim; the shape's design check compares the rim with the 3D footprint instead.
Nesting of pieces on the roll is not done: each sheet starts on its own page.
