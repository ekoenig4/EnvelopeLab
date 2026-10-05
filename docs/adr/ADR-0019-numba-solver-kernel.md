# ADR-0019: Optional Numba kernel for the preview solver

- Status: Accepted
- Date: 2026-10-04

## Context
Builders find preview solves slow: about 35 s for the generic fixture envelope at the
default 800 mm mesh (616 nodes, 21,000 dynamic-relaxation iterations). Profiling showed
that each iteration spends most of its time in the per-call overhead of many small NumPy
operations on arrays of about a thousand triangles, not in arithmetic. Precomputing the
fixed operators (sparse corner-to-node sums, chamber pressure groups, closure node sets,
explicit cross products) gains only 10-30 %.

## Decision
* `envelopelab.solvers.kernels.element_forces` evaluates, per triangle, the deformation
  gradient, Green strain, tension-field stress, internal corner forces and consistent
  pressure loads, and sums them onto the nodes. The NumPy implementation (the existing
  functions of `envelopelab.solvers.membrane`) remains the reference.
* When Numba (BSD-2-Clause; with llvmlite, BSD-2-Clause) is installed, the same
  arithmetic runs as one compiled loop (`njit(cache=True, nogil=True)`). Numba is an
  optional extra `fast` (installed by default by `scripts/install_env.sh`) and part of
  the `dev` extra, so the tests always compare both paths. `ENVELOPELAB_NO_JIT=1` forces
  the NumPy path.
* Both paths must agree to round-off: `tests/unit/test_solver_kernels.py` compares every
  output on taut, wrinkled and slack triangles with a relative tolerance of 1e-12.

## Consequences
Preview solves are 3-4x faster with the kernel (fixture envelope 10.2 s to 3.3 s at
1600 mm, a 16-gore dome sub-model 3.7 s to 0.9 s), 1.1-1.4x faster without it. Because
the kernel releases the GIL, the desktop application stays responsive while a solve runs
in its worker thread. Results differ from the previous implementation only by round-off
(largest node position difference 0.34 µm on the cases above), which changes iteration
counts by a few percent; no benchmark or golden value moved. The first solve after
installation compiles the kernel (about 1 s, then cached on disk).
