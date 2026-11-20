# ADR-0055: Panel colours as a visual layer (project format 8)

- Status: Accepted
- Date: 2026-11-20

## Context
Builders choose the colour of every panel (the envelope's gores and rows, and the
pieces of special shapes) before they order cloth, and want to try colour schemes the
way they would in an office or image-editing program. EnvelopeLab had no place to keep
those choices. Fabrics in the library already carry a colour, and panels take their
fabric from material zones (rows, `panel_zones`), but a fabric is an engineering choice:
it sets mass, strength and the cut lists, and changing it makes patterns and simulations
stale. Painting must not do that.

## Decision
* Panel colours are a **visual layer**, separate from fabrics and zones:
  `DesignState.colours` (`envelopelab.project.colours.PanelColours`) holds sRGB
  `#rrggbb` colours by envelope row letter and gore number (from 1), and by special-shape
  name, tier letter (`A` at the rim, or `cap`) and piece number (from 1). Uncoloured
  panels are left out. On a half-gore row (ADR-0048) each half may have its own colour
  (`halves`: row, gore, `left` or `right`), over the panel's; `left` is the half towards
  the previous gore, which is the same half on the cut half panels (cut down x = 0), the
  gore map and the 3D views (by the triangle's azimuth within its gore). Painting a whole
  panel resets its halves; half colours are drawn and exported only on rows cut as half
  gores, and dropped at the next colour edit from a row that is not.
* **Project format 8** writes `state.colours` (snapshots and versions too) only when
  some panel is coloured; versions 1 to 7 read as uncoloured. Older releases cannot open
  format 8 files.
* `colours` is an input group read by **no artifact**, and it is optional (left out of
  the hashes while empty): painting marks the design unsaved but never makes patterns,
  the rest mesh, simulations, shapes or exports stale, and existing projects keep their
  fingerprints.
* Edits: `paint_panels`, `replace_colour` and `clear_colours` (`envelopelab.project.
  edits`), one undo step each through `ProjectSession.edit_colours`. Colours follow a
  renamed row or shape. Colours of panels that left the design (a removed row, fewer
  gores, a deleted shape) are kept until the next colour edit drops them (`pruned`), so
  undoing such a change brings its colours back.
* A new **Colours** mode (after 3D / Simulation): the panel grid (the gore map cut at the
  row seams, each shape as a schematic grid of pieces and tiers with its cap on top) and
  a picker in the style of office suites: theme colours with tints and shades, standard
  colours, recent colours (application settings), the colours in the design (right click
  to replace one everywhere), a hex code field, No colour and More colours (the Qt colour
  dialog with its own screen eyedropper). Tools: Paint (click or drag), Fill row, Fill
  gore, Eyedropper, Repeat every N gores, Fill everything, Clear all.
* **The 3D views draw the colours** (Show on the 3D views, on by default): the balloon
  beside the grid, the inlays of the Shape, Patterns and Rigging modes, On the balloon,
  and the 3D / Simulation design surface and shape layers. A coloured panel takes its
  colour; an uncoloured one keeps the fabric or default shades, and the shape piece being
  edited stays amber. To colour by panel, the envelope sketch (`placement_map.Sketch`)
  gives every triangle its gore and row (the row seams are now rings of its grid), and a
  shape's display (`scene.ShapeDisplay.tier`) every triangle its tier, by the meridian
  position of its centre (display only: a triangle across a split takes its centre's
  tier). Result fields (stress, factor of safety) still replace the colours when shown.

* **The build pack carries the colours** (`export_build_pack(colours=...)`):
  every envelope row sheet (and each half of a half-gore row) gets the pieces to cut in
  each colour with their gores, every skin piece its colour (by tier and piece number; a
  tip or cap is piece 1), printed under the header of the DXF and on the 1:1 template
  (a swatch per colour; a gore's marking page names its one panel's colour) from the
  same data as `cad/index.json` `colours`. The output QA checks that the counts add up to
  the cut count and that the DXF and every page print the line generated from the index.
  The planning documents add a colour plan PDF and a cloth-per-colour CSV, and the 3D
  view draws the colours. A design without colours exports exactly as before (no
  `colours` keys, no colour documents), so the pack format stays
  `envelopelab-build-pack/4` (the keys are optional additions).

## Consequences
* The colours do not choose fabrics: a builder still sets each panel's fabric through
  zones (the cut list stays by fabric; the cloth per colour is a separate table).
* Solved shapes (shape simulations) have no tiers: a split shape's solved skin takes the
  colours of its first tier.
* Shape grids are schematic (pieces as equal-height columns at their relative widths);
  they show which piece is which, not its cut outline.
* Mirror twins (ADR-0043) are coloured on their own, not mirrored from their source.
