# ADR-0009: A fabric library per user, shared by all designs

- Status: Accepted
- Date: 2026-09-30

## Context
Builders need to create fabrics (from datasheets or their own tests) once and choose them in
any design. Until now the application created a fresh in-memory library with three
placeholder fabrics at every start: nothing a user entered could survive, and there was no
way to enter anything. Designs and project files store only fabric ids per zone
(`DesignDocument.zones`), so fabric values have to live somewhere else.

Once fabrics can be edited, a fabric edit changes the results of every design that uses it.
Fingerprints (ADR-0008) were computed from the design state alone, so a simulation built
from the old values would still have shown as current.

## Decision
* The fabric library is a SQLite file per user (`materials.sqlite` in the application data
  folder; `$ENVELOPELAB_MATERIAL_LIBRARY` or a preference selects another file, for example
  on a shared drive). It uses the SQLite store of ADR-0001, adds a layout version
  (`PRAGMA user_version`) and an `origin` column
  ([format](../formats/fabric-library.md)).
* User fabrics are created, edited and deleted through `FabricLibraryRepository`. Every
  write is checked by `validate_fabric` (finite, physically sensible values; a source tag on
  every value, per the AGENTS.md hard rule). The example fabrics are read-only; users
  duplicate them.
* Project files keep storing ids only. The values of the fabrics a design uses become the
  *external* input group `fabric_properties`, read by the simulation and nesting artifacts.
  The session gets them from a lookup the application supplies, and they are not part of
  the unsaved-changes comparison. When no lookup is supplied (scripts, tests), the group is
  left out of the fingerprints, so those fingerprints are unchanged.

## Consequences
* A fabric created once is available in every design that uses the same library file.
* Editing a fabric marks the simulations and nesting built from it stale in every design
  that uses it, but never marks a project as modified.
* Runs saved before this change were fingerprinted without the fabric values. The
  application now includes them, so those runs show as stale once and need a re-run. This
  is the safe direction: the old records do not say which fabric values they used.
* A design sent to another user refers to fabric ids that may be missing from their
  library. They see the zones as missing fabrics and get an assumed areal mass with a
  warning. Exporting and importing fabrics with a design is a possible later addition.
