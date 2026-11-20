# ADR-0047: The balloon in 3D in every design mode, the selection highlighted

- Status: Accepted
- Date: 2026-11-16
- Extends: ADR-0044 (placement views), ADR-0045 (responsive placement)

## Context
Only the Special shapes mode showed where things are on the balloon (its On the balloon
tab), and only the 3D / Simulation mode turned and highlighted things in 3D. Selecting a
panel row, a profile control point or a rigging component in the other modes showed it
in 2D only, and the 3D / Simulation mode could drag a special shape but not nudge it,
face it or show what was selected. Builders asked for the same tools in every mode.

## Decision
* One display function, `envelopelab.project.highlight.selection_highlight`, turns the
  workspace selection into 3D polylines on the display surface and a point to face:
  a row's band and one of its panels, a control point's ring, the profile's seam
  meridian, a rigging component's lines, the scoop's mouth arc. Pure, typed and tested
  (`tests/unit/test_highlight.py`); display only.
* A shared widget, `EnvelopeInlay`, draws the balloon as the On the balloon tab does
  (the same `BalloonSketch`, or `BalloonGpuView` on the graphics card when the 3D View is
  on, started when first shown; refreshed only while visible) with the selection in the
  highlight colour, turned to face it when the selection changes (double click: face it
  again). It is placed beside the editor of the Shape mode (under the profile; a point
  picked on the profile wins), the Patterns mode (beside the row form; the selected row)
  and the Rigging mode (beside the cards, every rigging line grey; clicking a card or
  editing one of its values selects that component). The special shapes and symmetry
  axes are drawn in it, not moved.
* The envelope sketch, shapes and axes come from the Special shapes panel's cached
  `placement_data`, published as `WorkspaceController.placement_provider`, so the inlays
  share its caches instead of rebuilding them.
* The 3D / Simulation mode gets a selection row: the selection's name, **Face
  selection**, the nudge arrows and step of On the balloon (for a selected special
  shape), and **Symmetry axis…**, which opens the live axis placement of ADR-0046 rather
  than duplicating its bar. The selection is highlighted in the 3D view (kept when the
  scene is rebuilt) and the view turns to a new selection. Pressing a shape with Drag
  selects it (the camera stays). Selecting a shape while in this mode no longer switches
  to the Special shapes mode.

## Consequences
* The same selection looks and behaves alike in every mode; new kinds of selection are
  added in one place (`selection_highlight`).
* Each inlay costs one coarse envelope sketch draw (shared, cached by the envelope
  inputs' hash) and is deferred while hidden; on the graphics card each inlay is one
  more OpenGL view, created only when it is first shown.
* Axis placement stays in the Special shapes mode's On the balloon tab (its bar holds
  the name, snap and target choices); the 3D / Simulation mode opens it there.
