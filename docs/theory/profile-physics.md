# Profile under load: membrane check and shapes that hold

_Modules: `envelopelab.solvers.axisymmetric` (statics), `envelopelab.project.profile_physics`
(a design's load); edit: `envelopelab.project.edits.snap_profile_to_hold`._

A drawn profile can be one the patterns cannot inflate to. The gore editor checks the
profile under its load while it is edited, in milliseconds and before any mesh exists. It
also offers the nearest shape that does hold.

## Geometry and load

The meridian runs from the mouth (\(s = 0\)) to the top opening (\(s = L\)). Its tangent
angle \(\theta\) is measured from the horizontal: \(r' = \cos\theta\), \(z' =
\sin\theta\). The outward normal is \(n = (\sin\theta, -\cos\theta)\) and the meridional
curvature is \(\kappa_m = \theta'\). The loads are:

* the differential pressure \(p(z) = \gamma (z - z_0)\), with \(\gamma = (\rho_{amb} -
  \rho_{int}) g\). The dry-air densities come from the design's operating conditions;
  the pressure is zero at the open mouth;
* the weight per area \(w = m_{env} g / A\), from the envelope mass estimate (fabric,
  tapes, seams) spread over the fabric area;
* the parachute closing the top opening. It hands \(P_{top} = \pi r_L^2 p(z_L)\) to the
  rim as a vertical load.

## Membrane check

Membrane theory of shells of revolution (Timoshenko and Woinowsky-Krieger, ch. 16).
Vertical equilibrium of everything above a parallel gives the meridional resultant;
normal equilibrium gives the hoop resultant:

\[
N_m = \frac{V(s)}{2\pi r\sin\theta},\qquad
V(s) = P_{top} + \int_s^L(-p\cos\theta - w)\,2\pi r\,ds',\qquad
N_h = \frac{r\,(p + w\cos\theta - N_m\kappa_m)}{\sin\theta}.
\]

A gore envelope carries hoop load only in tension, in the fabric between its tapes, and
meridional load only in tension. A span that needs **hoop compression** (\(N_h <
-0.02\max N_m\)) or meridional compression cannot keep its drawn shape. The editor draws
it in thick red. A straight-segment profile turns at its kinks. A kink turning by
\(\Delta\theta\) puts \(F = N_m r\Delta\theta\) into the horizontal tape there; a concave
kink would need a compressed tape and is reported. Near-horizontal spans
(\(|\sin\theta| < 0.05\)) are not evaluated.

**Benchmarks** (`tests/benchmarks/test_axisymmetric.py`):

* a pressurised sphere gives \(N_m = N_h = pr/2\) within 0.2 %;
* a closed cylinder gives hoop \(pr\) and axial \(pr/2\) exactly;
* a cylinder under a hydrostatic gradient gives \(N_m = p(z_{top})R/2\) and
  \(N_h = p(z)R\) by hand.

**Check against the preview solver.** With the generic assumed fabric, the 8-gore
fixture needs hoop compression over the lowest 23 % of its tape (up to 33 N/m against
meridional resultants up to 88 N/m). With the example fabric library's fabric (another areal mass) the
editor shows 25 %. In a converged preview solve (800 mm mesh), that is exactly where the solved
tape line moves **inward**, by up to 62 mm. Above it the fabric is in hoop tension and the
shape holds; the line only drifts 30–50 mm outward with fabric and tape stretch.

## Natural shape

With zero hoop stress the tapes carry the whole load: the classic natural shape (Taylor;
Smalley). With \(T = 2\pi r N_m\):

\[
\theta' = \frac{2\pi r (p + w\cos\theta)}{T},\qquad T' = 2\pi r\,w\sin\theta.
\]

It is integrated from the mouth with RK4. The mouth angle and tension are shot (damped
Newton, from a coarse grid when the guess is poor) so that the end has the top-opening
radius and the rim balances the parachute, \(T_L\sin\theta_L = P_{top}\). The end is at
the design's tape length, or its height. Benchmarks:

* under uniform pressure from pole to pole the integration gives the Mylar balloon's
  thickness/diameter \(\sqrt2\,\pi^{3/2}/\Gamma(1/4)^2 = 0.59907\) within \(10^{-4}\)
  (Paulsen 1994);
* the check of a natural shape gives \(|N_h| \le 1\,\%\) of \(\max N_m\);
* the mouth reaction balances lift minus weight within 0.5 %.

The editor can draw the natural shape for comparison. It is usually far from a drawn
profile: for the fixture it is 1.5 m lower and 1.7 m wider at the same tape length. A
gore envelope does not need it, because its fabric carries hoop tension.

## Snap to a shape that holds

The nearest shape that holds keeps the drawn curvature wherever the check passes. Where
the check finds compression, the curvature is limited to the zero-hoop value
\(\kappa_m \le (p + w\cos\theta)/N_m\), and concave kinks are straightened. The curve is
rebuilt from the mouth over the same tape length, the mouth angle shot so that the curve
ends at the top-opening radius, and the check repeated until nothing changes; spans once
limited stay limited. The result is fitted with control points within the fit tolerance
(5 mm by default): a spline, or straight segments for a straight-segment profile.

**Fixture, converged preview solves at 800 mm:**

| | Needs compression | Preview iterations | Largest deviation | RMS | Lower quarter |
|---|---|---|---|---|---|
| Drawn | 23 % of the tape | 40k | 103 mm | 49 mm | collapses inward by 62 mm |
| Snapped | none | 211k | 48 mm | 29 mm | no inward collapse |

The remaining deviation is mostly growth (height +43 mm, diameter +79 mm) from tape and
fabric stretch; *Compensate* removes it (see
[Solved shape vs drawn profile](profile-matching.md)). A snapped shape has spans at zero
hoop stress, which the preview's dynamic relaxation settles slowly. The snapped fixture
needs 211k iterations at 800 mm, just above the default limit of 200k. A 10 % hoop
margin (\(N_h \ge 0.1 N_m\)) reduced the deviation only to 43 mm and doubled the
iterations, so the snap uses none.

On these zero-hoop spans kinetic damping resets thousands of times, and its path depends
on round-off. From starts perturbed by \(10^{-15}\) relative, the same solve converged in
82k–211k iterations or wandered past 600k. Viscous damping (`damping="viscous"`,
\(c = 0.05\)) converges the snapped fixture in 71k iterations from every such start. The
end-to-end test uses it.

## Assumptions and valid range

* Axisymmetric, quasi-static membrane without bending.
* Weight uniform per area.
* The meridian is inextensible: tape stretch is left to compensation.
* Lobing between tapes is not resolved: this is the global tape-line state.
* Valid while \(\sin\theta\) stays away from zero, from scale models to crewed sizes.

## References

* S. Timoshenko and S. Woinowsky-Krieger, *Theory of Plates and Shells*, 2nd ed.,
  McGraw-Hill (1959), ch. 16.
* G. I. Taylor, "On the shapes of parachutes" (1919), *Scientific Papers* III,
  Cambridge (1963).
* J. H. Smalley, "Determination of the shape of a free balloon", AFCRL-64-734 (1964).
* W. H. Paulsen, "What is the shape of a mylar balloon?", *American Mathematical
  Monthly* 101 (1994) 953–958.
