# ADR-0051: Preview special shapes while they are edited, place them when edits pause

- Status: Accepted
- Date: 2026-11-20
- Extends: ADR-0050 (real-time edits)

## Context
Placing a special shape (its skin, footprint, flattened pieces with allowances, match
marks and checks) takes 0.3–0.5 s for the fixture shapes. Every edit of a shape value
started a placement, and the views had nothing to draw until it ended, so the shape
blinked out and back. Builders asked for changes to show almost instantly, as in a game
engine's viewport.

## Decision
* **Preview first.** `envelopelab.features.primitives.preview_primitive` builds only the
  skin and footprint (96 footprint samples, no pieces, no checks; about 25–45 ms) and
  flags the result `preview`. The shape service runs previews in their own worker for
  every edit of a shape already on screen, newest edit first, and the views draw the
  newest preview as soon as it arrives.
* **Full placement after a pause.** The full placement starts when the edits of the
  shapes pause for 350 ms (`ShapeService.settle_ms`; 0 in scripted windows, where it
  starts at once) and replaces the preview.
* **Never blank, never stale data.** `ShapeService.shown` gives what to draw: the current
  placement, else the newest preview or placement (later edits win over late results).
  `ShapeService.result` stays the only source of design data: checks, pieces, markings,
  simulations and exports never see a preview. The status line says *updating…* while a
  shape is drawn from a preview.
* The envelope surface is built once per envelope (host hash) and shared by both workers.

## Consequences
* Shape edits show on the balloon within about 0.1 s; checks and pieces follow about
  0.35 s after the last change plus the placement time.
* Mesh (free-form) shapes have no preview; they update when placed, as before.
* No design data, file format or numerical result changes.
