# ADR-0021: Flat-chord gores with a crest loft (design schema version 4)

- Status: Accepted
- Date: 2026-10-12

## Context
EnvelopeLab cut every gore one way: the flat gore follows a width model (small bulge or
a circular lobe between tapes, ADR-0014) and horizontal seams are straight.
Horizontal-cut pattern sets in common use are often drawn another way:

* the corners of every row lie a flat tape-to-tape chord apart, \(2r\sin(\pi/N)\);
* the panel sides are straight lines of the row's tape length;
* the centreline is longer than the flat trapezoid and the horizontal seams bow outward.
  The gore is lofted **lengthwise**: a loft given as a fraction of the radius, tapered to
  zero at the mouth and the opening.

Neither the lobe width model nor straight seams can reproduce such panels, so a design
cut this way could only be carried as hand-edited pattern overrides.

## Decision
* `GoreSpec.construction` selects `"lobe"` (default, unchanged) or `"flat_chord"`.
  A flat-chord gore's panel rows are straight-sided trapezoids between flat-chord
  corners (`envelopelab.geometry.gore.flat_chord_rows`). The seam bows are parabolas.
  They are either given per row (`PanelRow.bow_bottom`/`bow_top`, m) or computed from a
  crest loft (`GoreSpec.crest_loft`: offset \(\delta = \lambda\tau(f) r\) with taper
  stations). The crest loft lengthens the crest by \(2\delta\tan(\varphi/2)\) at every
  turn of the tape (`crest_bows`).
* `GoreSpec.profile_interpolation` selects a spline (default) or straight tape segments
  between control points, so straight panel sides and the tape agree exactly.
* `GoreSpec.panel_zones` gives single panels (a row and some gores) a material zone, for
  appliques and doubled panels.
* Panel-row letters may have up to 8 characters.
* The design document becomes schema version 4. Version-3 documents migrate unchanged:
  lobe construction, spline profile, no bows, no panel zones.
* The design volume of a flat-chord gore is that of the flat-gore polygon: the width
  model is the flat chord. The crest is not added. How far it stands out under pressure
  is a result of the preview and CalculiX solvers, which sew the bowed panels.

## Consequences
* Given per-row bows, a design reproduces such a pattern's panels. The crest loft
  generates bows for variants and new designs, the same on both sides of every seam.
* Every design document gains the new fields, so the content hash of a re-saved design
  changes. A version-3 file is still checked against the hash it was written with.
* Lobe designs are bit-identical: no field they use changed meaning.
* The volume of a flat-chord design is a lower bound on the inflated volume. It is
  \(N\sin(2\pi/N)/(2\pi)\) of the volume through the tapes, 98.4 % for 20 gores.
