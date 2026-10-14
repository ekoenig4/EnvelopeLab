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

## Flat-chord gores and the crest loft — `flat_chord_rows`, `CrestLoft`

A design with `construction: flat_chord` is cut the way many horizontal-cut patterns are
drawn:
every row is a flat tape-to-tape trapezoid, and the gore is lofted **lengthwise** by
making its centreline longer than its sides.

**Rows.** Row \(k\) runs along the tape from \(s_k\) to \(s_{k+1}\) (its tape length
\(L_k\)). Its corners lie a flat chord apart,

\[
w_j = r(s_j)\sin\frac{\pi}{N},
\]

either side of the centreline, and its sides are straight lines of length \(L_k\), since
the load tape is sewn along them. The top corners therefore stand

\[
h_k = \sqrt{L_k^2 - (w_{k+1} - w_k)^2}
\]

above the bottom ones. With straight tape segments between row corners
(`profile_interpolation: linear`) the panel side and the tape agree exactly.

**Bowed seams.** The bottom and top seam lines bow outward from the straight corner line
as parabolas

\[
d(x) = b\left(1 - \left(\frac{x}{w_c}\right)^2\right),
\]

so the centreline is \(h_k + b_{bottom} + b_{top}\) long. The seam is taken to be this
parabola. The bows are given per row (`bow_bottom`, `bow_top`; a
measured table) or come from a crest loft.

**Crest loft.** The crest of the fabric between two tapes is meant to stand

\[
\delta(s) = \lambda\,\tau(f)\,r(s), \qquad f = s/L_t,
\]

outside the flat chord: \(\lambda\) is the loft fraction ("2 % of radius") and
\(\tau\) a taper interpolated linearly between stations (0 at the mouth and the
opening for a loft that tapers to zero there). Offsetting a curve outward by \(\delta\)
lengthens it by \(\int \delta\kappa\,ds\), with \(\kappa\) the curvature of the
meridian. On the polyline profile the tape turns by \(\varphi_i\) at node \(i\), and the
offset gains \(2\delta_i\tan(\varphi_i/2)\) there. Each node's gain goes to the nearest
boundary between two rows. A boundary that collects \(e_j\) bows both seam lines that
meet there by \(\beta_j = e_j/2\), so the two sides of a seam have the same shape and
length. The mouth and the top opening stay straight; gains next to them go to the first
interior boundary.

**Volume and area.** The width model of a flat-chord gore is the flat chord
(\(k = \infty\)), so the design volume is that of the flat-gore polygon,
\(N\sin(2\pi/N)/(2\pi)\) times the volume through the tapes (98.4 % for 20 gores). The
crest is not added: how far it stands out under pressure is a result of the preview and
CalculiX solvers, which sew the bowed panels. The fabric area of the rows includes the
parabolic segments, \(\tfrac{2}{3}\,2w_c\,b\) per bowed seam.

**Display surface.** The 3D view draws a flat-chord gore as the flat chord between the
tapes moved by \(\delta(s)(1 - u^2)\) along the outward normal of the meridian,
\(u \in [-1, 1]\) across the gore (`crest_section`). With measured bows the offset at
seam \(j\) is taken from the bows by inverting the crest-loft relation above,

\[
\delta_j = \frac{2\beta_j}{\sum_i 2\tan(\varphi_i/2)},
\]

over the nodes the crest loft gives to that seam, with \(\beta_j\) the mean of the two
seam lines (`crest_offsets_from_bows`). It is linear between seams and 0 at the mouth and
the opening. Where the tape is straight (a total turn below \(10^{-3}\) rad) bows cannot be
shown as an offset and the offset is 0. This is a display of the cut shape, not the
inflated shape.

**Cut outline.** Each finished edge (bottom seam, side, top seam, side) is offset outward
by its allowance, with mitred joints, and the offset edges are extended along their end
segments to meet at the corners (`bowed_cut_outline`). Straight-seam rows keep the
cut outline above.

**Assumptions and valid range.** The fabric does not stretch. The crest offset is
measured normal to the tape and is small compared with the meridian radius of curvature.
The crest loft is a generator: it gives both sides of a seam the same bow, so it cannot
reproduce a pattern whose two sides differ; use measured bows to reproduce a pattern.

**Benchmarks** (`docs/validation/analytic-geometry.md`):
* a crest of 2 % of \(r\) on a spherical zone of radius \(R\) from latitude
  \(\theta_0\) to \(\theta_1\), against \(\lambda R(\sin\theta_1 - \sin\theta_0)\);
* no bows on a cylinder;
* a bowed cone row against the trapezoid plus two parabolic segments.

References: curves parallel to a plane curve (offset length \(\int\delta\kappa\,ds\)),
do Carmo, *Differential Geometry of Curves and Surfaces* (1976), sec. 1-7; area of a
parabolic segment (Archimedes' quadrature), CRC Standard Mathematical Tables, 31st ed.
(2003), sec. 4.5.

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
