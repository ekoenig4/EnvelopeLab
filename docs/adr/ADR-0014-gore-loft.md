# ADR-0014: Gore loft (lobe bulge between load tapes) in design schema v3

- Status: Accepted
- Date: 2026-10-03

## Context
Every standard-gore design used the small-bulge flat width \( w = \pi r / N \), which puts
the fabric between two load tapes on the circle through the tapes. Builders choose how much
each gore bulges (its *loft*): a flatter lobe narrows the gores and lowers the tape load
share of the fabric, a fuller one widens them, and the choice can vary from mouth to crown.
`envelopelab.geometry.gore` already had a lobe (chord-form) width model, but the design
schema, the editor and shape files could not store a loft, and the volume ignored the
lobes.

## Decision
* The loft is a **lobe-radius ratio curve** \( k(f) = \rho / r \) at stations \( f \),
  fractions of the tape length from the mouth (0) to the top opening (1), interpolated
  linearly and held beyond the ends (`envelopelab.geometry.gore.GoreLoft`). A ratio is
  scale-free, so a loft survives scaling and constraint-lock corrections, and \( k = 1 \)
  is exactly today's small-bulge gore.
* The design schema goes to **version 3**: `gores.loft` is an optional list of
  `{station, ratio}` (`null`: no loft, the small-bulge gore). Every ratio must be at least
  \( \sin(\pi/N) \) (a half-circle lobe). The v2 → v3 migration sets `loft: null`; the
  content hash of an older document is checked before migration as before.
* Panel rows, the mass estimate, the volume, gross lift, lift margin, the volume lock, the
  wizard and shape families use the lofted flat width and the lofted volume and area
  (`lofted_volume`, `lofted_area`). A design without a loft gives bit-identical results.
* Shape files (`envelopelab.shape` v1) get an optional `loft` block (stations as fractions
  of the gore length or station names). Older files remain valid, so the format version is
  unchanged.
* The loft enters the `geometry` input group only when it is set, so the fingerprints of
  existing designs and their built artifacts stay current.

## Consequences
Version-3 design files cannot be opened by earlier versions of EnvelopeLab. Shape files
with a `loft` block cannot be read by earlier versions. No numerical result of an
existing design changes. The lobe is modelled as a circular arc in the horizontal
section; this is exact for vertical tapes and approximate near the crown (see
`docs/theory/gore-geometry.md`). The pressurised lobe shape remains a solver result:
the preview and CalculiX solvers sew the lofted flat panels. No new dependency.
