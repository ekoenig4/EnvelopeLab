# Shape file (`envelopelab.shape` v1 and v2)

A shape file is YAML (`*.yaml`). It holds a [shape family](../theory/shape-families.md)
and the values that fix one design of it. It is read by
`envelopelab.io.shape_file.load_shape_file` and by **New design ▸ From shape file**.
Examples:

* `tests/fixtures/smalley_90k/shape.yaml` (version 1);
* `tests/fixtures/flat_chord_pattern/shape.yaml` (version 2, a synthetic flat-chord
  pattern set);
* `tests/fixtures/flat_chord_pattern/special.yaml` (version 2, special shapes added to
  it with `extends`).

Version 1 holds the shape and its size. [Version 2](#version-2) adds everything else a
design needs: named rows, zones, gore construction, openings, rigging, special shapes and
`extends`. A pattern set is then described in the file itself, with no edits after
loading.

Lengths and volumes are written **with their unit** and converted to SI on load. Length
units are `m`, `cm`, `mm`, `ft` and `in`; volume units are `m^3` and `ft^3`. A bare number
is accepted only for stations (fractions of the gore length), so a missing unit is an error,
not a guess.

```yaml
format: envelopelab.shape
format_version: 1
name: Smalley 90K
description: free text
source: {file: source/Smalley_90K.xlsx, reference: "Balloon Builders Journal, Issues 1 and 22"}

profile:
  source: datasheet            # datasheet | measured | assumed
  stations:                    # [s, r], fractions of the pole-to-pole gore length L
    - [0.00, 0.00000]          # s = 0 bottom pole ... s = 1 top pole
    - [0.02, 0.01535]
    # ...
    - [1.00, 0.00000]

stations:                      # optional named stations, fractions of L
  mouth: 0.14
  vent: 0.90
  parachute_overlap: 0.88      # if present: seal overlap = tape distance to the top opening

loft:                          # optional: lobe bulge between load tapes (default k = 1)
  stations:                    # [s, k]: s a fraction of L or a station name,
    - [mouth, 1.10]            #   k = lobe radius / tape radius (dimensionless)
    - [vent, 1.00]
# or, the same everywhere:
# loft: {ratio: 1.05}

design:
  hold:                        # exactly three of the quantities below
    nominal_volume: 92000 ft^3
    mouth_station: mouth       # a station name or a fraction
    top_station: vent
  gore_count: 20
  seam_allowance: 2 in         # cut allowance per gore edge

published: {}                  # optional: values computed by the source, regression only
```

## Quantities that can be held

| Key | Dimension | Meaning |
|---|---|---|
| `gore_length` | length | pole-to-pole gore length \( L \) |
| `mouth_station`, `top_station` | fraction | cut stations |
| `nominal_volume` | volume | closed shape, pole to pole (\( cL^3 \)); lofted |
| `envelope_volume` | volume | mouth to top opening, ends closed by discs; lofted |
| `height` | length | mouth to top opening |
| `max_diameter`, `mouth_diameter`, `top_diameter` | length | |
| `tape_length` | length | mouth to top opening along the tape |
| `max_cut_gore_width` | length | \( 2(\max w + a) \); \( 2(\pi r_{max}/N + a) \) without a loft |

`nominal_volume` and `gore_length` fix the same thing and cannot be held together.

## Rules

* `profile.stations` runs from s = 0 to s = 1, strictly increasing, with r ≥ 0 and
  \( |\Delta r| \le \Delta s \) between stations (r is plotted against tape length).
* `loft` is optional (no loft: small-bulge gores, \( k = 1 \)). Give either `ratio`
  (constant) or `stations`; stations are sorted, must differ, and \( k \) is
  interpolated linearly between them and held beyond the first and last. Every \( k \)
  must be at least \( \sin(\pi/N) \) for the file's gore count (a half-circle lobe).
  See [gore loft](../theory/gore-geometry.md#gore-loft-lobe-bulge-between-tapes-goreloft).
* The `published` block is never an input. Tests compare it with the solved design
  (`docs/validation/shape-families.md`).
* A breaking change to this format gets a new `format_version` and a migration.

## Version 2

`format_version: 2` adds the sections below. All of them are optional. A version-1 file
is read unchanged; a version-1 file that uses a version-2 section is refused, and the
message names the section. Unknown top-level keys are refused in version 2.

```yaml
format: envelopelab.shape
format_version: 2
extends: ../base/shape.yaml    # optional: merge this file over another one

profile:
  source: measured
  span: cut                    # poles (default) | cut
  interpolation: linear        # spline (default) | linear
  stations:                    # [s, r], fractions of the tape length T (span: cut)
    - [0.0, 0.10]
    # ...
    - [1.0, 0.12]

design:
  construction: flat_chord     # lobe (default) | flat_chord
  hold:
    tape_length: 18 m          # span: cut holds mouth_station 0 and top_station 1 itself
  gore_count: 16
  seam_allowance: 25 mm

rows:                          # mouth first
  - {name: SKIRT, top: 0.1, zone: mouth, bow: [0 mm, 2 mm]}
  # ...
  - {name: I, zone: body, bow: [3 mm, 0 mm]}

zones: {body: ripstop_nylon, mouth: nomex}   # zone -> fabric id
panel_zones:                   # single panels in another zone
  - {name: badge, row: C, gores: [16, 1], zone: mouth}

loft:
  crest: {fraction: 0.02, taper: [[0.1, 0], [0.5, 1], [1.0, 0]]}

openings: {seal_overlap: 300 mm, crown_ring: 4 m}

rigging:
  parachute: {panel_count: 16, shroud_attachment: 2 m}
  red_line: {guide_seam: 4, spare_length: 3 m}
  flying_wires: {count: 16, frame_radius: 500 mm, frame_drop: 1.5 m, crows_foot_drop: 0 m}
  scoop: {first_gore: 1, gore_count: 4, height: 1.5 m}
  turning_vents:
    - {name: left vent, seam: 8, rows: [E, F], direction: clockwise}
  crown_line: crown line

special_shapes: []             # see "Special shapes" below
```

### Profile span and interpolation

| `span` | Stations | \( L \) (what `gore_length` scales) |
|---|---|---|
| `poles` | pole (0) to pole (1); the design is cut at the mouth and top stations | pole-to-pole gore length |
| `cut` | mouth (0) to top opening (1); the radius need not be 0 at the ends | tape length, mouth to top opening |

With `span: cut` the mouth and top stations are held at 0 and 1 unless the file holds
them. So **one** more held value fixes the design (for example `tape_length` or
`envelope_volume`), and `nominal_volume` cannot be held.

`interpolation: linear` takes straight tape segments between the stations,
\( \Delta z = \sqrt{\Delta s^2 - \Delta r^2} \), instead of the cubic spline. This is
right for a measured pattern whose panel sides are straight between row corners. The
design keeps straight segments (`GoreSpec.profile_interpolation`).

### Gore construction and loft

| `design.construction` | Gore | Loft |
|---|---|---|
| `lobe` (default) | width model with a circular lobe between tapes, straight seams | `loft: {ratio}` or `loft: {stations}` (lobe-radius ratio) |
| `flat_chord` | flat tape-to-tape trapezoids with straight sides, bowed horizontal seams | measured `rows[].bow`, and/or `loft: {crest}` |

See [flat-chord gores](../theory/gore-geometry.md#flat-chord-gores-and-the-crest-loft-flat_chord_rows-crestloft).
`loft.crest` has a `fraction`, the crest offset over the tape radius where the taper
is 1, and a `taper` list of `[s, taper]` pairs (s a fraction of L or a station name).
When the rows carry measured bows, the file's design uses them, scaled with the gore
length for variants. The crest loft then generates seams only when asked
(`ShapeFile.design(seams="crest")`). Without measured bows, the crest loft sets the seams.

### Rows, zones and panel zones

`rows` lists the panel rows from the mouth up. Each row has:

* `name` (1–8 characters);
* `top`, the station of its top seam (a fraction of L or a station name), required for
  every row except the last, which ends at the top opening;
* `zone`, optional, a key of `zones`;
* `bow: [bottom, top]`, the measured seam bows (lengths, positive outward), given for
  every row or for none (`flat_chord` only).

Without `rows`, the design gets equal rows (count chosen when the design is made).

`zones` maps zone names to fabric ids of the fabric library. Without it there is one
`body` zone of the fabric chosen when the design is made.

`panel_zones` gives single panels their own zone (`GoreSpec.panel_zones`). Each entry is
`{name, row, gores, zone}`; a panel can be in only one panel zone.

### Openings and rigging

* `openings.seal_overlap` is the parachute seal overlap, measured along the fabric.
  Without it, the overlap is taken from a `parachute_overlap` station or from the
  template default.
* `openings.crown_ring` is the crown ring diameter (default: the top opening).

Each `rigging` section is merged over EnvelopeLab's default for it
(`envelopelab.rigging.defaults`), using the design model's field names
(`docs/formats/design-schema.md`). Lengths need a unit: `shroud_attachment`,
`centralizing_depth`, `centre_ring_diameter`, `spare_length`, `frame_radius`,
`frame_drop`, `crows_foot_drop`, `height` and `opening_width`. Each turning vent is
merged over the default vent. `null` removes a section.

### `extends`

`extends: <path>` (relative to the file) merges the file over its base, recursively:

* mappings merge key by key;
* the lists `special_shapes`, `panel_zones` and `turning_vents` merge by `name` (an
  entry with the base's name replaces it, a new name is added);
* every other value, including other lists such as `rows` and `profile.stations`, is
  replaced;
* `published` is never merged: it belongs to the file it is written in.

Both files must have the same `format_version`. A missing base and a cycle are errors.

### Special shapes

`special_shapes` lists the shapes added to the envelope. They are the shapes of the
**Special shapes** mode (`envelopelab.project.shapes`), written with units and placed
by gore and row. **New design ▸ From shape file** puts them in the new project.

```yaml
special_shapes:
  - name: horn
    kind: tube                 # dome | tube | revolved | mesh
    placement: {gore: 5, row: G, above: 600 mm, lean_deg: 30, lean_toward_deg: 90}
    base_radius: 400 mm
    tip_radius: 150 mm
    length: 2 m
    panels: 2
    feed_hole_radius: 300 mm   # hole under the base point
    zone: accent               # fabric of the skin, through `zones`
    seam_allowance: 25 mm
  - name: blister
    kind: mesh
    mesh: {file: shapes/blister.obj, up: Z}   # relative to this file
    placement: {gore: 12, row: E, at: 0.5}
    panels: 8
    feed_holes:                # more holes anywhere inside the footprint
      - {gore: 12, row: E, above: 400 mm, across: 0.2, radius: 200 mm}
```

Placement (and each feed hole) is given in one of three ways:
* `row` with `at`, a fraction of the row's tape length;
* `row` with `above`, a length up the panel's **centreline** from its bottom seam, the
  way a builder measures on the cut panel (on a flat-chord row the centreline is longer
  than the tape by the seam bows);
* `tape_position`, the tape length from the mouth.

Positions follow the rows of a scaled variant; the shape sizes do not scale.

The other keys are those of the project's shape specification, in its units:
* `base_radius`, `height`, `tip_radius`, `length`, `feed_hole_radius` and
  `seam_allowance` are lengths with a unit;
* `revolved` takes `profile: {unit, points: [[rho, zeta], ...]}`;
* `mesh` takes `mesh: {file, up, scale}`, read with `envelopelab.io.blender.read_shape_mesh`
  in the frame of a mesh shape: z out of the envelope, x up the tape.

Use `zone` (resolved through `zones`) or `fabric` (a fabric id) for the skin. An error
names the entry and key, for example `special_shapes[2].placement.row`.
