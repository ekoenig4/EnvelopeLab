# ADR-0053: Move where a mesh shape's panels meet

- Status: Accepted
- Date: 2026-11-20
- Extends: ADR-0052 (relative meeting point)

## Context
ADR-0052 sets where a dome's or revolved shape's panels meet as plan fractions
(`cap_across`, `cap_up`) by moving its cap. Mesh (free-form) shapes, such as an imported
eye pod, kept the controls greyed out: their panels are cut along half-planes through the
shape's axis and meet at the pole where the axis leaves the mesh, and nothing moved it.
Builders expect the same control on every shape with gores.

## Decision
* A mesh shape takes the same `cap_across` and `cap_up` (no format change: the keys
  exist since format 6). `to_primitive` turns them into `FreeformShape.seam_centre`, the
  plan offset (m) of a *seam line* parallel to the axis, using the mesh's widest distance
  from its axis seen from above (`widest_radius`).
* `build_mesh_skin` takes the pole, the seam half-planes, the cap cylinder and every
  angle round the shape about the seam line instead of the axis, so the seams run
  straight (seen from above) from the rim to the point and the panels meet where the
  line leaves the mesh, with or without a cap. The display colours the pieces about the
  same line.
* The crown seam turn and widths stay rim-only for mesh shapes (their seams are planar
  cuts); the panel says so.

## Consequences
* The Where the panels meet pad works on mesh shapes; mirror twins mirror the point.
* With the point on the axis the mesh panels are bit-identical to before.
* A point too far out can leave a panel that is not a disc or a footprint that no longer
  turns once round the line; the shape reports it, as for a leaning placement.
* Mesh shapes have no fast preview (ADR-0051), so each change is placed in full (about
  1 s for a full-size eye pod).
