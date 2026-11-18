# ADR-0050: Show where every number acts, and change numbers in real time

- Status: Accepted
- Date: 2026-11-18
- Extends: ADR-0047 (the balloon in every mode)

## Context
Many fields change the design (the Properties panel, the gore editor's locks and tables,
the rigging cards, the special shapes' layout) but nothing showed where on the balloon a
value acts: a builder had to know that "seal overlap" is the band below the top or that a
row's height moves two row seams. Values were also changed only by typing and pressing
Enter, and fast edits (holding a spin box, dragging a profile point) made the views fall
behind: the stutter harness measured gaps of 59–117 ms between frames.

## Decision
* **Hints.** Every widget that edits a design number carries a hint key (Qt property
  `designHint`): `field:<dotted path>` into the design data, `equator`, a selection key
  (`row:B`, `point:2`, `parachute`) or `shape:<field>` for the selected special shape.
  `envelopelab.project.highlight.hint_highlight` turns a key into lines on the balloon
  (pure, tested); the special-shape keys are resolved by the Special shapes panel from the
  shape's displayed seams, splits, cap and rim. One application event filter
  (`HintTracker`) follows the pointer and the keyboard focus: pointing at a field draws
  its hint in amber in every 3D view (the inlays, the Special shapes view and the 3D /
  Simulation view) and names it in the inlay caption; a focused field also turns the
  views to face it. The hint is an overlay: the balloon itself is not redrawn.
* **Live values.** The wheel and the Up/Down keys step a Properties number by one unit of
  its second significant digit (Shift ×10, Ctrl ×0.1); spin boxes and profile point drags
  apply as they move. `WorkspaceController.edit_live` keeps only the newest edit per key
  and applies it at the next turn of the event loop, so the views redraw once per frame
  however fast the value moves. Successive live edits of one key within 2 s are merged
  into one undo step (`Command.absorb`, `ProjectSession.merge_key`).
* **Keeping up.** `roll_fit` is memoised and shortlists the rotating-calipers widths
  before the exact rounded-turn check (results bit-identical); display outlines are
  thinned to 0.5 mm (Douglas–Peucker) for drawing only; the summary panels (validation,
  tree, history) refresh 150 ms after a live edit stops; the Python switch interval is
  2 ms so worker threads cannot hold the GUI thread for a whole frame.

## Consequences
* After the change the stutter harness measures p95 frame gaps of 17–30 ms and a worst
  gap under 50 ms during live edits (profile drag p95 30 ms).
* A test fails when a design number box in a mode panel has no hint; view settings (mesh
  size, the seam to face, an axis before it is added) are listed as exempt.
* Scripted windows (tests) apply live edits immediately, so a value set reads back at
  once. No design data, file format or numerical result changes.
