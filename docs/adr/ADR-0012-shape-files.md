# ADR-0012: Shape files for normalized gore tables and held-value design solving

- Status: Accepted
- Date: 2026-10-01

## Context
Builders keep designs as normalized gore tables, for example the Balloon Builders Journal
spreadsheets: radius against tape length as fractions of the gore length, scaled from a
volume. They want to keep such a design, change one value (the mouth opening, say) and have
the other values follow. The design schema stores only absolute control points, and the
editor's constraint locks keep values during profile edits, but neither describes "this
shape at any size". Hard-coding a design is not allowed (AGENTS.md §2).

## Decision
* A new YAML file format **`envelopelab.shape` v1** ([format](../formats/shape-file.md))
  stores the normalized table with its source tag, named stations, the three held values that
  fix the design (with explicit units, converted to SI on load), the gore count and the seam
  allowance, plus an optional `published` block of source values used only by tests.
* `envelopelab.project.shape_family` solves any three held quantities for the free design
  variables (gore length, mouth and top stations). One free variable uses Brent's method;
  more use bounded least squares. A solution is converged only within the default tolerances,
  and only a converged solution becomes a `DesignDocument`. The design schema is unchanged.
* Reference shape files live in `tests/fixtures/` (first: `smalley_90k`, with its source
  spreadsheet stored unmodified). The app opens them by path; none are bundled.

## Consequences
A shape file is an input from which designs are made; it is not a project. Edits made in
the editor afterwards are not written back to it. Volumes are integrated from the smooth
profile, not taken from a source's published coefficient, so lengths can differ slightly
from the source (0.05 % for `smalley_90k`); holding the gore length reproduces the source's
cut exactly. No new dependency.
