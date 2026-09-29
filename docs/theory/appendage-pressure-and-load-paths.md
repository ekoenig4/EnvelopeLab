# Appendage pressure and load paths

Special-shape features (pods, blisters, tubes, antennae, fins, reinforced holes, rim
tapes) change both the inflated appearance of an envelope and the way its loads reach the
load tapes. This page states the model used by `envelopelab.features` and the solver
extension it relies on. The module docstrings carry the same equations.

## Gas chambers

Every membrane triangle separates two gases: the gas on its *inside* (opposite to its
normal) and the gas on its *outside*. Each is the main envelope gas, the ambient air or an
appendage **chamber** (`SolverModel.chambers`, `SolverModel.tri_chambers`). The pressure
acting along the triangle normal is

\[
p_{net}(z) = p_{inside}(z) - p_{outside}(z),
\]

with the envelope gas at
\( \Delta p(z) = p_0 + (\rho_{amb} - \rho_{int})\,g\,\max(z - z_{mouth}, 0) \),
the ambient air at 0 and a chamber at

\[
p_c(z) = p_{ref} + \frac{dp}{dz}\,(z - z_{ref}), \qquad
\frac{dp}{dz} = (\rho_{amb} - \rho_{gas})\,g .
\]

So a pod skin carries \(p_c\), the envelope fabric under the pod carries
\(\Delta p - p_c\), a diaphragm with the same gas on both sides carries nothing, and the
rest of the envelope carries \(\Delta p\). Both the preview solver and the CalculiX
adapter evaluate loads through the same `SolverModel.triangle_pressure`, so the two
solvers see identical loads. Unmeshed caps (`PressureClosure`) may belong to a chamber
(for example a ball on an antenna neck).

The gas volume of each region is computed by the divergence theorem over the triangles
that bound it (those with the gas inside, and, reversed, those with it outside), openings
capped by flat fans; feed holes between two regions cancel in the total. The gross lift
is \( L = \sum_k V_k\,(\rho_{amb} - \rho_{gas,k})\,g \). Models without chambers take the
original code path and give bit-identical results.

## Pressure communication

A pressure-fed appendage is filled with envelope gas through feed holes cut in the
envelope. The envelope pressure is sampled at the feed-hole centres (area-weighted) and
reduced by the **pressure-loss factor** \(k\):

\[
p_{ref} = (1 - k)\,\frac{\sum_i A_i\,\Delta p(z_i)}{\sum_i A_i}, \qquad
z_{ref} = \frac{\sum_i A_i z_i}{\sum_i A_i}.
\]

!!! warning "Assumption (source tag `assumed`)"
    The loss factor is not measured. It stands for the steady pressure lost through the
    holes and by leakage through skin coating and seams. The build packs in this
    repository use \(k = 0.1\); the sensitivity sweep of the Reality Check report varies
    it by a factor of two either way.

With \(k = 0\) (fully communicating) the envelope fabric under a pod carries no net
pressure once the pod lifts its rim: it goes slack and its shape is undetermined (a
mechanism), which neither solver can converge on (observed: the preview residual stalls
near \(10^{-3}\), CalculiX keeps changing wrinkle states). Any \(k > 0\) loads that fabric
outwards and makes the problem well posed. An appendage may instead be given an
independent pressure (a sealed blister, or a sensitivity study).

Valid range: \(0 \le k < 1\), feed holes above the mouth.

## Designed ease and match points

A skin whose rim \(L_s\) is longer than its footprint line \(L_f\) carries designed ease
\(e = L_s - L_f\). With \(N\) match points spaced by arc length on both loops, the rim
correspondence is piecewise linear between matching match points, so every segment holds
\(e/N\). The skin keeps its as-cut rest lengths: the ease is a physical input to the
solve, and the seam audit classifies the seam as *designed ease*, never a seam error:

* `matched`: no ease declared and \(|L_b - L_a| \le\) tolerance (3 mm);
* `designed ease`: \(|(L_b - L_a) - e| \le\) tolerance;
* `seam error`: anything else.

Without match points (pinning in order round the rim) the surplus pools in the last
segment (`ease_mode: pooled`), which the metrics show as a pucker.

## Feature sub-model

A feature is solved as a local sub-model: a patch of the host envelope around the
footprint with its edge nodes fixed, the feature skin, the tapes and the chambers.

**Host surface.** A surface of revolution about the vertical axis whose meridian is
locally a circle of radius \(R_1\) and whose parallel through the patch centre has normal
radius \(R_2\) and normal elevation \(\beta\), fitted to the host panels of the build
pack. The chart

\[
v = R_1\psi, \qquad u = \rho(\psi)\,\theta, \qquad
\rho(\psi) = \rho_c + R_1\cos(\beta+\psi), \quad z(\psi) = z_c + R_1\sin(\beta+\psi)
\]

is the panel-by-panel frame in which a footprint is marked on the envelope (\(v\) along
the meridian, \(u\) across the panels at that height). Panel points map to it through
\( \theta = \tfrac{2\pi}{G}(g - g_c + \tau - \tfrac12) \) with \(\tau\) the fraction across
the panel, as in the initial-shape placement.

**Host prestress.** The host rest geometry is the designed patch shrunk by the far-field
prestrain \( \lambda_i = \sqrt{1 + 2E_i} \), \( E = \mathbb{C}^{-1}N_\infty \), so the fixed
patch edge carries the envelope's membrane resultants. Without a global solution
\(N_\infty\) follows the membrane theory of shells of revolution (Timoshenko and
Woinowsky-Krieger, *Theory of Plates and Shells*, sec. 105):

\[
N_v = \frac{p R_2}{2}, \qquad N_u = p R_2\left(1 - \frac{R_2}{2R_1}\right) \ (\ge 0).
\]

**Skin.** Either the flat as-cut pattern (rim nodes placed by the match-point
correspondence) or, for analytic benchmarks, a designed spherical cap whose rest shape is
the cap itself. The initial guess is an equal-arc spherical cap scaled to start 3 % slack
(an over-stretched start makes the explicit solver take huge first steps); it does not
enter the equilibrium.

**Tapes.** Host tapes (gore and row seams crossing the patch) and the rim tape are
tension-only bars along mesh edges with the host's rest lengths. The rim tape is either
*caught into* every host tape it crosses (shared node: the pod load goes straight into
the host tapes) or stops a gap short of each crossing on both sides (the pod load
reaches the host tapes through the host fabric). Where a tape touches the footprint
tangentially or runs within \(0.3\,h\) of it (\(h\) the mesh size), the meshing moves it off
the tangency or lets it follow the footprint line; each such move is recorded as a note in
the report.

**Tubes.** A tube is made from a developed conical pattern with base, neck and two sides
sewn together; an oblique base edge, cut to the ray lengths
\( \varrho(\phi) = h_a\cos\lambda / (\cos\lambda\cos\gamma - \sin\lambda\sin\gamma\cos\phi) \),
leans the axis by \(\lambda\) from the host normal. The neck may be closed by a chamber cap
carrying the net weight of an unmodelled end piece; optional internal ties hold the
section round; line-supported appendages add tension-only lines to fixed anchors.

## Load paths and metrics

For both solvers the metrics are computed from the solver-independent result:

* projected (dome) height above the designed host surface, footprint normal displacement;
* rim-tape tension and the load each host tape picks up (its largest tension minus its
  far-field tension at the patch edge);
* the largest major resultant \(N_1\) of the host fabric next to the rim;
* fabric factor of safety \( \min(N_{ult,warp}, N_{ult,weft}) / \max N_1 \) per region
  (required 5, assumed);
* wrinkled and slack skin fractions, per rim segment between match points (a segment
  25 % above the mean is a predicted pucker);
* for tubes: centreline stations, tip displacement, base reaction (resultant of all loads
  on the tube, which equilibrium passes through the base) and lean against the intended
  lean.

## Assumptions and limits

* Still air. **Appendage external aerodynamics (wind, climb) and turbulent flow round
  appendages are outside the initial model scope.**
* The sub-model boundary is fixed on the designed host surface; keep the margin at least
  half the footprint size. The host far-field state is taken as uniform over the patch.
* Seam allowances, stitching and tape widths are not modelled as material.
* The tension-field membrane has no bending stiffness: a tube stands only on its pressure
  and the tension of its fabric (a heavy tip on a leaning tube kinks, and the solve then
  reports *not converged*).
* A flat-pattern skin eased onto a smaller rim must wrinkle over most of its area (its
  hoops shorten as it domes); convergence is then slow and mesh-dependent, and a result
  that does not converge is reported as such.

## References

* S. P. Timoshenko and S. Woinowsky-Krieger, *Theory of Plates and Shells*, 2nd ed.,
  McGraw-Hill (1959), sec. 105.
* I. E. Idelchik, *Handbook of Hydraulic Resistance*, 3rd ed., Begell House (1996), ch. 4.
* D. Poynter, *Parachute Recovery Systems Design Manual*, Para Publishing (1991), ch. 6.
* W. T. Tutte, "How to draw a graph", Proc. London Math. Soc. 13 (1963) 743-767.
* W. Kabsch, Acta Cryst. A32 (1976) 922-923.
