# Fabric library file

The fabric library shared by all of a user's designs is a SQLite database
(`materials.sqlite` by default; see the [user guide](../user/fabric-library.md)). It is read
and written by `envelopelab.materials.repository.FabricLibraryRepository`; open it with
`open_user_library(path)`.

## Version

The layout version is stored as SQLite `PRAGMA user_version`:

| Version | Change |
|---|---|
| 0 | Original `fabrics` table (only ever held in memory before shared libraries existed). |
| 1 | Adds `origin` (`example` or `user`). Opening a version 0 file upgrades it in place: the ids `ripstop_nylon`, `polyester` and `nomex` become `example`, every other row `user`. |

A file with a higher version than the running EnvelopeLab knows is refused (it is not
modified); the application then falls back to a temporary library and says so.

## Table `fabrics`

One row per fabric. Every property is a pair of columns: the value (`REAL`) and its source
(`TEXT`, `<prop>_source`).

| Column | Type | Unit | Rule |
|---|---|---|---|
| `fabric_id` | TEXT, primary key | | 1–64 of `A-Z a-z 0-9 _ . -`, starting with a letter or digit |
| `name` | TEXT | | not empty |
| `areal_mass` | REAL | g/m² | > 0 |
| `warp_tensile`, `weft_tensile` | REAL | as entered | > 0 |
| `tear` | REAL | as entered | > 0 |
| `seam_efficiency` | REAL | – | 0 < x ≤ 1 |
| `e_warp`, `e_weft`, `g` | REAL | Pa | > 0 |
| `nu` | REAL | – | ≥ 0 and \(\nu^2 < E_{warp}/E_{weft}\) |
| `porosity` | REAL | as entered | ≥ 0 |
| `max_service_temperature` | REAL | °C | > −273.15 |
| `roll_width` | REAL | m | > 0 |
| `color` | TEXT | | colour name or `#rrggbb`; with `color_source` |
| `cost` | REAL | per m², as entered | ≥ 0 |
| `origin` | TEXT | | `example` (read-only placeholder) or `user` |

All values must be finite. Every source starts with a source tag, `datasheet`, `measured`
or `assumed`, optionally followed by a note (`"measured - coupon 2026-09"`).
`validate_fabric` enforces these rules for every write through the API. Rows written by
other tools are read as they are.

Library values are display units. They are converted to SI where they are used (areal mass
× 10⁻³ → kg/m², service temperature + 273.15 → K).

## Relation to project files

Project files (`*.elproj`) store only fabric ids in the design's `zones` map. The values of
the fabrics a design uses form the external input group `fabric_properties` of the
[staleness graph](../theory/design-editing.md#staleness-of-derived-artifacts). It is part
of the simulation and nesting fingerprints but not of the file.
