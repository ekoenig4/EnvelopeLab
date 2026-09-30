# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
- Shared fabric library: fabrics created once can be used in every design. The library is
  a per-user SQLite file (`materials.sqlite` in the application data folder, or
  `$ENVELOPELAB_MATERIAL_LIBRARY` / Preferences → Fabric library file), replacing the
  in-memory library that was reset at every start. The Materials panel gains **New fabric…**,
  **Duplicate…**, **Edit…** and **Delete**, backed by a fabric form with a source tag on every
  value. `FabricLibraryRepository.add_fabric` / `update_fabric` / `delete_fabric` validate
  every write (`validate_fabric`). Example fabrics are read-only. Library files carry a
  layout version (1; version 0 files are upgraded). See `user/fabric-library.md`,
  `formats/fabric-library.md` and ADR-0009.
- Staleness: the values of the library fabrics a design uses are a new external input group,
  `fabric_properties`, read by simulation and nesting. Editing a fabric marks the results
  built from it stale in every design that uses it, without marking the project modified.
  Runs saved before this change show as stale once in the application (they did not record
  fabric values); fingerprints computed without a library are unchanged.
- Desktop application: software OpenGL (`LIBGL_ALWAYS_SOFTWARE=1`) is selected
  automatically under WSL, where the GPU driver drew the window black; new launcher options
  `--software-gl` and `--hardware-gl`. An explicit `LIBGL_ALWAYS_SOFTWARE` is respected.
- `scripts/install_env.sh`: one-command environment setup for Linux and containers (system
  libraries for Gmsh, Qt and VTK via apt/dnf/pacman/zypper, CalculiX, Xvfb, virtualenv,
  `pip install -e .[dev,docs,gui]`, and a headless start check of the application); CI
  installs its Linux packages with it. New guide `user/installation.md` with per-distribution
  package lists and troubleshooting for the "Qt platform plugin xcb" start-up error.
- Desktop application shell (`envelopelab`, extra `gui`: PySide6, PyVista, pyvistaqt;
  ADR-0007): project open/save/save-as, recent projects, preferences, status bar,
  autosave and crash recovery; dockable Design Tree, Properties, Validation / Warnings,
  Materials and History panels with unsaved (●) and [STALE] indicators; undo/redo with
  full history, named snapshots and design versions; new-design wizard (standard gore from
  target volume/height/width, special shape from a mesh; design from measurements is a
  stub).
- `envelopelab.project`: project sessions (every edit an undoable command on
  `CommandStack`, snapshots, versions, provenance), fingerprint-based dependency graph of
  derived artifacts (a seam-allowance change marks patterns, nesting and export stale but
  not the rest mesh or simulations), gore live outputs and constraint locks. New file
  formats `envelopelab.project` v1 (`*.elproj`) and `envelopelab.autosave` v1 (ADR-0008,
  generated page `formats/project-file.md`).
- `CommandStack`: listeners, history, `go_to`, undo/redo texts and clean (saved) state.
- `FabricLibraryRepository.fabric()`, `.fabrics()` and `.catalog()` (thread-safe copy).
- Fixture `tests/fixtures/standard_gore/design.elproj`: the generic 8-gore design as a
  project. No existing numerical result changes.
- Standard-gore editor (draggable profile points, exact numeric entry, panel rows,
  height/volume/diameter/N locks, live area, volume, lift, mass and lift margin) and 2D
  pattern editor (seam allowance, grain, labels, zones, notches, tape paths, feature
  locations, flagged manual outline overrides with provenance and seam matching). Docs:
  `user/first-design.md`, `user/editing-designs.md`, `theory/design-editing.md`.
- Simulation Runs panel with separate Run Preview / Run CalculiX actions (Run CalculiX
  disabled with installation instructions when ccx is missing; ccx runs as an external
  process with a progress monitor), solver, convergence, residual and run time for every
  run, stale runs never shown as current; 3D view (design surface, rest mesh, preview,
  CalculiX and reference layers with distinct labels and colours, section plane, picking,
  spline widget). `envelopelab.project.simulation`: design -> build pack -> solver model
  pipeline and run records. Docs: `user/running-simulations.md`.
- `calculix_adapter.run_calculix`: optional `progress` callback (`CalculixProgress`) and
  `cancel` token (stops ccx, `CalculixCancelledError`). Results are bit-identical with and
  without them.
- `envelopelab.solvers.model`: gas chambers (`PressureChamber`, `SolverModel.chambers`,
  `tri_chambers`, `triangle_pressure`); closures may belong to a chamber. Preview solver
  and CalculiX adapter share the definition; chamber volumes and per-gas lift in the
  results (`chamber_volumes`). Models without chambers give bit-identical results.
- `envelopelab.features`: special-shape feature model (`features:` section of the build
  pack: ram-air pods, blisters, tubular and line-supported appendages, reinforced holes,
  rim tapes), pressure communication from feed holes with an `assumed` loss factor
  (default 0.1 in the fixtures), designed rim ease over match points, seam classification
  (matched / designed ease / seam error), construction-sequence, ordinate and doubler
  checks, appendage sub-model and tube builders (Gmsh), and appendage metrics identical
  for preview and CalculiX results.
- `envelopelab.report`: Reality Check report (three shape states, deviation heat map,
  dimensions, load paths, factors of safety, findings, convergence, sensitivity sweep)
  exported as HTML, PDF, JSON (`envelopelab.reality-check` v1) and CSV; `verified` only
  for a converged CalculiX solve within the documented tolerances.
- `envelopelab.io.reference_mesh`: OBJ/STL/PLY reference meshes, ICP registration (Open3D
  optional extra `registration`, MIT; SciPy fallback), signed distance, volume notation
  parsing.
- `envelopelab.solvers.dynamic_relaxation.enclosed_volume`: capped volume of a surface.
- Generated page `validation/special-shape-fixtures.md` (+ `.json`): hemispherical blister
  (preview and CalculiX), rim-tape load transfer (CalculiX golden: host N1 at the rim
  173.7 -> 326.8 N/m without the rim-to-tape connection), designed ease, Alien features.
  No existing numerical result changes.
- Alien fixture: `features:` and `reference:` sections and a reference mesh generated
  from the pack's 3D concept page.
- Documentation: `user/reality-check-report.md`, `theory/appendage-pressure-and-load-paths.md`,
  ADR-0006. Appendage external aerodynamics and turbulent flow are outside the model scope.
- `calculix_adapter` (`solvers/calculix_adapter`, optional): verification solve of a
  `SolverModel` with the external program CalculiX CrunchiX (`ccx`, GPL-2.0-or-later, not
  bundled). M3D3 membranes with per-element orientation and anisotropic material, as-sewn
  initial stress, tension-field wrinkling by iterative membrane properties that reproduce
  the preview's law at convergence, tension-only SPRINGA tapes, hydrostatic pressure, cap
  and dead loads as consistent nodal forces, fixed nodes and symmetry planes. Staged
  passes (held prestress job, balanced release job with ramped continuation and
  stabilisation), explicit convergence criteria, `not converged` findings otherwise.
  `find_calculix` / `require_calculix` detect `ccx` (`ENVELOPELAB_CCX` or `PATH`) and
  explain how to install it; nothing else in EnvelopeLab needs CalculiX.
- `envelopelab.solvers.simulation.SimulationResult`: solver-independent result (nodes,
  elements, stress resultants, tape tensions, reactions, residual and iteration history,
  solver version, mesh size, elapsed time, findings); `from_preview` normalises a preview
  result.
- `envelopelab.solvers.manifest.RunManifest` (`envelopelab.run-manifest` v1): design and
  model hash, material sources, solver settings, git commit, Python and dependency
  versions, mesh settings, random seed; fingerprint and field-by-field differences.
- `envelopelab.validation.comparison.compare_results`: aligns two results and compares
  height, maximum width, volume, displacement, stress resultants and tape tensions,
  flagging differences above 5 %.
- `envelopelab.solvers.dynamic_relaxation.ModelEvaluator`: the preview model's
  deformation, loads, volume and tape tensions at given positions (no numerical change).
- Generated page `validation/preview-vs-calculix.md` (+ `.json` data, `.svg` plot):
  CalculiX sphere and cylinder benchmarks, preview vs CalculiX on the generic envelope and
  a three-level CalculiX mesh-convergence study. No existing numerical results change.
- Documentation: `theory/verification-solver.md`, `dev/calculix-installation.md`, ADR-0005
  (CalculiX verification solver; both solvers retained) and a CalculiX section in
  `user/simulation-preview.md`.
- CI installs `calculix-ccx` on Linux (CalculiX tests are skipped with a message
  elsewhere); `mypy` now also checks `solvers/`.
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
- Generic spherical-envelope fixture (`tests/fixtures/spherical_envelope`) and generated
  page `validation/preview-solver-benchmarks.md` (sphere, cylinder, hydrostatic pressure,
  lift, elastic catenary, tension-field shear, global equilibrium, mesh refinement). No
  existing numerical results change.
- Documentation: theory page `theory/dynamic-relaxation.md`, user guide
  `user/simulation-preview.md` and ADR-0004 (dynamic relaxation for the preview solver).
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
