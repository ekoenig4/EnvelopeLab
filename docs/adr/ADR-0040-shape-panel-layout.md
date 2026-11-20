# ADR-0040: Panel layout of special shapes (project format version 4)

- Status: Accepted
- Date: 2026-11-14

## Context
Builders want to choose how a special shape is cut, not only how many pieces it has: where
the seams sit round the shape (to keep one off a face or a feed hole), how wide each gore
or panel is (a wide front panel, narrow side panels), and where pieces are cut across (a
tier near the base, a top section). Horizontal splits also make large pieces fit the
print roll. Until now every shape had \(M\) equal pieces between the meridians
\(2\pi j/M - \pi/M\), each running from the footprint to the tip or cap.

## Decision
* Every shape specification gets three fields: `seam_offset_deg` (turn of every seam
  round the axis, degrees, in [−180, 180]), `panel_widths` (relative width of every gore
  or panel, one per piece; empty: equal) and `splits` (fractions of the profile's arc
  length from the base circle, increasing in (0, 1), at most 25; empty: none). The
  primitives carry them as `seam_offset` (rad), `panel_widths` and `splits`
  (`envelopelab.features.primitives.seam_angles`, `split_heights`).
* A split cuts every piece across at a parallel of the shape. Each tier is developed on
  its own like a whole skin (exact frustum development, or a classic gore whose seams
  are equalised to their 3D length). Pieces are labelled with their tier letter, `A` at
  the rim (`ear-G3A`, `ear-G3B`). `CutPiece` gets `role` (`panel` or `tip`), `tier` and
  `index`; only tier 0 has a rim, the others a `bottom` edge. The build pack pairs each
  piece's top with the bottom of the piece above it, and the sub-model shares the split
  nodes and adds a `split <i>` seam.
* Mesh shapes take the seam turn and widths but not splits (their panels must stay discs
  from the footprint to the pole); the specification refuses splits on a mesh shape.
* The project format becomes version 4. Versions 1 to 3 are read and migrated: their
  shapes get the defaults (no turn, equal widths, no splits). Shape files accept the same
  three keys.
* With the defaults every result is bit-identical to before: equal widths keep the old
  seam, tip-ring and mark arithmetic exactly (checked against the previous release for
  domes, tubes, revolved and mesh shapes, with and without caps).

## Consequences
* Older releases cannot open version 4 files (they refuse the version, as for ADR-0020).
* Splitting a dome gore changes where its flattening strain goes (each tier is
  equalised to its own seams), so the predicted shape changes slightly; the area
  distortion check and the simulation show it.
* The 3D view colours pieces by their position round the axis; splits are drawn as seams.
