# Shape file (`envelopelab.shape` v1)

A shape file is YAML (`*.yaml`). It holds a [shape family](../theory/shape-families.md)
and the three values that fix one design of it. It is read by
`envelopelab.io.shape_file.load_shape_file` and by **New design ▸ From shape file**.
Example: `tests/fixtures/smalley_90k/shape.yaml`.

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
| `nominal_volume` | volume | closed shape, pole to pole (\( cL^3 \)) |
| `envelope_volume` | volume | mouth to top opening, ends closed by discs |
| `height` | length | mouth to top opening |
| `max_diameter`, `mouth_diameter`, `top_diameter` | length | |
| `tape_length` | length | mouth to top opening along the tape |
| `max_cut_gore_width` | length | \( 2(\pi r_{max}/N + a) \) |

`nominal_volume` and `gore_length` fix the same thing and cannot be held together.

## Rules

* `profile.stations` runs from s = 0 to s = 1, strictly increasing, with r ≥ 0 and
  \( |\Delta r| \le \Delta s \) between stations (r is plotted against tape length).
* The `published` block is never an input. Tests compare it with the solved design
  (`docs/validation/shape-families.md`).
* A breaking change to this format gets a new `format_version` and a migration.
