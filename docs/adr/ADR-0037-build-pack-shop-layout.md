# ADR-0037: Build pack format 3: shop layout and piece-sized 1:1 sheets

- Status: Accepted
- Date: 2026-11-03
- Changes: AGENTS.md §6.6 (PDF page size rule); supersedes the `pattern.pdf` layout of
  ADR-0016 and the file layout of ADR-0036

## Context
A builder supplied a complete hand-made build pack (kept as the regression fixture
`tests/fixtures/alien/pack`) and asked for the export to match it. That pack is laid out
the way a shop works: files named after the design and grouped (start here, layout and
planning, panel templates, appendages, top and bottom, CAD); envelope panels two rows to
a file and rows that carry features on their own sheet with every gore's markings drawn
over the one panel; and every 1:1 sheet as large as its piece, with **one side under the
roll width** ("every 1:1 sheet has one side under 1,500 mm so it fits a 60 in roll"),
the row height across the bolt and the gore width along the roll. Formats 1 and 2 wrote
every sheet on pages exactly as wide as the roll (`pattern.pdf`), which AGENTS.md §6.6
required ("PDF page size matches the target roll width"). A 2.8 m wide panel then
printed across two strips that had to be taped together.

## Decision
- Pack format `envelopelab-build-pack/3`. The top level holds the 1:1 template PDFs
  (`envelopelab.export.templates`) and the documents, named `<slug>-…`; `cad/` holds one
  DXF per sheet (unchanged) and `index.json`, which lists every file of the pack,
  including the template pages (sheet, band, turn, markings drawn over it).
- Template pages are piece-sized with one side no longer than the roll: upright when the
  height fits, turned a quarter when only the width fits, split into numbered bands
  across the roll when neither does. Each page carries two calibration lines (across and
  along), inside the piece, with labels generated from the drawn lengths.
- AGENTS.md §6.6 now reads: every 1:1 PDF page has one side no longer than the target
  roll width. The QA checks that, both calibration lines of every page, and that every
  sheet is drawn on a template page.
- `pattern.pdf` is no longer written.

## Consequences
- A panel prints whole on the roll whenever one of its sides fits, as in the builder's
  pack; banded pages remain for pieces larger than the roll both ways.
- Readers of `index.json` find it in `cad/`; sheet and seam file names gain the `cad/`
  prefix. The QA still reads format 1 and 2 packs.
- The documents of the builder's pack (index, spec summary, layout and planning sheets,
  sewing schedule, build log, appendage documents, combined DXFs, realistic 3D view) are
  generated in later steps of the same change; they reuse this layout.
