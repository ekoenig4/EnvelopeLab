# ADR-0032: Pointed special shapes are closed by a cap

- Status: Accepted
- Date: 2026-11-01

## Context
Domes, revolved profiles ending on the axis, pointed tubes and mesh shapes were cut into
gores or panels that all met in a single point at the top. With 16 or 20 pieces that
point stacks every seam and seam allowance in one spot and cannot be sewn or taped
cleanly. In ballooning practice the pieces' tops are sewn round a circle of measurable
diameter, closed by a round cap.

## Decision
* Every pointed shape can be closed by a cap of radius \( r_c \) (library field
  `cap_radius`, 0: a point). Parametric shapes stop their meridian where it is as wide as
  the cap and close it with a flat disc (the existing tip disc); a pointed tube becomes the
  frustum to that radius. A mesh shape keeps its surface: the part round the pole inside
  the cylinder \( \rho = r_c \) about the axis is cut off as one more piece, flattened with
  its edge at true length, and the panels end on that edge.
* Project shapes get `cap_diameter` (format version 3, still unreleased, optional): None
  is automatic, 0 a point, a value is kept. The automatic diameter gives each of the
  \(M\) pieces a top at least 100 mm wide, \( d = M \cdot 0.1\,\mathrm{m} / \pi \), at
  most half the base diameter (both assumed). Shapes in existing projects are capped
  automatically when opened.
* The cap is cut flat. In the sub-model a parametric cap's nodes start on the pointed
  surface it replaced (taut and curved), resting in the flat disc.

## Consequences
* Patterns can be sewn as built; the cap's sheet ticks where every seam meets it.
* Results change for existing shapes: capped domes are lower as designed, mesh shapes
  gain a cap piece, and the inflated top is flattened by the flat cap.
* The flat cap wrinkles round its edge under pressure, which the preview solver handles
  slowly; some large caps do not converge (reported as unconverged, never as results).
  A cap with fullness (darted or gored) would follow the top better and is a possible
  follow-up.
