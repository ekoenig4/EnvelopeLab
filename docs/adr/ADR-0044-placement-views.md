# ADR-0044: Placement views in the Special shapes mode

- Status: Accepted
- Date: 2026-11-15

## Context
A shape's position is typed as numbers (gore, tape position, fraction across, lean). The
3D View shows the result, but in another mode, so builders could not see where a shape
or a symmetry axis was while editing it.

## Decision
* Under the shape editor (a splitter shares the height), the Special shapes mode shows a
  **3D sketch** and a **gore map** side by side, both with every shape, its footprint,
  feed holes and the symmetry axes, the selected shape highlighted.
* The geometry is in the core (`envelopelab.project.placement_map`, typed and tested): the
  gore map lays the gores side by side at their true flat width with the panel's own
  across-mapping, its inverse for dragging, and a coarse sketch of the display surface.
* Both views are drawn with QPainter in the app (`envelopelab_app.placement_view`): no
  OpenGL, so they work where the 3D View is off, in tests and on remote desktops; the
  3D sketch is a depth-sorted, back-face-culled triangle drawing of a coarse grid, which
  draws in about 0.1 s.
* Clicking a shape on the map selects it; dragging moves it through the same
  `WorkspaceController.place_shape` as dragging in the 3D View (groups and mirror twins
  move along, one undo step).

## Consequences
* The sketch is coarse (4 columns per gore, 30 rings, shapes at 14 rows): it shows where
  things are, not the shape's detail, which stays in the 3D View.
* The gore map does not draw flat-chord seam bows or the gaps a footprint jumps between
  columns; it is a placement aid, not a pattern.
