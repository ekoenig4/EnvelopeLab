# ADR-0030: Special-shape simulations are solved automatically and kept in the project

- Status: Accepted; the automatic background solves are superseded by ADR-0031
- Date: 2026-10-31

## Context
The 3D view drew every special shape as its designed surface. How a shape actually forms
when its skin is sewn from the cut pieces and inflated was visible only after the builder
ran **Simulate shape** for it, and that result lived in memory: reopening the project
lost it. Shape simulations take seconds to a few minutes with the preview solver, and the
default 60 mm mesh made a large pod (a 23 m rim) far slower than it needs to be.

## Decision
* Project format version 3 adds `shape_runs`: the latest simulation of every special
  shape (`ShapeRunRecord`: summary, metrics, factor of safety per region, provenance and
  the key of its inputs) with a result file in the project's runs folder holding the
  skin as solved, split into its cut pieces with its seams and rim
  (`envelopelab.project.shape_runs`). A newer simulation of a shape replaces the older
  one. Versions 1 and 2 migrate with no shape runs; older releases refuse version 3.
* A kept simulation is current while the key of its inputs (the shape's specification,
  the envelope it is placed on, and the envelope's load case, materials and tapes)
  equals the shape's key now; otherwise it is STALE, as before.
* The desktop application solves every placed shape that can be fed and has no current
  simulation, one at a time in the background (preference *Simulate special shapes
  automatically*, on by default). The element size is
  `auto_mesh_size`: footprint length / 100, between 60 and 300 mm (assumed). A solve the
  builder starts replaces a running automatic one; an automatic solve that failed is not
  retried until its inputs change.
* The 3D view draws the kept simulation as the shape, as sewn and inflated; the designed
  shape stays available as a layer (hidden while a current simulation is shown).

## Consequences
* Opening a project shows its shapes as last solved, without solving again; results
  carry the same provenance as envelope runs.
* Files written by this release cannot be opened by releases that read only versions
  1 and 2.
* The automatic mesh size is a compromise between fidelity and solve time that no study
  has fixed; the builder can still solve any shape with a chosen element size. Preview
  results remain unverified (assumed stiffness values), and an unconverged result is
  kept and shown as NOT CONVERGED, never as final.
* Background solves use CPU while the builder works; they can be turned off in
  *Preferences*.
