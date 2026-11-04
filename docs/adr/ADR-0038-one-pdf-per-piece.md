# ADR-0038: One 1:1 PDF per piece, the whole piece on one page

- Status: Accepted
- Date: 2026-11-04
- Supersedes: the template grouping and banding of ADR-0037 (pair files, grouped file,
  per-shape pattern files, banded pages); amends AGENTS.md §6.6

## Context
ADR-0037 grouped the envelope rows two to a file (`<slug>-panels-A-B.pdf`), added a
grouped file, put a special shape's skin pieces in one multi-page patterns file, and
split a piece larger than the roll both ways into bands across the roll. The builder
reviewed a generated pack and asked for **each panel in its own PDF, sized to show the
entire panel**, and for the special shapes' pieces to be cutting sheets as well.

## Decision
- Every piece to cut has its own 1:1 PDF with one page: `<slug>-panel-<R>.pdf` per
  envelope row (a row carrying a shape's markings shows every gore's marks over the one
  panel, as before), `<slug>-parachute-panel.pdf`, `<slug>-parachute-centre.pdf`, and
  `<slug>-<shape>-<piece>.pdf` for every skin piece (e.g. `sample-eye-G1.pdf`).
- The page is the piece's cut outline plus 20 mm: the whole piece, never split. It is
  upright when its height fits the roll and turned a quarter when only its width does;
  a piece larger than the roll both ways stays whole and the page says so in red.
- No grouped file and no per-shape patterns file.
- AGENTS.md §6.6 reads: every piece has its own 1:1 PDF, one page showing the whole
  piece, with one side no longer than the roll or a note that it is larger both ways.
  The QA checks one page per piece and file, never banded, each sheet drawn once, and
  the page-size rule with that exception.

## Consequences
- More files (one per piece); the build-pack index lists them all, so it may run to a
  fourth sheet.
- Printing a piece larger than the roll both ways needs a plotter wider than the roll or
  tiling by the print software; the page warns instead of tiling silently.
- `index.json` (format 3) is unchanged in shape: each template entry has one page with
  `band` and `bands` of 1.
