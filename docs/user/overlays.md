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
* **Outline**: circle, ellipse, rectangle, **polygon** (type its corners about the centre
  in mm, and tick *Smooth curve* for a rounded shape) or an **imported outline** (the
  largest closed outline of a DXF or SVG file, scaled to fit the width and height).
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

## In the build pack
Each overlay gets its 1:1 template `<name>-<overlay>-overlay.pdf` (cut once, with its
colour) and every panel its outline crosses gets a marking page (`…-panel-<row>-gore-<g>.pdf`)
with the line to sew it on and the same numbered marks. The colour plan draws the
overlays over the gores and the cloth table counts them.
