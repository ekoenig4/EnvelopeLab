# Running simulations

The **Simulation Runs** panel (and the Simulation menu) has two separate actions:

| Action | Solver | Where it runs | Use it for |
|---|---|---|---|
| **Run Preview** (F9) | EnvelopeLab dynamic relaxation ([theory](../theory/dynamic-relaxation.md)) | inside EnvelopeLab | quick feedback while designing |
| **Run CalculiX** (Shift+F9) | CalculiX CrunchiX `ccx` ([theory](../theory/verification-solver.md)) | external `ccx` process | verification of a design |

Both solve the same model, built from the design exactly as a builder's patterns would be:
the rows are drawn to a DXF build pack, imported, sewn virtually and meshed
([virtual sewing](../theory/virtual-sewing.md)); the mouth is fixed and the crown is closed
by the parachute. The mesh edge length is set in **Preferences** (separately for each
solver).

!!! warning "Material values"
    Fabric areal mass and service temperature come from the fabric library with its source
    tags. Membrane stiffness, strength and seam efficiency and tape stiffness and mass are
    generic `assumed` values in this version. Every run lists its material sources.

## Telling results apart

* Every run row names its solver — **Preview (dynamic relaxation)** or **CalculiX
  verification** — on a solver-coloured background; the 3D view uses the same colours
  (preview blue, CalculiX orange, rest mesh olive, reference mesh green; the design
  surface in its fabric colours with dark seams) and the same names in its layer list and
  legend.
* Each run shows its **state** (CURRENT or STALE), whether it **converged**, the final
  **residual** (hover for what it measures), iterations, run time, nodes/elements, mesh
  size, volume, lift and material sources.
* A run whose inputs differ from the current design is **STALE**: greyed and italic in
  the table, `[STALE]` in the 3D layer name and in the panel titles, and listed in
  Validation. It is never shown as current. Undoing the edit makes it current again.
* A run that did not converge is shown **NOT CONVERGED** in red and listed as an error in
  Validation; its numbers are not final.

## Preview runs

The preview reports progress (iteration, residual against the 1e-6 target, time) in the
panel and status bar; **Cancel** stops it (the result is kept with status `cancelled`,
not converged).

## CalculiX runs

CalculiX is optional and not bundled. EnvelopeLab looks for `ccx` at the path set in
**Preferences**, then `$ENVELOPELAB_CCX`, then `PATH` (see
[CalculiX installation](../dev/calculix-installation.md)). When it is missing,
**Run CalculiX is disabled**, the status bar says *CalculiX not found*, and the runs
panel shows where it looked, why each place failed, and the installation instructions. After installing, use **Simulation ▸ Detect
CalculiX again**.

A CalculiX run launches `ccx` as a separate process for each job of the staged solve; the
progress monitor shows the pass, the job (held or release) and the latest out-of-balance
force. **Cancel** stops `ccx`; a cancelled CalculiX run leaves no result.

CalculiX checks a preview's equilibrium with its own elements; it does not find the shape
itself. When a current, converged preview of the same mesh exists, CalculiX starts from
its shape. Otherwise **Run CalculiX** first solves a preview, which appears in the runs
list as its own run, and then starts CalculiX from it. If that preview does not converge,
CalculiX is not started and the message says why. Either way, the CalculiX result is
accepted only on its own convergence criteria. Started from a preview, it usually needs
one pass: seconds rather than minutes (4 s on the generic 8-gore fixture at 800 mm, after
an 18 s preview).

## Saved results

Run records are saved in the project and their result arrays next to it
(`<project>.elproj.runs/`), with the design content hash, solver version and run manifest,
so every run can be reproduced.
