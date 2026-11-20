# ADR-0042: Template pages in the print roll's frame (build pack format 4)

- Status: Accepted
- Date: 2026-11-14
- Amends: ADR-0038 (how a piece is placed on its page)

## Context
A roll printer or plotter has a fixed width across the roll and any length along it.
Format 3 pages kept the piece upright when its height fitted the roll, so the page's
*height* had to go across the roll, and a typical envelope panel came out as a page wider
than the roll that only fitted when printed sideways. Nothing on the page said which way
it went, and the Special shapes panel only said "fits" or "fits turned". A piece that fits
the roll only at a slant (a long diagonal gore) was reported as larger than the roll.

## Decision
* Every template page is in the roll's frame: page width across the roll (never wider
  than it unless the page says the piece is larger than the roll), page height along it.
  Pages print at 100 % without rotating.
* The piece is turned on its page (`envelopelab.export.templates.roll_fit`): 90°
  (its height, the row height, across the roll, as the shop pack cuts panels across the
  bolt), else 0°, else the narrowest turn over its convex hull's edges (rotating
  calipers); oversize only when even that is wider than the roll.
* Each page's bottom margin has a double arrow across the page, labelled with the page
  width, the roll width and the turn. The UP / warp arrow turns with the piece.
* `index.json` records `turn_deg`, `across_roll_mm` and `along_roll_mm` per page
  (replacing `turned`); the QA checks the page *width* against the roll for format 4 and
  keeps the format 3 rule (one side) for older packs. Pack format
  `envelopelab-build-pack/4`.
* The Special shapes panel shows each piece's width across the roll and its turn, and can
  draw the pieces laid along a strip of the roll.

## Consequences
* The physical orientation of envelope panels on the roll is unchanged (row height
  across), but their PDF pages are now turned a quarter compared with format 3.
* A piece turned to a slant prints fine on paper, but its grain is then at that slant on
  the page: the template is laid on the cloth by its warp arrow, and cutting it from the
  cloth still needs a bolt as wide as its grain-aligned width (the shop limits keep
  reporting that).
* Pattern geometry, DXFs and seam lengths are unchanged.
