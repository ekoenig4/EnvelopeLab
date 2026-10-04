# ADR-0020: Special shapes in the project file (format version 2)

- Status: Accepted
- Date: 2026-10-04

## Context
Domes, tubes, revolved and free-form shapes (ADR-0015, ADR-0018) were available only from
Python. To design them in the desktop application they must be saved with the design,
undone and redone with every other edit, kept in snapshots and versions, and take part in
staleness tracking (ADR-0008). Placing a shape takes from a fraction of a second to a few
seconds, too long to run on every edit in the GUI thread.

## Decision
* The design state gets a list `shapes` of shape specifications
  (`envelopelab.project.shapes`): plain data in m and degrees, a discriminated union on
  `kind` (`dome`, `tube`, `revolved`, `mesh`) with unique names. A mesh shape stores its
  vertices and triangles, so the project does not depend on the imported file.
* The project format becomes `envelopelab.project` version 2. Version 1 files are read
  and migrated (their states have no shapes); files are always written as version 2.
* A new input group `shapes` and a new artifact `shapes` (inputs `geometry`, `row_zones`,
  `materials`, `shapes`). No existing artifact reads the new group, so every existing
  fingerprint is unchanged and a shape edit never makes patterns, models or runs stale.
* The design document schema is unchanged: shapes live beside it in the project, like
  the pattern annotations.
* The desktop application places shapes in a worker thread keyed by the shape and the
  envelope inputs it reads; results for an older key are dropped. Shape simulations run
  in their own worker, are kept in memory for the session, and are marked stale when the
  shape, the envelope or its simulation inputs change.

## Consequences
* Older releases cannot open version 2 files (they refuse an unknown version rather than
  dropping the shapes silently).
* Design files (`*.json` design documents) still cannot carry shapes; exporting a design
  document alone leaves them out.
* Shape simulations are not saved; a reopened project shows its shapes but not their
  last solve.
