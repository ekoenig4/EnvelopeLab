# ADR-0010: Row zones, parachute rings and scoop in design schema v2

- Status: Accepted
- Date: 2026-09-30

## Context
Builders lay out an envelope as a Nomex row at the mouth, N nylon rows and the parachute
at the top; the parachute has a crown ring at the rim of the opening and a centre ring at
its apex, and a design may have a scoop below the mouth. Row materials lived only in the
project's pattern annotations, so a new design could not state them, and schema v2
(ADR-0009) had no rings or scoop.

## Decision
* Extend schema v2 (not yet released, so no version bump) with optional fields:
  `gores.panel_rows[].zone`, `parachute.crown_ring` / `parachute.centre_ring`
  (`RingSpec`: class, linear mass, strength, required factor of safety, all tagged) and
  `parachute.centre_ring_diameter`, and a top-level `scoop` (`ScoopSpec`). All default to
  null, and the v1 → v2 migration leaves them null.
* A row's zone is resolved as: pattern annotation, else the design row's zone, else the
  first zone. It belongs to the `row_zones` input group, not `geometry`, so choosing a
  row's fabric does not make the profile stale.
* A `scoop` input group is read by the patterns artifact.

## Consequences
Wizard designs name their mouth and body zones in the design document. v2 documents saved
before this change on a development branch have a different content hash (the new null
fields are hashed) and are refused as a hash mismatch; no released file is affected. The
scoop is not part of the structural model; ring and scoop loads other than those in
`theory/rigging.md` are not assessed.
