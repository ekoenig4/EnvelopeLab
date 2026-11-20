# ADR-0052: Set where special-shape panels meet as relative plan coordinates (format 6)

- Status: Accepted
- Date: 2026-11-20
- Extends: ADR-0049 (where special-shape panels meet at the crown)

## Context
ADR-0049 moves the point where a shape's panels meet (the cap's centre) by a distance
along the skin from the tip (`cap_shift`, m) towards a direction round the axis
(`cap_direction_deg`). Builders found it unclear: the row was labelled *Move the cap*, the
distance did not say where on the shape the point ends up, and a resized shape kept the
distance, so the point moved relative to the shape. They asked to set the point with
relative coordinates.

## Decision
* **Plan fractions.** A shape may give its meeting point seen from above as `cap_across`
  and `cap_up`: fractions of its widest radius across the gores (towards the next gore)
  and up the tape, each -1 to 1 with `cap_across² + cap_up² <= 1` (0, 0: the tip). When
  the shape becomes a primitive they are turned into the ADR-0049 move
  (`envelopelab.features.primitives.meeting_point_shift`: direction `atan2(across, up)`,
  distance the arc length from the tip at which the pointed meridian first reaches the
  plan radius), so the skin, pieces, checks and simulation are unchanged and shapes
  without the new keys give bit-identical results.
* **One way at a time.** A shape uses the fractions or `cap_shift`, not both (validation
  error otherwise). Older files keep `cap_shift`; the panel shows it as fractions
  (`meeting_point_plan`) and the first edit stores fractions.
* **Discoverable.** The Panel layout section's crown box is renamed *Where the panels
  meet (crown)* and starts with a top-down pad: the shape's outline, its tip and the seams
  running to the point, clicked or dragged to move it, with Across/Up boxes, *Back to the
  tip*, and the distance down the skin it means. It previews on the balloon as it moves
  (ADR-0051).
* Mirror twins negate `cap_across`. Shape files take the same keys.
* The project format becomes version 6 (two optional keys on special shapes); versions 1
  to 5 read unchanged.

## Consequences
* The meeting point stays at the same place relative to the shape when it is resized.
* Older releases cannot open version 6 project files.
* Meridians whose radius shrinks again below the tip are handled by the running maximum
  (the first point reaching each radius); the shape reports when the cap no longer
  covers the tip, as before.
