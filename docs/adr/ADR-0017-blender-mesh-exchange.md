# ADR-0017: Mesh exchange with Blender (OBJ Y up, STL and PLY Z up, metres)

- Status: Accepted
- Date: 2026-10-04

## Context
Builders want to see the envelope and its special shapes, as designed and as simulated,
in Blender, and to model free-form shapes there and bring them back. Blender works in
metres with Z up, but its OBJ importer and exporter default to *forward -Z, up Y*, while
its STL and PLY tools default to *forward Y, up Z*. EnvelopeLab works in metres with
Z up.

## Decision
* `envelopelab.io.blender` writes OBJ with Y up, \( (x, y, z)_{OBJ} = (x, z, -y) \), and reads
  OBJ the same way, so files open upright and come back upright with Blender's default
  settings. STL and PLY are written and read Z up. An `up` argument overrides either.
* No unit conversion: metres throughout (Blender's default unit scale 1). Reading takes a
  `scale` in metres per file unit for other tools.
* A scene is one OBJ file with one named object per part (`o envelope`,
  `o <name>_designed`, `o <name>_simulated`). An unconverged solve is exported under the
  name `<name>_simulated_UNCONVERGED`, so it cannot be mistaken for a prediction.
* `envelopelab.features.scene` builds the objects: the envelope's surface of revolution,
  each shape's designed skin, and each solved skin moved from its sub-model frame back
  onto the envelope.

## Consequences
No new dependency (OBJ and STL are written with the standard library; reading reuses
`envelopelab.io.reference_mesh`). OBJ files written by EnvelopeLab before this ADR
(`envelopelab.solvers.results.write_obj`) stay Z up and are unchanged; that writer remains
the solver's own debug output. The envelope object has no lobe bulge between its tapes.
