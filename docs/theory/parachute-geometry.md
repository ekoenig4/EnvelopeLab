# Parachute geometry

Module: `envelopelab.geometry.parachute` (pieces), `envelopelab.project.gore_design`
(design integration: overrides, findings, live outputs) and `envelopelab.mass_estimate`
(`estimate_parachute_mass`).

The parachute (crown valve) closes the crown hole of a gore envelope from inside. The
internal over-pressure holds it against the hole rim, where it overlaps the envelope by the
**seal overlap** \( \delta \) all round.

## Flat circular parachute

A design's parachute (`gores.parachute` in the [design schema](../formats/design-schema.md))
is a flat circular canopy of finished diameter \( D = 2R \), made of \( N \) identical gores
sewn to each other along radial seams and, at their inner ends, round a centre disc of
finished diameter \( 2r_c \). Each finished gore is an annular sector of angle

\[ \theta = \frac{2\pi}{N} \]

between the radii \( r_c \) and \( R \), with straight radial sides and circular-arc ends:

\[
L_\text{radial} = R - r_c, \qquad
L_\text{rim} = \theta R, \qquad
L_\text{inner} = \theta r_c, \qquad
A_\text{gore} = \frac{\theta}{2}\left(R^2 - r_c^2\right).
\]

So the \( N \) inner ends add up to the disc circumference \( 2\pi r_c \), and the finished
canopy area is \( N A_\text{gore} + \pi r_c^2 = \pi R^2 \). A new parachute gets

\[ D = D_\text{hole} + 2\delta, \qquad N = N_\text{envelope}, \qquad 2 r_c = 0.2\,D, \]

the centre fraction being a generic starting value to review, not a design rule. Cut
outlines add the seam allowance all round (mitred offset, as for envelope panels).

**Pattern frame.** A gore is drawn with its centreline on the \( y \) axis, the finished rim
arc through the origin and the parachute centre at \( (0, R) \): the rim is the *bottom*
edge and the inner end the *top* edge, as for envelope panels whose top points to the crown.

## Checks

Every edit re-checks the parachute (tolerance 3 mm, the seam-audit default):

* the two radial sides of a gore (sewn to the neighbouring gore) have the same length;
* the \( N \) inner ends match the disc circumference;
* the rim diameter \( L_\text{rim} N / \pi \) overlaps the hole by the design's seal
  overlap (a warning otherwise);
* a manual outline override is flagged, and is an error when the parachute spec changed
  after it was drawn.

In a build pack written with the parachute, its gores and disc are **audited, unmeshed
parts**: the radial seams and the centre seam are measured like every other seam, and the
rim is a declared `parachute_rim` opening with its hem tape.

## Mass

The parachute is part of the envelope mass and so of the lift margin: fabric from the cut
areas (\( N \) gores and the disc, each in its own zone), a radial tape on every radial
seam (\( N L_\text{radial} \)), a rim tape (\( N L_\text{rim} \)) and thread on the radial
and centre seams, with the same tape and thread values as the envelope (generic `assumed`
values unless measured ones are supplied). The parachute does not change the volume or the
lift: the volume is that of the surface of revolution closed by a flat disc at the hole.

## Assumptions and valid range

* Flat canopy: no fullness or doming is designed into the gores, and fabric stretch is
  neglected. A shaped or domed parachute is entered as a manual outline override.
* The solver does not mesh the parachute: it closes the crown with an unmeshed cap that
  carries the pressure to the hole rim (see [dynamic relaxation](dynamic-relaxation.md)).
  The parachute's own shape, the seal, and its centering and confluence line loads are
  not predicted.
* Arcs are sampled at no more than 0.5° per segment: chord errors are below 5e-6
  (lengths) and 2e-5 (areas), relative. Valid for \( N \ge 3 \) and \( 0 < r_c < R \).

## References

* D. Poynter, *Parachute Recovery Systems Design Manual*, Para Publishing (1991): flat
  circular canopies and gore layout.
* D. J. Struik, *Lectures on Classical Differential Geometry*, 2nd ed., Dover (1988): arc
  length and area of plane curves.
