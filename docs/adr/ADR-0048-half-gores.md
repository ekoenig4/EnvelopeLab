# ADR-0048: Half gores and print-roll advice (design schema version 9)

- Status: Accepted
- Date: 2026-11-16

## Context
A panel must print on the builder's roll (ADR-0042). When panels are wider than the roll,
the gore count can be raised (it could be changed at any time, but only from the
Constraint locks box) or rows split, and nothing said which change would work. Builders
also cut wide panels as **half gores**: each panel in two pieces, left and right of the
gore centreline, sewn together along a centre seam. EnvelopeLab could not do that.

## Decision
* `PanelRow.half_gore` (default false) marks a row cut as half gores. Design schema
  version 9; version-8 rows migrate as whole panels.
* `envelopelab.geometry.gore.half_panel` cuts a row panel down \(x = 0\): each half is
  offset by the row's allowance on all four edges, mitred corners; the halves' finished
  areas add up to the panel's.
* The flag is the input group `piece_split`, read by the patterns only (not geometry): a
  half-gore change marks the patterns, nesting and export stale, never the rest mesh or
  simulations. While no row uses it the group is left out of the fingerprints
  (`OPTIONAL_GROUPS`), so existing projects keep theirs.
* Build packs cut the halves: one sheet, DXF and 1:1 template per half (`row C left
  half`), cut once per gore; the sewing schedule starts with the centre seams; row seams
  join both halves to the next row; documents that show the envelope row by row keep the
  whole panel (`row_sheets`). Shape marking pages stay on the whole panel ("sew its two
  halves together first").
* The mass estimate adds the halves' extra cloth and the centre seams' thread (sewn like
  the gore seams: assumed; no tape).
* `envelopelab.project.roll_advice` says whether every piece fits the roll and what
  would: the smallest gore count (bisection up to 200, re-checked), half gores for the
  rows that do not fit, or splitting rows that are too wide even halved. It changes
  nothing.
* The Shape mode gets a **Panels and print roll** box at the top: the gore count, half
  gores for all rows / the rows too wide / none, the fit status and **Suggest…**; the
  rows table has a half-gores column; Patterns has the checkbox for the selected row and
  prints each half as its own page on the roll.

## Consequences
* Older releases cannot open designs of schema version 9 (as for every schema bump).
* A row with a manual outline override is still cut in halves from its generated
  outline (the build pack has always used the generated outlines).
* The envelope panels that special shapes are sewn on are marked on the whole panel,
  after the halves are joined.
