# Parachute, red line, flying wires and turning vents

Module: `envelopelab.rigging` (`parachute`, `rings`, `flying_wires`, `turning_vents`,
`scoop`, `analysis`).
Benchmarks: [rigging benchmarks](../validation/rigging-benchmarks.md). All quantities are
SI; heights are those of the meridian profile, whose mouth is the zero-pressure level.

**Status.** These are design-stage estimates from closed-form statics and kinematics. They
are not a structural simulation of the parachute or the basket suspension: the envelope
simulation still closes the crown with an unmeshed cap that loads the crown ring (see
*Limitations*). Factor-of-safety failures are always shown as errors.

## Conventions

Vertical seam \(k\) (1..N) joins gore \(k\) and gore \(k+1\) and lies at azimuth
\(\varphi_k = 2\pi k/N\), counter-clockwise seen from above (seam N at 0). The hydrostatic
differential pressure is

\[ \Delta p(z) = (\rho_{amb} - \rho_{int})\,g\,(z - z_{mouth}) \]

([atmosphere](atmosphere.md)). Rigging loads are *limit* loads: static load times the
design's limit load factor \(n_{LF}\) (default 1.4, the minimum of 14 CFR 31.23). A line,
wire or load tape passes when breaking strength / limit load \(\ge\) the required factor of
safety (default 5, the fibrous-rigging factor of 14 CFR 31.25(b)). Both defaults are tagged
`assumed`; the builder sets the values the applicable rules require.

## Parachute

The parachute is a round fabric valve inside the crown, pressed by internal pressure
against the envelope around the crown opening (radius \(r_h\), height \(z_t\), the top of
the profile) over the seal overlap \(o\) (`gores.seal_overlap`, measured along the fabric).

*Seated shape.* The edge is the envelope point \(E\) at meridian distance \(s_E = L - o\);
the parachute meridian follows the envelope from \(E\) to the rim \(R = (r_h, z_t)\) and
then a spherical cap with rise \(h = 2 b\, r_h\) (billow \(b\)), sphere radius
\(\rho = (r_h^2 + h^2)/(2h)\). The flat panels are the gores of this surface of revolution,
cut with the envelope's small-bulge width model ([gore geometry](gore-geometry.md)) as one
panel row from the edge (wide end) to the apex, with the design's seam allowance.

*Lines.* One shroud line and one centralising line leave each radial seam. The shroud line
runs from \(E\) to the load tape at \(s_A = s_E - a\) (\(a\) = shroud attachment),
\(L_s = |E - A|\); the centralising line runs from \(E\) to the confluence
\(C = (0, z_t - d)\) on the axis, \(L_c = |E - C|\), where the red line is attached.

*Load.* Pressure over the overlap annulus is carried by contact with the envelope; pressure
over the hole is carried by the parachute fabric to its edge and so by the shroud lines.
Taking the pressure at the cap apex (the largest over the cap; conservative),

\[ F = \Delta p(z_t + h)\,\pi r_h^2, \qquad
   T_s = \frac{n_{LF}\,F}{n\,\sin\alpha}, \qquad \sin\alpha = \frac{z_E - z_A}{L_s}. \]

*Opening (red-line pull).* Pulling the red line by \(\delta\) lowers the confluence. With
taut, inextensible lines the edge moves on the circle of radius \(L_s\) about \(A\),
\(E(\psi) = A + L_s(\cos\psi, \sin\psi)\), and
\(z_C(\psi) = z_E(\psi) - \sqrt{L_c^2 - r_E(\psi)^2}\), so \(\delta(\psi) = z_C(0) - z_C(\psi)\).
The path ends where \(\delta\) stops increasing (lines straight) or the edge reaches the
axis. Reported travels:

* **seal open**: \(|E - R| \ge o\) — the overlap fabric can no longer lie against the rim;
* **full open**: in addition the annular gap between the edge ring and the envelope wall,
  \(A_g = 2\pi r_E\, d_w(E)\) with \(d_w\) the distance from \(E\) to the envelope meridian,
  equals the hole area \(\pi r_h^2\).

A parachute that cannot reach full open, or whose confluence would be pulled below the
mouth, is an error.

## Crown ring and centre ring

Both rings are thin circular rings under an axisymmetric radial line load \(q\) (outward
positive), whose hoop force is \(H = q\,a\) for ring radius \(a\) (tension positive).

*Crown ring* (rim of the crown opening, radius \(r_h\)). The envelope fabric pulls on it
along the meridian tangent, at an angle \(\beta\) above the horizontal (taken from a
second-order one-sided difference of the profile at the rim). Carrying a vertical force
\(F\) needs \(n_m = F/(2\pi r_h\sin\beta)\), so \(q = n_m\cos\beta\) and

\[ H_{crown} = \frac{F}{2\pi\tan\beta}. \]

The design uses \(F = \Delta p(z_t + h)\,\pi r_h^2\), the full pressure force over the
hole — the load path of the simulation's cap closure and an **upper bound** for a
parachute design, whose shroud lines take most of it to the load tapes lower down. A
meridian that turns inward below the rim puts the ring in compression (buckling is not
checked: warning); a horizontal meridian at the rim cannot hold it (error).

*Centre ring* (parachute apex, radius \(a\), where the radial tapes meet and the crown
line is attached). The cap is a pressurised spherical membrane of radius \(\rho\) with
isotropic resultant \(n = p\rho/2\), so

\[ H_{centre} = \frac{p\,\rho\,a}{2}. \]

A flat parachute cannot carry pressure as a membrane, so its centre-ring load is not
assessed (warning). The parachute panels end at the centre ring (the cap meridian runs
from the rim to radius \(a\)). The crown-line load is not computed. Both rings are
checked against their own required factor of safety (default 1.5 for a metal part,
14 CFR 31.25(a); `assumed`), at the limit load. References: W. C. Young, R. Budynas,
*Roark's Formulas for Stress and Strain*, ch. 9 and 13.

## Red line

The red line runs from the confluence down to a guide ring on the chosen load tape at the
mouth, then to the burner-frame attachment point nearest that tape:
\(L = |C - G| + |G - B| + \ell_{spare}\). Its pull force is not computed (it depends on
the pressure distribution over the parachute during opening), so its strength is not
assessed; the panel says so.

## Flying wires

The N load tapes end at the mouth ring (radius \(r_m\)). They are gathered in \(w\) equal
groups of \(g = N/w\) tapes; each group meets at a carabiner a height \(d\) below the mouth,
at the group's mean azimuth and centroid radius
\(r_c = r_m \sin(\pi g/N)/(g \sin(\pi/N))\). One wire runs from each carabiner to the nearest
of \(n_f\) frame points (radius \(R_f\), a height \(H_f\) below the mouth, first at azimuth
\(\alpha_0\)). With the suspended weight \(W = m_{payload}\, g\), equal vertical shares per
wire and per crow's-foot leg:

\[ T_j = \frac{n_{LF} W}{w\cos\theta_j}, \qquad
   t_k = \frac{T_j\cos\theta_j}{g\cos\beta_k}. \]

Wires are checked against the cable strength, legs against the vertical tape class
strength. Assumptions: rigid, level burner frame; the carabiner position is prescribed, so
horizontal equilibrium at the carabiner is not enforced and leg loads are estimates; the
envelope's own weight is carried by the fabric. \(N\) must be a multiple of \(w\) (error);
\(w\) not a multiple of \(n_f\) shares the frame points unequally (warning).

## Turning vents

A turning vent is a vertical seam left open over consecutive rows, a slot from \(s_0\) to
\(s_1\) along the tape, pulled open to a gap width \(w\). With the orifice equation (jet
speed \(v = \sqrt{2\Delta p/\rho_{int}}\), discharge coefficient \(C_d\)):

\[ \dot m = \int C_d\,w\sqrt{2\rho_{int}\Delta p}\,ds, \quad
   F = \int 2 C_d\,w\,\Delta p\,ds, \quad
   \tau = \pm\int r(s)\,2 C_d\,w\,\Delta p\,ds, \quad
   \dot Q = \dot m\,c_p (T_{int} - T_{amb}), \]

with \(c_p = 1007\) J/(kg K) (Incropera, Table A.4). The jet is tangential; the torque is
positive for a counter-clockwise rotation seen from above. Unbalanced vents (net side
force above 10 % of the summed thrust) and vents that cancel (net torque below 5 % of the
summed magnitudes) are warnings. A vent marked *simulate open* is left open in the
structural model (an `open_seams` entry of the build pack, hemmed with the vertical tape
class); otherwise the seam is simulated closed.

Assumptions: quasi-steady jet from a thin-walled slot of uniform width; no wind; uniform
densities; the vent does not change the envelope shape used for the jet.

## Scoop

An optional scoop continues the envelope below the mouth ring (radius \(r_m\)) over
\(k\) consecutive gores (all \(N\): a full skirt), as a conical frustum of depth \(H\)
flaring outward at \(\phi\) from the vertical: bottom radius \(r_m + H\tan\phi\), slant
length \(H/\cos\phi\). Each scoop panel is the gore of that frustum cut with the
envelope's width model, so its top edge equals the mouth row's bottom edge (the seam
matches). Its fabric defaults to the mouth row's zone (Nomex). A scoop reaching the burner
frame is a warning. Wind loads on the scoop and its effect on the mouth are not modelled.

## Mass

Parachute fabric, radial and edge tapes and thread (the envelope's mass estimate,
`envelopelab.mass_estimate`, applied to the parachute panels), crown and centre rings,
shroud and centralising lines, red line, flying wires, crow's-foot legs, vent control
lines and the scoop panels (with their tapes and thread) are
summed into the *parachute and rigging mass*, which the lift margin subtracts.

## Limitations

* The envelope simulation closes the crown with an unmeshed flat cap whose pressure force
  loads the crown-ring nodes; in the built balloon the shroud lines take that force to the
  load tapes at the attachment points. The difference is local to the top of the load
  tapes; modelling the parachute as a meshed membrane with shroud-line cables is planned.
* Opening travels are geometric; deflation rate, the red-line pull force and the effect of
  pressure on the parachute shape during opening are not predicted.
* Rigging analysis is available for standard-gore designs; special shapes report an info
  finding.

## References

* 14 CFR Part 31, *Airworthiness standards: manned free balloons*, §§31.23, 31.25, 31.27.
* FAA-H-8083-11B, *Balloon Flying Handbook*, ch. 2.
* F. M. White, *Fluid Mechanics*, McGraw-Hill, ch. 2, 3 and 6.
* F. P. Incropera et al., *Fundamentals of Heat and Mass Transfer*, Table A.4.
