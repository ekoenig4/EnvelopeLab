# ADR-0049: Where special-shape panels meet at the crown (project format version 5)

- Status: Accepted
- Date: 2026-11-17
- Extends: ADR-0040 (panel layout of special shapes)

## Context
The seam turn, panel widths and horizontal splits (ADR-0040) decide how a shape's skin is
cut, but every seam ran straight up a meridian from the rim to a cap centred on the tip:
where the pieces met at the crown followed from the rim and could not be changed. Builders
want to choose it, for example equal panels round the cap under a wide face panel at the
rim, seams turned off a marking near the top, or a cap moved to one side.

## Decision
* **Seam angles at the crown.** A shape may have its own crown seam turn and widths
  (`crown_seam_offset_deg`, `crown_panel_widths`; unset: as at the rim). The skin keeps a
  seam coordinate \( \psi \) (the rim angle) and maps it to the angle
  \( \phi = \psi + \delta(\psi)\,g(u) \): \( \delta \) the crown angle minus the rim
  angle, linear between seams, \( g \) a smoothstep from 0 at the highest footprint point
  to 1 at the lowest top of the skin. Every development, check, mesh and drawing works on
  \( (u, \psi) \) through the skin, so they all follow; the rim, footprint, marks and
  attachment are unchanged. Turned frustum panels are laid out as classic gores (not
  exact developments).
* **A moved cap.** A dome or revolved shape with a cap may move it off the tip by
  `cap_shift` (m along the skin) towards `cap_direction_deg`. The cap's plane is square
  to the skin at its new centre, at the centred cap's depth; the top tier ends on the
  plane's section, and the cap piece is that section, exactly flat. The cap must still
  cover the tip (the panels must meet round it); moving it right off the tip would need
  another parameterisation of the skin and is refused with a message.
* **Developing the gores.** Top-tier gores under a moved cap are developed on the
  parallels up to their highest cap point and cut along the cap edge; their equalisation
  fits both seams and the cap edge (\( \alpha, \kappa, \gamma, \beta \), least-norm
  Gauss-Newton). A gore whose seams do not close in on each other gets a one-sided
  stretch \( \gamma \) when the shear cannot tell its two seams apart. Shapes without a
  crown layout take exactly the former path (bit-identical results).
* **Checks.** *cap seam match* (panel tops against the cap's edge) now also applies to
  domes and revolved shapes with a crown layout; *area distortion* reports the extra
  strain.
* The project format becomes version 5 (the four keys on special shapes); versions 1 to 4
  read with the seams meeting the crown as they leave the rim and centred caps. Mirror
  twins mirror the crown layout (turn and cap direction negated, widths reversed after the
  first). Shape files take the same keys. Mesh shapes and tube tip discs are not
  changed by this.

## Consequences
* Older releases cannot open version 5 project files.
* Turned seams and moved caps distort the pieces more than meridian seams (up to a few
  per cent on 8-gore shapes); the warning says so and the simulation predicts the shape
  that follows.
* A cap can be moved by less than its radius. A cap far down one side, or a pointed tip
  moved off the axis, is not supported.
