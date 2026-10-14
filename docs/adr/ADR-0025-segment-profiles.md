# ADR-0025: Segment profiles (design schema version 7)

- Status: Accepted
- Date: 2026-10-14

## Context
A profile was a list of control points joined by one spline or by straight segments.
Builders draw an envelope as a few simple pieces instead: a straight cone above the
mouth, a cylinder, an arc shoulder, a smooth crown. With one spline, a straight section
takes many points held in line by hand, and an arc can only be approximated. CAD
sketches solve this with segment types and joint constraints (G0/G1/G2).

## Decision
* `GoreSpec.profile_interpolation` gains `"segments"`. `GoreSpec.profile_segments` then
  lists one `ProfileSegment` per span between consecutive control points: `kind` (`line`,
  `arc` or `curve`), `bulge` (arcs, tan of a quarter of the included angle, DXF
  convention) and `smooth` (a G1 joint at the span's start). Validation requires one
  segment per span, and segments only with `"segments"`.
* The control points stay the joints. The locks, the bulk point tools, the row fit, the
  3D view and every output keep working on the same arrays. Only the profile builder
  (`profile_from_arrays`, via a hashable `SegmentLayout`) knows about segments.
* Joints are resolved from the mouth up, the more flexible span adapting (lines fixed,
  then arcs, then curve runs). A smooth joint that cannot be met is reported as a kink,
  not solved by moving points. Joints are G1; curvature continuity holds inside curve
  runs only.
* All-curve and all-line layouts draw exactly the spline and straight-segment profiles,
  so converting a design to segments changes nothing until a span is edited.
* The design document becomes schema version 7. Version-6 documents migrate unchanged:
  they have no segments.

## Consequences
* Straight sections and arcs are exact. Their volume, area and length match closed forms
  (generated analytic benchmarks).
* Simplify does not apply to segment profiles, because their points are joints.
* Shape files do not describe segment profiles yet.
* A G2 joint between an arc and a curve, and a constraint solver that moves points to
  meet tangencies, are possible later extensions. They are not needed for G1 shapes.
* Older EnvelopeLab versions cannot read version-7 documents.
