# Balloon coordinates

Module: `envelopelab.project.coordinates` (user guide:
[Positions](../user/positions.md)).

A point on the envelope is stored as its gore \(k\) (from 1), the fraction
\(a \in [-\tfrac12, \tfrac12]\) of the gore's width from its centre line (positive towards
gore \(k + 1\)) and its tape position \(s\) (m along the load tape from the mouth). The
application shows and takes it in one of two forms; what is stored does not change.

## Metres

Gore \(k\), the offset from the centre line across the cloth and \(s\):

\[ x = 2\,a\,w(s) \quad \text{(m)}, \]

with \(w(s)\) the flat half width of the gore at \(s\), the width the patterns are cut
to. An offset with \(|x| > w(s)\) lies outside the gore and is refused.

## Balloon coordinates

Gore \(k\) plus the fraction across it from the seam with gore \(k - 1\) (0) to the seam
with gore \(k + 1\) (1),

\[ f_g = a + \tfrac12, \]

and the panel row \(r\) containing \(s\) plus the fraction up it from its bottom seam
\(s_{r,0}\) to its top seam \(s_{r,1}\),

\[ f_r = \frac{s - s_{r,0}}{s_{r,1} - s_{r,0}}, \qquad
   s = s_{r,0} + f_r\,(s_{r,1} - s_{r,0}). \]

A point on a row seam belongs to the row above it (\(f_r = 0\)), except at the crown end
of the top row (\(f_r = 1\)). Positions beyond the ends of the tape are taken at the ends.

## On a special shape

A position on a special shape is given in the shape's own frame. A horizontal split is
stored as the fraction \(f\) of the skin meridian's length \(S\) from the rim to the tip
(or the edge of a centred cap). In metres it is shown as \(d = f S\) along the skin; in
balloon coordinates as \(100 f\) %. Where the panels meet is stored as plan fractions
\((c_a, c_u)\) of the widest radius \(R\) (ADR-0052). In metres it is shown as
\((c_a R, c_u R)\), and in balloon coordinates as \((c_a, c_u)\).

## Assumptions and valid range

* The rows tile the load tape from the mouth to the crown without gaps (the rows of
  `envelopelab.features.primitives.EnvelopeSurface`).
* The conversion is a display: it is applied when a position is shown or typed, so a
  feature keeps its tape position in metres when rows change.
* The two forms are exact inverses up to rounding (`tests/unit/test_coordinates.py`,
  property tests of both round trips).
