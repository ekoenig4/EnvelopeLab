# Simulation preview: inflated shape, forces and wrinkles

The simulation preview predicts how an envelope **as sewn from your patterns** settles when
inflated: its 3D shape, the fabric forces, the load-tape forces and where the fabric is
likely to wrinkle. It is meant to update quickly while you change a profile, fabric, seam,
temperature or tape layout.

!!! danger "A design aid, not a certification"
    The preview is not certified engineering software and does not replace structural
    verification, testing or an airworthiness approval. The builder is responsible for
    airworthiness. Results marked **NOT CONVERGED**, any **FAIL** in the factor-of-safety
    table and any temperature exceedance must be resolved before you rely on a design.

## What you need

1. A build pack that imports and sews cleanly ([Importing patterns](importing-patterns.md)).
   The preview starts from the as-sewn rest model: the flat shape of every panel, its grain
   arrow and material zone, and every seam with its load tape.
2. A fabric for every material zone, and a tape material for every `load_tape` name, each
   value tagged `datasheet`, `measured` or `assumed`.
3. A load case: internal temperature (or densities), altitude and ISA deviation.

## Running a preview from Python

```python
from envelopelab.assembly.pipeline import import_build_pack
from envelopelab.materials.membrane import MaterialValue as V, MembraneMaterial, TapeMaterial
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions, model_from_rest_model
from envelopelab.solvers.results import summary_markdown

pack = import_build_pack("my-envelope/build-pack.yaml")
nylon = MembraneMaterial(
    name="coated nylon",
    stiffness_warp=V(1.0e5, "N/m", "measured"),
    stiffness_weft=V(0.8e5, "N/m", "measured"),
    shear_stiffness=V(5.0e3, "N/m", "assumed"),
    poisson_warp_weft=V(0.3, "-", "assumed"),
    areal_mass=V(0.065, "kg/m^2", "datasheet"),
    strength_warp=V(1.5e4, "N/m", "datasheet"),
    strength_weft=V(1.4e4, "N/m", "datasheet"),
    seam_efficiency=V(0.8, "-", "measured"),
    max_service_temperature=V(393.15, "K", "datasheet"),
)
tape = TapeMaterial("25 mm tape", V(5.0e4, "N", "measured"), V(7.0e3, "N", "datasheet"))
conditions = OperatingConditions.hot_air(internal_temperature=373.15, altitude=500.0)
model = model_from_rest_model(
    pack.rest_model,
    {"default": nylon},
    conditions,
    {"25 mm load tape": tape},
    fixed_openings=("mouth",),
    closed_openings=("crown",),
)
result = solve(model)
print(summary_markdown(model, result))
```

`closed_openings=("crown",)` treats the crown ring as closed by a parachute whose pressure
is carried by the ring. Leave it out to model an open vent. The rest model places the
mouth at \(z = 0\), which is the default zero-pressure level (`mouth_height`) of
`OperatingConditions`.

In the desktop app the same solve runs on a background thread (`SolverJob`), so the window
stays responsive; the progress bar follows the residual and **Cancel** stops the solve.
After a small change the app restarts from the previous shape (a *warm start*), which is
usually faster than a fresh solve.

## Reading the results

| Result | Unit | What it shows |
|---|---|---|
| Deformed shape | m | Equilibrium node positions; export with `write_obj`. |
| Displacement map | m | Movement from the initial (as-sewn guess) shape, not from the flat patterns. |
| Principal resultants \(N_1\), \(N_2\) | N/m | True fabric force per unit width; \(N_2 \approx 0\) where the fabric wrinkles. |
| Warp / weft resultants | N/m | Force along the yarns, compared with the fabric strength. |
| Wrinkle-zone map | – | taut, wrinkled (tension in one direction only) or slack (no tension). |
| Released compression | N/m | The compression the fabric could not carry; larger values mean stronger wrinkling. |
| Tape tension | N | Force in every tape element; slack tapes show 0. |
| Force balance | N | Pressure, weights and loads against the support reactions. |
| Factor of safety | – | Strength / largest load for each fabric zone (warp, weft), seam and tape. |

Every quantity carries its unit, and the result metadata records convergence status,
iterations, final residual, mesh size, material sources, load case, run time, git commit,
dependency versions and the design content hash.

### What the results mean

- **Shape:** where the sewn panels settle for this load case. Lobes between tapes, a
  narrowing near the mouth and a flatter crown appear if the patterns produce them.
- **Wrinkle zones:** regions where the fabric cannot be taut in every direction. Real
  fabric forms visible wrinkles or folds there; the preview marks the region but does not
  draw individual wrinkles.
- **Forces:** membrane and tape forces in equilibrium with pressure and weight. Wrinkled
  regions pass load only along one direction, so nearby tapes pick up more.

### What the results do not mean

- They are not a certification, a guarantee of strength or a flight clearance.
- They do not include wind, gusts, burner pressure, dynamic inflation, deflation,
  landing loads, fabric ageing, heat damage, porosity or creep.
- The exact position of wrinkled fabric between tapes (and of the tapes crossing it) is
  only loosely determined and changes with the mesh by 10 % or more; read displacements
  of wrinkled regions as indicative. Volume and crown position are mesh-converged.
- The factor of safety uses the required value you give (default 5, tagged *assumed*):
  take the value from the airworthiness code that applies to your build.
- Values tagged `assumed` in your materials make every result that depends on them an
  estimate.

## Warnings

| Code | Severity | Meaning and action |
|---|---|---|
| `not_converged` | error | The solve stopped before equilibrium (iteration or time limit, cancel, divergence). Do not use the result; refine or fix the model and solve again. |
| `unconstrained` | error | No support: fix the mouth ring or add constraints. |
| `temperature_exceedance` | error | Internal temperature above a fabric's service limit. |
| `large_strain` | warning | Fabric strain above 10 %: outside the material model; check stiffness values. |
| `compression_residual` | warning | Compression left in wrinkled fabric above 1 % of the largest tension. |
| `wrinkles` | info | Share of the fabric in wrinkled or slack state. |
| `tape_slack` | info | Tape elements with no tension (common where the fabric is taut). |

## Mesh size and run time

The solve time grows faster than the mesh size. Use a coarse mesh (for example 1–2 m edge
length on a 7 m radius envelope) while iterating on a design and refine for checking.
Fine meshes with large wrinkled regions can take much longer (a 5 000-node mesh of the
generic envelope needed 25 min). Measured on the development container (one CPU thread, generic spherical
envelope, 100 °C, tolerance 1e-6):

| Mesh | Nodes | Fresh solve | Warm start after 100 → 90 °C |
|---|---|---|---|
| 1 700 mm | 696 | 9.6 s | 5.5 s |
| 850 mm | 1 908 | 41 s | 37 s |

The [preview solver benchmarks](../validation/preview-solver-benchmarks.md) list the
accuracy checks and the mesh-refinement study; the [theory page](../theory/dynamic-relaxation.md)
gives the equations, assumptions and limitations.

## Checking a final design with CalculiX

For final design studies, cross-check the preview with the CalculiX verification solver
(install it first: [CalculiX installation](../dev/calculix-installation.md)). Start it from
the preview's result; it re-solves the same model with an independent finite-element code
and reports `converged` only when its own equilibrium checks pass:

```python
from calculix_adapter import run_calculix
from envelopelab.solvers.simulation import from_preview
from envelopelab.validation.comparison import compare_results

check = run_calculix(model, start_positions=result.positions)
comparison = compare_results(from_preview(model, result), check)
print(comparison.to_markdown())  # rows above 5 % are marked "beyond tolerance"
```

A result that is not `converged`, or a comparison with flagged rows, is not a
verification: look at `check.findings` and at the
[known differences](../validation/preview-vs-calculix.md#known-differences-and-limitations) before using
the numbers. `check.manifest.save("run.json")` records everything needed to repeat the
run.
