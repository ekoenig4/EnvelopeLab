# ADR-0039: Marked panel sheets, picture assembly instructions, a 3D page per shape

- Status: Accepted
- Date: 2026-11-04
- Amends: ADR-0038 (row sheets are now clean; marked panels have their own sheets)

## Context
The builder exported the pack of their own special-shape design and listed what a pack
must hold: (1) a PDF per base-envelope panel; (2) a PDF per special-shape panel; (3) a
PDF per base panel with the lines drawn on where feed holes and appendages are sewn;
(4) diagrams of the build steps for each section, for the base envelope and for each
special shape, like flat-pack furniture instructions; (5) 3D views of every shape of the
design showing the metrics measured in the simulations. Their export also failed for
shape names with spaces, and its 3D page showed the design only because the hidden 3D
view was never brought up to date before the export.

## Decision
- `<slug>-panel-<R>.pdf` is the clean panel. Each envelope panel that carries a shape's
  footprint or a feed hole gets `<slug>-panel-<R>-gore-<g>.pdf`: the same panel with that
  panel's footprint lines, side ticks, numbered marks and feed holes (every shape's marks
  on that panel), marked *mark only*.
- `<slug>-assembly-envelope.pdf` and `<slug>-assembly-<shape>.pdf`
  (`envelopelab.export.assembly`): numbered picture frames drawn from the pack's own
  pieces, with few words: parts with counts, marking, building a gore bottom-up, joining
  gores, mouth and crown, parachute, where each shape goes, rigging, inspection; and for
  each shape its parts, marking, side seams in order, tip, feed holes, the rim onto the
  marked line with the numbered marks, the finished shape.
- `<slug>-<shape>-3d.html` per special shape: the shape as designed and, when it has a
  simulation, as inflated with every metric the application shows for it and that
  simulation's banner (stale, not converged, failing, preview only); "Not simulated"
  otherwise. The envelope page stays `<slug>-3d.html`.
- Template page records are kept as data (sheet names are free text); the export always
  refreshes the 3D view first.

## Consequences
- The QA counts one page per piece plus one per marked panel; a marked panel's sheet may
  repeat its row (with markings), every marking sheet is drawn on one.
- Metrics need current simulations: an export made after the design changed shows the
  results grey and says they are stale; re-run the preview and the shape simulations
  first.
