# ADR-0054: Shape a special shape's crown cap with an outline (format 7)

- Status: Accepted
- Date: 2026-11-20
- Extends: ADR-0049 (crown layout), ADR-0052 and ADR-0053 (where the panels meet)

## Context
A special shape's gores or panels meet round a cap at the crown. The cap was always a
circle (its diameter), flat for domes and revolved shapes, cut by a cylinder for meshes.
Builders want other caps: the shape of the footprint repeated small at the top, an
ellipse, a polygon, or an outline drawn in a CAD or drawing program.

## Decision
* **Outlines.** `envelopelab.features.crown` turns a `CrownShape` into one closed polygon
  seen from above, round the point where the panels meet (plan coordinates across towards
  the next gore and up the tape): the footprint or an imported outline centred on its area
  centroid and scaled to the cap diameter as its widest width (turned), an ellipse (width,
  length, turn) or a polygon through corners (straight, or a closed centripetal
  Catmull-Rom curve). It must be star-shaped from the meeting point; its radius in every
  direction is the exact ray-edge intersection.
* **Cut, not reshaped.** The cap is the skin inside the outline's prism along the shape's
  axis. The designed skin is unchanged: on a dome or revolved shape each meridian ends
  where it leaves the prism (bisection to `ROOT_TOLERANCE`); the patch above is meshed and
  flattened like a mesh cap (LSCM, ARAP, true-length edge), so the cap's edge keeps the
  gores' top lengths (cap seam match). Mesh shapes cut their cap with the prism instead of
  a cylinder. The sub-model sews the flattened cap to the gores, each node starting where
  it was cut from the skin. A circle stays the flat disc of ADR-0049 (bit-identical).
* **Files.** `envelopelab.io.outline_file` reads the largest closed outline of a DXF
  (ezdxf, already a dependency) or SVG (read here; elliptical arcs and transforms are not
  read). The points are kept in the project, so the file is not needed afterwards.
* **Data.** Special shapes take `crown_shape` (`kind`, `width`, `length`, `turn_deg`,
  `points`, `smooth`, `source`); mirror twins mirror it. Project format 7; versions 1 to 6
  read unchanged. Shape files take `crown_shape` with lengths in units or an outline
  `file`. Tubes keep their round tip disc.
* **UI.** *Cap shape* under *Where the panels meet*: kind, turn, an ellipse's size, a
  polygon's corner table (add, remove, smooth), or *Import outline*; the pad draws the cap.

## Consequences
* A cap cut from a strongly curved top is doubly curved: flattened with its edge at true
  length its area is smaller than designed (7 % for a 30-degree spherical cap), which the
  *area distortion* check reports as a warning. A circle's flat disc does not show this.
* An outline that reaches the footprint, does not cover the tip or is not star-shaped
  from the meeting point is refused with the reason.
* Older releases cannot open format 7 project files.
