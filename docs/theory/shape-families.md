# Shape families

A *shape family* is one envelope shape at every size: a table of radius \( r \) against
station \( s \) along the load tape, both as fractions of the pole-to-pole gore length
\( L \). The Balloon Builders Journal gore-layout tables (Issues 1 and 22) are of this
kind. Module: `envelopelab.project.shape_family`; file format:
[shape file](../formats/shape-file.md).

## Design variables

A design of the family is fixed by three continuous variables:

* the gore length \( L \) (m), which scales the whole shape;
* the mouth station \( s_m \) and the top-opening station \( s_t \) (fractions of \( L \)),
  where the envelope is cut;

plus the gore count \( N \) and the seam allowance \( a \) (per gore edge), which do not
change the shape. Holding **any three** quantities fixes the design. These can be variables
or computed values such as the mouth diameter or the volume. Examples:

| Held | Solved | Meaning |
|---|---|---|
| nominal volume, \( s_m \), \( s_t \) | \( L \) | the spreadsheet's own design |
| mouth diameter, \( s_m \), \( s_t \) | \( L \) | same shape scaled to a given mouth |
| nominal volume, mouth diameter, \( s_t \) | \( L \), \( s_m \) | same balloon, mouth cut lower or higher |

## Profile from the table

Because \( s \) is tape (arc) length, the height follows from

\[ z(s) = L \int_0^s \sqrt{1 - r'(\sigma)^2}\, d\sigma , \]

with \( r(s) \) the not-a-knot cubic spline through the table, integrated by 8-point
Gauss–Legendre quadrature per interval. Where spline overshoot gives \( |r'| > 1 \), the tape
is taken as horizontal. (Taking each interval as a straight chord instead shortens the tape
by \( \kappa^2 \Delta s^3 / 24 \) per interval: 2.9 mm on a 25 m sphere table with 50
intervals, which failed the 1 mm benchmark.) The design profile is the editor's parametric
cubic spline through the stations between \( s_m \) and \( s_t \), with the end points on
\( r(s), z(s) \). Every value below is therefore exactly what the editor shows for the
design.

## Computed quantities

* Nominal volume \( V_n = c L^3 \): \( c \) is the volume of the closed shape at
  \( L = 1 \), from pole to pole (with a loft, the lofted volume of the closed shape for
  the design's gore count).
* Envelope volume, height, maximum diameter and tape length of the profile from the mouth
  to the top opening. Open ends are closed by flat discs; the volume is the lofted volume
  ([gore geometry](gore-geometry.md#gore-loft-lobe-bulge-between-tapes-goreloft)).
* Mouth and top diameters \( 2r(s_m) \), \( 2r(s_t) \).
* Maximum cut gore width \( 2(\max_s w(s) + a) \), \( w \) the flat half-width of the
  lofted gore (\( \pi r/N \) for the small-bulge gore).

## Loft

A shape family may carry a loft: the lobe-radius ratio \( k = \rho/r \) at stations
\( s \) given as fractions of \( L \) (or station names). A design cut at
\( s_m, s_t \) gets the loft re-expressed in fractions of its own tape length,
\( f = (s - s_m)/(s_t - s_m) \), with the interpolated ratios at both cuts
(`NormalizedShape.design_loft`), so the editor shows the same lofted volume as the shape
solve.

## Measured pattern sets: cut span, straight tape, flat-chord gores

A shape file can describe a pattern set measured from its panels rather than a published
table (format version 2):

* **Cut span.** The table runs from the mouth (\( s = 0 \)) to the top opening
  (\( s = 1 \)), with \( L \) the tape length; the closed shape beyond the cuts is not
  known. The cut stations are held at 0 and 1, so one more held value fixes the design,
  and the nominal volume is not defined.
* **Straight tape.** With straight panel sides between row corners, the tape is the
  polyline through the corners. The height then gains
  \( \Delta z = \sqrt{\Delta s^2 - \Delta r^2} \) per interval, exactly, instead of the
  quadrature of the spline. The design keeps the polyline (`profile_interpolation:
  linear`), so a row's corners and its side length are those of the pattern.
* **Flat-chord gores.** The width model is the flat chord, so volumes are those of the
  flat-gore polygon, \( N\sin(2\pi/N)/(2\pi) \) of the volume through the tapes. The
  lengthwise loft (seam bows, crest loft) does not change the computed quantities; it
  shapes the panels ([flat-chord gores](gore-geometry.md#flat-chord-gores-and-the-crest-loft-flat_chord_rows-crestloft)).

Measured seam bows are lengths at the file's own size. A variant (another held value)
scales them by \( L/L_{file} \), as it scales every other length of the shape.

## Solving

With one free variable, Brent's method searches its whole range: \( L/1000 \) to
\( 1000 L \) for the gore length, pole to equator for \( s_m \), and equator to pole for
\( s_t \). A target outside the reachable range is reported with that range. With two or
three free variables, `scipy.optimize.least_squares` (trust-region reflective, bounded)
minimises the relative errors from the starting design. A solution counts as converged only
when every held value is met: lengths within 1 mm, volumes within 0.1 %, stations within
1e-6. An unconverged solution never becomes a design.

## Assumptions and valid range

Axisymmetric envelope with a tape on every gore seam; fabric stretch neglected; the table
smooth enough for a cubic spline between stations (error \( O(\Delta s^4) \)); the mouth below
and the top opening above the equator station. A table whose radius changes faster than the
tape length (\( |\Delta r| > \Delta s \)) is refused. Validation:
[shape-family benchmarks](../validation/shape-families.md).

## References

* Balloon Builders Journal, Issues 1 and 22: gore layout from a normalized natural-shape table.
* R. P. Brent, *Algorithms for Minimization without Derivatives*, Prentice-Hall (1973), ch. 4.
* M. A. Branch, T. F. Coleman and Y. Li, SIAM J. Sci. Comput. 21 (1999) 1–23 (trust-region
  reflective least squares).
