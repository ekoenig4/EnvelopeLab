# Solved shape vs drawn profile

_Module: `envelopelab.project.profile_match`; edits: `envelopelab.project.edits`
(`compensate_profile`, `adopt_solved_profile`, `restore_profile_target`)._

The drawn meridian profile of a standard-gore design is the tape line the builder
*intends*. The patterns cut from it inflate to the shape that equilibrium gives. Tapes
stretch, the gores lobe and the crown flattens, so the inflated tape line can differ
from the drawn one by much more than the build tolerance. The gore editor draws the
solved tape line of the latest preview and CalculiX run over the profile. It can then
change the profile in one of two ways:

* **compensate**: change the cut so that the patterns inflate onto the intended line;
* **adopt**: make the drawn line the shape the patterns actually fly.

## Solved tape line

The initial shape places gore \(g\) of \(G\) between the azimuths \(2\pi g/G\) and
\(2\pi(g+1)/G\) ([virtual sewing](virtual-sewing.md)). So the nodes of the vertical seams,
which carry the load tapes, are the nodes whose *initial* azimuth is a multiple of
\(2\pi/G\). Each seam is walked from the mouth along the mesh edges that join its nodes.
A seam whose nodes do not form one simple path is skipped. This happens for a turning
vent simulated open, where two unsewn edges lie on the same line. The read is refused
when fewer than half the seams are found, which means the gore count is wrong.

Along a seam, the material station is the normalised arc length of the *initial* seam
line:

\[
\sigma = \frac{1}{S}\int_0^{s} \lvert \mathbf{x}_0'\rvert \, ds \in [0, 1].
\]

This equals \(s/L\) on the drawn profile, because the initial shape is a surface of
revolution parameterised by meridian arc length [Struik]. Each seam's solved points
\((\sqrt{x^2+y^2},\, z)\) are joined by a cubic spline in \(\sigma\). Straight chords
between nodes one mesh edge apart would sag by \(\ell^2/8R\): 27 mm for 0.8 m edges on a
3 m radius. The seams are then averaged at common stations. The solved line is shifted in
height so that the mouth, which the solver holds fixed, sits at the drawn mouth height.
The largest distance of a single seam from the mean is reported. A non-zero spread means
the result is not axisymmetric.

**Check.** Reading the *initial* positions of the 800 mm fixture model gives the drawn
profile back within 0.4 mm. A uniform stretch of a revolved mesh is measured exactly
(`tests/unit/test_profile_match.py`).

## Deviation

The reported deviation is measured against the intended profile: the compensation target
when there is one, else the drawn profile. It gives:

* the largest and RMS distance from the solved seam nodes to the closest point of the
  profile curve, in the meridian plane. These are the nodes themselves, so no
  interpolation error enters;
* the largest offset between solved and intended points of the same station, which is
  what compensation corrects;
* the change of height and of maximum diameter.

The solved line is only known to about the mesh resolution, because its nodes are one
mesh edge apart.

## Compensation (inverse problem)

With \(\mathbf{C}(\sigma)\) the drawn (cut) profile, \(\mathbf{Q}(\sigma)\) the solved line
of a run of that cut, \(\mathbf{T}(\sigma)\) the target and \(\alpha \in (0, 1]\) the step
factor, one compensation step is the fixed-point update

\[
\mathbf{C}_{k+1}(\sigma) = \mathbf{C}_k(\sigma) - \alpha\bigl(\mathbf{Q}_k(\sigma) -
\mathbf{T}(\sigma)\bigr).
\]

This is the pattern-compensation idea of form finding: the cut is pre-deformed by the
opposite of the deformation under load [Bletzinger]. It converges when the inflated
shape follows a change of the cut roughly one to one.

The first step stores the drawn profile as the project's **target**. Later steps correct
towards that target and not towards the current cut line, which would drift. Every step
needs a new solve, because the previous run is stale once the profile changes.

**Measured convergence.** On the generic 8-gore fixture (800 mm preview mesh, \(\alpha =
1\)), the largest distance from the target fell 103 → 47 → 32 → 21 → 16 mm over four
steps. The height error fell 101 → 44 → 28 → 18 → 15 mm, and every solve converged. The
inflated shape follows a change of the cut by somewhat less than one to one, so the error
drops by roughly a third to a half per step.

Two alternatives were tried and rejected:

* A secant estimate of the step factor (\(\alpha = 1/J\),
  \(J = (1 - e_{k}/e_{k-1})/\alpha_{k-1}\), clamped to \([0.25, 1.5]\)) oscillated. It
  produced one unconverged solve and ended about where \(\alpha = 1\) did.
* Correcting only the offset normal to the target curve converged at the same rate as the
  station offsets.

The step factor therefore stays in \((0, 1]\). Lower it when a step does not reduce the
deviation. The target keeps the deviation before each step, so the convergence is
visible.

## Adoption

\[
\mathbf{C}(\sigma_i) \leftarrow \mathbf{Q}(\sigma_i)
\]

The drawn line becomes the solved line, and any target is dropped. The cut changes with
it, so its inflated shape changes again. Repeating adoption after each solve tends
towards a self-consistent profile whose patterns inflate onto themselves. The originally
intended shape is not kept.

## Flight shape

Adoption cuts the inflated tape line, and that line is the cut *stretched* by its load. A
pattern cut to it is longer than the one before, and it stretches again when inflated.
Repeated adoption therefore grows by the stretch every cycle: on the full-size fixture
(2600 m³, 20 gores, 1600 mm preview), +0.39 % of tape per cycle with tapes cut to the tape
line, and +0.67 % with tapes cut to the gore edge
([gore geometry](gore-geometry.md#vertical-tape-length)).

The flight shape keeps the solved shape and takes the stretch out
(`profile_match.flight_shape_points`, edit `fit_flight_shape`):

\[
\mathbf{C}(\sigma) = \mathbf{M} + c\,\bigl(\mathbf{Q}(\sigma) - \mathbf{Q}(0)\bigr)
  + \sigma^2\,\bigl(r_t - C_r(1)\bigr)\,\mathbf{e}_r ,
\]

with \(\mathbf{M}\) the drawn mouth point (held by the rigging), \(r_t\) the design
top-opening radius and \(c \approx L_d / L_s\) corrected until the curve is the design's
tape length \(L_d\). The top opening is held separately: its ring stretches more than the
tapes (1.2 % against 0.38 % on that fixture). One factor for the whole line would cut the
opening 35 mm wider in radius every cycle.

**Measured, full-size fixture, tapes cut to the tape line, 1600 mm preview, 10 cycles.**
The tape length stays at 20.906 m within 1 mm, and the stretch taken out is 0.38–0.39 %
each cycle. The shape does not settle. It keeps getting taller and narrower: the height
gain per cycle falls from +474 mm to +113 mm of solved over drawn, about 3 % less each
cycle, and the drawn height rises 15.14 → 16.20 m while the volume falls 2600 → 2458 m³.
The re-cut gore widths follow the narrower profile, which moves the equilibrium again. A
fixed point, if there is one, lies far from the drawn design. Use the update one or two
cycles at a time and watch the deviation, or hold the shape with *Compensate* instead.

## Control points of an updated profile

Both updates keep the existing control points, moved to their new place, and the
design's interpolation (a spline for an adopted segment profile). Then, while the new
profile is more than the fit tolerance from the line it was built from, a control point is inserted at the station of largest error,
up to 40 points. A solved line usually has features that the few points of a drawn
profile cannot follow, such as the steeper rise off the fixed mouth.

On the fixture, the 5-point profile needs about 13 points to follow the line within the
editor's default 5 mm, and 21 points for 1 mm. The default is 5 mm, not the 1 mm
geometry tolerance, because the solved line itself is only known to about the mesh
resolution. A finer fit mostly follows mesh noise. The fit error is reported after every
update.

## Rules

* Only a **current and converged** run may drive an update. Stale and unconverged runs
  are still drawn, dotted, and flagged in the editor.
* *Fixed height*, *Fixed volume*, *Fixed maximum diameter* and the mouth and top-hole
  diameter locks refuse an update. The update changes these quantities on purpose.
* A segment profile (lines, arcs and curves) refuses compensation, because a solved line
  is none of these. Adoption makes it a spline, in the same command. Spline and
  straight-segment profiles keep their interpolation.
* *Fit profile to simulated shape* adopts from the latest current, converged run, the
  chosen solver first (`profile_match.usable_run_shape`). Without one, it adopts from
  a preview run it starts. An unconverged preview changes nothing.
* Each update is one undoable command. The target is an editor setting, like the locks.
  It is saved with the project but is not part of the undo history. *Restore intended
  profile* sets the drawn profile back to the target in one command.

## Assumptions and valid range

* Standard-gore rings, solved with the mouth fixed, as set up by
  `envelopelab.project.simulation.build_solver_model`.
* Points are matched by normalised station. This assumes the tape stretches nearly
  uniformly along its length, which holds for the small strains of load tapes.
* Axisymmetry: the seams are averaged, and their spread is reported.
* A compensated cut is verified only by a new solve of that cut. Its deviation from the
  target is what the editor reports.

## References

* [Struik] D. J. Struik, *Lectures on Classical Differential Geometry*, Dover (1988):
  surfaces of revolution parameterised by meridian arc length.
* [Bletzinger] K.-U. Bletzinger, R. Wüchner, F. Daoud and N. Camprubí, "Computational
  methods for form finding and optimization of shells and membranes", *Computer Methods
  in Applied Mechanics and Engineering* 194 (2005) 3438–3452.
