# ADR-0022: Shape files describe a whole pattern set (format version 2)

- Status: Accepted
- Date: 2026-10-12

## Context
A version-1 shape file (ADR-0012) holds a normalized profile, a lobe loft and three held
values. Everything else a pattern set fixes was chosen afterwards in the wizard or edited
by hand in the design:
* the named rows and their heights;
* a Nomex row and other zones;
* the gore construction;
* the parachute overlap, the parachute, turning vents and other rigging;
* appliques and special shapes.

A pattern set, or a special shape built on one, could therefore only be reproduced by
edits after loading, never from the file alone.

## Decision
* `format_version: 2` adds optional sections:
  * `profile.span` (`poles` or `cut`) and `profile.interpolation` (`spline` or `linear`);
  * `design.construction` (`lobe` or `flat_chord`, ADR-0021);
  * `loft.crest`;
  * `rows` (name, top station, zone, measured seam bows);
  * `zones`, `panel_zones` and `openings`;
  * `rigging` (merged over EnvelopeLab's defaults, design-model field names, lengths with
    units);
  * `special_shapes` (shapes of `envelopelab.project.shapes`, placed by gore and row);
  * `extends`.
* `ShapeFile.design()` builds the complete design document from the file;
  `shape_design()` stays for version-1 use. The wizard uses `ShapeFile.design()` for
  every file.
* `extends` merges a file over its base:
  * mappings key by key;
  * the named lists (`special_shapes`, `panel_zones`, `turning_vents`) by `name`;
  * everything else is replaced, and `published` is never inherited.
* Version-1 files are read unchanged. A version-1 file that uses a version-2 section is
  refused rather than half-read.
* A cut-span file holds the mouth and top stations at 0 and 1 itself, so the existing
  three-held-values solver is used unchanged.

## Consequences
* A pattern set is now reproducible from its shape file alone. A special-shape file
  can add its shapes to a pattern set without copying it (the synthetic fixtures in
  `tests/fixtures/flat_chord_pattern/`).
* Version-2 files cannot be opened by earlier releases.
* Rigging sections use the design model's field names. A rename there is a breaking
  change of the shape file too, and needs a new format version and a migration.
