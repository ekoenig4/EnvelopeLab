# ADR-0005: Keep a preview solver and a separate CalculiX verification solver

- Status: Accepted
- Date: 2026-09-28
- Replaces the planned Kratos verification solver mentioned in ADR-0004.

## Context
ADR-0004 added the dynamic-relaxation preview solver for interactive use. Final design
studies need an independent, slower and reproducible check of the same model by a
general-purpose nonlinear finite-element code. Kratos Multiphysics was proposed; its
licence (BSD-4-Clause, with the advertising clause) is not compatible with EnvelopeLab's
GPL-3.0 licence (ADR-0002) when the two are combined in one program. CalculiX CrunchiX
(GPL-2.0-or-later) has membrane and shell elements, anisotropic materials with
per-element orientation, initial stress, tension-only nonlinear springs and geometrically
nonlinear static analysis, runs as a separate program and is packaged for Linux and
conda-forge.

## Decision
- Keep **both** solvers. The preview solver (NumPy dynamic relaxation) stays the
  interactive tool; **CalculiX** is the verification solver for final design studies.
- Drive CalculiX **as a separate program** from `solvers/calculix_adapter` (installed as
  the `calculix_adapter` package): the adapter writes an input deck, runs `ccx` in a
  subprocess and parses its text output. Nothing in `envelopelab` imports the adapter, and
  basic geometry, editing and build-pack export never need CalculiX.
- Model the fabric with M3D3 membrane elements (no bending, like the preview), the as-sewn
  misfit as an initial stress, tapes as tension-only SPRINGA elements, and the tension
  field with iterative membrane properties that reproduce the preview's tension-field law
  at the fixed point. Pressure, cap and dead loads are consistent nodal forces (CalculiX
  2.21 crashes with element pressure on M3D3). Height-dependent pressure, cap loads and
  wrinkle states are updated in fixed-point passes, each a held job (prestress and
  out-of-balance) and a release job (balanced start, ramped release, continuation on
  failure) stabilised by node-to-reference springs whose final force is the reported
  residual. S3 thin shells were tried and rejected: on the sewn envelope they carried load
  through transverse shear at the seam creases.
- Normalise both solvers into `envelopelab.solvers.simulation.SimulationResult`, compare
  them with `envelopelab.validation.comparison` (default tolerance 5 %) and record every
  run in an `envelopelab.run-manifest` (design hash, material sources, settings, versions,
  mesh, seed).

## Consequences
- No new Python dependency; CalculiX is an optional external program (see
  `docs/dev/calculix-installation.md`). Tests that need it are skipped, with a message,
  where it is not installed; CI installs it on Linux.
- A verification solve takes seconds to minutes where a preview takes seconds, and needs a
  start close to equilibrium on a full envelope: started from the design shape (misfit
  forces about 90 times the load) or 0.2-0.3 m away from equilibrium, CalculiX's passes do
  not converge on the generic fixture.
  The validation study therefore starts CalculiX from the preview's equilibrium and
  accepts the result only on CalculiX's own convergence criteria, which verifies that the
  preview's shape is an equilibrium of an independent finite-element model but does not
  replace the preview's form finding.
- The two solvers share the model definition (rest geometry, materials, loads) but not the
  equilibrium solution or the element formulation, so agreement is evidence that the
  preview's mechanics are right; known differences are listed in
  `docs/validation/preview-vs-calculix.md`.
- Kratos is not used. A future Kratos adapter would need the licence question resolved
  first (for example a separately licensed driver process).
