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

**Special shapes are solved in the same run.** After the envelope, each placed special
shape that has a feed hole is solved with the same solver and load case: the shape's own
sub-model, its skin sewn from its cut pieces on a patch of the envelope round it
([special shapes](special-shape-primitives.md)). Its element size is about 1/40 of its
footprint length (100 to 300 mm, assumed), not the envelope's mesh size; its peak values
depend on that size (each result warns of it); a CalculiX run
starts each shape from a preview of the same sub-model. The results appear in the
**Special shapes** panel and in the 3D view as *as sewn and inflated*, are saved with the
project with the run they belong to, and go STALE when the shape or the envelope changes.
A shape without a feed hole, still being placed or that cannot be placed is left out, and
the status bar says so. The envelope's own solve does not include the shapes.

!!! warning "Material values"
    Fabric areal mass and service temperature come from the fabric library with its source
    tags. Membrane stiffness, strength and seam efficiency and tape stiffness and mass are
    generic `assumed` values in this version. Every run lists its material sources.

## Telling results apart

* Every run row names its solver — **Preview (dynamic relaxation)** or **CalculiX
  verification** — with a solver-coloured swatch; the 3D view uses the same colours
  (preview blue, CalculiX orange, rest mesh olive, reference mesh green; the design
  surface in its fabric colours with dark seams) and the same names in its layer list and
  legend.
* Each run shows its **state** as a chip with the same symbols and colours as the 3D
  view's banner (i *Current*, ✓ *Current* for CalculiX, ◷ *Stale*, ▲ *FoS fail*, ✕ *Not
  converged*), whether it **converged**, the **Min FoS** (the lowest fabric factor of
  safety, warp or weft, of a current converged preview run, marked **FAIL** in bold below
  the required 5; "—" otherwise, hover for why), the final **residual** (hover for what it
  measures), iterations, run time, nodes/elements, mesh size, volume, lift and material
  sources. With no run yet, the panel says how to start one.
* The toolbar starts runs (**Run Preview** is the main action). A chip beside it shows the
  CalculiX version found; without CalculiX a banner says where it looked and why
  *Run CalculiX* is disabled.
* A run whose inputs differ from the current design is **STALE**: greyed and italic in
  the table, `[STALE]` in the 3D layer name and in the panel titles, and listed in
  Validation. It is never shown as current. Undoing the edit makes it current again.
* A run that did not converge is shown **NOT CONVERGED** in red and listed as an error in
  Validation; its numbers are not final.

## Results in the 3D view

The 3D view's toolbar chooses what it shows:

* **Run**: the result the colours, the banner and the run details describe (the latest
  preview or CalculiX run).
* **Colour by**: *Factor of safety, warp* or *weft* (the default for a current, converged
  preview run), the principal, warp and weft resultants (N/m), *Wrinkling* (taut,
  wrinkled, slack) and *Displacement from the as-sewn shape* (mm), or *Layer colour*.
  A field the run cannot give is listed but greyed out; hover for why (for example
  "CalculiX does not report warp/weft resultants", or a run from an older version that
  has to be run again).
* **Display**: *Shaded*, *Shaded + mesh edges* or *Wireframe*.

The factor of safety is coloured in bands of the required factor (5 by default, tagged
*assumed*): everything **below the limit is orange and labelled FAIL** on the colour
scale, whatever else is shown; above it, blues get lighter with more margin. It is the
fabric strength of the triangle's zone over its warp or weft resultant, so the lowest
value in a zone is the factor in the run's factor-of-safety table. Seams and tapes are not
coloured; read them in the table.

A **status banner** across the top of the view always states the chosen run's state, worst
first. It cannot be closed; it goes when the state does:

| Banner | When | The view |
|---|---|---|
| ✕ **Not converged — values are not final.** | the solve stopped before converging, or reported an error | surface in its layer colour with red mesh edges; no field colours |
| ◷ **Stale result.** | the design changed since the run | grey; no field colours; *Re-run* button |
| ▲ **Factor of safety below the limit** / **A design limit is exceeded** | a zone direction under the required factor, or a temperature limit exceeded | names the zones and the minimum; failing regions orange |
| i **Current and converged** — preview only | no current CalculiX run yet | *Run CalculiX* button |
| ✓ **Current and converged** | a current, converged CalculiX run exists too | — |

"Verified" only means a current, converged CalculiX run exists for the same design; compare
the two runs in the Simulation Runs table. The **Run details** card beside the layer list
gives the solver and version, status, iterations, final residual (hover for what it
measures), mesh size, load case, run time, volume and the material source tags
(**assumed** in bold). The **Probe** tool (on the left of the view) shows the zone and
every field's value of the element you click, and flags a factor below the limit.

!!! warning "Strength values"
    In this version the fabric strengths are generic `assumed` values (see *Material
    values* above), so the factor-of-safety colours are only as good as those values.
    Check the materials and their sources before relying on them.

## Progress and remaining time

The progress bar never moves backwards and is full when the run ends.

* **Preview.** The bar follows the best residual reached so far, in decades from where
  the run started down to the 1e-6 target. It also follows the share of the iteration
  limit used, so a run that will stop at the limit fills the bar by then. The text gives
  the residual, the elapsed time and the time until the iteration limit. Once the
  residual is clearly falling it adds *about N s left*. The residual of the preview
  usually stalls between 1e-1 and 1e-2 for most of a run before it drops, so early
  estimates err long. *May not converge before the limit* means the present rate would
  not reach the target in time.
* **CalculiX.** The bar moves while each `ccx` job runs (read from its status file every
  half second). The text gives the pass, the job and its progress, the out-of-balance
  against the 1e-5 target, and, after the first pass, the remaining time from the time
  and gain per pass so far.
* A CalculiX run that solves its preview first says *Step 1 of 2* (the preview) and
  *Step 2 of 2* (CalculiX). Building the model (import, seam audit, meshing, sewing)
  fills the first tenth of the bar.

## Preview runs

**Cancel** stops a preview; its result is kept with status `cancelled`, not converged.

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
