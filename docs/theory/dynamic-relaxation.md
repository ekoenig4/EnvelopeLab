# Dynamic-relaxation preview solver

Modules: `envelopelab.solvers.model` (input), `envelopelab.solvers.membrane` (element),
`envelopelab.solvers.dynamic_relaxation` (solver), `envelopelab.solvers.results`
(post-processing), `envelopelab.materials.membrane` (fabric and tape properties). All
quantities are SI: m, N, Pa, kg, K; stress resultants in N/m, tape forces in N.

The preview solver predicts the **inflated equilibrium** of an envelope *as sewn*: the
flat (as-cut) shape of every triangle comes from the patterns, and the 3D shape, membrane
forces, tape forces and wrinkle zones follow from equilibrium with the internal pressure,
weight and applied loads. It is an interactive preview, not the final high-fidelity
verification solver (see [ADR-0004](../adr/ADR-0004-preview-solver-dynamic-relaxation.md)).

## Input model

| Item | Meaning | Unit |
|---|---|---|
| Triangles with rest coordinates \(X_a\) | flat as-cut geometry (from the rest model) | m |
| Grain direction per triangle | warp axis in the flat frame (the pattern's grain arrow) | – |
| Material zone per triangle | `MembraneMaterial` (warp/weft stiffness, strength, mass) | N/m, kg/m² |
| Cable sets (tapes) | tension-only bars on mesh edges, rest length = flat seam length | N, m |
| Seam lines | mesh edges checked for seam factor of safety | – |
| Node constraints | fixed or prescribed nodes (mouth ring, crown points, supports) | m |
| Symmetry planes | nodes kept on a plane | – |
| Point, line, distributed loads | dead loads (rigging, appendages, coatings) | N, N/m, Pa |
| Pressure closures | openings closed by an unmeshed cap (parachute, end cap) | – |
| Operating conditions | \(\rho_{amb}\), \(\rho_{int}\), mouth height, \(g\), extra uniform \(p_0\) | kg/m³, m, m/s², Pa |

`model_from_rest_model` builds the model from a build pack's rest model: grain and zone per
instance, one cable set per seam that has a `load_tape`, the mouth ring fixed and chosen
openings closed.

## Membrane element

Constant-strain triangles in the fabric axes (1 = warp, 2 = weft). With the rest
coordinates rotated into fabric axes,

\[
F = \sum_a x_a \otimes \nabla N_a, \qquad E = \tfrac12\left(F^\mathsf{T} F - I\right),
\]

the Green–Lagrange strain \(E\), exact for large rotations. The St. Venant–Kirchhoff
orthotropic law in resultant form is

\[
\begin{bmatrix} S_{11} \\ S_{22} \\ S_{12} \end{bmatrix} =
\frac{1}{1-\nu_{12}\nu_{21}}
\begin{bmatrix} E_1 t & \nu_{12} E_2 t & 0 \\ \nu_{12} E_2 t & E_2 t & 0 \\
0 & 0 & (1-\nu_{12}\nu_{21}) G_{12} t \end{bmatrix}
\begin{bmatrix} E_{11} \\ E_{22} \\ 2E_{12} \end{bmatrix},
\qquad \nu_{21} = \nu_{12} E_2 / E_1,
\]

with second Piola–Kirchhoff resultants \(S\) (N/m). Isotropic fabric is the special case
\(E_1 = E_2\), \(G_{12} = E/(2(1+\nu))\) (`MembraneMaterial.isotropic`). Nodal internal
forces are the energy gradient \(f_a = A_0\, F S\, \nabla N_a\); reported stresses are the
true (Cauchy) resultants \(\sigma = J^{-1} F S F^\mathsf{T}\), \(J = A/A_0\).

### Tension field (wrinkling)

Fabric carries tension but no compression. With the trial stress \(S^\ast = \mathbb{C}:E\),
its principal values \(s_1 \ge s_2\) and major direction \(n\),
\(\varepsilon_n = n^\mathsf{T} E n\), each triangle is

| State | Condition | Stress |
|---|---|---|
| taut | \(s_2 > 0\) | \(S = S^\ast\) |
| wrinkled | \(s_2 \le 0\), \(\varepsilon_n > 0\) | \(S = E_n\varepsilon_n\, n\otimes n + \kappa(S^\ast - E_n\varepsilon_n\, n\otimes n)\) |
| slack | \(s_2 \le 0\), \(\varepsilon_n \le 0\) | \(S = \kappa S^\ast\) |

\(E_n = (v^\mathsf{T}\mathbb{C}^{-1}v)^{-1}\), \(v = (n_1^2, n_2^2, n_1 n_2)\), is the
uniaxial stiffness along \(n\) with free lateral contraction, so the stress is continuous
across both state changes. \(\kappa\) (`slack_stiffness_ratio`, default \(10^{-3}\)) keeps a
small stiffness in released directions so slack fabric has no zero-energy modes; the
residual compression it leaves is at most \(\kappa|s_2^\ast|\) and is reported
(`compression_residual` warning above `wrinkle_tolerance`, default 1 % of the largest
tension). Triangles in the wrinkled or slack state are the **probable wrinkle zones**; the
released compression \(\max(-s_2^\ast, 0)\) is available as a field.

The criterion is the mixed stress–strain criterion of Kang and Im; the wrinkle direction
is taken from the trial stress, which is exact for isotropic fabric and an approximation for
strongly orthotropic fabric.

## Loads

Differential pressure (internal minus ambient) at height \(z\):

\[
\Delta p(z) = p_0 + (\rho_{amb} - \rho_{int})\, g\, \max(z - z_{mouth}, 0).
\]

It acts normal to the *current* surface (follower load). On a triangle with nodal
pressures \(p_a\), area \(A\) and unit normal \(n\) the consistent nodal forces are
\(f_a = (2p_a + p_b + p_c)\, A\, n / 12\) (exact for linear \(\Delta p\)). An opening in
`closures` is closed by a flat fan cap from the loop centroid; its pressure resultant is
transferred to the ring nodes in proportion to their tributary length. Fabric weight
\(m_A A_0 g\) and tape weight \(m_L L_0 g\) use rest area and rest length (dead loads).
Point loads (N), line loads (N/m of initial length) and distributed tractions (Pa of rest
area) are dead loads.

For an open envelope \(\oint \Delta p\, n\, dA = (\rho_{amb}-\rho_{int})\,g\,V\,\hat z\) (the
cap over the mouth carries zero pressure), so the pressure resultant equals the gross lift
\(L = V(\rho_{amb}-\rho_{int})g\); both are reported and compared.

## Tapes and cables

Tension-only bars: \(T = EA\,\max(L/L_0 - 1, 0)\) with \(EA\) in N. Tapes from a build pack
use the flat seam length as \(L_0\) (averaged over both sides), so a tape is exactly as
long as the fabric edge it is sewn to.

## Boundary conditions and reactions

Each node has a projector \(P_i\) onto its free directions: \(P_i = 0\) for a fixed node,
\(P_i = I - \hat m\hat m^\mathsf{T}\) for a node on a symmetry plane with normal \(\hat m\),
or the free axes of a partially constrained node. Prescribed positions are applied before
the first step. Reactions are the removed residual components,
\(r_i = -(I - P_i)R_i\), grouped by constraint name (a symmetry plane gets the component
along its normal).

## Dynamic relaxation

With fictitious time step \(\Delta t = 1\) and nodal masses \(m_i\):

\[
R = F^{ext}(x) - F^{int}(x),\qquad
v_i^{t+\frac12} = v_i^{t-\frac12} + \frac{P_i R_i^t}{m_i},\qquad
x^{t+1} = x^t + v^{t+\frac12}.
\]

**Masses.** \(m_i = \lambda \sum_j |K_{ij}| / 2\), the Gershgorin bound of the tangent
stiffness with the full (taut) material matrix, the geometric stiffness of the current
stress and an estimate of the pressure load stiffness (\(\lambda\) = `mass_factor`,
default 1). This is twice the explicit stability limit \(m_i \ge \sum_j|K_{ij}|/4\); the
tension field only lowers the true stiffness, so the bound holds in every state. Masses
are recomputed at each kinetic-energy reset.

**Kinetic damping** (default). The kinetic energy \(KE = \sum \tfrac12 m_i|v_i|^2\) is
tracked; when it decreases the peak has passed, the positions are moved back to the
estimated peak \(x^\ast = x^t - \tfrac12 v^{t-\frac12}\), velocities are set to zero and
the next step uses half an acceleration step. **Viscous damping** (`damping="viscous"`)
uses \(v^{t+\frac12} = [(1 - c/2)v^{t-\frac12} + R/m]/(1 + c/2)\).

**Warm starts.** `solve(..., initial_positions=previous.positions)` restarts from an
earlier equilibrium (constrained nodes keep their prescribed positions), which is how the
GUI updates the preview after a small design change.

### Implementation of the element evaluation

Each iteration evaluates every triangle's deformation gradient, strain, tension-field
stress, internal corner forces and consistent pressure loads, and sums them onto the
nodes (`envelopelab.solvers.kernels.element_forces`). With the optional `fast` extra
(Numba, ADR-0019) this runs as one compiled loop. Otherwise the vectorized NumPy
functions of `envelopelab.solvers.membrane` are used. The two give the same forces to
round-off (relative 1e-12, `tests/unit/test_solver_kernels.py`), so the choice changes
only run time.

## Convergence criteria

| Status | Meaning |
|---|---|
| `converged` | \(\lVert P R\rVert_2 / \lVert F^{ext}\rVert_2 <\) `tolerance` (default \(10^{-6}\), AGENTS.md) |
| `max_iterations` | iteration limit reached |
| `time_limit` | wall-time limit reached |
| `cancelled` | the `CancellationToken` was set (checked every `progress_interval` iterations) |
| `diverged` | NaN or relative residual above \(10^8\) |

Every status other than `converged` adds an **error**-level `not_converged` warning and the
result metadata says "NOT CONVERGED – not a valid result"; factors of safety from such a
result report `not converged` instead of pass/fail. The residual history is sampled every
`progress_interval` iterations.

Other findings: `unconstrained` (error, no constraint or symmetry plane),
`temperature_exceedance` (error, internal temperature above a fabric's service limit),
`large_strain` (warning, major strain above 10 %), `compression_residual` (warning),
`wrinkles` and `tape_slack` (info).

## GUI integration

`SolverJob(model, settings, progress).start()` runs the solve on a worker thread;
`cancel()` sets the token, `done()` polls, `result(timeout)` waits. Progress callbacks run
on the worker thread (a Qt GUI forwards them with a queued signal). The solver itself holds
no global state and never blocks the caller's thread.

## Post-processing

`envelopelab.solvers.results` provides fields for heat maps (displacement from the initial
guess, pressure, principal and warp/weft/shear resultants, strains, area ratio, wrinkle
state, released compression, tape tension), the deformed mesh (OBJ export), the global
force-balance table, factors of safety and a JSON export (`envelopelab.preview-result`
v1) with units and metadata.

Factors of safety: fabric zone \(N_{ult}/\max N\) along warp and weft separately; seam
\(\eta\min(N_{ult,warp}, N_{ult,weft}) / \max N_{nn}\) with \(N_{nn}\) the resultant normal
to the seam edge and \(\eta\) the seam efficiency; tape \(T_{ult}/\max T\). The required
factor defaults to 5 (tagged *assumed*: take it from the applicable airworthiness code).

## Assumptions

- Membrane only: no bending stiffness; fabric folds and wrinkles are represented by the
  tension-field state, not resolved geometrically.
- Linear elastic, small strain (< 10 %) fabric; no creep, hysteresis, temperature-
  dependent stiffness or porosity.
- Constant strain per triangle; stresses are element averages.
- Static gas with uniform internal and ambient densities; no dynamic (wind, burner) pressure.
- Seam allowances are folded away; seams do not add stiffness or mass except through tapes.
- Tapes are straight bars between nodes, tension only, attached at every node they pass.
- Closures (parachute, end caps) are flat rigid caps that pass their pressure to the ring.

## Limitations

- The position of wrinkled fabric between tapes, and of the tapes crossing it, is only
  weakly determined by equilibrium. Maximum displacements there are **not** mesh-converged:
  on the generic spherical envelope a 425 mm mesh moved them by 9–12 % against 600 mm,
  while volume and crown rise changed by 0.15 % and 1.3 % (see
  [preview solver benchmarks](../validation/preview-solver-benchmarks.md)).
- Fine meshes with large wrinkled regions converge slowly: the 425 mm mesh (5 028 nodes)
  needed about 90 000 iterations (25 min) against about 10 000 at 600 mm.
- Wrinkle direction is approximate for strongly orthotropic fabric.
- Explicit iterations grow roughly linearly with the number of elements across the
  envelope; very fine meshes are slow in pure NumPy.
- No contact (fabric self-contact, basket, ground), no dynamic response, no deflation.
- Cross-checked against the CalculiX verification solver on the generic envelope (see
  [verification solver](verification-solver.md) and
  [preview vs CalculiX](../validation/preview-vs-calculix.md)).

## Valid range

Envelopes and scale models from about 0.3 m to 40 m, internal overpressures up to a few kPa,
fabric strains below 10 %, meshes with well-shaped triangles (quality \(\ge 0.3\)).

## References

- M. R. Barnes, "Form finding and analysis of tension structures by dynamic relaxation",
  *Int. J. Space Struct.* 14 (1999) 89–104.
- B. H. V. Topping and P. Iványi, *Computer Aided Design of Cable Membrane Structures*,
  Saxe-Coburg (2007), ch. 3.
- P. Underwood, "Dynamic relaxation", in *Computational Methods for Transient Analysis*,
  North-Holland (1983) 245–265.
- S. Kang and S. Im, "Finite element analysis of wrinkling membranes", *J. Appl. Mech.* 64
  (1997) 263–269.
- R. K. Miller and J. M. Hedgepeth, "An algorithm for finite element analysis of partly
  wrinkled membranes", *AIAA J.* 20 (1982) 1761–1763.
- J. Bonet and R. D. Wood, *Nonlinear Continuum Mechanics for Finite Element Analysis*,
  2nd ed., Cambridge University Press (2008).
- R. M. Jones, *Mechanics of Composite Materials*, 2nd ed., Taylor & Francis (1999).
- H. M. Irvine, *Cable Structures*, MIT Press (1981).
- E. H. Mansfield, *The Bending and Stretching of Plates*, 2nd ed., Cambridge University
  Press (1989), ch. 10.
