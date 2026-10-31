# ADR-0031: Special shapes are solved with the envelope, not in the background

- Status: Accepted
- Date: 2026-10-31
- Supersedes: the automatic background solves of ADR-0030

## Context
ADR-0030 solved every placed special shape in the background whenever it had no current
simulation. On a full-size design with two 23 m eye pods and two antennae that kept the
computer busy for a quarter of an hour after every shape or envelope edit, with results
that the builder had not asked for, and separately from the envelope's own runs. Builders
run the envelope when they want results; the shapes belong with that run.

## Decision
* The automatic background solves and their preference are removed.
* **Run Preview** and **Run CalculiX** solve the envelope and then, in the same run and
  worker, every placed special shape that can be fed (it has a feed hole), with the same
  solver and load case: each shape's own sub-model (ADR-0006), at the element size of
  `envelopelab.project.shape_runs.auto_mesh_size` (footprint length / 100, 60 to 300 mm,
  assumed), not the envelope's mesh size. CalculiX starts each shape from a converged
  preview of the same sub-model; when that preview does not converge, it is kept as the
  shape's result with an error finding.
* Each result is kept as the shape's `ShapeRunRecord` (format version 3, ADR-0030) with
  `envelope_run_id` naming the run; the latest result per shape is kept. *Simulate shape*
  still solves one shape on its own, with a chosen element size (no envelope run id).
* Shapes that are not placed or cannot be fed are left out and reported when the run
  starts; a shape that fails does not stop the others.

## Consequences
* Shape results come with the envelope run that produced them and nothing is solved
  that was not asked for.
* An envelope run takes longer by the time of its shapes' solves.
* The envelope's own solve still does not include the shapes' loads; a combined model
  (the skins sewn into the full envelope mesh) remains a possible follow-up.
