# Overlays (appliqués)

An **overlay** is a flat patch of cloth sewn on top of the envelope: a logo, an eye, a
star, a stripe. It can lie anywhere and across seams. EnvelopeLab draws it, cuts it and
marks where to sew it on every panel it crosses.

## Adding and editing
In **Special shapes**, choose **Add shape ▸ Overlay (appliqué)**. A 1 m circle appears on
gore 1, half way up, and the overlay editor opens:

* **Gore**, **Tape position from mouth**, **Across gore**: where its centre lies. You can
  also drag it on the gore map or in 3D, or nudge it with the arrow buttons or keys, as
  a shape.
* **Outline**: circle, ellipse, rectangle, **polygon** or an **imported outline** (the
  largest closed outline of a DXF or SVG file, scaled to fit the width and height).
  Shape a polygon in the drawing of the cut piece under the fields: **drag a corner** to
  move it (one undo step per drag; the drawing keeps its scale while you drag), **double
  click an edge** to add a corner there, **double click or right click a corner** to
  remove it (three always stay). A move that would make the outline cross itself is
  drawn red and not applied. Tick *Smooth curve* for a rounded shape through the corners;
  **Corner table (mm)** unfolds a table to type exact corner positions about the centre.
  A polygon's size is its corners, so *Width* and *Height* are greyed out.
* **Symmetry** (polygons): *1 axis* mirrors left and right, *2 axes* also up and down,
  *5 axes* makes a five-pointed star, and so on up to 8. The axes are drawn as dashed
  green lines through the centre (they turn with the overlay). You shape one slice
  between two neighbouring axes: dragging any corner moves its mirror images too, and a
  corner added or removed is added or removed in every slice (on an axis it is its own
  mirror image). Choosing a symmetry keeps the corners already in the first slice;
  *None* keeps the whole shape as plain corners.
* **Scale** dial (beside the drawing): turn it to scale the whole shape about its
  centre, ×0.5 to ×2 per turn; one turn of the dial is one undo step. A polygon's corners
  are scaled; any other outline's width and height.
* **Width**, **Height**, **Turn**: its size across and up the tape, and its turn.
* **Hem turned under**: cloth added round the outline for the hem (12 mm by default).
* **Fabric** (default: as the panel under its centre) and **Colour**.

Under the fields the cut piece is drawn: the cut line, the sew line dotted and a numbered
mark wherever it crosses a seam, with the panels it lies over. Overlays are listed with
the shapes; **Duplicate** copies one a gore further round, **Remove** removes it, and
every change is one step in **Edit ▸ Undo**.

## How well it fits
The envelope is curved both ways and a flat patch cannot follow it exactly. The editor
shows the difference between the outline on the piece and the line marked on the panels;
above 1 % of the outline it warns you (also in **Validation / Warnings**): work the ease
in between the numbered marks, or make the patch smaller. An overlay that would run past
the mouth or the crown is refused.

## Colour
Choose its colour with **Colour…**, or paint it in **Colours**: overlays are drawn over
the panels there, and a click with **Paint** colours the overlay (the fill tools paint the
panels under it, never the overlay).

## Its cutting pattern
With an overlay selected, the result tabs on the right show its pattern:

* **Cut pieces**: the piece as cut (cut line, sew line dotted), its size and area, and how
  its 1:1 page lies on the print roll (tick *Show as printed on the roll*);
* **Checks**: how well it fits the curved envelope and whether its page fits the roll;
* **Envelope panels**: every panel it crosses with the line to sew it on and the numbered
  marks; **Attachment**: the length of that line on each panel.

**Export pattern (1:1 PDF + DXF)…** writes just this overlay's pattern into a folder: its
1:1 template (print at 100 % and measure both calibration lines) and DXFs in mm of the
piece and of the line marked on each panel. The build pack has the same files.

## In the build pack
Each overlay gets its 1:1 template `<name>-<overlay>-overlay.pdf` (cut once, with its
colour) and every panel its outline crosses gets a marking page (`…-panel-<row>-gore-<g>.pdf`)
with the line to sew it on and the same numbered marks. The colour plan draws the
overlays over the gores and the cloth table counts them. The index lists every overlay
among the features, and its build order says when to cut them (**CUT OVERLAYS**) and
sew them on: an overlay inside one panel before the panels are joined (**SEW
OVERLAYS**), one that crosses seams once those seams are sewn (**SEW OVERLAYS ACROSS
SEAMS**).
