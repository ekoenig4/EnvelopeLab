# ADR-0015: Parametric special-shape primitives with an as-cut skin

- Status: Accepted
- Date: 2026-10-04

## Context
Special-shape features could be analysed only when their pieces were drawn in outside CAD
and imported through a build pack (ADR-0003, ADR-0006). Builders asked to start from a
standard-gore design, add shapes on top of it, and get the attachment line on the
envelope panels and the cutting pattern of the shape from EnvelopeLab itself. The
existing appendage sub-model accepted only a single flat skin piece or an analytic
spherical cap, so a skin sewn from several gores could not be simulated as cut.

## Decision
* **Parametric primitives first.** `envelopelab.features.primitives` offers a dome (half
  spheroid) and a tube (straight frustum with a flat tip disc), placed by gore, tape
  position, offset across the gore and lean. Arbitrary meshes and revolved profiles may
  follow; they would reuse the same footprint, attachment and sub-model code.
* **Footprint by continuation.** Each skin meridian continues along its base tangent
  until it meets the envelope (the surface of revolution of the load-tape meridian), so
  the skin always reaches the envelope, also under a leaned base.
* **Cutting pattern.** Tube panels are exact developments. Dome gores are classic gores
  (true centreline and parallel lengths) sheared and stretched so that both seam edges
  have the seam's true 3D length; the remaining area distortion is reported.
* **As-cut skin in the solver.** The builder gets a third skin mode, `designed`, in which
  a factory meshes every cut piece in its own flat coordinates round the host mesh's
  footprint nodes. Each triangle rests in the cut cloth, scaled by chord / arc of the
  designed surface along each side (the faceting correction), and the seams are shared
  mesh lines.
* **True-envelope host.** For primitives the host patch is the design envelope itself
  (`EnvelopeHost`, a `HostSurface` subclass), not a fitted circle, so the skin's rim
  and the host footprint have the same length.

## Consequences
The existing skin modes and their results are unchanged (no benchmark moves). The
inflated shape of a primitive follows from the pattern actually cut, so the effect of a
low gore count or a poor flattening is visible before cloth is cut. The faceting
correction ties rest lengths to the designed shape at the scale of one element; it tends
to the plain cut lengths as the mesh is refined. Primitives are not yet stored in the
design file or shown in the application, and the cutting pattern is not yet exported as
DXF or PDF (planned with the build-pack export, which brings the output QA of AGENTS.md
§6.6). No new dependency.
