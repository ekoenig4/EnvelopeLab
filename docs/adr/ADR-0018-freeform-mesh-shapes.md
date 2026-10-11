# ADR-0018: Free-form special shapes from meshes, flattened with true-length edges

- Status: Accepted
- Date: 2026-10-04

## Context
Domes, tubes and revolved profiles (ADR-0015) cover shapes that are symmetric about an
axis. Ears, curved horns and faces are not. Builders model them in Blender (ADR-0017)
and want EnvelopeLab to attach them to the envelope, cut them into panels, give the
cutting pattern and simulate them like the parametric shapes.

## Decision
* A `FreeformShape` is a closed mesh in the shape's own frame. It is placed with the
  primitives' axis frame, clipped at the envelope (the cut edge is the footprint), and cut
  into panels along half-planes through its axis that meet at the pole where the axis
  leaves the mesh. It flows through the same `PrimitiveDesign`, attachment lines, match
  marks, build-pack export and `designed` sub-model as the parametric shapes.
* Panels are flattened by LSCM then ARAP (Lévy et al. 2002; Liu et al. 2008), then the
  boundary is rebuilt at exact 3D edge lengths (closed by least-norm edge rotations) and
  the interior relaxed with the boundary held. Sewn edges and the rim are exact. The
  remaining strain is in the interior and is reported (area distortion, edge strain).
* Shapes whose axis does not leave through their top, panels that are not discs, and
  panels that fold when flattened are rejected with a message. Nothing is silently
  repaired.
* No new dependency: the flattening uses SciPy's sparse solvers.

## Consequences
Any closed shape can be designed, cut, exported and simulated. Flattening strain falls
with the number of panels; a generic ellipsoid needs about 16 panels to pass the 1 %
area-distortion check. Panels always run from the footprint to the pole: horizontal
panel rows, darts and seams placed by hand are not supported. The input mesh is taken as
the designed surface, so a coarse mesh is simulated as the polyhedron it is.
