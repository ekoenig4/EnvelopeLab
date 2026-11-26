# Scale models

A scale model is cut from the same flat patterns as the full-size envelope with every
length multiplied by the scale factor \( k = 1/n \) (a 1:n model;
`envelopelab.export.scale_model`, ADR-0062):

\[
\mathbf{x}_\text{model} = k\,\mathbf{x}_\text{full}, \qquad
L_\text{model} = k\,L, \qquad A_\text{model} = k^2 A, \qquad V_\text{model} = k^3 V .
\]

Finished outlines, sewn edges, match marks, footprint lines, feed holes and the planned
seam ease all scale by \( k \), so the sewn model is geometrically similar to the
patterns the full-size envelope is sewn from.

The model is made by scaling the **inputs** (ADR-0063): every length of the design (the
meridian control points, row heights and seam bows, mouth, crown ring, parachute hole and
seal overlap, tape widths, seam allowances, rigging and parachute lengths, scoop, vent
openings), of the row annotations, of the overlays and of every special shape (its
position up the tape, radii, heights, profile, mesh, cap and crown outline). Angles,
counts, lofts, tapers and relative widths are dimensionless and kept. The gore geometry
is homogeneous of degree one in these lengths, so the envelope and parachute sheets cut
from the scaled design equal the scaled full-size sheets to rounding (a test). A special
shape is designed again on the scaled envelope, with its seam allowance, feed holes,
check tolerance and feed-hole clearance scaled: its skin is flattened again at model
size and agrees with the scaled full-size pieces within 0.1 % in area and in every sewn
edge's length (a test), though a piece may lie turned slightly in the plane.

The documents are made from the scaled inputs by the same code as the full-size pack.
Volume, height and widest diameter follow the similarity above (\( V_m = k^3 V \);
`model_summary`, shown in the export dialog).

## Seam allowance

The cut outline either scales with the piece (an exact 1:n copy) or is the scaled
finished outline offset outward by a fixed allowance \( a \) at model size (mitred
offset, `envelopelab.geometry.polygon.offset_polygon`). A 25 mm allowance at 1:20 is
1.25 mm; a fixed 5 mm tab is easier to glue or sew.

## Fitting the paper

Each piece is printed whole on one sheet, inside a printer margin \( m \) on every side:
the printable area is \( W \times H = (w_p - 2m) \times (h_p - 2m) \) for paper
\( w_p \times h_p \) (a standard size or a custom one). For a print size limited only
in width (a roll or strip), \( H = \infty \) and the sheet is not turned landscape: a
piece fits when \( a(\theta) \le W \). A cut outline turned by \( \theta \) with bounding box
\( a(\theta) \times b(\theta) \) fits when

\[
\big(a \le W \text{ and } b \le H\big) \quad\text{or}\quad \big(a \le H \text{ and } b \le W\big)
\]

(portrait or landscape). The turns tried are upright, a quarter turn, every edge
direction of the outline's convex hull (where the minimum-area enclosing rectangle lies,
Freeman and Shapira 1975) and every whole degree; upright and a quarter turn are taken
first when they fit.

With the allowance scaled the whole cut outline scales, so the largest factor at which
piece \( i \) fits is exactly

\[
k_i = \max_\theta \max\left(
\min\left(\frac{W}{a}, \frac{H}{b}\right),
\min\left(\frac{H}{a}, \frac{W}{b}\right)\right).
\]

With a fixed allowance the box of the scaled finished outline grows by \( a \) on every
side (exact for a rounded offset), so \( W, H \) are replaced by \( W - 2a, H - 2a \)
and \( a(\theta), b(\theta) \) are those of the finished outline. The mitred corners of
the drawn offset reach slightly further; the exact cut outline is then measured and
\( k_i \) multiplied by its remaining room until it fits, so the result always fits.

The model's scale is \( n = 1 / \min_i k_i \), rounded up to a whole number by default:
the largest whole-number 1:n model whose every piece fits. *Fit to paper* in the export
dialog uses this.

## Assumptions and valid range

* Weights, loads, strengths, factors of safety, lift and flows are printed *n/a (scale
  model)* in the model's documents, and the lift charts are left out (below).
* Geometric similarity only. A model in paper, tissue or film is **not** dynamically or
  structurally similar to the full-size envelope: lift scales with \( k^3 \) while skin
  mass scales with \( k^2 \) (times the model material's areal mass), and membrane
  stresses, wrinkling and fabric strain do not scale. A model shows the shape of the
  patterns as built; it is not evidence of the full-size envelope's strength or
  airworthiness.
* The fit covers the cut outline only; text and calibration lines are laid out round it.
* Turns are sampled every whole degree plus the hull-edge turns; a piece that fits only
  in a range of turns narrower than that can be reported as not fitting (a conservative
  error: the scale found is then slightly smaller than possible, never too large).

## References

* H. Freeman and R. Shapira, "Determining the minimum-area encasing rectangle for an
  arbitrary closed curve", *Comm. ACM* 18(7), 409–413 (1975).
* ANSI/ASME Y14.1 (US paper sizes) and ISO 216 (A sizes).
