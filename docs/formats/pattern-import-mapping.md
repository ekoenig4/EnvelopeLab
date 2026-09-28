# Pattern import mapping (build-pack YAML)

_The field tables on this page are generated from the Pydantic models in
`envelopelab.io.pattern_import` and `envelopelab.assembly.spec` by
`scripts/generate_pattern_mapping_docs.py`; do not edit by hand._

Every build pack gets one YAML file, stored next to its DXF files, with two sections:

* `import` - how to read the DXF files: which layers carry cut lines, sew lines,
  dimensions, feature marks, tape lines, match marks, notches, grain arrows and labels;
  how labels are parsed (regular expressions); units, seam allowance and per-piece
  overrides.
* `assembly` - how the imported pieces are sewn: gore rings, instance overrides (feature
  openings, embedded marks, material zones), parts, explicit seams with metadata
  (including designed ease), declared openings, mesh settings and the initial-shape
  method.

Nothing about a particular design is built into EnvelopeLab; everything design-specific
belongs in this file. Lengths are in **mm** in the file and converted to SI (m) on load.
`mapping_version` is recorded in the provenance of every imported entity and in the rest
model, so give the file a new version whenever you change it.

## Conventions

* **Pattern frame.** Patterns are read in a frame with +y pointing up the envelope (towards
  the crown), seen from the outside of the fabric. Use `up_axis` and `pattern_face` when a
  pack is drawn differently. Outlines are normalised to counter-clockwise order.
* **Pieces.** Every closed outline on a cut layer is a piece. A cut outline inside another
  one without its own label is a hole of that piece. Sew lines, labels and marks belong to
  the innermost cut outline that contains them.
* **Labels.** Each text entity inside a piece is matched against the `labels` rules in
  order; the first match names the piece. Named groups: `panel` (id), `quantity` (cut
  count) and `mirror` (any match marks the piece as also cut mirrored); `piece_id` is a
  template over the named groups (default `"{panel}"`).
* **Cut and sew lines.** If a piece has a sew line, it is the finished outline. Otherwise
  the cut line is inset by the seam allowance (`seam_allowance_mm`, overridable per file
  and per piece). A zero allowance means the cut line is the finished edge.
* **Flattening.** Circles, arcs, bulges and splines are flattened with a maximum chord
  error of `flatten_tolerance_mm`; a closed curve is shortened by about 2.1 times that
  value (0.1 mm at the default 0.05 mm).
* **Edges.** A finished outline is split into edges at corners (turning angle above
  `corner_angle_deg`, measured over a 20 mm arc window). Four-corner pieces get the edges
  `bottom`, `right`, `top`, `left`; others `e0`, `e1`, ... from the corner nearest the
  bottom-left; outlines without corners have a single edge `loop`.
* **Instances.** Ring panels are named `<ring>/<row>@<gore>` (for example
  `envelope/N@4`); parts use their `name`. Edge references are
  `{instance: ..., edge: ...}` or `{instance: ..., mark: ...}` for embedded marks and
  instance openings.
* **Orientation.** `reversed` (default) means the start of side A is sewn to the end of
  side B, as for two panels lying side by side. `same` is used when an appendage is sewn
  onto a marked line or hole rim, whose loop runs counter-clockwise.
* **Designed ease** (`designed_ease_mm`) is the intended excess length of side B over side
  A. It is not reported as a seam error and is passed to the structural simulation.
* **Attachment seams** (`attachment: true`) sew an appendage onto a line marked on a
  panel surface. The mesh edges along that line have three triangles by design and are
  reported separately from non-manifold edges.

## `import` section

### `ImportMapping`

Per-build-pack pattern import mapping (the ``import`` section of the YAML file).

| Field | Type | Default | Description |
|---|---|---|---|
| `format_version` | `Literal[1]` | `1` | Mapping file format version (currently 1). |
| `mapping_version` | `str` | **required** | Version of this mapping; recorded in every provenance. |
| `units` | `Literal['auto', 'mm', 'cm', 'm', 'in', 'ft']` | `'auto'` | Drawing unit; auto reads $INSUNITS. |
| `seam_allowance_mm` | `float` | **required** | Default seam allowance. |
| `flatten_tolerance_mm` | `float` | `0.05` | Max chord error when flattening circles, arcs and splines; a closed curve comes out about 2.1 x this value short. |
| `join_tolerance_mm` | `float` | `0.5` | Gap closed when chaining line segments into outlines. |
| `duplicate_vertex_tolerance_mm` | `float` | `0.2` | Consecutive vertices closer than this are merged. |
| `pattern_face` | `Literal['outside', 'inside']` | `'outside'` | Side of the fabric the patterns are drawn from; inside mirrors them. |
| `up_axis` | `Literal['+y', '-y', '+x', '-x']` | `'+y'` | Drawing direction that points up the envelope. |
| `layers` | `LayerMap` | **required** | Layer names per role (applies to every source unless overridden). |
| `labels` | `list[LabelRule]` | `[]` | Label rules, tried in order; the first match names the piece. |
| `sources` | `list[SourceSpec]` | **required** | DXF files of the build pack. |
| `pieces` | `dict[str, PieceOptions]` | `{}` | Per-piece overrides keyed by piece id. |
| `default_material_zone` | `str` | `'default'` | Material zone of pieces without an override. |
| `default_grain` | `tuple[float, float] \| None` | `None` | Grain direction used when a piece has none. |
| `corner_angle_deg` | `float` | `30.0` | Turning angle above which an outline vertex is a corner. |

### `LayerMap`

DXF layer names for each pattern role (case-insensitive).

| Field | Type | Default | Description |
|---|---|---|---|
| `cut` | `list[str]` | `[]` | Cut lines (outer cut outline). |
| `sew` | `list[str]` | `[]` | Sew (finished) lines. |
| `dimension` | `list[str]` | `[]` | Dimension annotations. |
| `feature` | `list[str]` | `[]` | Feature marks: holes, appendage footprints, etc. |
| `tape` | `list[str]` | `[]` | Load-tape paths. |
| `match_mark` | `list[str]` | `[]` | Match marks. |
| `notch` | `list[str]` | `[]` | Notches. |
| `grain` | `list[str]` | `[]` | Grain arrows (line from tail to head). |
| `label` | `list[str]` | `[]` | Text labels. |
| `ignore` | `list[str]` | `[]` | Layers that are known but deliberately not imported (no warning). |

### `LabelRule`

A regular expression that recognises a piece label.

| Field | Type | Default | Description |
|---|---|---|---|
| `pattern` | `str` | **required** | Python regular expression matched against label text. |
| `piece_id` | `str` | `'{panel}'` | Piece id template filled from named groups. |
| `kind` | `Literal['panel', 'appendage', 'mark']` | `'panel'` | panel (envelope panel), appendage (separate skin) or mark (not cut). |
| `quantity` | `int \| None` | `None` | Fixed cut count; overrides a `quantity` group. |
| `ignore_case` | `bool` | `False` | Match the pattern case-insensitively. |

### `SourceSpec`

One DXF file of the build pack, with optional per-file overrides.

| Field | Type | Default | Description |
|---|---|---|---|
| `file` | `str` | **required** | Path relative to the mapping file. |
| `layers` | `LayerMap \| None` | `None` | Replaces the global layer map. |
| `units` | `Literal['auto', 'mm', 'cm', 'm', 'in', 'ft'] \| None` | `None` | Drawing unit of this file (overrides the global units). |
| `seam_allowance_mm` | `float \| None` | `None` | Seam allowance for pieces in this file. |
| `labels` | `list[LabelRule] \| None` | `None` | Replaces the global label rules for this file. |

### `PieceOptions`

Per-piece overrides keyed by piece id.

| Field | Type | Default | Description |
|---|---|---|---|
| `quantity` | `int \| None` | `None` | Cut count (overrides the label; reported as info). |
| `kind` | `Literal['panel', 'appendage', 'mark'] \| None` | `None` | Piece category (overrides the label rule). |
| `material_zone` | `str \| None` | `None` | Material zone of the piece. |
| `grain` | `tuple[float, float] \| None` | `None` | Grain (warp) direction in the pattern frame. |
| `seam_allowance_mm` | `float \| None` | `None` | Seam allowance of the piece. |
| `corner_angle_deg` | `float \| None` | `None` | Corner detection threshold for the piece. |
| `notes` | `str \| None` | `None` | Free text shown in reports and quantity warnings. |

## `assembly` section

### `AssemblySpec`

The ``assembly`` section of a build-pack YAML file.

| Field | Type | Default | Description |
|---|---|---|---|
| `kind` | `Literal['standard_gore', 'special_shape']` | **required** | standard_gore (rings only) or special_shape (rings plus appendages). |
| `rings` | `list[RingSpec]` | `[]` | Gore rings. |
| `instances` | `list[InstanceOverride]` | `[]` | Changes applied to selected ring instances. |
| `parts` | `list[PartSpec]` | `[]` | Single piece instances outside the rings. |
| `seams` | `list[SeamSpec]` | `[]` | Explicit seams between edge chains. |
| `openings` | `list[OpeningSpec]` | `[]` | Declared openings made of instance edges. |
| `mesh` | `MeshOptions` | defaults | Triangulation settings. |
| `initial_shape` | `InitialShapeSpec` | defaults | Initial 3D guess settings. |

### `RingSpec`

Standard gore construction: rows stacked into gores, gores joined into a ring.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | **required** | Ring name, used in instance ids <ring>/<row>@<gore>. |
| `gore_count` | `int` | **required** | Number of gores. |
| `rows` | `list[str]` | **required** | Piece ids from bottom to top. |
| `first_gore` | `int` | `1` | Number of the first gore. |
| `bottom` | `BoundarySpec` | **required** | Open boundary along the bottom edges of the first row. |
| `top` | `BoundarySpec` | **required** | Open boundary along the top edges of the last row. |
| `edges` | `dict[Literal['bottom', 'top', 'left', 'right'], str]` | `{'bottom': 'bottom', 'top': 'top', 'left': 'left', 'right': 'right'}` | Edge names used for each side of a row piece. |
| `horizontal_seam` | `SeamProperties` | defaults | Metadata of the seams between rows. |
| `vertical_seam` | `SeamProperties` | defaults | Metadata of the seams between gores. |
| `open_seams` | `list[OpenSeamSpec]` | `[]` | Vertical seams left unsewn (e.g. turning vents). |
| `material_zone` | `str \| None` | `None` | Overrides piece zones. |

### `BoundarySpec`

An open ring boundary (mouth or crown) and its hem.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | **required** | Opening name. |
| `kind` | `Literal['mouth', 'parachute_opening', 'vent', 'feed_hole', 'feature_opening']` | **required** | Opening kind. |
| `hem` | `SeamProperties \| None` | `None` | Hem (rim seam) metadata. |

### `OpenSeamSpec`

A vertical ring seam left unsewn over some rows (e.g. a turning vent).

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | **required** | Opening name. |
| `gores` | `tuple[int, int]` | **required** | The two neighbouring gores, e.g. [15, 16]. |
| `rows` | `list[str]` | **required** | Rows over which the seam stays open. |
| `kind` | `Literal['mouth', 'parachute_opening', 'vent', 'feed_hole', 'feature_opening']` | `'vent'` | Opening kind. |
| `hem` | `SeamProperties \| None` | `None` | Hem (rim seam) metadata. |

### `SeamProperties`

Seam metadata shared by ring seams, explicit seams and hems.

| Field | Type | Default | Description |
|---|---|---|---|
| `allowance_mm` | `float \| None` | `None` | Expected allowance on both sides (None: not checked). |
| `allowance_a_mm` | `float \| None` | `None` | Side A allowance. |
| `allowance_b_mm` | `float \| None` | `None` | Side B allowance. |
| `stitch_rows` | `int` | `2` | Number of stitch rows. |
| `stitch` | `str \| None` | `None` | Stitch/seam construction name. |
| `load_tape` | `str \| None` | `None` | Load tape type sewn in the seam. |
| `designed_ease_mm` | `float` | `0.0` | Intended length excess of side B over side A (not an error). |
| `construction_order` | `int` | `0` | Assembly step number. |
| `orientation` | `Literal['reversed', 'same']` | `'reversed'` | reversed: side A start meets side B end (normal for panels that lie side by side); same: starts meet (appendage sewn onto a marked line). |
| `tolerance_mm` | `float` | `3.0` | Allowed length mismatch. |
| `notes` | `str \| None` | `None` | Free text. |

### `SeamSpec`

An explicit seam between two edge chains.

| Field | Type | Default | Description |
|---|---|---|---|
| `allowance_mm` | `float \| None` | `None` | Expected allowance on both sides (None: not checked). |
| `allowance_a_mm` | `float \| None` | `None` | Side A allowance. |
| `allowance_b_mm` | `float \| None` | `None` | Side B allowance. |
| `stitch_rows` | `int` | `2` | Number of stitch rows. |
| `stitch` | `str \| None` | `None` | Stitch/seam construction name. |
| `load_tape` | `str \| None` | `None` | Load tape type sewn in the seam. |
| `designed_ease_mm` | `float` | `0.0` | Intended length excess of side B over side A (not an error). |
| `construction_order` | `int` | `0` | Assembly step number. |
| `orientation` | `Literal['reversed', 'same']` | `'reversed'` | reversed: side A start meets side B end (normal for panels that lie side by side); same: starts meet (appendage sewn onto a marked line). |
| `tolerance_mm` | `float` | `3.0` | Allowed length mismatch. |
| `notes` | `str \| None` | `None` | Free text. |
| `name` | `str` | **required** | Unique seam id. |
| `type` | `Literal['horizontal_panel', 'vertical_gore', 'reinforcement', 'appendage', 'rim', 'closing']` | **required** | Seam type. |
| `a` | `list[EdgeRef \| RingBoundaryRef]` | **required** | Side A: chain of edge or ring-boundary references in sewing order. |
| `b` | `list[EdgeRef \| RingBoundaryRef]` | **required** | Side B: chain of edge or ring-boundary references in sewing order. |
| `attachment` | `bool` | `False` | Side A is a line marked on a panel surface (T-junction seam). |

### `EdgeRef`

One edge of an instance: a named outline edge, an embedded mark or an opening.

| Field | Type | Default | Description |
|---|---|---|---|
| `instance` | `str` | **required** | Instance id. |
| `edge` | `str \| None` | `None` | Outline edge name (bottom, right, top, left, e0.., loop). |
| `mark` | `str \| None` | `None` | Embedded mark or instance opening name. |
| `reverse` | `bool` | `False` | Traverse the edge backwards. |

### `RingBoundaryRef`

All bottom or top edges of a ring, in gore order.

| Field | Type | Default | Description |
|---|---|---|---|
| `ring` | `str` | **required** | Ring name. |
| `boundary` | `Literal['bottom', 'top']` | **required** | bottom or top edges of the ring, in gore order. |

### `InstanceOverride`

Changes applied to the selected ring instances.

| Field | Type | Default | Description |
|---|---|---|---|
| `select` | `InstanceSelect` | **required** | Which ring instances to change. |
| `material_zone` | `str \| None` | `None` | New material zone. |
| `openings` | `list[InstanceFeature]` | `[]` | Feature openings cut in the instances. |
| `marks` | `list[InstanceFeature]` | `[]` | Feature marks embedded in the mesh. |
| `notes` | `str \| None` | `None` | Free text. |

### `InstanceSelect`

Selects ring instances by ring, rows and gores (empty = all).

| Field | Type | Default | Description |
|---|---|---|---|
| `ring` | `str` | **required** | Ring name. |
| `rows` | `list[str]` | `[]` | Row piece ids (empty = all rows). |
| `gores` | `list[int]` | `[]` | Gore numbers (empty = all gores). |

### `InstanceFeature`

A feature opening or embedded mark in selected instances.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | **required** | Name of the opening or mark within the instance. |
| `feature` | `FeatureSelector` | **required** | Selects the feature entity in the piece. |
| `kind` | `Literal['mouth', 'parachute_opening', 'vent', 'feed_hole', 'feature_opening']` | `'feature_opening'` | Opening kind (ignored for marks). |
| `hem` | `SeamProperties \| None` | `None` | Hem (rim seam) metadata for openings. |

### `FeatureSelector`

Selects one feature entity (circle or closed polyline) inside a piece.

| Field | Type | Default | Description |
|---|---|---|---|
| `circle_radius_mm` | `float \| None` | `None` | Select circles of this radius. |
| `near_mm` | `tuple[float, float] \| None` | `None` | Feature centre closest to this point. |
| `entity_id` | `str \| None` | `None` | DXF handle. |
| `tolerance_mm` | `float` | `2.0` | Radius match tolerance. |

### `PartSpec`

A single piece instance outside the rings (appendage, mirrored copy, ...).

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | **required** | Instance id of the part. |
| `piece` | `str` | **required** | Piece id. |
| `mirror` | `bool` | `False` | Use the mirror image of the piece. |
| `material_zone` | `str \| None` | `None` | Overrides the piece zone. |
| `mesh` | `bool` | `True` | False: seam graph and audit only. |
| `reason` | `str \| None` | `None` | Why the part is not meshed. |

### `OpeningSpec`

An explicitly declared opening made of instance edges.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | **required** | Opening name. |
| `kind` | `Literal['mouth', 'parachute_opening', 'vent', 'feed_hole', 'feature_opening']` | `'feature_opening'` | Opening kind. |
| `edges` | `list[EdgeRef]` | **required** | Edges forming the opening. |
| `hem` | `SeamProperties \| None` | `None` | Hem (rim seam) metadata. |
| `reason` | `str \| None` | `None` | Why the boundary is left open (shown in reports). |

### `MeshOptions`

Triangulation settings (all lengths in mm).

| Field | Type | Default | Description |
|---|---|---|---|
| `target_edge_length_mm` | `float` | `300.0` | Interior target edge length. |
| `seam_edge_length_mm` | `float \| None` | `None` | Edge length along seams (default 0.5 x target). |
| `corner_edge_length_mm` | `float \| None` | `None` | Edge length at corners (default 0.5 x seam). |
| `hole_edge_length_mm` | `float \| None` | `None` | Edge length on holes and marks (default 0.5 x seam). |
| `appendage_edge_length_mm` | `float \| None` | `None` | Edge length on appendage seams (default = hole). |
| `refinement_distance_mm` | `float \| None` | `None` | Distance over which sizes grow to the target (default 1.5 x target). |
| `growth` | `float` | `1.3` | Growth ratio of boundary spacing away from corners. |
| `min_quality` | `float` | `0.3` | Triangle quality below which the mesh check fails. |
| `algorithm` | `Literal['frontal_delaunay', 'delaunay', 'meshadapt']` | `'frontal_delaunay'` | Gmsh 2D algorithm. |

### `InitialShapeSpec`

Initial 3D guess for the as-sewn rest model (never the inflated shape).

| Field | Type | Default | Description |
|---|---|---|---|
| `method` | `Literal['gore_revolution', 'reference_mesh']` | `'gore_revolution'` | gore_revolution, or reference_mesh (project onto an OBJ). |
| `reference_mesh` | `str \| None` | `None` | OBJ file (m), relative to the YAML file. |
| `appendage_lift` | `float` | `0.5` | Outward offset of unplaced nodes per m of distance. |

## Complete example

`tests/fixtures/special_shape/build-pack.yaml` (generic special-shape fixture):

```yaml
# Generic special-shape fixture: a 6-gore body with a tube appendage sewn to a hole in
# panel B of gore 1, closed by a cap. The tube base is 40 mm longer than the hole rim
# (designed ease). Generated by tests/fixtures/generate_generic_fixtures.py.
import:
  mapping_version: generic-special-shape/1
  units: auto
  seam_allowance_mm: 25
  default_grain: [1.0, 0.0]
  layers:
    cut: [CUT]
    sew: [SEW]
    feature: [FEATURE]
    tape: [TAPE]
    grain: [GRAIN]
    label: [NOTES]
  labels:
    - pattern: '^PANEL\s+(?P<panel>[A-Z])\s+x(?P<quantity>\d+)$'
    - pattern: '^(?P<panel>TUBE|CAP)\s+x(?P<quantity>\d+)$'
      piece_id: "{panel}"
      kind: appendage
  sources:
    - file: patterns.dxf
  pieces:
    TUBE: {material_zone: appendage}
    CAP: {material_zone: appendage}

assembly:
  kind: special_shape
  rings:
    - name: body
      gore_count: 6
      rows: [A, B, C]
      bottom: {name: mouth, kind: mouth}
      top: {name: crown, kind: parachute_opening}
      horizontal_seam: {allowance_mm: 25, construction_order: 1}
      vertical_seam: {allowance_mm: 25, load_tape: "25 mm load tape", construction_order: 2}
  instances:
    - select: {ring: body, rows: [B], gores: [1]}
      openings:
        - name: tube_hole
          kind: feature_opening
          feature: {circle_radius_mm: 300}
          hem: {load_tape: "12 mm tape", construction_order: 3}
  parts:
    - {name: tube, piece: TUBE}
    - {name: cap, piece: CAP}
  seams:
    - name: tube_closing
      type: closing
      a: [{instance: tube, edge: right}]
      b: [{instance: tube, edge: left}]
      allowance_mm: 25
      construction_order: 4
    - name: tube_base
      type: appendage
      orientation: same
      a: [{instance: body/B@1, mark: tube_hole}]
      b: [{instance: tube, edge: bottom}]
      designed_ease_mm: 40
      allowance_b_mm: 25
      load_tape: "12 mm tape"
      construction_order: 5
    - name: tube_cap
      type: appendage
      a: [{instance: tube, edge: top}]
      b: [{instance: cap, edge: loop}]
      allowance_mm: 25
      construction_order: 6
  mesh:
    target_edge_length_mm: 300
```
