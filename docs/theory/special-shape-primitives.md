# Special-shape primitives

A *primitive* is a parametric shape added to a standard-gore envelope: a **dome**
(blister, lobe, ear) or a **tube** (horn, nose, mast) closed by a flat tip disc.
`envelopelab.features.primitives` derives everything a builder needs from the placement
alone: the footprint, where it crosses every host panel, numbered match marks, the
cutting pattern of the skin and checks on it. It also builds a sub-model whose skin rests
in the cut pieces, so the solvers predict how the sewn feature takes shape under pressure.
The module docstrings carry the same equations.

## Envelope surface

The host is the surface of revolution of the design's load-tape meridian
\( (r(s), z(s)) \), with \(s\) the tape arc length from the mouth:

\[
\mathbf{X}(s, \theta) = (r\cos\theta,\ r\sin\theta,\ z), \qquad
\mathbf{n} = (z'\cos\theta,\ z'\sin\theta,\ -r').
\]

Gore \(k\) (numbered from 1) spans \( \theta \in [(k-1), k)\,2\pi/N \). A point at
fraction \( \tau \in [-\tfrac12, \tfrac12] \) across gore \(k\) sits at

\[
x = 2\tau\,w(s), \qquad y = s - s_{row}
\]

in the flat pattern of that gore's row, with \(w(s)\) the flat half-width of the design's
width model. This is exact on the centreline and on the load tapes; across the lobe of a
lofted gore a mark is placed in proportion to the flat width (the lobe bulge between the
tapes is not part of the host surface here).

## Skin

The axis passes through the base point \( \mathbf{P}_0 = \mathbf{X}(s_0, \theta_0) \)
along the outward normal tilted by the lean \( \lambda \) towards the azimuth \( \psi \)
of the tangent plane (\( \psi = 0 \): up the tape, \( 90^\circ \): towards the next gore):

\[
\mathbf{a} = \cos\lambda\,\mathbf{n} + \sin\lambda\,(\cos\psi\,\mathbf{e}_s +
\sin\psi\,\mathbf{e}_\theta).
\]

The skin revolves a meridian \( (\rho(\sigma), \zeta(\sigma)) \) about it, with \( \sigma \)
the arc length from the base circle to the tip:

\[
\mathbf{S}(\sigma, \phi) = \mathbf{P}_0 + \rho(\sigma)(\cos\phi\,\mathbf{b}_1 +
\sin\phi\,\mathbf{b}_2) + \zeta(\sigma)\,\mathbf{a},
\]

with \( \mathbf{b}_1 \) the up-tape direction made normal to the axis and
\( \mathbf{b}_2 = \mathbf{a}\times\mathbf{b}_1 \). A dome is a half spheroid
\( \rho = a\cos\omega,\ \zeta = h\sin\omega \); a tube is a straight frustum from radius
\(r_b\) to \(r_t\) over the axial length \(L\). A *revolved* shape takes any meridian
given as points \( (\rho_i, \zeta_i) \) from the base circle to the tip, joined by a cubic
spline or by straight segments. It ends in an apex when its last point is on the axis and
in a flat tip disc otherwise.

**Footprint.** Below the base circle every skin meridian continues along its base
tangent: a dome's wall drops straight down the axis, a tube's generator continues. A
profile that flares outward at its base (an onion or a ball) would run into the axis if
continued backwards, so its wall drops straight down the axis instead. The
footprint point on meridian \( \phi \) is the last crossing of that line from inside to
outside the envelope. It is found by sampling the signed distance to the meridian curve
at 241 points along the path (about 1 % of its length apart), which brackets the
crossing, and bisecting to \(10^{-7}\) m. So the skin always reaches the envelope,
including where a leaned base circle dips below it. A meridian that crosses the envelope
more than once (the skin touching the envelope again) is rejected; a second crossing
closer than the sample spacing is not detected.

## Cutting pattern

The skin is cut into \(M\) pieces between the meridians
\( \phi_j = 2\pi j/M - \pi/M \), so piece 1 is centred on the top of the feature. Each
meridian runs from its footprint point (\(t = 0\)) to the tip (\(t = 1\)).

### Tube panels: exact developments

This applies to tubes and to revolved profiles of a single straight segment.

A cone of half-angle \( \gamma \), with \( \sin\gamma = (r_b - r_t)/\ell \), unrolls about
its apex. The polar radius is the slant distance from the apex and the polar angle is
\( \alpha = \phi\sin\gamma \); a cylinder unrolls to \( x = r_b\phi \) [Struik]. Every
length and angle is kept, the footprint edge included.

### Dome gores: classic gores with true-length seams

This applies to domes and to every other revolved profile.

The centreline of the gore is laid straight with its true length \(y(t)\). Every parallel
\(t\) = const is laid straight across it with its true arc length from the centreline,
\(x(t, \phi)\) [Pagon]. A doubly curved gore cannot be flattened without strain: in this
layout the flat seam edges come out longer than the 3D seams (by about 3 % for an
8-gore hemisphere). They also differ between the two sides of a seam when the footprint
is not symmetric. The gore is therefore sheared and stretched along its length,

\[
x' = x + \kappa\,y, \qquad y' = (1 + \alpha)\,y,
\]

with \( \alpha \) and \( \kappa \) found by Newton iteration so that both seam edges get
their true 3D length. The two sides of every seam then match exactly, the rim stays on
\(y = 0\) and the apex stays one point. The shear lengthens one seam edge and shortens the
other without changing the area, and the stretch changes both. The distortion that remains
is reported as the *area distortion* (flat area against designed area). For a
hemispherical dome it falls as about \(1/M^2\): 3.7 %, 0.9 % and 0.2 % for 8, 16 and 32
gores (see [Special-shape primitives](../validation/special-shape-primitives.md)).

### Checks

| Check | Measure | Limit (source) |
|---|---|---|
| footprint between mouth and crown | tape clearance, m | > 0 |
| rim length | sum of rim edges − footprint length, m | 3 mm (assumed, AGENTS.md sewn edges) |
| skin seam match | largest length difference of the two sides of a seam, m | 3 mm (assumed) |
| seam flattening | largest relative difference of a flat seam edge from its 3D seam | 2 % (assumed) |
| area distortion | largest relative difference of a piece's flat and designed area | 1 % (assumed) |
| feed hole inside footprint | — | inside |

## Free-form shapes from a mesh

A `FreeformShape` is a closed triangle mesh in its own frame: \(z\) along the axis,
\(x\) up the tape, origin at the base point. It is placed with the same axis frame as
the parametric shapes and **clipped at the envelope**. Every edge whose ends lie on either
side of the envelope is cut where the signed distance is zero (bisection to
\(10^{-7}\) m), and the part inside is dropped. The cut edge is the footprint; it must be
one loop turning once round the axis. The point where the axis leaves the mesh (the
*pole*) is inserted as a vertex. The skin is then cut along the half-planes
\( \phi_j = 2\pi j/M - \pi/M \), so every panel is a disc bounded by the footprint, two seams
and the pole.

**Flattening** [Levy, Liu]. Each panel is mapped by least-squares conformal maps, then
by as-rigid-as-possible iterations that fit every triangle's best rotation and solve the
cotangent-weighted Laplace system

\[
\min_{\mathbf{u}} \sum_t \sum_{(i,j)\in t} c_{ij}
\lVert (\mathbf{u}_i - \mathbf{u}_j) - R_t(\mathbf{x}_i - \mathbf{x}_j) \rVert^2,
\]

with the seam and footprint edges weighted up. The boundary is then rebuilt with
every edge at its exact 3D length. Its edge directions come from that solution, and the
closure gap is removed by the least-norm change of the edge angles, which changes no
length. The interior is relaxed again with the boundary held. Footprint and seams
keep their true lengths and both sides of every seam match exactly. The strain of
flattening a doubly curved panel goes into its interior and is reported as *area
distortion* and *edge strain* (largest relative change of a triangle side, limit 2 %,
assumed).

The sub-model meshes every flat panel round the footprint nodes like the parametric
shapes. Its interior nodes start on the mesh (barycentric in the flat panel), and every
triangle rests in its flat panel. No faceting correction is applied: the mesh is taken as
the designed surface.

## Sub-model with an as-cut skin

`primitive_appendage` builds an `AppendageSpec` with `skin_mode="designed"`. The skin
factory triangulates every cut piece **in its own flat coordinates** around the footprint
nodes of the host mesh. Seam, rim, tip and apex nodes are shared between the pieces that
meet there, and interior nodes start on the designed shape through the inverse of the
piece's development. Every triangle therefore rests in the cut cloth and the seams are mesh
lines.

**Faceting correction.** A flat triangle stands in for a patch of curved cloth: its sides
are chords of the designed surface, but the cut cloth between its corners follows the
surface. Rest lengths taken straight from the pattern would leave an excess of about
\( (\kappa h)^2/24 \) (0.2 % for 0.2 m elements on a 1 m dome). That is far more than the
fabric strain under envelope pressure (about \(10^{-4}\)), and the solver would report it
as slack cloth. Each flat side length is therefore scaled by chord / arc of the same path
on the designed surface. This keeps the pattern's own strain, removes the faceting excess,
and tends to 1 as the mesh is refined.

**Host.** The host patch is the true envelope (`EnvelopeHost`) in the chart
\( u = r(s)\,\Delta\theta,\ v = s - s_0 \) (true hoop and meridian arcs). The skin's rim
and the host footprint therefore have the same length. The load tapes on the gore seams,
and optionally the row seams, cross the patch. The far-field prestress of the patch uses
the local radii at the base point (\(R_1\) from the meridian's curvature over
\( \pm 0.25 \) m, \( R_2 = r/\cos\beta \)) in the membrane theory of shells of revolution.

**Assumptions.** Seam allowances, stitching and tape widths are not modelled as material.
The patch edge is held on the designed envelope (keep the margin at least half the
footprint size). The tip disc of a tube is flat as cut.

## What the solver shows

At hot-air envelope pressures (tens of Pa) fabric strains are of order \(10^{-4}\). Any
difference of a cut pattern from its designed shape larger than that leaves cloth the
pressure cannot take up. The preview solver reports it as wrinkled (uniaxially tensioned)
skin and as a shape that differs from the design. In the
[mesh study](../validation/special-shape-primitives.md), a 16-gore dome stands under 1 %
taller than designed, and taller than the same model with its skin resting in the designed
shape. Read the projected height and the inflated shape as the prediction. The wrinkled
fraction depends on the mesh and is an indicator only.

## Valid range

The footprint must stay on the convex part of the envelope between the mouth and the
crown, and be star-shaped about the base point. Bases larger than about a quarter of the
local envelope radius, and leans that make the skin touch the envelope again, are
rejected. Leans are limited to 75°.

## References

- [Levy] B. Lévy, S. Petitjean, N. Ray and J. Maillot, "Least squares conformal maps for
  automatic texture atlas generation", ACM Trans. Graph. 21(3) (2002) 362-371.
- [Liu] L. Liu, L. Zhang, Y. Xu, C. Gotsman and S. J. Gortler, "A local/global approach to
  mesh parameterization", Comput. Graph. Forum 27(5) (2008) 1495-1504.

- [Struik] D. J. Struik, *Lectures on Classical Differential Geometry*, 2nd ed., Dover
  (1988), sec. 2-1 and 2-8 (surfaces of revolution; developable cones and cylinders).
- [Pagon] W. W. Pagon, "Gore patterns for balloons and airship envelopes", in
  *Scientific Ballooning Handbook*, NCAR TN-99 (1975), sec. 7.
- S. P. Timoshenko and S. Woinowsky-Krieger, *Theory of Plates and Shells*, 2nd ed.,
  McGraw-Hill (1959), sec. 105 (membrane resultants of shells of revolution).
