# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
- `envelopelab.solvers`: interactive preview solver for the inflated equilibrium of an
  as-sewn envelope (`dynamic_relaxation.solve`). Dynamic relaxation with kinetic damping
  (viscous optional), orthotropic constant-strain membrane triangles in grain axes
  (isotropic default), tension-field wrinkling with probable-wrinkle-zone output,
  tension-only tapes and cables, follower hydrostatic pressure
  dp = (rho_amb - rho_int) g max(z - z_mouth, 0), pressure closures
  (parachute, end caps), fabric and tape weight, point/line/distributed loads, fixed or
  prescribed nodes and symmetry planes. Convergence at relative residual 1e-6; every other
  stop is an explicit `not_converged` error. `SolverJob` runs a solve on a worker thread
  with progress callbacks and cancellation; warm starts from a previous shape.
- `envelopelab.solvers.model.model_from_rest_model`: solver model from a build pack's rest
  model (grain and zone per instance, one tape per seam `load_tape`, mouth fixed).
- `envelopelab.solvers.results`: displacement, principal and warp/weft stress-resultant,
  strain, wrinkle-state, released-compression and tape-tension fields with units; deformed
  mesh (OBJ); global force-balance table; factors of safety by zone, seam and tape; JSON
  export `envelopelab.preview-result` v1 with reproducibility metadata.
- `envelopelab.materials.membrane`: `MembraneMaterial` and `TapeMaterial` with a unit and
  source tag on every value.
- `envelopelab.io.pattern_import`: DXF pattern import with ezdxf, driven by a per-build-pack
  YAML mapping (layer roles for cut, sew, dimension, feature, tape, match-mark, notch,
  grain and label layers; label regular expressions; units; allowances); packs with cut
  and sew lines or cut lines only; full provenance (file, layer, handle, mapping version).
- `envelopelab.geometry.polygon`: outline validation (closed, simple, oriented, nonzero
  area), mitred allowance offsets with loop trimming, windowed corner detection.
- `envelopelab.assembly`: finished panel outlines, assembly spec (gore rings, instance
  overrides, parts, seams, openings), seam graph with CSV/JSON export, seam-length audit
  with designed ease, Gmsh triangulation and virtual sewing into one tagged rest mesh,
  mesh validation, initial 3D guess and the `envelopelab.rest-model` v1 JSON file.
- Import reports (panel inventory, seam audit, seam graph, mesh report, warnings) in
  HTML/CSV/JSON and the `envelopelab-import` command.
- Generic standard-gore and special-shape fixtures and the Alien build pack as a
  regression fixture; generated pages `validation/pattern-import-fixtures.md` and
  `formats/pattern-import-mapping.md`.
- New runtime dependencies: ezdxf, gmsh, PyYAML (ADR-0003). No existing numerical results
  change.
- `envelopelab.atmosphere`: ISA (0–32 km), ideal-gas density with optional humidity
  correction, gross lift and hydrostatic differential pressure.
- `envelopelab.geometry.gore`: meridian profile (volume, area, height, width, length),
  small-bulge and chord/lobe gore widths, panel row splitting with cut outlines
  (mitre/bevel corners) and loft tables, and the inverse widths → profile fit with
  outlier rejection.
- `envelopelab.mass_estimate`: fabric by zone, tapes, thread and lift margin.
- Theory pages for atmosphere and gore geometry; generated analytic benchmark page.
- Initial scaffold with design schema, fabric library, and command pattern base.
