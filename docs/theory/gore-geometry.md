# Gore envelope geometry

Modules: `envelopelab.geometry.gore` (profile, widths, rows, inverse) and
`envelopelab.mass_estimate` (materials and lift margin). All lengths in m.

## Assumptions

* The envelope is axisymmetric with \(N\) identical gores and a load tape on every vertical
  seam.
* The **meridian profile** \(r(s), z(s)\) is the curve followed by a load tape; \(s\) is tape
  arc length measured from the mouth (\(s = 0\)) to the top edge (crown ring or parachute hole).
* The flat gore is drawn with its centreline on \(y = s\) and half-width \(x = \pm w(s)\).
  Fabric stretch is neglected. Because a doubly curved surface cannot be flattened exactly,
  the flat side edge is slightly longer than the tape,
  \(\ell_{side} = \int \sqrt{1 + w'(s)^2}\,ds\); `PanelRow.side_length` reports it.
* Horizontal seams are straight lines across the flat gore (constant \(s\)).

## Profile quantities — `MeridianProfile`

The profile is a polyline. `from_control_points` interpolates control points with a parametric
cubic spline (chord-length parameter) and samples it densely (default 4 001 points), so the
polyline error is negligible (< 10⁻⁶ relative for a sphere).

| Quantity | Formula (per segment \(i\)) |
|---|---|
| Volume | \(V = \left|\sum_i \frac{\pi}{3}(r_i^2 + r_i r_{i+1} + r_{i+1}^2)(z_{i+1} - z_i)\right|\) (exact for cone frusta) |
| Area (through the tapes) | \(A = \sum_i \pi (r_i + r_{i+1})\,\Delta s_i\) |
| Height | \(\max z - \min z\) |
| Max width | \(2 \max r\) |
| Meridian length | \(s_{end}\) |

Open ends are closed by flat discs for the volume only. Valid for profiles whose closing discs
do not cut the surface (z monotonic, or a single turn-back).

## Flat gore half-width

**Small-bulge form** — the fabric lies on the circle through the tapes:

\[
w(s) = \frac{\pi\,r(s)}{N}.
\]

**Exact chord form** — adjacent tapes are a chord \(c = 2 r \sin(\pi/N)\) apart and the fabric
between them bulges as a circular lobe of radius \(\rho\):

\[
w(s) = \rho \arcsin\!\left(\frac{r(s)\sin(\pi/N)}{\rho}\right),
\qquad \rho \ge r \sin(\pi/N).
\]

Limits: \(\rho \to \infty\) gives the flat chord \(w = r\sin(\pi/N)\); \(\rho = r\) gives the
small-bulge form. `GoreWidthModel(n_gores, "chord", bulge_radius=ρ)` uses a constant ρ (m);
`bulge_ratio=k` uses \(\rho = k\,r(s)\). Flat chord ≤ lobe ≤ small bulge for \(k \ge 1\).

In the chord form, \(r\) and the volume/area above refer to the tape surface; the lobe volume
between tapes is not added.

## Panel rows — `split_rows`

Rows are given as finished heights along \(s\) from the mouth upward and must cover the
meridian within 1 mm (unless `require_full_coverage=False`).

* **Finished outline**: \((\pm w(s), s - s_{bottom})\) for the row's stations (profile nodes
  plus at least 65 evenly spaced points), closed by straight bottom and top seam lines.
* **Cut outline**: the side edge is offset outward by the side allowance (mitred joints
  within the polyline, so every segment is exactly the allowance away); the bottom and top
  lines move out by their allowances. Corner treatment:
    * `miter` — the offset side line is extended along its end tangent to meet the offset
      horizontal line (sharp corner);
    * `bevel` — the corner is cut by a straight line from the side-offset point normal to
      the finished corner to the point on the offset seam line directly above/below it.
    * Where the offset side already crosses the offset seam line (side leaning outward over
      the seam), both treatments trim at the crossing.
* **Loft table**: finished full widths \(2w\) at 0, 25, 50, 75 and 100 % of each row height
  (configurable).

Check: with the small-bulge form, \(N \sum A_{finished} = \int 2\pi r\,ds = A\) exactly.

## Inverse: measured widths → profile — `profile_from_gore_widths`

1. Radius from the measured full width: \(r_i = N\,w_{full,i}/(2\pi)\) (small bulge) or the
   chord-form inverse \(r = \rho\sin(w/\rho)/\sin(\pi/N)\) (constant ρ) /
   \(r = w / (k \arcsin(\sin(\pi/N)/k))\) (ρ = k r).
2. Gross outliers are removed one at a time (worst first) using leave-one-out local
   quadratic residuals and the robust score \(|e_i - \tilde e|/(1.4826\,\mathrm{MAD})\)
   (threshold 3.5; scale floor 1 mm).
3. A cubic smoothing spline \(r(s)\) is fitted to the inliers (penalty chosen by generalised
   cross-validation unless given); every station is re-tested against it and the set of
   outliers is iterated to a fixed point. Residuals and RMS are reported.
4. Height from arc length:
   \(z(s) = \int_0^s \sqrt{1 - r'(\sigma)^2}\,d\sigma\). Samples with \(|r'| > 1\) are
   non-physical; they are clipped and counted in `slope_clipped`.

Valid for profiles where \(z\) increases monotonically with \(s\). Accuracy degrades where
\(|dr/ds| \to 1\) (horizontal fabric), since \(dz/ds\) is then very sensitive to \(r'\).
The fitted spline has natural end conditions (\(r'' = 0\)), which biases the first and last
few stations when the data are noisy.

## Mass and materials — `estimate_mass`, `lift_margin`

* Fabric per zone: cut area \(N\sum A_{cut}\) × areal mass; allowance area =
  cut − finished.
* Tapes: vertical \(N\sum \ell_{side}\); horizontal rings on internal row boundaries
  \(N\,w_{full}(s_k)\); rim ring at the mouth; hole ring at the top.
* Thread: \(c\,(n_v L_{seam,v} + n_h L_{seam,h})\) × linear mass, with \(c\) the thread length
  per seam length per stitch row (lockstitch ≈ 2.5–3).
* Lift margin: \(V(\rho_{amb} - \rho_{int}) - m_{envelope} - m_{payload}\) (kg).

Every material value is passed in as a `MaterialProperty` with a source tag; the estimate
lists the tags it used. Nesting waste on the roll, tape end overlaps and reinforcements are
not included.

## Validation

See [analytic benchmarks](../validation/analytic-geometry.md): sphere and cylinder volume
and area < 0.1 %, profile → gores → profile round trip < 1 mm. The panel-row check against
the reference fixture's panel C is pending until that fixture profile is added.

## References

* D. J. Struik, *Lectures on Classical Differential Geometry*, 2nd ed., Dover (1988) —
  surfaces of revolution. The lobe (chord) formula is elementary circle geometry.
* P. J. Green and B. W. Silverman, *Nonparametric Regression and Generalized Linear
  Models* (1994) — smoothing splines and GCV.
* F. R. Hampel, "The influence curve and its role in robust estimation", *JASA* 69 (1974) —
  MAD-based outlier scores.
