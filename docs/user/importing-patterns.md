# Importing patterns

This guide takes a build pack of flat DXF patterns to an **as-sewn rest model**: the
panels exactly as they will be cut and sewn, joined into one mesh that the inflation solver
starts from. Background and definitions are in
[Virtual sewing](../theory/virtual-sewing.md); every YAML field is listed in
[Pattern import mapping](../formats/pattern-import-mapping.md).

!!! warning "Design aid, not certification"
    EnvelopeLab checks geometry and seams; it does not certify a design. Treat every
    error in the reports as a blocker and every warning as something to understand. The
    builder is responsible for airworthiness.

## 1. What you need

* The pack's DXF files with **closed cut outlines** on one layer. Sew (finished) lines on
  another layer are optional but recommended.
* A label (text) inside each cut outline that names the piece, e.g. `PANEL C x20`.
* Optional layers for feature marks (holes, appendage footprints), tape lines, match
  marks, notches, grain arrows and dimensions.
* The seam allowance, and whether the drawing's `$INSUNITS` header is set (otherwise
  state the units).

## 2. Write the `import` section

Create `build-pack.yaml` next to the DXF files. Map layers to roles and describe the label
format with a regular expression:

```yaml
import:
  mapping_version: my-pack/1
  units: auto              # or mm, cm, m, in, ft
  seam_allowance_mm: 25
  default_grain: [1.0, 0.0]  # warp along the pattern x axis
  layers:
    cut: [CUT]
    sew: [SEW]             # leave out for cut-only packs
    feature: [FEATURE]
    label: [TEXT]
    ignore: ["0", Defpoints]
  labels:
    - pattern: '^PANEL\s+(?P<panel>\S+)\s+x(?P<quantity>\d+)'
  sources:
    - file: panels.dxf
```

Tips:

* Layers that are neither mapped nor ignored produce an `unknown_layer` warning, so
  nothing is dropped silently.
* Use several label rules for different piece types (`kind: appendage` for separate
  skins, `kind: mark` for outlines that are only marked, not cut). A rule's `piece_id`
  template can build ids from named groups, e.g. `"mouth_g{gore}"`.
* A cut-only pack works too: the finished outline is the cut line inset by the allowance.
  Set per-piece allowances under `pieces:` where they differ.

## 3. Describe how the pieces are sewn: the `assembly` section

For a standard gore envelope a ring is enough:

```yaml
assembly:
  kind: standard_gore
  rings:
    - name: envelope
      gore_count: 20
      rows: [A, B, C, D]          # bottom (mouth) to top (crown)
      bottom: {name: mouth, kind: mouth}
      top: {name: crown, kind: parachute_opening}
      vertical_seam: {allowance_mm: 25, load_tape: "25 mm load tape"}
```

Special shapes add:

* `instances`: per-panel changes, selected by ring, rows and gores: cut a feature opening
  (`openings`, e.g. a feed hole selected by its circle radius), embed a marked line
  (`marks`) or change the material zone (e.g. a doubled panel).
* `parts`: appendage pieces (use `mirror: true` for mirrored copies, `mesh: false` for
  parts that should only be audited).
* `seams`: explicit seams between edges, marks and ring boundaries. Declare intended
  length differences with `designed_ease_mm`; declare sewing onto a marked line with
  `attachment: true` and `orientation: same`.
* `openings`: boundaries that stay open (with a `reason`).

The generic special-shape fixture at the end of the
[format page](../formats/pattern-import-mapping.md#complete-example) is a complete example.

## 4. Run the import

```bash
envelopelab-import build-pack.yaml reports/
```

or from Python:

```python
from envelopelab.assembly.pipeline import import_build_pack
from envelopelab.assembly.reports import write_reports

result = import_build_pack("build-pack.yaml")
write_reports(result, "reports/")
print(result.status)  # PASS / FAIL / INCOMPLETE
```

Use `--no-mesh` to check the import and seam audit quickly, and `--target-edge-mm` to try
a different mesh size.

## 5. Read the reports

Open `reports/index.html`. Every page starts with the overall status.

| File | What to look at |
|---|---|
| `import-warnings.*` | Missing labels, unknown layers, invalid geometry, ambiguous seams, quantity differences and every assumption made (for example "finished outline = cut line inset by 25 mm"). |
| `panel-inventory.*` | Quantity, finished and cut area, material zone, grain and its source, where the finished outline came from, configured vs measured allowance, and the source entity of every piece. |
| `seam-audit.*` | Length mismatch of every sewn pair; errors above the tolerance, designed ease shown separately, unmatched and duplicate edges, allowance conflicts. |
| `seam-graph.*` | Every seam with its sides and metadata (CSV for reading, JSON for tools). |
| `mesh-report.*` | Manifoldness, boundary loops (each must be a declared opening), connected parts, orientation, triangle quality, inverted elements and rest area vs finished area. |
| `rest-model.json` | The as-sewn rest model for the inflation solver. |

Typical fixes:

* **Missing label**: the label text is outside the cut outline or does not match any
  rule; test the regular expression against the text shown in the warning.
* **No edge 'bottom'**: the corner detector did not find four corners; adjust
  `corner_angle_deg` for that piece, or refer to edges by `e0`, `e1`, ...
* **Length mismatch**: check the pairing and the pattern; if the difference is intended,
  declare it as `designed_ease_mm` on that seam.
* **Unintended hole**: an edge is not sewn; add the seam or declare the opening.

## 6. Limitations

* Marked lines that cross several panels (for example a pod footprint) cannot yet be
  embedded in the mesh; parts sewn to them are audited but must be `mesh: false`.
* Appliqués and doublers are not separate mesh layers; use a material zone.
* The initial 3D shape is a starting guess for the solver, never the inflated shape.
