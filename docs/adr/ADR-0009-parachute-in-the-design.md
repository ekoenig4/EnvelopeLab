# ADR-0009: Parachute in the design (design schema v2)

- Status: Accepted
- Date: 2026-09-29

## Context
A gore envelope is closed at the crown by a parachute, but the design schema (v1) only held
its hole diameter and seal overlap. Its pattern pieces were missing from the patterns, its
seams were never audited and its fabric, tape and thread were left out of the envelope mass
and the lift margin. Builders need the parachute in the design like every other panel.

## Decision
* **Design schema v2** adds an optional `gores.parachute` (`gore_count`, finished
  `diameter` and `centre_diameter`, m): a flat canopy of radial gores sewn round a centre
  disc ([theory](../theory/parachute-geometry.md)). It must be larger than the hole it
  closes. The v1 → v2 migration first checks the stored content hash against the v1
  canonical form, then recomputes it, so a changed v1 file is still refused.
* The **project file** (`envelopelab.project` v1) gains optional pattern annotations
  `patterns.parachute.gore` / `.centre` (label, grain, zone, allowance, manual outline
  override). This is additive: every existing project loads unchanged, and its saved runs
  stay current.
* In the dependency graph the parachute is a new input group read by the **patterns**
  artifact only (and so by nesting and export). The solver closes the crown with an
  unmeshed cap and never reads the parachute, so parachute edits do not mark rest meshes
  or simulations stale.
* The parachute counts in the live envelope mass and lift margin. In a build pack it is
  written as **audited, unmeshed parts** with its radial and centre seams and a declared
  `parachute_rim` opening (a new mapping opening kind); the solver's own build pack leaves
  it out.
* New standard-gore designs from the wizard get a generated parachute; it can be removed.

## Consequences
Designs saved by this version cannot be read by older versions (schema v2). Meshing the
parachute as a membrane (its shape, the seal and its line loads) is out of scope. It would
need line elements, contact with the hole rim and new benchmarks, and would supersede the
"patterns only" dependency decided here.
