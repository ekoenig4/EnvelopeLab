# Design editing: live outputs, constraint locks and staleness

Modules: `envelopelab.project.gore_design`, `envelopelab.project.dependencies`,
`envelopelab.project.edits`. All quantities are SI (m, m², m³, K, Pa, kg, N).

## Live outputs

The profile is the parametric cubic spline through the control points
\((r_i, z_i)\), sampled at 2001 points ([gore geometry](gore-geometry.md)). From it:

\[ V = \sum_i \frac{\pi}{3}(r_i^2 + r_i r_{i+1} + r_{i+1}^2)(z_{i+1} - z_i), \qquad
   A = \sum_i \pi (r_i + r_{i+1})\, \Delta s_i \]

and the gross lift with dry-air densities \( \rho = p / (R T) \)
([atmosphere](atmosphere.md)) at the design's ambient pressure and ambient and internal
temperatures:

\[ L = V (\rho_{amb} - \rho_{int})\, g . \]

The envelope mass is `envelopelab.mass_estimate.estimate_mass` of the cut panel rows
(finished rows plus seam allowances, times \(N\)), with fabric areal mass from the fabric
library (stored in g/m², converted to kg/m², source tag kept), and generic `assumed` tape
(0.02 kg/m) and thread (30 tex, 2.75 m per m of seam per stitch row, two rows) values. The
lift margin is \( L/g - m_{env} - m_{payload} \).

**Validated by** `tests/unit/test_gore_design.py`: a two-point (conical frustum) profile
gives \( V = \pi h (r_0^2 + r_0 r_1 + r_1^2)/3 \) and \( A = \pi (r_0 + r_1) \ell \) to
1e-9, and \(L\) equals the hand calculation (21.991 m³ × 0.2790 kg/m³ × 9.80665 m/s² =
60.17 N at 15 °C / 100 °C).

## Constraint locks

A lock holds the value its quantity had when it was switched on. After each profile edit
the control points are corrected:

| Locked | Correction |
|---|---|
| height \(H\) | \( z' = z_0 + k (z - z_0) \), \(k\) iterated until \(|H - H_0| \le 0.1\) mm |
| maximum diameter \(D\) | \( r' = k r \), iterated likewise |
| volume \(V\), diameter free | \( r' = k r \), \(k\) by Brent's method |
| volume, height free | \( z' = z_0 + k(z - z_0) \), \(k\) by Brent's method |
| volume, height and diameter | fullness \( r' = r_{max}(r/r_{max})^{1/k} \): keeps \(r_{max}\), moves the other radii (the mouth too) |
| gore count \(N\) | edits of \(N\) are refused |

Iteration is needed because the spline through scaled points is not the scaled spline (the
chord parameterisation changes). After correction every lock is checked (lengths 1 mm,
volume 0.1 %); an edit that cannot meet them raises `LockError` and changes nothing.

## Wizard profile

The new-design wizard uses a truncated superellipse of revolution
\( |r/R|^n + |(z - z_c)/b|^n = 1 \), \( R = D/2 \), cut at the mouth and top-opening radii;
\(b\) makes the cut height \(H\) and the exponent \(n \in [1.2, 12]\) (fullness; 2 is an
ellipse) is found by Brent's method so that \(V\) is the target. Eleven control points are
placed on it (the equator is one) and the height and diameter corrections above are
applied inside the root search. Valid range: targets whose volume lies between the
\(n = 1.2\) and \(n = 12\) shapes; outside it the wizard reports the achievable range.

## Staleness of derived artifacts

The design state is split into input groups (geometry, seam allowance, seam construction,
manual outlines, labels, grain, row zones, tape paths, feature locations, tapes, materials,
operating conditions, features, meta, rigging, scale variants). Each artifact reads some
groups and some upstream artifacts:

| Artifact | Reads | Upstream |
|---|---|---|
| profile | geometry | |
| patterns | geometry, seam allowance, manual outlines, labels, grain, row zones, tape paths, feature locations | |
| assembly | geometry, manual outlines, tape paths, feature locations, features, tapes | |
| rest mesh | grain, row zones | assembly |
| simulation | operating, materials, tapes, seam construction | rest mesh |
| flattening | geometry, manual outlines | |
| nesting | materials | patterns |
| export | meta, rigging, scale variants | nesting |

The fingerprint of an artifact is the SHA-256 of its input groups (canonical JSON) and its
upstream fingerprints. An artifact or run is *current* when it was built from the current
fingerprint and *stale* otherwise. The seam allowance is read only by the patterns branch
(the rest mesh is built from finished outlines), so changing it leaves the rest mesh and
simulations current. `tests/unit/test_project_dependencies.py` checks the table.

## Manual outline overrides and seam matching

An override replaces a row's finished outline by an edited polygon (right side up, left
side down, \(2k\) points). Seams are compared by length: each row's left and right sides
(the vertical seam between neighbouring gores) and each row's top with the next row's
bottom; a difference above 3 mm (AGENTS.md default) is an error. The build pack uses the
override as the sewn outline (cut outline = mitred offset by the allowance), so the seam
audit of the [pattern import](virtual-sewing.md) sees the same mismatch.

## References

* R. P. Brent, *Algorithms for Minimization without Derivatives*, Prentice-Hall (1973).
* D. J. Struik, *Lectures on Classical Differential Geometry*, 2nd ed., Dover (1988).
