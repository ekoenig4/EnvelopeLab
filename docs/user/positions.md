# Positions: metres or balloon coordinates

Every position on the balloon (where a special shape stands, its feed holes, where an
overlay lies, the point under the pointer on the gore map, a symmetry axis) can be shown
and typed in one of two ways. Choose it in **File ▸ Preferences ▸ Positions shown in**.
It only changes what you see and type: the project stores the same position either way,
and no result changes when you switch.

| | Metres (default) | Balloon coordinates |
|---|---|---|
| Round the balloon | **Gore** and the offset from the gore's centre line in m (+ towards the next gore) | **Gore** and the fraction **across** it: 0 at the seam with the previous gore, 0.5 on its centre line, 1 at the seam with the next gore |
| Up the balloon | Tape position: m along the load tape from the mouth | **Panel row** and the fraction **up** it: 0 on its bottom seam, 1 on its top seam |
| Example | gore 3, +0.120 m from its centre, 4.250 m up the tape | gore 3 + 0.62, row F + 0.40 |

In balloon coordinates, the placement form shows a row picker and a fraction box instead
of the tape position, and the feed-hole table takes text such as `F + 0.4` in its *row +
fraction up* column (a row alone means its bottom seam). A point on a row seam counts as
the bottom of the row above it.

Positions are converted when you type them. If you later make a row taller or shorter,
a feature keeps its height in metres: it does not stay at the same fraction of its row.
An offset in metres must lie inside the gore at that height; one that does not is refused
with a message and nothing changes.

## On a special shape

A position *on* a special shape uses the shape's own frame, not the envelope's:

| | Metres | Balloon coordinates |
|---|---|---|
| Horizontal split (Panel layout) | m along the skin from the rim | % of the profile's length from the rim |
| Where the panels meet (Across, Up) | m from the tip, seen from above | fraction of the shape's widest radius seen from above |

So a split typed as `0.40` in metres lies 40 cm up the skin, and as `40` in balloon
coordinates 40 % of the way to the top. The shape's base point is a position on the
envelope, so it uses the envelope's coordinates above.

Sizes (radii, widths, heights, seam allowances) and distances you move things by are
always in metres. A symmetry axis runs from the mouth to the crown, so its offset in metres
would change with the gore's width; it is given as a fraction of its gore either way.

How the conversion works: [Balloon coordinates](../theory/balloon-coordinates.md).
