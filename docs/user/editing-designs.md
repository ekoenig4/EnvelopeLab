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
* **Control-point table**: type exact radius and height values (m). *Insert point after*
  adds a point on the curve halfway to the next one; *Delete point* removes one.
* **Panel rows**: finished height along the tape (m) and fabric zone per row; *Split row*,
  *Merge with next*, and *Fit rows to meridian*. With *Keep panel rows fitted*
  (Preferences, on by default) every profile edit rescales the rows in the same command.
* **Constraint locks**: *Fixed height*, *Fixed volume*, *Fixed maximum diameter* and
  *Fixed N* hold the value the quantity had when the lock was switched on. Profile edits
  are corrected to keep every locked value (lengths within 1 mm, volume within 0.1 %); an
  edit that cannot is refused. With height, diameter *and* volume locked, the fullness of
  the profile changes, which also moves the mouth radius. See
  [theory](../theory/design-editing.md).

## Properties and materials

Select a section in the **Design Tree** (operating conditions, tapes, seam types,
parachute, rigging, turning vents, …) and edit its fields in **Properties**; the
parachute, red line, flying wires and turning vents are added and checked in the
**Rigging** panel ([guide](rigging.md)). Values are SI: lengths m, temperatures K (°C shown
beside), pressure Pa, masses kg. The **Materials** panel lists your fabric library with source
tags and maps each material zone to a fabric. The library is shared by all your designs:
create fabrics there once (**New fabric…**, **Duplicate…**) and use them anywhere; see
[Creating fabrics for all your designs](fabric-library.md).

## The 3D design surface

The 3D view draws the design as a solid surface: each panel row in its fabric's colour,
every second gore slightly darker, the vertical seams (load tapes) as thick dark lines and
the horizontal row seams as thinner grey rings, so individual gores and panels can be
picked out. The parachute, rigging and scoop are a separate layer.

## The 2D pattern view

The pattern view fills the **Patterns** mode (Ctrl+2), beside the Materials panel. It stacks the
pieces vertically in the order they are sewn up a gore: the scoop (if any) at the bottom,
the panel rows from the mouth up (e.g. the Nomex mouth row, then the nylon rows), and the
parachute panel on top. Each panel row is drawn as cut (dashed) and finished (solid,
filled with the zone's fabric colour) outlines with its label, grain arrow, notches, tapes
and features; the parachute and scoop panels are read-only here (edit them in the
Rigging panel and Properties).
For the selected row you can set the label, grain direction, zone, seam allowance (for all
rows or this row), add notches, tape paths across the panel and feature locations (drag a
feature to move it).

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
