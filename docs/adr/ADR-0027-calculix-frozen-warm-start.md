# ADR-0027: CalculiX starts from a preview equilibrium with frozen tension-field states

- Status: Accepted
- Date: 2026-10-17

## Context
The CalculiX verification solve (ADR-0005) applies the tension-field law by iterative
membrane properties. Every pass freezes the states and wrinkle directions, and the next
pass re-classifies them. Started away from equilibrium these passes never converge, which
`docs/theory/verification-solver.md` already documented. The application nevertheless
started CalculiX from the initial shape whenever no current preview existed. Even from a
converged preview, the first pass at `kappa_start` = 0.1 moved the equilibrium by 23 mm
and the passes then wandered.

On the generic 8-gore fixture (800 mm mesh) users waited 129–147 s for an unconverged
result. A 5 % hysteresis band on the state test alone did not help: with no state
changes the passes still wandered, because the wrinkle directions were re-frozen every
pass.

## Decision
* A warm start (`start_positions`) uses the final κ from pass 1 and keeps the states and
  directions classified at the start (`CalculixSettings.freeze_states`, default on).
* When the passes have settled on the frozen material, the frozen material's resultants
  are compared with the tension-field law's at the new geometry (*law consistency*). Above
  `stress_tolerance` the states are re-classified with a hysteresis band (`state_band`,
  1e-3 of the largest major trial resultant) and the passes continue.
* A frozen solve converges only with law consistency within `stress_tolerance`, in
  addition to every existing criterion.
* The application always starts CalculiX from a preview equilibrium. Without a current
  converged preview of the same mesh, the CalculiX run solves one first, keeps it as its
  own run record, and does not start CalculiX if it fails to converge.
* Cold starts keep the per-pass classification and κ continuation; their results are
  bit-identical (`tests/calculix/test_warm_start.py`).

## Consequences
* CalculiX is explicitly an equilibrium check of the preview's shape with independent
  elements, material evaluation and equation solver, as the validation study already
  used it. It is not an independent form finder.
* Fixture: 1 pass in 4.4 s, converged (out-of-balance 6.7e-7, law consistency 7e-7).
  Validation envelope: 30–35 % faster, results equal within 1e-7 relative.
* A CalculiX run in the application costs a preview solve when no current preview exists.
