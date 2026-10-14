# Profile editing: soft selection, straight sections and simplify

Module: `envelopelab.geometry.profile_editing` (edits in `envelopelab.project.edits`:
`move_points`, `scale_points`, `rotate_points`, `straighten_points`, `smooth_points`,
`simplify_profile`).

The envelope profile is a list of control points \(p_k = (r_k, z_k)\) (m, mouth first),
joined by a spline or by straight segments ([gore geometry](gore-geometry.md)). These
functions change many points in one edit. Each edit is then corrected for the
constraint locks, and the rows are refitted
([design editing](design-editing.md#constraint-locks)), so a bulk edit never breaks a
locked height, volume, diameter or opening.

## Soft selection

A transform \(T\) (move by \((\Delta r, \Delta z)\), scale by \((k_r, k_z)\) or rotate by
\(\alpha\) about a pivot, by default the centroid of the selection) applies fully to the
selected points and partly to their neighbours:

\[ p_k' = p_k + w_k\,\bigl(T(p_k) - p_k\bigr), \qquad r_k' \leftarrow \max(r_k', 0). \]

\(w_k = 1\) for a selected point. For the others, \(w_k = w(d_k/R)\), with \(d_k\) the
distance along the control polygon to the nearest selected point and \(R\) the soft
radius. With \(u = d/R\) and \(t = 1 - u\), and \(w = 0\) for \(u \ge 1\):

| Falloff | \(w(u)\) for \(u < 1\) |
|---|---|
| smooth | \(3t^2 - 2t^3\) |
| linear | \(t\) |
| sharp | \(t^2\) |
| sphere | \(\sqrt{1 - u^2}\) |
| constant | \(1\) |

These are the falloff profiles of soft selection ("proportional editing") in 3D
modelling tools. Measuring \(d\) along the profile, not straight across, keeps a drag on
one side of a narrow neck from moving the other side. A soft radius below 1 µm is no
soft selection.

## Straight sections

*Straighten* between points \(i < j\) puts every point \(i < k < j\) on the segment
\(p_i p_j\), at its fraction of the control-polygon length between them,
\(t_k = (s_k - s_i)/(s_j - s_i)\):

\[ p_k' = p_i + t_k\,(p_j - p_i). \]

\(p_i\) and \(p_j\) do not move. With straight-segment interpolation the section is then
exactly straight. With a spline it is straight between the inner points and blends into
the curve over the first and last interval.

## Smoothing

Laplacian smoothing of the selected interior points,

\[ p_k \leftarrow p_k + \lambda\left(\tfrac12(p_{k-1} + p_{k+1}) - p_k\right), \]

with \(\lambda = 0.5\), one pass per press. The first and last control points never move.
Repeated smoothing also shrinks a curve [Taubin]. A locked volume or height corrects
this, otherwise it shows in the live outputs.

## Curvature comb

The curvature of the densely sampled profile is \(\kappa = d\varphi/ds\) (1/m), with
\(\varphi\) the direction of the tangent. It is computed by finite differences, and is
exact for a polyline on a circle to 1e-6. The comb draws \(\kappa\) as spikes along the
normal, on the side away from the centre of curvature. The longest spike is 12 % of the
profile's larger dimension. A smooth profile has a smooth comb. A kink shows as one tall
spike, and a wiggle as a comb that changes side. Membrane stress depends on the
curvatures, so an uneven comb is worth fixing before any simulation.

## Simplify

*Simplify* replaces the control points by fewer ones whose profile, with the same
interpolation, stays within a tolerance \(\varepsilon\) of the current one. The distance
between profiles is the symmetric Hausdorff distance between their dense polylines.
Each point's nearest vertex on the other polyline is found with a k-d tree, then the
exact distance to the two segments on either side of it is taken. The mouth and top
points are always kept, so the mouth and top-hole locks still hold.

* **Straight segments**: Ramer-Douglas-Peucker [RDP]. Kept points are a subset of the
  originals, and every removed point lies within \(\varepsilon\) of the new segments.
  If that needs as many points as there are now, the smallest tolerance that removes at
  least one point is found by bisection. The edit is then refused, because it would
  exceed \(\varepsilon\).
* **Spline**: greedy insertion. Start with the two ends. Repeatedly add the sample of the
  original curve furthest from the current fit, until the fit is within \(\varepsilon\).
  It stops when the number of points would not fall. New points lie on the original
  curve.

A volume lock moves the simplified profile back to the locked volume. The reported
deviation is measured before that correction.

**Validated by** `tests/unit/test_profile_editing.py` (falloffs; soft weights; transforms;
straight sections are collinear to 1e-12; smoothing removes a kink; curvature of a circle;
Hausdorff distance of a shifted arc; spline simplify within tolerance for 10, 2 and
0.5 mm; straight-segment simplify keeps only the corners of a cone-cylinder-cap profile;
a Hypothesis property that each point moves by its weight),
`tests/unit/test_edits_profile_tools.py` (one undo per edit, locks held, refusals leave
the design unchanged) and `tests/gui/test_gui_profile_tools.py`.

References:

- [Farin] G. Farin, *Curves and Surfaces for CAGD*, 5th ed., Morgan Kaufmann, 2002 —
  curvature, fairing, interpolating splines.
- [RDP] D. H. Douglas, T. K. Peucker, "Algorithms for the reduction of the number of
  points required to represent a digitized line or its caricature", *Cartographica*
  10(2), 1973.
- [Taubin] G. Taubin, "A signal processing approach to fair surface design", SIGGRAPH
  1995.
- Blender manual, *Proportional Editing* (falloff profiles).
