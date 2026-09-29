# ADR-0006: Appendage sub-models, gas chambers and the Reality Check report

- Status: Accepted
- Date: 2026-09-29

## Context
Special-shape features (ram-air pods, blisters, tubes, antennae, fins) change the inflated
shape and the load paths of an envelope. Modelling them needs: separately pressurised gas
volumes fed from the envelope, skins with designed ease sewn onto lines that cross many
envelope panels, rim and host tapes, and a report that compares the predicted shape with
an intended reference mesh. The as-sewn rest mesh (ADR-0003) embeds marked lines only
inside one panel; the full Alien envelope preview solve (5 932 triangles) did not converge
in 200 000 iterations (17 min), so solving every feature inside the whole envelope is not
practical today. Registering a reference mesh needs ICP; Open3D provides a maintained
point-to-plane ICP.

## Decision
- **Gas chambers in the solver model.** `SolverModel.chambers` and `tri_chambers` give
  each triangle an inside and an outside gas (main envelope, ambient or a chamber). The
  preview solver and the CalculiX adapter both take the triangle pressure from
  `SolverModel.triangle_pressure`, so the two solvers see the same loads. Without
  chambers the original code path runs and results are bit-identical.
- **Features as local sub-models.** A feature is assembled with a patch of its host
  (a fitted surface of revolution, prestrained to the envelope's membrane state, edge
  fixed), its skin (flat as-cut pattern with the match-point ease correspondence, or a
  designed cap for benchmarks), tapes and chamber, meshed with Gmsh (OCC fragments). All
  design data comes from a `features:` section of the build-pack YAML.
- **Pressure communication** from the feed holes with an explicit, `assumed` loss factor.
- **Reality Check report** (`envelopelab.report`): three states, deviation heat map,
  dimensions, load paths, factors of safety, findings, convergence, sensitivity sweep;
  HTML (inline SVG), PDF (own minimal vector writer, no dependency), JSON
  (`envelopelab.reality-check` v1) and CSV. `verified` only for a converged CalculiX
  result whose solver settings are at least as strict as the documented tolerances.
- **Reference meshes**: own OBJ/STL/PLY readers; ICP with **Open3D** (MIT) as an optional
  extra (`envelopelab[registration]`) and a SciPy point-to-point ICP otherwise. Open3D is
  optional because its wheels are large and need system graphics libraries.

## Consequences
- Features are not yet re-solved inside the whole envelope; the envelope far from a
  feature does not respond to it. Embedding feature lines across panels in the global
  mesh remains future work.
- A loss factor of exactly 0 leaves the fabric under a pod unloaded (a mechanism) and the
  solve does not converge; this is documented and reported, not hidden.
- Tension-field-dominated eased skins converge slowly and mesh-dependently; CalculiX does
  not converge on the Alien pod sub-model, so its report is not verified.
- New optional dependency Open3D (MIT) listed in `LICENSES.md`; CI installs it on Linux.
