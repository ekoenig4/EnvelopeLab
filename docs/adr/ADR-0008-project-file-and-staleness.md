# ADR-0008: Project files, command history and fingerprint-based staleness

- Status: Accepted
- Date: 2026-09-29

## Context
The editor needs undo/redo with full history, snapshots and versions, pattern annotations
(labels, grain, zones, notches, tapes, feature locations, manual outline overrides),
provenance of flagged edits, and run records that must never be shown as current after an
input changed. The design schema (`DesignDocument`, v1) has no place for these, and a
schema migration for editor state was not wanted.

## Decision
* A new file format **`envelopelab.project` v1** (`*.elproj`, [format](../formats/project-file.md))
  wraps the unchanged design document with pattern annotations, locks, snapshots, versions,
  an append-only provenance log and run records; result arrays go to a sibling `.runs/`
  folder as `.npz`. Autosave files (`envelopelab.autosave` v1) support crash recovery.
* Every edit is a `StateCommand` on the existing `CommandStack` storing the whole state
  before and after (states are a few kB), so undo/redo is exact and the history can jump.
* Derived artifacts (patterns, assembly, rest mesh, simulation, flattening, nesting,
  export) form a fixed dependency graph over *input groups* of the state. Staleness compares
  SHA-256 fingerprints of the inputs an artifact or run was built from with the current
  ones, instead of invalidation flags set by edits.

## Consequences
Undoing an edit makes results current again; a seam-allowance change cannot invalidate the
rest mesh because the rest mesh does not read it. Pattern annotations are not part of the
design content hash (they are in the project and the fingerprints). A future design-schema
version may absorb the annotations; this ADR would then be superseded.
