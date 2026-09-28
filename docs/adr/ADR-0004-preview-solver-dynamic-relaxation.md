# ADR-0004: Dynamic relaxation for the in-app preview solver

- Status: Accepted
- Date: 2026-09-28

## Context
Builders need an inflated-shape, force and wrinkle prediction that updates while they edit
a design, starting from the as-sewn rest model (flat panel triangles, grain, zones, seams
and tapes). The final verification solver (Kratos, planned) is too heavy to run on every
edit and is an optional dependency. The preview must handle a tension-only membrane with
large slack regions, tension-only tapes, follower hydrostatic pressure and cancellation
from a GUI.

## Decision
- Implement the preview solver in `envelopelab.solvers` with **NumPy only** (no new
  dependency): constant-strain orthotropic St. Venant–Kirchhoff triangles in fabric axes,
  a mixed stress–strain tension-field law with a small residual stiffness (default 1e-3),
  tension-only bars for tapes, and **dynamic relaxation with kinetic damping** (viscous
  damping as an option). Fictitious masses are the Gershgorin bound of the full (taut)
  tangent stiffness.
- Explicit dynamic relaxation needs no global matrix or linear solver, handles the
  tension-field non-smoothness and slack mechanisms robustly, can be stopped between
  iterations and restarted from a previous shape.
- Convergence is declared only at relative residual below 1e-6 (AGENTS.md). Other stops
  return an explicit `not_converged` error.
- `SolverJob` runs the solve on a worker thread with a thread-safe cancellation token and
  progress callbacks, so the GUI event loop is never blocked.
- Results are written as `envelopelab.preview-result` version 1 JSON with units and
  reproducibility metadata.

## Consequences
- No new runtime dependency; the solver runs wherever EnvelopeLab runs.
- Iterations grow roughly linearly with the number of elements across the envelope; fine
  meshes take tens of seconds. A compiled kernel or an implicit (Newton) solver may be
  added later behind the same `solve` interface.
- The preview is validated against closed-form benchmarks (docs/validation/
  preview-solver-benchmarks.md); cross-solver agreement with Kratos (5 %) remains to be
  shown when the Kratos adapter lands.
- Stress-based wrinkle direction is exact for isotropic and approximate for strongly
  orthotropic fabric.
