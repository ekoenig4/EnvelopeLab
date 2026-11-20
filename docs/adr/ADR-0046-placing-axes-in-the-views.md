# ADR-0046: Placing symmetry axes in the placement views

- Status: Accepted
- Date: 2026-11-16
- Amends: ADR-0043 (how an axis is placed), ADR-0044 (placement views)

## Context
A symmetry axis was placed by typing a gore number in a dialog, which showed only where
it lies in words. Builders could not see where the axis would go, or where a mirror image
would land, while deciding.

## Decision
* Adding, moving and mirroring across an axis open an **axis bar** on the On the balloon
  tab (no dialog). While it is open the pointer places the axis in the gore map and in
  the 3D view (both 3D views): the axis under the pointer is drawn dotted, a click or a
  drag chooses it (drawn dashed), typing the gore line does the same; positions snap to
  gore centrelines and seams (half gore widths, `placement_map.snap`) unless unticked.
* The **mirror images** the axis would make are drawn dashed while deciding: the selected
  shape's (adding an axis, Mirror…), the group's (Mirror group…), the twins' new places
  (moving an axis). They are the footprints mirrored on the map
  (`placement_map.mirrored_lines`, \( g' = 2g_m - g \)) and in 3D
  (`placement_map.reflect`, reflection in the meridian plane), at the chosen axis, or at
  the one under the pointer until one is chosen.
* Mirror… and Mirror group… offer the existing axes in the bar; choosing one fixes the
  line. Place/Mirror commits in one edit (a new axis and its twins: two undo steps);
  Cancel or Escape changes nothing.
* An axis on the gore map can be dragged directly; the move is committed on release
  (one undo step; its twins follow, ADR-0043).

## Consequences
* The axis bar shows the gore line both ways (number and *centre of gore 6*), so typing
  stays available for exact values.
* The 3D mirror preview reflects the footprint drawn on the display surface; lobed gores
  are symmetric about their centrelines and seams, so with snapping it lies on the
  envelope; off those lines it is a close approximation (the placed twin is exact).
