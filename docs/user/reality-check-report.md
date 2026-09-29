# Reality Check report

The Reality Check report compares the shape you *intend* (a reference mesh, the numbers
on your drawings) with the shape predicted from the patterns you will actually sew. Use
it before cutting cloth for any special-shape feature: a pod, blister, horn, antenna or
fin.

!!! danger "Design aid only"
    EnvelopeLab is not certified engineering software. A report is **verified** only when
    the CalculiX verification solve converged within the documented tolerances. Preview
    results are never verified, and a result that did not converge is not a prediction.
    The builder is responsible for airworthiness.

## 1. Describe the feature in the build pack

Features live in a `features:` section of the build-pack YAML, next to `import:` and
`assembly:`. Everything specific to your design goes here (never in code):

```yaml
features:
  - name: pod_left
    kind: ram_air_pod          # ram_air_pod | blister | tubular | line_supported | ...
    host: {ring: body, gores: [3, 5], rows: [C, E], margin_mm: 1500}
    footprint: {piece: pod_footprint}       # the line marked on the envelope
    skin: {piece: pod_skin, strips: {file: pods.dxf, layer: PIECING}}
    skin_zone: black
    rim: {seam: pod_rim, match_points: 12, tape: "rim tape", caught_into_host_tapes: true}
    feed_holes: [{opening: "body/D@4:feed"}]
    pressure: {mode: fed, loss_factor: 0.1}   # assumed; see the theory page
    intended: {dome_height_mm: 600}
    construction:
      - {step: strip_seams}
      - {step: ordinate_check, tolerance_mm: 10}
      - {step: gore_assembly}
      - {step: feed_holes}
      - {step: rim_tape}
      - {step: ease_onto_envelope}
```

* The footprint is placed with its bounding box on the named gores and rows; its height
  is checked against the rows.
* The rim seam in `assembly:` declares the designed ease (`designed_ease_mm`). It is
  classified *designed ease*, not a seam error, and it is passed to the solver.
* Tubes (`kind: tubular`) take `skin: {instance: <part>}` and a `tube:` block naming the
  pattern edges (`base_edge`, `neck_edge`, `side_a`, `side_b`), the base mark on the host,
  the tip mass and lift of an end piece that is not modelled, and optional internal ties.
  A doubled base panel is declared with `doubler: {instance: ...}` and must be caught into
  all its surrounding seams at gore assembly.
* An optional `reference:` section names the reference mesh (`mesh`, OBJ/STL/PLY, `scale`
  in m per unit), its frame (`rotate_z_deg` about the vertical axis relative to the build
  pack) and a document whose title carries the volume notation (`title_source`).

## 2. Run the check

```python
from envelopelab.report.feature_workflow import FeatureRunConfig, feature_reality_check
from calculix_adapter import run_calculix  # optional verification solver

cfg = FeatureRunConfig(
    materials={"ripstop": my_fabric, "black": my_black_fabric},
    tapes={"rim tape": my_tape, "25 mm load tape": my_tape},
    internal_temperature=373.15,  # K
    verify=lambda model, start: run_calculix(model, start_positions=start),
    sweep=True,
)
run = feature_reality_check("my-pack/build-pack.yaml", "pod_left", cfg)
run.report.write_all("reports/pod_left")  # HTML, PDF, JSON and CSV
```

Every material value must carry its source tag (`datasheet`, `measured`, `assumed`); the
report repeats them.

## 3. Read the report

**Banner.** `VERIFIED: ...` (green) or `NOT VERIFIED: <reason>` (red). The reason says
exactly what is missing: no CalculiX solve, CalculiX not converged, error findings, or
solver settings looser than the documented tolerances.

**Three states side by side**, each with its label on the view and in every export:

| state | label | meaning |
|---|---|---|
| as-sewn rest shape | `AS-SEWN REST SHAPE (geometry, not solved)` | the assembled patterns in their starting geometry |
| inflated, predicted | `PREDICTED - PREVIEW SOLVER (converged, not verified)` or `PREVIEW - NOT CONVERGED` | dynamic relaxation |
| inflated, verified | `VERIFIED - CalculiX ...` or `CalculiX - NOT VERIFIED` / `NOT CONVERGED` | CalculiX |

The colour is the **signed distance to the registered reference** (blue: inside the
reference, red: outside); without a reference it is the major stress resultant.

**Dimensions.** Heights, widths and volumes of each state, the projected feature
dimensions (dome height above the host, footprint, rim lengths, lean of a tube), the
intended values from the build pack and the values measured on the reference mesh, the
reference's title volume and the as-sewn envelope volume.

**Critical load paths and factors of safety.** The most loaded tapes with their factor of
safety, and the fabric factor of safety per material zone (required 5, an assumed value:
use the one your airworthiness code requires).

**Findings.** Errors first: unconverged solves, factors of safety below the required
value, construction-sequence errors, seam errors, feature geometry that disagrees with
the design (for example a tube pattern whose side seams are equal although a lean is
intended), mesh adjustments, the registration quality and the scope note.

**Sensitivity sweep** (preview solver, never verified): internal temperature
\(\pm 10\) K, fabric stiffness \(\times 0.8/1.2\), material weight \(\times 0.8/1.2\),
seam-length error \(\pm 5\) mm per rim segment and the pressure-loss factor
\(\times 0.5/2\). Each row gives the metric at the low and high value and the slope when
both ends converged.

**Exports.** `reality-check.html`, `reality-check.pdf`, `reality-check.json`
(`envelopelab.reality-check` v1) and `reality-check-csv/` (states, dimensions,
deviation, load paths, FoS, convergence, features, sensitivity, findings). Every CSV
starts with the verification status line.

## 4. Reference meshes

Any OBJ, STL (ASCII or binary) or PLY (ASCII or binary) triangle mesh can be the
reference (`envelopelab.io.reference_mesh.read_mesh`). It is registered to the
simulation by ICP: with the optional Open3D package (`pip install envelopelab[registration]`)
its point-to-plane ICP is used, otherwise a SciPy point-to-point ICP; the backend is
recorded in the report. For a feature on an otherwise axisymmetric envelope give the
reference frame (`rotate_z_deg`): ICP alone cannot tell where round the axis the feature
sits, and only the host outside the footprint is used for the fit, so that the feature is
what gets compared.

## Limitations

* Appendage external aerodynamics (wind, climb) and turbulent flow are outside the model
  scope; shapes and loads are for still air.
* Reinforced holes and rim tapes are modelled as parts of a pod, blister or tube (feed
  holes with hem tapes, the rim tape); a standalone sub-model of either is not supported
  yet.
* Features are solved as sub-models of the host; the envelope far from the feature is
  not re-solved with it.
* Heavily eased flat skins wrinkle over most of their area; their solves are slow and
  mesh-dependent. Check convergence and refine the mesh before relying on a dome height.
