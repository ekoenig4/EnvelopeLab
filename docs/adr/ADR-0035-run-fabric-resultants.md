# ADR-0035: Preview runs store warp/weft resultants for per-element factor of safety

- Status: Accepted
- Date: 2026-11-02

## Context
The redesigned 3D view colours a solved envelope by its fabric factor of safety, with
everything below the required factor drawn in a fail colour. The factor along warp and
weft is \( N_{ult} / N \) with \( N \) the resultant along the deformed yarn direction.
The preview solver computes these resultants, but a run's stored result arrays kept only
the principal resultants, which do not give the warp and weft values. A factor from the
principal resultants alone (\( \min N_{ult} / N_1 \)) is a conservative bound that
disagrees with the zone table of the Reality Check, so it would show two different
"factors of safety" for the same run.

## Decision
* `SimulationResult` gets an optional `fabric_resultants` (N/m, warp, weft, shear per
  element), filled by the preview solver. CalculiX does not report it.
* `run_record` stores it in the run's `.npz` as `fabric_resultants` when present. The
  key is optional: runs from earlier versions and CalculiX runs have none, and read as
  before. No project format version change.
* `triangle_factors_of_safety` gives the per-element factor; its minimum over a zone is
  the zone factor of `factors_of_safety`, so the colours and the table agree.
* A run without the array, or one that is stale or unconverged, is not coloured by
  factor of safety; the view says why instead of showing an approximation.

## Consequences
* Each preview run's result file grows by 24 bytes per element (about 13 kB for the
  544-element fixture mesh).
* CalculiX runs cannot be coloured by factor of safety until the adapter derives yarn
  resultants from its stress output; the stresses are shown instead.
* Existing runs must be run again to be coloured by factor of safety.
