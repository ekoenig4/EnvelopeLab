# Virtual sewing: from flat patterns to an as-sewn rest model

Modules: `envelopelab.io.pattern_import`, `envelopelab.geometry.polygon`,
`envelopelab.assembly` (`pieces`, `spec`, `seam_graph`, `audit`, `mesh`, `initial_shape`,
`rest_model`, `pipeline`). All quantities are SI (m, m²) inside the library; the build-pack
YAML file uses mm.

The simulation starts from **what will actually be sewn**: the flat cut and sew lines in
the build pack's DXF files, not the designer's 3D reference. Pieces are imported,
reduced to their finished outlines, joined along declared seams into one topological
mesh whose triangles keep their flat (as-cut) shape, and given an initial 3D placement
that the inflation solver starts from.

## Definitions

Cut line
: The outline along which the fabric is cut. It includes the seam allowance.

Sew line
: The line the stitches follow. After sewing it is the visible edge of the panel. Packs
  may draw it (e.g. dotted) or leave it implicit.

Seam allowance
: The strip of fabric between the sew line and the cut line, \(a\) (25 mm is common). It is
  folded into the seam and carries no membrane load in this model. For a hole the
  allowance lies *inside* the finished edge: the cut hole is smaller than the finished one.

Finished geometry
: The piece bounded by its sew lines (outer outline minus finished holes). Finished
  geometry is what the rest mesh is built from; its area is the *finished area*.

Seam
: A sewn relationship between two chains of finished edges (side A and side B), with
  metadata: type (horizontal panel, vertical gore, reinforcement, appendage, closing, rim),
  allowance per side, stitch rows, load tape, designed ease, construction order and
  orientation. A *rim seam* (hem) has one side only.

Seam mismatch
: The unintended length difference of a seam,
  \(\delta = (L_B - L_A) - e\), where \(L_A, L_B\) are the finished side lengths and \(e\)
  the designed ease. Relative mismatch \(\delta_\mathrm{rel} = |\delta| / \max(L_A, L_B)\).

Designed ease
: An intended length excess \(e\) of side B over side A, declared explicitly per seam
  (for example a pod skin eased onto its footprint line so that it domes). Designed ease
  is not an error: it is excluded from the mismatch and passed to the structural
  simulation with the seam.

Opening
: A boundary that is meant to stay open after sewing: mouth, parachute opening, vents,
  feed holes and any explicitly declared feature opening. A hole whose rim is sewn to an
  appendage is *covered* and is no longer an opening of the envelope.

Attachment seam
: An appendage sewn onto a line marked on a panel surface (not onto a panel edge). Three
  surfaces meet along it (panel outside the line, panel inside it, appendage), a
  T-junction that is intended and declared (`attachment: true`).

## Finished outlines

If a piece has a sew line, it is the finished outline. Otherwise the cut outline is inset
by the seam allowance with a mitred offset: each vertex moves along its corner bisector so
that both adjacent edges move by exactly \(d\) along their unit outward normals
\(\mathbf n_1, \mathbf n_2\) [Held]:

\[
\mathbf p' = \mathbf p + d\,\frac{\mathbf n_1 + \mathbf n_2}{1 + \mathbf n_1\cdot\mathbf n_2},
\qquad d = -a \text{ (inset)}, \; d = +a \text{ (hole growth)}.
\]

This form is stable for nearly collinear edges (densely digitised curves). Corners whose
mitre would exceed four allowances are bevelled. Where short edges of the cut line
collapse (for example the clipped corners common in real packs), the raw offset forms small
"swallowtail" loops; they are removed by splitting the outline at the crossing and keeping
the larger part.

*Valid range.* The offset is *supported* when \(a\) is smaller than the local feature size
of the outline (no edge shrinks past zero length, no two offset edges cross). Every result
is validated; an unsupported inset is reported as invalid geometry, never used silently.
The property tests check validity for star-shaped outlines with allowances up to 60 mm,
and that growing then insetting an outline restores it. On the Alien regression pack the
cut line inset by 25 mm reproduces the drawn sew line of every envelope panel to 0.1 mm
(see [Pattern-import fixtures](../validation/pattern-import-fixtures.md)).

The *mitred offset area* is \(A(d) = A + dP + d^2\sum_i \tan(\theta_i/2)\) with perimeter
\(P\) and signed turning angles \(\theta_i\), which the unit tests use as a closed-form
check.

### Validation

Every finished and cut outline is checked to be **closed**, **non-self-intersecting** (no
two non-adjacent segments intersect or overlap, [O'Rourke] sec. 1.5), of **nonzero area**,
and is normalised to **counter-clockwise** order in the pattern frame (seen from the
outside, \(+y\) up). A cut line and sew line of opposite orientation are reported. With
counter-clockwise panels every assembled triangle's normal points out of the envelope.

## Edges and corners

A finished outline is split into edges at its corners: vertices where the turning angle
between the chords to the points one arc-length window \(w\) (20 mm) behind and ahead
exceeds a threshold (30° by default). The window keeps jagged or densely digitised curves
from producing spurious corners; within one window only the sharpest vertex counts.
Four-corner pieces get edge names from the direction of each edge's outward normal
(`bottom`, `right`, `top`, `left`); other outlines get `e0`, `e1`, ...; an outline without
corners is one closed edge `loop`.

## Seam graph

Nodes are finished edges (panel edges, appendage and feature edges, hole rims, embedded
marks, tape paths) plus composite mouth and parachute-opening boundaries. Graph edges are
seams between node chains. A standard gore ring with \(G\) gores and rows
\(r_1..r_n\) generates \(G(n-1)\) horizontal seams (top of \(r_k\) to bottom of
\(r_{k+1}\)) and \(Gn\) vertical seams (right edge of gore \(g\) to left edge of gore
\(g+1\), cyclically), except those declared open (vents). Explicit seams come from the
assembly spec. With consistently oriented panels two pieces lying side by side traverse
their common seam in opposite directions (`orientation: reversed`); an appendage sewn onto
a counter-clockwise hole rim or marked loop runs the same way as the loop
(`orientation: same`). Where both sides share a frame (same ring or same piece) the
declared orientation is checked against the edge directions.

## Seam-length audit

For every two-sided seam the audit reports \(L_A\), \(L_B\), \(e\), \(\delta\),
\(\delta_\mathrm{rel}\), the source panels, the seam type and a severity:

* **error** when \(|\delta|\) exceeds the seam tolerance (3 mm by default, per seam
  configurable), when the declared orientation contradicts the geometry, or when
  \(\delta_\mathrm{rel} > 5\,\%\) (probable wrong pairing);
* **warning** for incompatible seam allowances: the median distance from a side's finished
  edge to its cut line differs by more than 2 mm from the declared allowance, or the two
  sides differ and no per-side allowance is declared;
* **info** for designed ease (with the residual still checked against the tolerance) and
  for seams that are audited but not meshed.

Edges that are neither sewn nor part of a declared opening are *unmatched* (error), and
edges used by more than one seam or opening are *duplicate assignments* (error).

## Virtual sewing and meshing

**Seam-conforming discretisation.** Let side A of a seam have break points (edge ends)
\(u^A_i\) and side B \(u^B_j\) as arc-length fractions of each chain. In A's
parameterisation B's break points are \(u^B_j\) (orientation `same`) or \(1 - u^B_j\)
(`reversed`). The union of both sets is subdivided so that each interval has spacing
\(h(s) = \min(h_\mathrm{seam}, h_\mathrm{corner} + (g - 1)\,d(s))\), graded towards the
break points (\(d\) distance to the nearer break point, \(g\) growth ratio). Both sides
receive the *same* fractions \(t_j\); node \(j\) of A is sewn to node \(j\) (same) or
\(N - j\) (reversed) of B. A length difference between the sides is therefore spread
uniformly between break points, as when a seam is eased by hand between match marks. The
original seam lengths and designed ease stay in the seam metadata.

**Panel triangulation.** Each distinct instance geometry is triangulated once in its flat
local frame with Gmsh [Gmsh] (Frontal-Delaunay). The prescribed boundary points are kept
exactly (every boundary segment is a transfinite line with two nodes); holes are inner
curve loops; marks and tape paths are embedded lines. A background size field (distance
thresholds) refines the mesh near seams, holes, marks and corners and grows to the target
edge length inside the panel.

**Sewing.** The local nodes of all instances are merged with a union-find over the seam
node pairs [Tarjan], producing one topological mesh. Openings are not sewn and stay open.
Each triangle keeps its flat rest coordinates, panel (instance) id, material zone, grain
direction and source pattern id (`file:layer:handle`); seam and tape paths are kept as
edge lists for later cable elements.

**Area invariant.** Because triangulation does not move the prescribed boundary, the rest
area of each instance equals the area of its discretised finished outline minus its
discretised openings. The difference from the exact finished area is the chord error of
the resampled curved edges, of order \((h\kappa)^2\) relative for curvature \(\kappa\).

## Mesh validation

| Check | Definition |
|---|---|
| Manifold edges | every edge has 1 (boundary) or 2 triangles; edges of declared attachment seams have exactly 3 |
| Non-manifold vertices | the triangles around a vertex are connected through shared edges |
| Boundary loops | chains of boundary edges; each must lie on a declared opening, and every opening must appear |
| Connected parts | components of the triangle–node graph (must be 1) |
| Orientation | on interior edges the two triangles traverse the edge in opposite directions |
| Inverted elements | flat signed area \(\le 0\) |
| Quality | \(q = 4\sqrt3 A / (l_1^2 + l_2^2 + l_3^2)\), 1 for an equilateral triangle |
| Rest area | \(\sum A_\triangle\) vs the sum of finished instance areas (outline minus openings), within 0.5 % |
| Euler characteristic | \(\chi = V - E + F\); for one orientable part with \(b\) boundary loops and genus 0, \(\chi = 2 - b\) |

## Initial geometry (starting guess only)

For gore rings, rows are stacked along the gore centreline: a point \((u, v)\) of row
\(k\) sits at arc length \(s = S_k + v\). With left/right finished edges \(x_l(v), x_r(v)\)
and \(G\) gores

\[
\tau = \frac{u - x_l}{x_r - x_l},\quad
\theta = \frac{2\pi}{G}(g + \tau),\quad
\rho(s) = \frac{G\,(x_r - x_l)}{2\pi},\quad
z(s) = \int_0^s \sqrt{1 - \rho'(\sigma)^2}\,d\sigma,
\]

the surface of revolution whose parallels have the sewn circumference [Struik]
(\(|\rho'|\) clamped to 1). Nodes sewn from several panels take the mean of their
placements. Appendage nodes are placed by a discrete harmonic extension from the placed
seam nodes, lifted along the mean attachment normal in proportion to their rest-mesh
distance, then relaxed towards their rest edge lengths by a few hundred Jacobi projection
sweeps with a small outward push. With `method: reference_mesh` the guess is projected onto
a user-supplied OBJ surface by closest-point projection [Ericson]. None of this is the
inflated shape; the rest model says so explicitly.

## Assumptions and valid range

* Fabric is inextensible for the purpose of the rest geometry; seam allowances are folded
  away and not modelled as material.
* Seam ease (mismatch or designed ease) is distributed uniformly between chain break
  points.
* Multi-ply regions (doublers) are one mesh layer with their own material zone.
* Appendages can be sewn to panel edges, hole rims and marks *within one panel*. Marked
  lines that cross several panels (for example a pod footprint spanning nine panels) are
  audited in the seam graph but not yet embedded in the mesh; such parts are declared
  `mesh: false` and reported as warnings.
* The initial geometry is a guess for the solver, not a prediction.

## References

- [Held] M. Held, *On the Computational Geometry of Pocket Machining*, Springer LNCS 500
  (1991).
- [O'Rourke] J. O'Rourke, *Computational Geometry in C*, 2nd ed., Cambridge University
  Press (1998).
- [Gmsh] C. Geuzaine, J.-F. Remacle, "Gmsh: a 3-D finite element mesh generator with
  built-in pre- and post-processing facilities", Int. J. Numer. Meth. Engng 79 (2009)
  1309-1331.
- [Tarjan] R. E. Tarjan, "Efficiency of a good but not linear set union algorithm",
  J. ACM 22 (1975) 215-225.
- [Struik] D. J. Struik, *Lectures on Classical Differential Geometry*, 2nd ed., Dover
  (1988).
- [Ericson] C. Ericson, *Real-Time Collision Detection*, Morgan Kaufmann (2005).
