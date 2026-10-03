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

The `MeridianProfile` volume and area above are those of the tape surface (the surface of
revolution through the tapes). The lofted volume and area below add the lobes.

## Gore loft (lobe bulge between tapes) — `GoreLoft`

A design's **loft** sets how much each gore bulges between its two load tapes. It is the
lobe-radius ratio

\[
k(f) = \frac{\rho}{r}, \qquad f = \frac{s}{L_t} \in [0, 1],
\]

given at stations \(f\) along the tape (fraction of the tape length \(L_t\) from the mouth
to the top opening), interpolated linearly between stations and held constant beyond the
first and last. The flat half-width is the chord form with \(\rho = k(f)\,r(s)\):

\[
w(s) = k\,r \arcsin\!\left(\frac{\sin(\pi/N)}{k}\right),
\qquad k \ge \sin(\pi/N).
\]

| \(k\) | Lobe | Gore width |
|---|---|---|
| \(\sin(\pi/N)\) | half circle (fullest possible) | \(\tfrac{\pi}{2}\) × chord |
| \(< 1\) | fuller than the tape circle | wider than small bulge |
| \(1\) | on the circle through the tapes (**small bulge**, the default) | \(\pi r / N\) |
| \(> 1\) | flatter | narrower |
| \(\infty\) | flat chord | \(r \sin(\pi/N)\) |

The editor also shows the **extra width** over the flat chord,
\(e = k \arcsin(\sin(\pi/N)/k) / \sin(\pi/N) - 1\) (`loft_extra_width`); for \(k = 1\) it is
\((\pi/N)/\sin(\pi/N) - 1\), e.g. 1.15 % for 12 gores. A design without a loft is the
small-bulge gore, bit for bit.

**Lofted cross-section.** A horizontal section is the regular N-gon through the tapes plus
N circular segments of radius \(\rho\), half-angle \(\theta = \arcsin(\sin(\pi/N)/k)\):

\[
\frac{A}{\pi r^2} = c(k, N) = \frac{N}{\pi}\left[\sin\frac{\pi}{N}\cos\frac{\pi}{N}
  + k^2(\theta - \sin\theta\cos\theta)\right]
\]

(`lobe_area_factor`; \(c = 1\) for \(k = 1\), \(c = N\sin(2\pi/N)/(2\pi)\) for flat gores).

**Lofted volume and area** (`lofted_volume`, `lofted_area`):

\[
V = \sum_i c_{i+\frac12}\,\frac{\pi}{3}(r_i^2 + r_i r_{i+1} + r_{i+1}^2)(z_{i+1} - z_i),
\qquad
A = 2N \int_0^{L_t} w(s)\,ds .
\]

\(A\) is the area of the N flat finished gores, the same fabric the mass estimate cuts. The
editor's volume, gross lift, lift margin and the volume lock use \(V\); the wizard and shape
families solve for it.

**Display.** The 3D view draws each horizontal section as the lobes
(`lobe_ring`): at arc angle \(t \in [-\theta, \theta]\) a point lies at
\(a = r\cos(\pi/N) - \rho\cos\theta + \rho\cos t\) along and \(b = \rho \sin t\) across the
gore's bisector.

**Assumptions and valid range.** The lobe is a circular arc in the horizontal section, as
the width model takes it across the flat gore. Both are exact for a vertical tape and good
while the lobes are shallow compared with the meridian curvature radius; near a nearly
horizontal tape (crown) the true lobe lies in the plane normal to the tape. The loft is a
*design* input: the pressurised lobe shape follows from the flat patterns in the preview
and CalculiX solvers, which sew the lofted panels.

**Benchmarks** (`docs/validation/analytic-geometry.md`): flat gores on a sphere against the
inscribed-polygon volume \(\tfrac{N}{2}\sin(2\pi/N)\cdot\tfrac43 R^3\); a 12-gore cylinder
with \(k = 1.5\) against the hand polygon-plus-segment volume and arc-length area; a 24-gore
sphere with \(k = 2\) against \(A = 4NR^2 k\arcsin(\sin(\pi/N)/k)\); and the inverse round
trip with \(k\) varying from 1.5 to 0.8.

References: circular-segment area, CRC Standard Mathematical Tables, 31st ed. (2003),
sec. 4.5; surfaces of revolution, Struik (1988).

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

Check: with the small-bulge form, \(N \sum A_{finished} = \int 2\pi r\,ds = A\) exactly; with a
loft, \(N \sum A_{finished}\) equals the lofted area \(A\) above.

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
