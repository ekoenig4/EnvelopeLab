# Editing designs

Every change you make — dragging a point, typing a value, placing a notch — is one command
in the undo history. Nothing is edited by hand in JSON.

## Undo, redo, history, snapshots and versions

* **Edit ▸ Undo / Redo** (Ctrl+Z / Ctrl+Y) step through the full history; the menu names
  the edit. The **History** panel lists every edit; click an entry to return to that
  state (you can redo forward again).
* **Snapshots** (History ▸ Snapshots, or Edit ▸ Take snapshot…) keep a named copy of the
  design; *Restore* is itself undoable.
* **Versions** (Edit ▸ Commit version…) give the design a new `version_id` whose parent is
  the previous one, with a message. *Check out* returns to a committed version.
* An edit that would make the design invalid (e.g. fewer than 3 gores) is refused, and the
  status bar says why; the design is unchanged.

## The standard-gore editor

* **Profile canvas**: drag a control point; the curve follows while you drag, and
  releasing the mouse makes one edit. Radii cannot become negative.
  The canvas also marks where the panels lie: a tick across the curve at every row seam,
  and the row letter beside its stretch of tape. Selecting a row in the *Panel rows*
  table highlights its stretch in orange. The marks follow the curve while you drag, as
  the fitted rows will. A green dashed line from the axis marks the **equator**, the
  widest point of the envelope, labelled with its diameter. *Live outputs* say how far
  above the mouth the equator is and how far along the tape (also as a percentage of the
  tape length).
  Dash-dot lines from the axis mark the **mouth** and the **top (parachute) hole**,
  labelled with their diameters. With a parachute, a purple dashed line marks its seated
  **edge**, the overlap down the tape from the top hole, labelled with the parachute's
  diameter; it moves when the overlap is changed in the Rigging panel. *Live outputs*
  list the mouth and top-hole diameters and the parachute diameter.
* **Control-point table**: type exact radius and height values (m). *Insert point after*
  adds a point on the curve halfway to the next one; *Delete point* removes one.
  *Set profile from file…* takes the profile of a shape file (`.yaml`) or another project
  (`.elproj`) into the open design: its control points, interpolation and segments.
  Everything else stays (rows, zones, construction, parachute and rigging). The rows are
  refitted to the new tape length, and the design's stated mouth and top-hole diameters
  follow the new profile. Locks still apply, so with *Fixed volume* the imported shape is
  scaled to keep the volume; unlock them to take the shape exactly. It is one edit, and
  *Undo* restores the previous profile.
* **Editing many points at once** (*Edit selected points*):
    * *Select* points by clicking one, Ctrl/Shift+clicking to add or remove one, dragging
      a box on empty canvas, or selecting rows in the table (the two follow each other).
      *Select all* takes every point. Selected points are orange.
    * *Drag* any selected point to move the whole selection.
    * *Soft radius* (m, along the profile) and *falloff*: neighbours within the radius
      follow a drag, scale or rotation, less the further away they are (*smooth*,
      *linear*, *sharp*, *sphere* or *constant*). Use it to push a shoulder out or pull a
      neck in without kinks. *Off* moves only the selected points.
    * *Scale* the selection about its centre (% across and up). *Rotate* it about its
      centre (degrees, counter-clockwise).
    * *Straighten* makes a straight section. The points between the first and last
      selected point go onto the line joining those two.
    * *Smooth* evens out the selected points (all points when none is selected). The
      mouth and top points stay put.
    * *Curvature comb*: red spikes show how sharply the profile bends. Wiggles, flat spots
      and kinks (one tall spike) stand out.
    * *Simplify within* a tolerance (mm) replaces all control points by as few as keep the
      profile within it. The mouth and top points stay, and the status line says how many
      points remain and the largest change. If no profile with fewer points meets the
      tolerance, nothing changes. Use it after importing or tracing a profile with many
      points.

    Each of these is one undoable edit. The constraint locks are applied to the result as
    to any profile edit, and rows stay fitted
    ([theory](../theory/profile-editing.md)).
* **Reference profiles** (below the point tools): other outlines drawn dashed over the
  profile for comparison, each in its own colour with a legend at the top left.
    * *Add from file…* reads a shape file (`.yaml`) or another project (`.elproj`).
    * *Snapshot current* keeps the profile as it is now, so later edits can be compared
      with it.
    * In the table, untick a reference to hide it or type over its name to rename it.
      *Δz* shifts it up or down (m) to line it up with the design. *Max distance* is the
      largest gap between it and the current profile.
    * *Use as profile* makes the selected reference the design's profile. Its outline is
      fitted with as few spline control points as keep it within 2 mm (a reference with
      straight sections needs many; *Set profile from file…* takes a file's profile
      exactly). It is one undoable edit.
    * *Remove* deletes the selected reference.

  A reference keeps its own copy of the outline, 401 points along the tape. It does not
  change when the design or its file changes. References are saved with the project and
  change nothing in the design.
* **Panel rows**: name, finished height along the tape (m) and fabric zone per row;
  *Split row*, *Merge with next*, and *Fit rows to meridian*. With *Keep panel rows
  fitted* (Preferences, on by default) every profile edit rescales the rows in the same
  command.
    * Type over a row's name to rename it. Its pattern marks, panel zones and turning
      vents follow.
    * Clear a row's zone to use the design's first zone. The pattern view's *Fabric zone*
      choice edits the same setting.

* **Gore construction**: *Gores cut as* chooses how the gores are cut.
    * *Lobe (straight seams)* is the default. The gore is cut wider than the
      tape-to-tape chord and bulges between the tapes, set by the gore loft below.
    * *Flat chord (bowed seams)* cuts every row as a flat trapezoid between the tapes.
      The gore is lofted lengthwise instead: its horizontal seams bow outward.

  Switching resets the loft: lobe gores lose their seam bows, and flat-chord gores get a
  default crest loft (2 % of the tape radius, tapered to zero at both ends). With
  *Fixed volume* locked, the profile is corrected to keep the volume, because a flat-chord
  gore holds less than a lobed one. *Profile between points* chooses a smooth *Spline*,
  *Straight segments* (for a measured pattern whose panel sides are straight), or
  *Segments (lines, arcs, curves)*. The locks and the row fit follow that choice.
* **Segment profiles**: with *Segments*, each control point is a joint, and the table
  gets three columns:
    * *span to next*: how the profile runs to the next point. A *line* gives a straight
      cone or cylinder section; an *arc* a circular arc; a *curve* a smooth spline.
      Consecutive curves form one smooth run.
    * *smooth joint*: ticked, the profile has no corner at the point. A ring-less point is
      smooth; a point drawn with a dark ring is a corner.
    * *arc bulge*: the arc's bulge, tan of a quarter of its angle. Positive bows outward
      going up; 0 is straight and 1 a half circle. A greyed value is set by the
      neighbouring span: an arc with a smooth start follows the span before it, and an
      arc with a corner start before a smooth line ends tangent to that line.

    At a smooth joint the more flexible span adapts: lines are fixed, an arc or curve
    takes the neighbour's tangent. A smooth joint that cannot be met, such as two lines
    at an angle, is listed as a warning with the angle of the kink.

    Switching from *Spline* or *Straight segments* to *Segments* keeps the exact shape
    (all curves, or all lines), so you can then change only the spans you want: for
    example a straight cylinder in the middle and an arc shoulder. *Insert point after*
    splits a span into two that draw the same. *Delete point* merges two spans. *Straighten*
    turns the spans it covers into lines. *Simplify* is for spline and straight-segment
    profiles only. Shape files cannot describe segment profiles yet.
* **Gore loft** (lobe gores): how far each gore bulges between its two load tapes. Each row of the
  table is a *station* along the tape (0 at the mouth, 1 at the top opening) and its
  *lobe ratio* \(k = \rho/r\), the radius of the fabric lobe over the tape radius; the
  ratio is interpolated between stations and held beyond the first and last. *Extra
  width* shows how much wider than the straight tape-to-tape chord the flat gore is.
    * \(k = 1\) (no loft, the default) is the classic small-bulge gore, \(w = \pi r/N\).
    * \(k > 1\) makes flatter lobes and narrower gores; less fabric and less volume.
    * \(k < 1\) makes fuller lobes and wider gores, down to a half circle at
      \(k = \sin(\pi/N)\), the smallest value accepted.

  *Add station* inserts one in the middle of the widest gap without changing the loft
  until you edit it; *Remove station* deletes the selected one; *Small bulge (no loft)*
  clears the table. The flat patterns, the 3D lobes, the volume, lift and mass all
  follow the loft, and the simulation sews the lofted panels. With *Fixed volume* locked,
  a loft edit also corrects the profile to keep the volume. See
  [theory](../theory/gore-geometry.md#gore-loft-lobe-bulge-between-tapes-goreloft).
* **Crest loft and seam bows** (flat-chord gores): the seams bow in one of three ways.
    * *Crest loft*: the bows are computed from a *crest fraction*, the crest offset in %
      of the tape radius, and a *taper* table of stations along the tape. Edit the
      fraction and the table; *Add station* and *Remove station* work as for the gore
      loft. The panel-row table shows the computed bows read-only, in mm.
      *Follows seam* puts a station on a row's bottom seam, for example *bottom of F*. It
      then moves with that seam when rows are resized, renamed or split, or when the
      profile changes. Typing a station number frees it again. A seam's bow comes from
      the crest offset where the tape turns near that seam (at the seam itself for
      straight tape segments). So for no loft below row F and the full loft from F up,
      set taper 0 at *bottom of E* and 1 at *bottom of F*: the E–F seam is the first to
      bow.
    * *Measured bows*: each row has its own bottom and top bow, typed in the panel-row
      table in mm, positive outward. *Freeze as measured bows* turns the crest loft's
      bows into measured ones, so you can adjust single seams; the panels do not change.
      Editing a bow keeps every other row's bow.
    * *Straight seams*: no bows. *Use crest loft* goes back to the default crest loft.

  The status line gives how much the seam bows add to the gore centreline, over the
  flat trapezoids. *Split
  row* puts a straight seam inside a row with measured bows, and *Merge with next*
  keeps the outer seams' bows. The design volume does not include the crest; see
  [theory](../theory/gore-geometry.md#flat-chord-gores-and-the-crest-loft-flat_chord_rows-crestloft).
* **Constraint locks**: *Fixed height*, *Fixed volume*, *Fixed maximum diameter*,
  *Fixed mouth diameter*, *Fixed top (parachute) hole diameter* and *Fixed N* hold the
  value the quantity had when the lock was switched on. Profile edits are corrected to
  keep every locked value (lengths within 1 mm, volume within 0.1 %); an edit that cannot
  is refused. With height, diameter *and* volume locked, the fullness of the profile
  changes, which also moves the mouth radius unless the mouth diameter is locked too.
  The mouth and top-hole locks hold the first and last control points' radii. While
  locked, that point is drawn with a dotted ring, it moves only up and down when dragged
  (also during the drag), its radius cell in the table is read-only, and it cannot be
  deleted. Typing a mouth or top-hole
  target also sets the design's stated mouth diameter, or its parachute hole and crown
  ring diameters.
  The field beside each lock shows the current value. Type a target there to lock the
  quantity at that value: the profile is solved to it in one step, keeping the other
  locks; a target that cannot be met is refused. See
  [theory](../theory/design-editing.md).

## Properties and materials

Select a section in the **Design Tree** (operating conditions, tapes, seam types,
parachute, rigging, turning vents, …) and edit its fields in **Properties**; the
parachute, red line, flying wires and turning vents are added and checked in the
**Rigging** panel ([guide](rigging.md)). Values are SI: lengths m, temperatures K (°C shown
beside), pressure Pa, masses kg.

Each field gets the editor its value needs:

* **Numbers and text** are typed. **Lists** are separated by commas (`E, F`), and
  name-to-value maps are typed as `name=value, name=value` (for example the fixed sizes
  of a scale variant).
* **Yes/no fields** are check boxes, and **fields with fixed choices** (for example a
  vent's direction or a value's source tag) are drop-down lists.
* **Optional values** have a *Clear* button. Clearing a value the design needs, such as
  a centre ring's diameter while the ring is there, is refused.
* **Optional sections**, for example the parachute's crown and centre rings, have *Add*
  and *Remove* buttons. *Add* starts from the rigging defaults.
* **Lists of entries** have *Add* and *Remove* buttons per entry. This covers turning
  vents, seam types, features, scale variants and panel zones, which give single panels
  of a row their own zone. A new entry copies the last one under a free name; a new panel
  zone takes the first free panel.

Fields that another editor owns are shown greyed out with that editor's name: the
profile, rows, gore count, construction and lofts belong to the gore editor, and the zones
to the **Materials** panel. Every change is one undoable step. A value the design schema
refuses is reported and changes nothing.

The **Materials** panel lists your fabric library with source
tags and maps each material zone to a fabric. Type over a zone's name to rename it: every
row, panel zone, parachute and scoop that uses it follows. *Add zone* refuses a name the
design already has. *Remove zone* is refused while anything uses the zone, and the message
says what does. The library is shared by all your designs:
create fabrics there once (**New fabric…**, **Duplicate…**) and use them anywhere; see
[Creating fabrics for all your designs](fabric-library.md).

## The 3D design surface

The 3D view draws the design as a solid surface, so individual gores and panels can be
picked out:

* every panel is drawn in its fabric's colour (its panel zone's, else its row's), with
  every second gore slightly darker;
* the vertical seams (load tapes) are thick dark lines, and the horizontal row seams
  thinner grey rings.

Between the tapes, each gore shows the loft you set in the gore editor, as cut:
* **Lobe gores** bulge as the lobe of their loft (a circle through the tapes without one).
* **Flat-chord gores** are the flat chord between the tapes with the crest raised by the
  crest offset, a parabola across the gore, so the horizontal seams bow outward
  mid-gore. With a crest loft the offset is \(\lambda\tau r\). With measured seam bows
  it is the offset those bows imply at each seam. With straight seams the gores are flat.
  The layer's label says which one is drawn.

How far the fabric really stands out under pressure is a result of the preview and
CalculiX solves.

Other layers:
* **Panel details:** the outlines of the panels in a panel zone, and the tape paths and
  feature locations placed in the pattern view (on every panel of the row, since a row
  is cut once per gore).
* **Special shapes**, each with its feed holes as magenta rings. They are moved onto the
  drawn surface, but are placed and simulated on the surface through the tapes.
* **Parachute and rigging:** the parachute, rigging, turning vents and scoop.

Notches, labels, grain and seam allowances belong to the cut panels and appear in the 2D
pattern view only.

## The 2D pattern view

The pattern view fills the **Patterns** mode (Ctrl+2), beside the Materials panel. It stacks the
pieces vertically in the order they are sewn up a gore: the scoop (if any) at the bottom,
the panel rows from the mouth up (e.g. the Nomex mouth row, then the nylon rows), the
parachute's radial panel on top and, above it, its circular centre panel. Each panel row is drawn as cut (dashed) and finished (solid,
filled with the zone's fabric colour) outlines with its label, grain arrow, notches, tapes
and features; the parachute and scoop panels are read-only here (edit them in the
Rigging panel and Properties).
For the selected row you can set the label, grain direction, zone, seam allowance (for all
rows or this row), add notches, tape paths across the panel and feature locations (drag a
feature to move it). *Marks on this row* lists them; *Remove selected mark* deletes one.

Patterns are drawn **as last generated**. When the design has changed since, a red
**STALE** banner says so and the panels are greyed until you press **Regenerate patterns**
(F5), or enable automatic regeneration in the preferences.

### Manual outline overrides

*Edit outline (manual override)* shows handles on the selected row's finished outline.
Moving one replaces the generated outline by yours: a **manual override**. It is

* drawn red and labelled **MANUAL OVERRIDE** in the view and the design tree;
* listed in **Validation / Warnings**, together with any seam whose two sides now differ
  by more than 3 mm (vertical seams: the row's left and right sides; horizontal seams:
  the top of one row and the bottom of the next);
* recorded in the **Provenance** log (who, when, largest vertex movement, edge lengths);
  undoing it is logged too;
* an input of the simulation: existing results become **STALE**.

If the design geometry changes after the override was drawn, Validation reports the
override as outdated. *Remove manual override* restores the generated outline.

## What an edit makes stale

| Edit | Stale afterwards |
|---|---|
| Profile, gore count, rows | patterns, assembly, rest mesh, simulations, flattening, nesting, export |
| Seam allowance | patterns, nesting, export (the rest mesh and simulations stay current) |
| Labels, notches | patterns, nesting, export |
| Grain, row zone | patterns, rest mesh, simulations, nesting, export |
| Manual outline, tape paths, feature locations | patterns, assembly, rest mesh, simulations, flattening, nesting, export |
| Operating conditions, zone fabrics, tapes | simulations (fabrics also nesting and export) |
| Values of a library fabric the design uses (edited in the Materials panel) | simulations, nesting, export (the project file is unchanged) |

Staleness compares fingerprints of the inputs, so undoing an edit makes a result current
again. The **Derived artifacts** node of the design tree shows the state of each.
