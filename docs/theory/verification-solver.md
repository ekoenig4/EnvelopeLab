# CalculiX verification solver

Package: `calculix_adapter` (source `solvers/calculix_adapter/`): `detect` (finding
`ccx`), `deck` (input deck), `results` (output parsing), `analysis` (the staged solve),
`validation` (benchmarks and the preview comparison). Shared result and comparison code
lives in `envelopelab.solvers.simulation`, `envelopelab.solvers.manifest` and
`envelopelab.validation.comparison`. All quantities are SI: m, N, Pa; stress resultants in
N/m, tape forces in N.

The verification solver solves **the same model** as the
[preview solver](dynamic-relaxation.md) (`SolverModel`: flat rest triangles, grain, zones,
tapes, constraints, symmetry planes, loads, operating conditions) with an independent,
general-purpose nonlinear finite-element code, CalculiX CrunchiX, run as a separate
program (see [ADR-0005](../adr/ADR-0005-verification-solver-calculix.md) and the
[installation guide](../dev/calculix-installation.md)). The two solvers share only the
model definition and the load definitions; element formulation, equation solver and
equilibrium iteration are CalculiX's.

## Translation of the model

| EnvelopeLab | CalculiX |
|---|---|
| Membrane triangle, zone material, grain | `M3D3` membrane element (no bending), own `*ORIENTATION` (local 1 = warp mapped to the current shape), `*ELASTIC,TYPE=ANISO` with the plane stiffness \(D\) of the element, `*MEMBRANE SECTION` of nominal thickness \(t\) |
| Flat rest geometry (as-sewn misfit) | `*INITIAL CONDITIONS,TYPE=STRESS`: the exact rest-to-reference stress of every element |
| Tapes (vertical, horizontal, mouth, crown, hole lines) | one `SPRINGA` element per tape edge, `*SPRING,NONLINEAR` force-elongation table: \(T = (EA/L_0)(l - L_0)\) for \(l \ge L_0\), zero below |
| Hydrostatic pressure \(\Delta p(z)\), closures (parachute, caps) | consistent nodal forces `*CLOAD` per pass: \(f_a = \sum_e \tfrac{2p_a + p_b + p_c}{12}\,\tfrac12 (x_b - x_a)\times(x_c - x_a)\); cap resultants as in the preview |
| Fabric and tape weight, point/line/distributed loads | nodal forces `*CLOAD` |
| Fixed nodes (mouth ring, crown points) | `*BOUNDARY` |
| Symmetry planes | `*BOUNDARY` (plane normal to an axis) or `*EQUATION` \(n\cdot u = 0\) |

Stress resultants are recovered as \(N = t\,\sigma\) from CalculiX's Cauchy stress (printed
in the element's local axes); results do not depend on \(t\).

Pressure is applied as nodal forces rather than element pressure because CalculiX 2.21
stops with a segmentation fault for `*DLOAD` pressure on `M3D3` elements, and because the
applied force vector is then known exactly to the adapter (used for reactions and the
force balance). The follower character of the pressure is captured by re-evaluating the
loads at the start of every pass.

CalculiX's printed nodal forces (`RF`) contain the membrane forces only: spring elements
(tapes, stabilisation springs) are left out. The adapter adds the tape forces itself, with
the same force-elongation law as the deck.

## Material: tension field by iterative membrane properties

The fabric law is the preview solver's St. Venant–Kirchhoff tension-field membrane. For a
pass the tension-field state of every element (taut, wrinkled, slack; same criterion as the
preview) and the wrinkle direction \(n\) are frozen, which makes the law linear in the
Green strain \(E\) (Voigt, engineering shear, fabric axes):

\[
S = D\,E, \qquad
D = \begin{cases}
\mathbb{C} & \text{taut}\\
(1-\kappa)\,E_n\,v v^\mathsf{T} + \kappa\,\mathbb{C} & \text{wrinkled},\quad v = (n_1^2, n_2^2, n_1 n_2)\\
\kappa\,\mathbb{C} & \text{slack}
\end{cases}
\]

with \(E_n = (v^\mathsf{T}\mathbb{C}^{-1}v)^{-1}\) the uniaxial stiffness along \(n\) and
\(\kappa\) the residual stiffness ratio (default \(10^{-3}\)). This is the *iterative
membrane properties* approach of Liu, Jenkins and Schur (2001): states and directions are
updated between passes. At a fixed point of the passes, \(S = D E\) is exactly the preview
solver's tension-field stress. A wrinkled element's \(D\) is fully populated, hence
`TYPE=ANISO` (thickness direction decoupled: plane stress).

## Stages

A **pass** solves the equilibrium of one frozen state: reference geometry \(x_r\),
element materials \(D\), initial stress \(\sigma_0\) = exact stress \(J^{-1} F (D E) F^\mathsf{T}\)
from the rest triangles to \(x_r\), and nodal loads \(f_{ext}(x_r)\). It runs two CalculiX
jobs.

1. **Held job (prestress).** Every node is held at \(x_r\); the printed forces plus the tape
   forces are the internal force \(f_{int}\) of the prestressed state, and
   \(B = f_{int} - f_{ext}\) is the out-of-balance force (at the symmetry-plane nodes its
   normal component is the plane's reaction and is not counted).
2. **Release job (nonlinear static inflation).** Static `NLGEOM` steps: a balanced start
   applying \(f_{ext} + B\) at once (`AMPLITUDE=STEP`), then ramp steps releasing \(B\) to
   zero (continuation; CalculiX ramps loads linearly within a step). `SPRING1` springs of
   stiffness \(k_s\) tie every node to \(x_r\) so that the Newton matrix stays positive
   definite on the near-mechanisms of wrinkled fabric.
3. **Continuation on failure.** A release job that does not complete is retried with twice
   the ramp steps (up to 32), then four times \(k_s\), then half the first increment.
4. The new reference is \(x_r + u\); states, directions and loads are re-evaluated.

Pass 1 establishes the prestress (form finding from the start geometry) and applies the
inflation loads over `ramp_steps` steps; later passes are balanced restarts. With the
tension field and a cold start, \(\kappa\) may be lowered pass by pass from `kappa_start`
to its final value.

### Warm start: frozen states, refreshed on settling

Started from a preview equilibrium (`start_positions`, the way the application and the
validation study run it), the passes use the final \(\kappa\) from pass 1 and keep the
states and wrinkle directions classified at the start **frozen** (`freeze_states`).
Re-classifying them every pass makes the passes wander. A wrinkled element is stiff only
along \(n\), so a few degrees' change of \(n\) moves its stress a lot. On the generic
8-gore fixture (800 mm mesh, 616 nodes) the old scheme never settled. Started from the
converged preview it went 60 passes (129 s) with the out-of-balance between 0.04 and 0.2.
The first pass at `kappa_start` = 0.1 alone moved the preview equilibrium by 23 mm.

When the passes have settled on the frozen material (movement, stress consistency and
out-of-balance within their tolerances), the frozen material is compared with the
tension-field law itself at the new geometry. This is the **law consistency**: the largest
difference between the frozen material's resultant and the preview law's resultant
(state and \(n\) from the strain at that geometry, final \(\kappa\)), relative to the
largest resultant. Above `stress_tolerance` the states are re-classified and the passes
continue. The re-classification has a hysteresis band \(\beta\) (`state_band`, default
\(10^{-3}\)) of the largest major trial resultant \(S\):

* a taut element is released only when \(s_2 < -\beta S\), and a released one becomes
  taut again only when \(s_2 > \beta S\);
* wrinkled and slack swap only when \(E_n\varepsilon_n\) leaves \(\pm\beta S\).

The law is continuous at both switch points, so inside the band either state gives the
same resultant within \(O(\beta S)\). That is half the stress tolerance.

With this scheme the fixture converges in one pass (4.4 s; out-of-balance
\(6.7\times10^{-7}\), law consistency \(7\times10^{-7}\)), and the validation envelope
runs 30–35 % faster with the same results. A cold start keeps the per-pass
classification and the \(\kappa\) continuation.

Because the springs are re-anchored every pass, their final force equals the
out-of-balance of the unstabilised problem at the new positions; the converged result does
not depend on \(k_s\). \(k_s\) starts at \(10^{-2}\) times the fabric stiffness, halves
after every pass and grows fourfold when a pass made the out-of-balance worse.

## Convergence and reported quantities

A result is `converged` only when **all** hold:

- a pass moved no node by more than 1 mm, changed the tension-field state of at most 0.5 %
  of the elements, and ended with CalculiX's stresses within 0.2 % (of the largest) of the
  exact law and an out-of-balance below \(10^{-5}\) of the load;
- the held job of the next pass, i.e. CalculiX's internal force for the exact law at the
  settled geometry, is below \(10^{-5}\) of the load;
- for a warm start with frozen states: the law consistency (above) is within 0.2 %. The
  frozen material then gives the tension-field law's stresses at the result, so the
  equilibrium is one of the law and not only of the frozen material;
- the global force balance (applied loads + mouth/tape/plane reactions) closes within
  0.5 % of the pressure resultant.

Anything else is reported with an error finding and status `not converged` (or `failed`
when a CalculiX job did not complete even at the continuation limits). The result is a
`SimulationResult` (same model as the preview's `from_preview`): positions, elements,
stress resultants and principal values, tape tensions, reactions per constraint and
symmetry plane, CalculiX Newton residual history, per-pass movement and out-of-balance,
CalculiX version, mesh size and elapsed time, and a run manifest (design and model hash,
material sources, solver settings, git commit, Python and dependency versions, mesh
settings, random seed).

## Assumptions and valid range

- Same as the preview solver: thin membrane without bending stiffness, St. Venant–Kirchhoff
  fabric (strains below about 10 %), tension-only tapes, quasi-static inflation, no
  contact. Valid for envelopes and scale models from about 0.3 m to 40 m.
- One CalculiX thread (`OMP_NUM_THREADS=1`) so that repeated runs give identical numbers.
- **Starting geometry: an equilibrium check, not independent form finding.** The start
  geometry does not enter the equilibrium equations, but CalculiX's Newton iteration must
  release the start's out-of-balance. On the generic envelope fixture it cannot: from the
  design shape the as-sewn misfit forces are about 90 times the pressure load and the
  release fails even at the continuation limits; from a shape 0.2–0.3 m away from
  equilibrium the passes stall near 10 % out-of-balance after 60 passes (with the tension
  field about 1 % of the elements change state every pass; without it the compressed
  fabric buckles). The validation study and the application therefore start CalculiX
  from the preview's equilibrium (`start_positions`). Without a current preview of the
  same mesh, the application solves one first and keeps it as its own run. The result is
  accepted only on CalculiX's own criteria.
  This verifies that the preview's shape, stresses, tape tensions and reactions are an
  equilibrium of an independent finite-element model; the preview remains the form-finding
  tool. The analytic benchmarks start from their stress-free initial shape.
- **Same discretisation class.** M3D3 elements are constant-strain triangles like the
  preview's, on the same mesh; the comparison checks equilibrium and its evaluation, and
  the mesh-convergence study addresses discretisation error.

## Why not shells

CalculiX `S3` thin shells (1 mm, negligible bending) reproduce the sphere and cylinder, but
on the sewn envelope they carried load through transverse shear in the expanded wedge
elements at the seam creases, so the membrane state was wrong. `M3D3` has no bending or
transverse shear, like the preview.

## References

- X. Liu, C. H. Jenkins and W. W. Schur, "Large deflection analysis of pneumatic
  envelopes using a penalty parameter modified material model", *Finite Elements in
  Analysis and Design* 37 (2001) 233–251.
- G. Dhondt, *The Finite Element Method for Three-Dimensional Thermomechanical
  Applications*, Wiley (2004); *CalculiX CrunchiX User's Manual*, version 2.21.
- L. F. Richardson, "The deferred approach to the limit", *Phil. Trans. R. Soc. A* 226
  (1927) 299–361; P. J. Roache, *Verification and Validation in Computational Science and
  Engineering*, Hermosa (1998), ch. 5 (mesh-convergence estimates).
