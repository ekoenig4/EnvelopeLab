# Adding special shapes to a standard envelope

Start from a standard-gore design, add domes (blisters, lobes, ears), tubes (horns,
masts) and revolved shapes of any profile (noses, bulbs, onions, balls) on top of it, and
EnvelopeLab works out:

* where each shape meets the envelope (the **footprint**), as a line to mark on every
  envelope panel it crosses, in that panel's own pattern coordinates;
* numbered **match marks** on that line and on the shape's rim, so the skin goes on
  in the right place;
* the **cutting pattern** of the shape: finished and cut outlines of every gore or panel,
  and the tip disc or **cap** their tops are sewn round;
* **checks** on that pattern;
* a **simulation model** whose skin is sewn from exactly those cut pieces, so you can see
  how the shape holds under pressure before cutting cloth.

!!! danger "Design aid only"
    EnvelopeLab is not certified engineering software. Preview results are not verified,
    and a result that did not converge is not a prediction. The builder is responsible
    for airworthiness.

The shapes are part of the project: they are saved in the project file, undone and redone
with the rest of the design, and kept in snapshots and versions. Use them in the desktop
application ([below](#in-the-desktop-application)) or from Python (sections 1 to 5).

## In the desktop application

Open a standard-gore project and choose the **Special shapes** mode (**View ▸ Special
shapes**, or its tab). This mode uses the whole window: the design tree and properties
are folded away and the Validation / Warnings strip is made compact (it is never hidden);
both come back when you change mode. The screen has three columns:

* on the left, the list of special shapes with **Add shape**, **Duplicate**, **Remove**
  and the exports;
* in the middle, the selected shape's editor in tabs: **Placement & size**, **Profile**
  (revolved shapes only), **Feed holes & cap**, **Panel layout** and **Simulation**;
* on the right, in tabs: **On the balloon** (where the shapes sit, below; the tab that
  opens), **Cut pieces** (a drawing and a table), **Envelope panels** (where it is sewn
  on the envelope), **Checks** and **Attachment**.

**On the balloon.** This tab shows a 3D view over a gore map (drag the bar between them
to share the height): every shape, its footprint and feed holes, and the symmetry axes.
Each shape is drawn by its cut panels: neighbouring gores or panels in alternating fabric
shades, a flat tip disc in its own shade, and its seams and horizontal splits drawn over
them, so the panel layout can be judged on the balloon. The selected shape's panels are
tinted magenta with magenta seams; the axes are green.

Changes show at once, as in a game engine's viewport: while you type, scroll or hold a
value, every view of the balloon (this tab, the 3D views of the other modes and the 3D /
Simulation view) draws a fast preview of the shape's skin, within a tenth of a second or
so. When you stop for about a third of a second the shape is placed in full (its pieces
flattened and checked) and the preview is replaced; until then the status line says
*updating…*. The checks, cut pieces, markings, simulations and exports never use a
preview, only the full placement. A shape imported from a mesh has no preview and
updates when it is placed. The views follow every number you type
in the editor next to them, and you can move the selected shape on either:

* **Nudge**: the ◀ ▶ buttons move the selected shape round the envelope, ▲ ▼ up and down
  the tape, by the step chosen next to them (10 to 250 mm, measured on the flat gore;
  hold a button to repeat). With the 3D view or the gore map clicked, the arrow keys do
  the same, and Shift+arrow takes five steps. Every nudge is one undo step; a grouped
  shape takes its group, a mirror twin its original.
* **3D**: the envelope with its gore and row seams and the shapes as designed. With the
  3D View on (Preferences) it is drawn by the graphics card, like the 3D View; otherwise
  a lighter drawing that needs no OpenGL stands in. Drag the background to turn it, use
  the wheel to zoom; **drag a shape** over the envelope to move it there. It turns to
  face a shape when you select it, and a double click faces the selected shape again.
* **Gore map**: the gores side by side as they are cut, at their true flat width, gore
  numbers along the top and row letters down the side; hover for the gore, row and tape
  position under the pointer. **Click** a shape to select it; **drag** it to move it
  (one undo step: a grouped shape takes its group, a mirror twin its original). The
  wheel zooms; **drag empty space** (or drag with the middle or right button) to pan;
  **Fit** in the corner, or a double click, shows the whole map again.

1. **Add shape** ▸ **Dome**, **Tube** or **Revolved profile** adds a shape sized from your
   envelope on gore 1, about halfway up the tape. **Import mesh (OBJ/STL/PLY)…** adds a
   free-form shape modelled in Blender (metres, Y up for OBJ as Blender exports it; Z up
   for STL and PLY). The mesh is stored in the project, so the file is no longer needed.
2. Edit the shape. **Placement & size**: placement (gore, tape position from the
   mouth in m, position across the gore, lean and lean direction in degrees), sizes in m,
   the number of skin gores or panels, match marks per piece, seam allowance and the
   skin fabric (by default the fabric of the envelope row the shape sits on).
   **Profile**: a revolved shape's profile points (radius and height in m, base first,
   axis last). **Feed holes & cap**: an optional feed hole in the envelope under the base
   point, the cap, and *More feed holes*, extra holes inside the footprint (gore, tape
   position from the mouth in m, position across the gore, radius in m). *Add feed
   hole* puts one at the base point to edit; *Remove feed hole* deletes the selected
   one. **Cap diameter** closes the top of a shape whose
   gores or panels would otherwise meet in a point: their tops are sewn round a cap of
   that diameter instead, which is how points are made in practice. *Automatic* (the
   default) makes every gore's or panel's top at least 100 mm wide (a 20-panel shape gets
   a 637 mm cap, a 16-panel one 509 mm), but at most half the shape's base diameter;
   untick it to type a diameter, or 0 to bring the pieces to a point. Every change is one
   undo step.

   **Panel layout** decides how the skin is cut:

   * **Seam turn** (degrees) turns every seam round the shape's axis. Gore or panel 1 is
     centred this far round from the direction up the tape (0°), towards the previous
     gore at 90° (−90° towards the next gore). Use it to keep a seam off a face, a
     marking or a feed hole.
   * **Panel widths**: one relative width per gore or panel, piece 1 first (2 is twice as
     wide as 1); the second column shows the angle each piece spans. **Equal widths**
     makes them all the same again. Changing the number of gores or panels keeps the
     widths of the first ones (new ones get the last width).

     Click a row to pick that gore or panel: it is shown in amber on the balloon (this
     tab, the 3D views of the other modes), in the cut pieces (every tier of it) and in
     the **Where the panels meet** circle, so you can see which piece the numbers act
     on. Picking a row of the crown widths does the same. **Split panel in two** cuts the
     picked piece into two of half its width: the shape gets one more gore or panel,
     every other seam stays where it was (the seam turn is corrected when piece 1 is
     split, as it is centred on it) and the crown's widths are split alike. Start from
     equal panels, split the ones that are too wide for the print roll; one undo joins
     them again.
   * **Horizontal splits** cut every gore or panel across, in per cent of the profile's
     length from the base circle (0) to the tip (100). **Add split** splits the tallest
     tier in the middle; **Remove split** removes the selected one (or the top one). The
     tiers are sewn edge to edge and the pieces are named with their tier letter, `A` at
     the rim: `Ear-G3A`, `Ear-G3B`, … A split must lie above the footprint all round (a
     leaning shape's footprint climbs up one side); the shape says so if it does not.
     Splitting a large piece is the way to make it fit the print roll. Mesh shapes take
     the seam turn and widths but cannot be split across.
   * **Where the panels meet (crown)** sets where the pieces meet at the top.

     **Where the panels meet** is the point every gore runs to (the centre of the cap).
     The circle beside it is the shape seen from above, the cross its tip, with the
     seams drawn from the point to where they leave the rim. Click or drag in the circle
     to move the point, or type **Across** (towards the next gore) and **Up** (up the
     tape) as fractions of the shape's widest radius: 0, 0 is the tip, 0.5, 0 is halfway
     to the edge towards the next gore. The point keeps its place when the shape is
     resized; the line under the numbers says how far down the skin the cap's centre
     then is. **Back to the tip** (or a double click in the circle) centres it again.
     On a **mesh** shape (for example an eye pod) the seams are cut straight from the
     rim to the point, with or without a cap; the crown seam turn and widths stay as at
     the rim. A mesh shape is placed again in full on every change (about a second for
     an eye pod; it has no fast preview), so drag the point and let go, or type the
     numbers. A dome or revolved shape needs a cap (**Feed holes & cap**): the panels
     meet round the cap's edge. The cap stays a flat disc square to the skin there, the
     same depth as before; the gores on that side end lower on a slant and those
     opposite reach higher. The cap must still cover the tip, so the point moves by less
     than the cap's radius; the shape says so if it does not.

     Tick **Own crown
     layout** to give the crown its own **Crown seam turn** and **Crown widths**
     (**Equal at crown**, or **As at the rim**): the seams leave the rim where the seam
     turn and widths above put them and turn smoothly, above the footprint, to the crown
     angles, so you can, for example, keep the rim's wide face panel and still meet the
     cap with equal panels, or turn the seams off a marking near the top. Untick it to
     go back to the rim's layout. Turned seams and a moved meeting point distort the
     pieces more (see **Checks**); more gores reduce it.

   Every 1:1 sheet says what each edge is sewn to (for an upper tier, *BOTTOM: sew to
   G3A (its top)*), and the shape's assembly instructions sew each tier into a ring, then
   ring onto ring. The same keys (`seam_offset_deg`, `panel_widths`, `splits`) can be
   written in a [shape file](../formats/shape-file.md).
3. The shape is placed in the background while you keep editing; the list says
   **being placed…** until it is done (usually under a second). The right-hand column then
   shows the **Cut pieces**: a drawing of every piece, named under it (finished line
   solid, cut line dashed, the rim sewn to the envelope in red; the mouse wheel zooms,
   dragging with any button pans, **Fit** or a double click shows them all again), and a
   table of their sizes and
   areas; the **Envelope panels** the shape is sewn on; the **Checks** of the pattern;
   and the **Attachment** lines on each envelope panel.

   **How the pieces go on the print roll.** The roll has a fixed width (**Print roll
   width** in **Preferences**, default 60 in, also the starting roll width of the build
   pack) and any length. Each piece's 1:1 page (its cut line plus a 20 mm margin) is laid
   with its width across the roll: the piece is turned a quarter if its height fits
   across (as panels are cut across the bolt), else printed upright, else turned to its
   narrowest. The table's **Page on print roll** column says how much of the roll's width
   the page takes and how the piece is turned (*1324 mm across, upright (its width across
   the roll)*; hover for the length along the roll). Tick **Show as printed on the roll**
   above the drawing to see the pieces one page after another down a strip of the roll
   (the roll's width across the view, its edges in blue, the roll running down), each
   turned as it is printed. The base envelope's panels have the same view in **Patterns**
   (Layout ▸ *On the print roll*). A piece wider than the roll at any turn
   says **LARGER THAN … ROLL**, is filled amber and labelled *▲ larger than roll*, gets a
   **roll width** warning in **Checks** and is listed in **Validation / Warnings**.
   Envelope panel rows larger than the roll are listed there too. Split the piece (more
   panels, or a horizontal split) or plan to join paper.

   **Envelope panels** shows, for the selected shape only, every envelope panel it crosses
   or lies over, gore by gore (for example *GORE 3 ROW D: ear*), as on the build pack's
   marking sheets: the footprint line the shape's rim is sewn on, with short ticks on the
   shape's side; the numbered match marks, each naming the skin piece with the same
   number; and every feed hole, cut (dashed) and finished (solid), with its sizes. It opens
   zoomed on the marked area; the mouse wheel zooms, dragging with any button pans at any
   zoom, **Fit** goes back to the marked area, and a double click switches to the whole
   panels and back. Below it, each row says which of its gores are marked. Hover a
   panel for the full sewing directions. While the patterns are STALE the panels are
   greyed and the tab says so. The **Patterns** view shows only the base envelope. The **3D View** shows the shape on the
   envelope as it is sewn: each gore or panel in the colour of the skin fabric (every
   second one darker, like the envelope's gores), the seams between them and the rim
   sewn to the envelope drawn as dark lines.
4. To move a shape by hand, press **Drag in 3D view…** (or tick **Drag special shapes**
   in the 3D View). Press the left mouse button on a shape and drag it over the
   envelope: a magenta ring shows where its base will sit, and the 3D View's info line
   gives the gore, the tape position from the mouth and the position across the gore.
   Release to place it there; the shape is placed again in the background and the move
   is one undo step (**Edit ▸ Undo** moves it back). The lean set in the form is kept.
   Pressing anywhere else still turns the view. The ring is an approximate preview (a
   circle of the base radius, without the lean); the real footprint, pattern and checks
   come when the shape is placed.
5. Every placed shape that has a feed hole is **simulated with the envelope**: **Run
   Preview** and **Run CalculiX** solve the envelope and then each shape with the same
   solver, its skin sewn from the cut pieces and inflated, at an element size of about
   1/40 of the footprint length (100 to 300 mm; see
   [Running simulations](running-simulations.md)). On the **Simulation** tab,
   **Simulate shape (preview solver)**
   solves the selected shape on its own, with the element size you choose (finer is
   slower). **Cancel** stops it. The result lists the
   convergence status, iterations, final residual, mesh size, heights above the envelope
   as designed and inflated, chamber pressure, wrinkled fraction, rim tape tension and
   the factor of safety of each region. The 3D View then draws the shape **as sewn and
   inflated**: the skin sewn from its cut pieces, as the solver left it, with the same
   colours and seams. While that result is current the designed shape is hidden; tick
   its layer in the layer list to compare the two (your choice is kept). A result that
   did not converge says **NOT CONVERGED** in its label, and a **STALE** one is drawn grey.
6. **Export build pack…** (also **File ▸ Export build pack…**, [guide](build-pack.md)) writes the envelope rows, the parachute (radial panel and
   centre panel) and every shape's pieces and marking sheets (DXF, PDF and `index.json`,
   section 4). **Export to Blender (OBJ)…** writes the
   envelope, every shape and every current shape simulation (section 5).
7. **Groups: several shapes as one object.** A head with ears and a nose is several
   shapes; give them the same **Group** (in **Placement & size**, type a name or pick
   one; clear it to take a shape out). The list shows grouped shapes as
   *Head ▸ Ear (Dome)*. Every shape keeps its own pieces, checks and simulation; the
   group moves and mirrors them together, each in one undo step:
   * **Move group…** turns every member round the envelope (in gores) and moves it up or
     down the tape (in m), feed holes with it. A turn keeps the shapes exactly; a move
     along the tape keeps each shape, but the gores narrow towards the mouth and the
     crown, so the members end up a little closer or further apart. Dragging a grouped
     shape in the 3D view moves its whole group.
   * **Mirror group…** adds a linked mirror twin of every member across a symmetry axis,
     placed or chosen as in step 8 with every member's mirror image shown while you
     decide; shapes standing on the axis itself are left out.
   * **Export group to Blender…** writes the envelope and that group's shapes only. The
     build pack lists the groups in its `index.json`, and every skin sheet names its object.
8. **Symmetry: axes and mirror twins.** A face's left and right ears are one shape and
   its mirror image. Name the plane they are mirrored in once, then let EnvelopeLab keep
   the two sides symmetric:
   * **Placing an axis, seen as you go.** **Add axis…** (under the shape list) opens a
     green-framed bar on the **On the balloon** tab. Move the pointer over the gore map or
     the 3D view: a dotted green line shows where the axis would go, snapped to the
     nearest gore centreline or seam (untick *Snap* to place it anywhere). **Click** to put
     it there (or drag along, or type the gore line: 6 = the centreline of gore 6, 6.5 =
     the seam between gores 6 and 7): it is drawn dashed, and the bar says where it lies
     (*centre of gore 6*, *seam 6|7*). A dashed magenta outline shows where the selected
     shape's mirror image would land. Name it and press **Place axis** (Escape or
     **Cancel** leaves everything as it was).
   * The list under the shapes shows each axis and how many twins use it; **Edit…** (or
     a double click) moves or renames it the same way, with its twins' new places shown
     dashed as it moves. You can also **drag an axis on the gore map**: its twins follow
     when you let go (one undo step). **Remove** deletes an axis no twin uses. The 3D View
     draws every axis as a green line from the mouth to the crown (layer *Symmetry axes*).
   * **Mirror…** adds the selected shape's **mirror twin**: the same bar opens, and as you
     move the pointer the dashed magenta outline shows where the mirror image would land
     for an axis there. Click to place a new axis, or choose an existing one in the bar
     (*Across Face centre*), and press **Mirror across it**: `Ear mirror` is added,
     mirrored in everything: position, lean direction, feed holes, seam turn, panel
     widths, a mesh's geometry, every size, and its group.
   * The twin stays linked: **edit or drag either side and the other follows** as its
     mirror image (one undo step). Moving an axis moves its twins; moving a group carries
     the axes of the twins in it. The list marks linked shapes with ⇄ (*Ear mirror (Dome)
     ⇄ mirror of Ear*), and the selected shape says what it mirrors or is mirrored by.
   * **Unlink** makes a twin an ordinary shape again (it keeps its geometry). Removing the
     original leaves its twin as an ordinary shape. A shape standing on an axis is its
     own mirror image and cannot be mirrored across it.

Nothing is hidden. A shape that cannot be placed (for example a base too large for the
local curvature), a failed check, a simulation that did NOT converge, a factor of safety
below 5, and a simulation that is **STALE** because the shape or the envelope changed
after it ran are shown in red in the panel and listed in **Validation / Warnings**.
Selecting such a warning opens the shape. The build pack is not written while a shape
is being placed or cannot be placed, so a pack never leaves a shape out without saying
so. Shape simulations are saved with the project (the latest one of every shape) and
shown again when it is reopened, still marked STALE if the shape or the envelope changed.

## 1. Place a shape

```python
from envelopelab.features.primitives import (
    Dome,
    Tube,
    Placement,
    EnvelopeSurface,
    design_primitive,
)

surface = EnvelopeSurface.from_design(design)  # your standard-gore design

ear = Dome(
    "ear",
    Placement(gore=3, tape_position=12.0),  # gore 3, 12 m up the tape from the mouth
    base_radius=1.0,
    height=1.2,  # m
    gores=16,  # skin gores
)
horn = Tube(
    "horn",
    Placement(
        gore=6,
        tape_position=10.0,
        across=0.5,  # on the load tape of gores 6/7
        lean_deg=30,
        lean_toward_deg=0,
    ),  # leaning 30° towards the crown
    base_radius=0.8,
    tip_radius=0.3,
    length=2.5,  # m
    panels=4,
)
d = design_primitive(ear, surface, seam_allowance=0.0125, feed_hole_radius=0.3)
```

**Any profile.** A `Revolved` shape spins a profile you give as `(rho, zeta)` points
about its axis. `rho` is the distance from the axis and `zeta` the height above the base
circle, both in metres, from the base circle (`zeta` = 0) to the tip. End on the axis
(`rho` = 0) for a point, or anywhere else for a flat tip disc:

```python
from envelopelab.features.primitives import Revolved

onion = Revolved(
    "onion",
    Placement(gore=9, tape_position=11.0),
    profile=((0.4, 0.0), (0.9, 0.5), (0.8, 1.0), (0.3, 1.5), (0.0, 1.9)),
    gores=12,
)
```

The points are joined by a smooth curve (`smooth=False` for straight segments). A single
straight segment is a frustum and is unrolled exactly like a tube.

**Placement.** Gores are numbered from 1. `across` is the fraction of the gore width from
its centreline (−0.5 and +0.5 are the load tapes either side). `tape_position` is measured
along the load tape from the mouth, in metres. The lean tilts the shape's axis away from
the envelope normal: `lean_toward_deg` 0 leans it up towards the crown, 90 towards the
next gore and 180 down towards the mouth.

**Shapes from Blender.** Model anything else (an ear, a curved horn, a face) in Blender
and bring it in as a `FreeformShape`:

* model it in metres around the origin, with **Z out of the envelope** (the shape's
  axis), **X up the balloon** towards the crown, and the origin where the axis meets the
  envelope;
* make it a closed surface and **sink its base a little below Z = 0**, as you would for a
  boolean union with the balloon. EnvelopeLab cuts away everything inside the envelope,
  and the cut edge becomes the footprint;
* the axis must leave the shape through its top. The panels are cut along half-planes
  through the axis, like gores, and meet there;
* export it with **File ▸ Export ▸ Wavefront (.obj)** using the default settings (or STL).

```python
from envelopelab.features.primitives import FreeformShape
from envelopelab.io.blender import read_shape_mesh

ear = FreeformShape(
    "ear",
    Placement(gore=4, tape_position=13.0, lean_deg=15),
    read_shape_mesh("ear.obj"),  # Blender's default OBJ axes, metres
    panels=12,
)
d = design_primitive(ear, surface, feed_hole_radius=0.3)
```

Each panel is flattened so that its footprint edge and both seam edges keep their exact
lengths. Then both sides of every seam match and the rim matches the footprint. The
flattening strain of a curved panel goes into its interior, and the *area distortion*
and *edge strain* checks report it: use more panels until they pass.

## 2. Read the result

```python
for c in d.checks:
    print(c.severity, c.name, c.value, c.message)

for line in d.attachment:  # footprint on each host panel
    print(line.gore, line.row, line.points)  # m, panel pattern coordinates

for m in d.marks:  # match marks
    print(m.number, m.gore, m.row, m.host_xy, m.piece, m.piece_xy)

for p in d.pieces:  # cutting pattern
    print(p.label, p.size, p.cut_count)  # finished width, height (m)
    p.finished, p.cut  # outlines, m

summary = d.as_dict()  # JSON-ready, units in the keys
```

Panel pattern coordinates are the same as the 2D pattern view: `x` across the panel from
the gore centreline, `y` up from the finished bottom seam line of the row. Mark 1 is at
the top of the shape (towards the crown) and the numbers run round it. Every mark has a
partner on a skin piece's rim edge (`piece`, `piece_xy`).

**What the checks mean**

* *rim length*, *skin seam match*: the skin's rim must equal the footprint, and the two
  sides of every skin seam must be the same length (within 3 mm). Tube panels are exact
  developments, and dome gores are laid out so both sides of each seam have the seam's
  true length.
* *attachment ease*: the skin's rim is sewn to the line marked on the **flat** envelope
  panels, which is a little longer or shorter than the rim (the flat gore includes the
  bulge of the lobe). The difference is worked in between match marks. The marks on the
  envelope panels are placed so that they divide the marked line in the same proportions
  as the rim marks divide the rim, so every interval eases the same small fraction of
  its length (they are therefore not exactly at the rim marks' angles round the shape).
  The check gives the largest difference between two neighbouring marks and the total.
  Above 3 mm it is an error: add match marks (*marks per piece*), use more envelope
  gores, or a smaller shape.
* *area distortion*: a dome's gores cannot be flattened without changing their area.
  Above 1 % the check warns. Use more gores: the distortion drops about four times when
  you double them (3.7 % at 8, 0.9 % at 16, 0.2 % at 32 gores for a hemisphere).
* *host panels*: the gores and rows the footprint crosses. Mark it on all of them.
* *feed hole inside footprint*: every hole cut in the envelope to inflate the shape must
  lie inside the footprint. Besides the hole under the base point, a shape can have extra
  holes anywhere under it (`feed_holes`; in a shape file, placed by gore and row). The
  build pack draws each on the panel it is cut in, and adds a marking sheet for a panel
  that only has a hole.
* *feed hole clear of seams*: a hole's finished edge must stay clear of every seam of the
  panel it is cut in, by the width of the hole tape (the hem band) plus the seam
  allowance (the fell): 76 mm for a 25 mm tape and 2 in seams. A hole too close is an
  error. **Move feed holes clear of seams** (under *More feed holes*) moves every extra
  hole that is too close the least distance, inside its panel and the footprint, in one
  undo step, and says what it moved. The hole under the base point moves with the shape,
  so it is only reported: move the shape or make the hole smaller.

A shape is rejected if it does not fit: a base too large for the local envelope
curvature, a lean that brings the skin back onto the envelope, or a footprint that would
reach the mouth or the crown.

## 3. See how it holds its shape

```python
from envelopelab.features.builder import build_appendage
from envelopelab.features.metrics import appendage_metrics
from envelopelab.features.primitives import primitive_appendage
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions
from envelopelab.solvers.simulation import from_preview

spec = primitive_appendage(d, mesh_size=0.2, load_tape=tape, rim_tape=tape, hem_tape=tape)
cond = OperatingConditions.hot_air(373.15, mouth_height=0.0, self_weight=False)
am = build_appendage(spec, cond, {"host": envelope_fabric, "skin": skin_fabric})
result = from_preview(am.model, solve(am.model))
metrics = appendage_metrics(am, result)
print(result.status, metrics.projected_height, spec.intended["projected_height_m"])
print(metrics.fos, metrics.skin_wrinkled_fraction)
```

The skin is sewn from the cut pieces exactly as patterned, and the shape is filled
through its feed hole. The result shows:

* **projected height** against the designed height: how well the sewn shape keeps the
  shape you designed;
* **factors of safety** of the skin, the envelope under the shape and around it;
* **wrinkled skin**: where the cloth carries tension in one direction only. At envelope
  pressures any pattern that differs from the designed shape by more than about 0.01 %
  shows some, so read it as an indicator that depends on the mesh, not as a count of
  visible wrinkles;
* the load in the envelope's tapes near the shape.

Check `result.converged` before reading anything. A result that did not converge is not
a prediction. The same model can be verified with CalculiX (`calculix_adapter.run_calculix`)
or run through the [Reality Check report](reality-check-report.md) workflow.

## 4. Export the cutting patterns

```python
from envelopelab.export.build_pack import export_build_pack
from envelopelab.export.qa import check_pack

export_build_pack(
    design,
    [d],  # the envelope and its placed shapes
    "build-pack/",
    skin_fabric={"ear": "ripstop red"},  # per shape, or one name for all
    roll_width=60 * 0.0254,  # m (60 in roll)
)
assert check_pack("build-pack/") == []  # the output QA, from the files alone
```

The pack contains:

* one DXF per piece, in millimetres: the envelope's row panels (cut once per gore) and
  every gore, panel and tip disc of each shape;
* a **marking sheet** for each envelope panel a shape crosses or lies over: the panel
  with the footprint line the shape's rim is sewn on (short ticks point into the shape),
  the numbered match marks, each naming the skin piece with the same number (`55 (P15)`),
  and every feed hole drawn twice, as cut and as finished, with its sizes and the hem
  (by default a double fold over the hole tape). Mark them on the cut panels before
  sewing the envelope. Each envelope row sheet lists which of its gores have a marking
  sheet or a feed hole, so none is missed when the copies of the row are cut;
* on every skin piece, what each edge is sewn to: the rim to the envelope (with its mark
  numbers and the panels they lie on), each seam to the neighbouring piece, the top to
  the tip disc (cap) or the apex. The tip disc has a tick on its edge where every seam
  meets it, and each piece's name between the two ticks its top is sewn between;
* the 1:1 templates: the envelope rows (a row that carries a shape on its own sheet, with
  every gore's marks over the one panel, labelled by gore) and each shape's skin pieces
  (`<name>-<shape>-<piece>.pdf`, one PDF per piece), each page showing the whole piece
  with one side within your fabric roll;
* `cad/`: one DXF per sheet and `index.json`, with every file, piece, cut count, fabric,
  finished size, and which edges are sewn together.

Before cutting, **measure both calibration lines** on every printed or plotted sheet. Each
must measure what its label says (for example 500 mm with ticks every 100 mm). If it
doesn't, the sheet was scaled when it was printed. The layers and the index are described in
[Build pack](../formats/build-pack.md).

## 5. Look at it in Blender

```python
from envelopelab.features.scene import export_scene

export_scene(
    "balloon.obj",
    surface,
    designs=[d],  # shapes as designed
    solved=[(d, am, result)],  # and as simulated (from step 3)
)
```

In Blender use **File ▸ Import ▸ Wavefront (.obj)** with the default settings. The file is
written with Y up, which is what Blender's importer expects, so the balloon stands
upright, in metres. Each part is a separate object: `envelope`, `<name>_designed` and
`<name>_simulated`. A simulation that did not converge is named
`<name>_simulated_UNCONVERGED`: it is not a prediction. For STL use
`envelopelab.io.blender.write_stl_object`; STL files are written Z up, Blender's STL
default.

## Limitations

* Revolved shapes are symmetric about their axis. Use a Blender mesh for anything
  else.
* A free-form shape's axis must leave the mesh through its top, and each panel must be
  a single piece. A strongly curved horn may need a leaned placement, or more panels.
* A free-form shape rests in its flattened panels exactly as the mesh describes it. Use
  a mesh fine enough to follow the curved surface (the solver does not correct a coarse
  mesh's flat facets).
* The envelope is the surface of revolution through the load tapes. The lobe bulge
  between tapes is not included when placing the footprint, and marks across a lofted
  gore are placed in proportion to its flat width.
* Seam allowances, stitching and tape widths are not part of the simulation model.
* A cap is cut flat, so it flattens the top of a curved shape: by up to the height the
  cap takes off (a dome's apex) or the cap's rise on a mesh's top, less what the cloth
  stretches. The cloth round its edge wrinkles, and the preview solver may need more
  iterations there, or not converge for a large cap. A smaller cap, more pieces or a
  different element size can help; an unconverged result is never a prediction.
* In the desktop application, shape simulations use the preview solver with assumed
  stiffness values, and those solved with the envelope use an automatic element size
  (footprint length / 40, between 100 and 300 mm, assumed; ADR-0034). At that size the
  shape and its volume are settled to a fraction of a per cent, but peak values (the
  largest tape tension or fabric resultant, and the factors of safety from them) still
  change with the mesh; every result says so. Solve with a chosen, finer size, or compare
  two sizes, before relying on a peak value.
