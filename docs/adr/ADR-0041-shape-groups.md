# ADR-0041: Shape groups (several special shapes as one object)

- Status: Accepted
- Date: 2026-11-14

## Context
A special shape of a real balloon is often several shapes: a head is a dome with two
ears and a nose, a character a body with arms. Builders want to place, move and mirror
those parts together and see them together in the build pack, while every part keeps
its own pieces, checks and simulation (the pattern of each part is already right).

## Decision
* A shape specification gets an optional `group` (a name, the same rules as a shape
  name). Shapes sharing a group are one object. There is no separate list of groups: a
  group exists while one of its shapes does, so removing or renaming a shape cannot leave
  a group that points at nothing, and groups are saved, undone and versioned with the
  shapes. The field is part of project format version 4 (ADR-0040; not yet released, so
  it takes no version of its own). Shape files accept `group`.
* `envelopelab.project.shape_groups` holds the geometry: `moved` turns a member round
  the envelope's axis (gore widths) and shifts it along the tape (m), feed holes with it;
  `mirrored` reflects it in a meridian plane (gore position), reversing the lean
  direction, the seam turn and the order of the panel widths, and a mesh's `y` with its
  triangles turned over. A turn is exact (a rotation about the axis); a shift along the
  tape keeps each shape but not the arc between members.
* Edits (one undo step each): `set_shape_group`, `rename_shape_group`,
  `move_shape_group`, `mirror_shape_group` (in place, or a mirrored copy of every member
  not on the mirror line, joining the same group). Dragging a grouped shape in the 3D
  view moves its whole group.
* The build pack lists the groups in `index.json` (`shape_groups`, group to member
  names) and every skin piece's sheet names its object; Blender export can write one
  group's shapes only.

## Consequences
* A group has no pattern or simulation of its own; parts that touch or overlap are not
  joined or checked against each other.
* Moving a group along the tape changes the spacing of its members slightly (gores narrow
  towards the mouth and crown); a whole-gore turn never changes a pattern.
