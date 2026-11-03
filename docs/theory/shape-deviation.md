# Deviation of the solved shape from the design

`envelopelab.project.deviation` measures where an inflated (solved) shape lies **outside**
or **inside** its design, and by how much. The 3D view colours the design surface by it,
and the Patterns view maps it onto the flat panels.

## Definition

For every node \(\mathbf{x}\) of the solved membrane mesh, with \(\mathbf{q}\) the closest
point of the designed surface and \(\hat{\mathbf{n}}(\mathbf{q})\) the design's outward unit
normal there:

\[ d = (\mathbf{x} - \mathbf{q}) \cdot \hat{\mathbf{n}}(\mathbf{q}) \]

\(d > 0\): the fabric bulges **outside** the design; \(d < 0\): it lies **inside**. Only the
normal component counts, so fabric that slid along the surface without leaving it (a seam
that moved up the tape) reads as zero. Units: m (shown in mm).

## How it is computed

* The closest point is exact on each candidate triangle (Ericson, *Real-Time Collision
  Detection*, 2005, 5.1.5); the candidates are the 12 triangles with the nearest centroids.
* The normal is the barycentric blend of the design's area-weighted vertex normals,
  oriented away from the z axis for an envelope (its crown and mouth are open).
* The deviation is evaluated **at the solved nodes**, where the solver's positions are
  exact, against a dense tessellation of the design (24 segments per gore and per row).
  A flat triangle of edge \(h\) on a surface of radius \(R\) lies up to
  \(h^2/(6R)\) inside it: about 0.5 mm on a 3 m radius with 8 gores.
* For display it is interpolated linearly (barycentric) from the nodes onto the design's
  display surface. Between nodes the colours are that interpolation, not solver values;
  the colour scale is set by the exact node values, so the largest deviation is never cut
  off.

## On the flat panels

A display-surface point at tape length \(s\) in a row and fraction \(u\) across its gore
(0 at its left seam, 1 at its right) is drawn on the flat panel at

\[ y = s - s_{bottom}, \qquad x = (2u - 1)\,\frac{w(y)}{2} \]

with \(w(y)\) the panel's finished width at that height (`panel_deviation`). This is a
display mapping (the panel's \(y\) is its centreline length up from the bottom seam). Every
gore of a row is cut from the same panel, so at each point the panel shows the gore that
deviates most there, and its tooltip names it.

## Assumptions and valid range

* Solved and designed shapes are in the same frame (m, mouth at z = 0) and the solve covers
  the shape (the preview solver models the whole envelope). Nodes farther than an optional
  distance from the design are left out (NaN).
* The designed surface is consistently wound; one outward orientation is chosen for all
  of it.
* Shown only for a **current, converged** run: a stale or unconverged run has no
  deviation field, and the view says why.

## Checks

* Sphere: points on a sphere of radius \(R + \delta\) against a design sphere of radius
  \(R\) give \(d = \delta\) for \(\delta = \pm 50\) mm, within the faceting bound above
  (`test_sphere_offset_matches_hand_calculation`).
* Envelope fixture: at the widest solved node the deviation equals the solved minus the
  designed maximum radius within 5 mm (`test_preview_run_record`).
* Closest point in every Voronoi region of a triangle, outward normals for either winding,
  exact linear interpolation, and the panel mapping (heights, edges, worst gore).
