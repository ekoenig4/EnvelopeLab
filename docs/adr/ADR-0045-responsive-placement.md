# ADR-0045: A responsive On the balloon tab

- Status: Accepted
- Date: 2026-11-16
- Amends: ADR-0044 (placement views)

## Context
Builders found the Special shapes mode laggy while moving a shape or changing it, and
wanted to nudge a shape while looking at either view, and the placement tab to open by
default. Measured on the test design (four shapes, one twin): an edit held the GUI for
about 3 s; the 3D sketch took about 110 ms a frame and the gore map 30 ms.

## Decision
* **Measure first.** A heartbeat timer measures how long the event loop is blocked while
  shapes are nudged ten times, 150 ms apart; a stack sampler names what blocks it. The
  numbers below come from that harness.
* **Roll check**: the narrowest-turn search of `roll_fit` evaluates every hull direction
  in one array operation instead of a Python call per direction (same result); the
  roll findings of the envelope rows are cached by the rows' cut outlines and roll
  width, a shape's roll checks by its placed design. The envelope surface and the
  placement drawings are rebuilt only when the envelope inputs change
  (`shape_host_hash`), not on every edit of a shape.
* **Gore map**: painter paths in metres, built when the envelope, an axis or a shape's
  footprint changes, drawn through one transform with cosmetic pens.
* **3D**: with the 3D View on, a PyVista view (created the first time the tab is shown)
  that updates only the actors that changed; otherwise the QPainter sketch, which keeps
  the shaded envelope per view, draws the shapes' front faces over it, and draws only
  lines and markers while it is turned or while changes keep coming (shading follows
  200 ms after the last one).
* **Hidden result tabs** of the Special shapes panel are filled when shown (interactive
  application; scripted windows fill them at once).
* **Nudging**: ◀ ▶ ▲ ▼ with a step (10-250 mm on the flat gore,
  `envelopelab.project.placement_map.nudged`), the arrow keys in either view (Shift: five
  steps), and dragging a shape in the 3D view as well as on the map, all through
  `WorkspaceController.place_shape` (one undo step; groups and twins follow).
* **On the balloon** is the first tab and opens by default.

## Consequences
* Ten nudges: longest GUI block 3 s -> under 0.1 s with the software sketch, about 0.12-
  0.14 s with the PyVista view on software OpenGL (one frame); 95 % of event-loop gaps
  stay under 11 ms. Placing a shape still takes about 0.45 s on its worker thread (it
  does not block the GUI); the shape is drawn at its new place when that finishes.
* Pattern geometry and every numerical result are unchanged.
