# ADR-0043: Symmetry axes and linked mirror twins

- Status: Accepted
- Date: 2026-11-15
- Amends: ADR-0041 (mirroring a group)

## Context
Mirroring was a one-time copy, reached only through a group dialog that asked for a bare
gore number; the mirror plane was not stored or shown, and the two sides of a face
drifted apart as soon as one was edited. Builders asked for an obvious way to handle the
axes of symmetry of a design, and chose that a mirrored shape stays linked and always
symmetric.

## Decision
* The design state gets `symmetry_axes`: named meridian planes (`name`, `line` = gore
  position). They are saved, undone and versioned with the shapes, listed in the Special
  shapes panel with where they lie (*centre of gore 6*, *seam 6|7*) and drawn on the
  envelope in the 3D view.
* A shape may be a **mirror twin**: `mirror = {of, axis}`. The twin is stored in full
  (so placing, checking, simulating and exporting it need nothing new) and kept the
  mirror image of its source by `envelopelab.project.symmetry.sync_twins`, run at the
  single place every shape and axis edit goes through (`ProjectSession.edit_symmetry`),
  and after design edits (a gore count change moves the axes' azimuths). An edit that
  changed a twin but not its source is carried to the source first, so either side can
  be edited or dragged; links alone (renames) never count as edits.
* Edits: `add_symmetry_axis`, `update_symmetry_axis` (moves or renames; twins follow),
  `remove_symmetry_axis` (refused while twins use it), `mirror_shape`, `unlink_mirror`;
  `mirror_shape_group` takes an axis and makes linked twins. A twin follows its source's
  group; moving a group moves the axes of its twin pairs, and is refused when a pair or
  an axis is shared with shapes outside the group.
* Both fields are part of project format 4 (not yet released, ADR-0040).

## Consequences
* A twin cannot have its own size, layout or placement; unlink it for an asymmetric
  design.
* Twins of twins, and a shape on its own axis, are refused.
* Shape files do not carry axes or links yet (their shapes come in independent).
