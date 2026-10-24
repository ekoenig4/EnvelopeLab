# ADR-0028: The preview solver runs its iterations compiled

- Status: Accepted
- Date: 2026-10-23

## Context
ADR-0019 compiled the element loop of the preview solver. Each iteration still ran in
Python: the step and the kinetic energy, the tape and closure forces, the constraint
projection and the residual norm. Each one is a handful of NumPy calls on small arrays.
After a kinetic-energy reset the Python code also rebuilt the fictitious masses, about
8 ms each. On the generic 8-gore fixture at the default 800 mm mesh, the solve took
22–24 s for about 40,000 iterations, most of it in call overhead and not in arithmetic.

## Decision
* With Numba available (ADR-0019, the `fast` extra), `solve` runs the whole iteration
  loop compiled (`envelopelab.solvers.kernels.relax_kernel`). That covers the step,
  kinetic damping and its resets, forces, tapes, closures, chamber pressures, projection
  and residual. The masses after each reset are rebuilt inside the loop too.
* The loop runs in chunks. Every `progress_interval` iterations it returns to Python,
  where the progress report, cancellation and time limit are handled exactly as before.
* The Python loop stays as the reference and runs without Numba or with
  `ENVELOPELAB_NO_JIT=1`. The compiled functions use the same arithmetic in the same
  order. `tests/unit/test_compiled_iterations.py` checks the following on symmetry
  planes, tapes, point, line and distributed loads, closures and shared-wall chambers:
  * forces, external forces and masses agree to 1e-12 relative;
  * 300-iteration runs give the same status, iteration and reset counts, and positions
    within 1e-9 of the model size;
  * converged solves reach the same equilibrium.

## Consequences
On the generic fixture, preview solves are about 4× faster: 24.2 → 6.1 s at 800 mm
(39,829 against 37,620 iterations) and 2.9 → 0.7 s at 1600 mm. Results are unchanged
except for round-off, which over a long solve changes the iteration count by a few
percent. The equilibria agree within 0.21 µm, with the same volume. No benchmark or
golden value moved. The compiled loop is a second copy of the iteration: any change to the Python loop must
be made in both, and the equivalence tests fail when they differ. The first solve after
installation compiles the loop once; Numba caches it on disk.
