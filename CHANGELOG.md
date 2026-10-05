# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
- Special shapes: new *attachment ease* check. The skin rim is sewn to the footprint
  line marked on the flat envelope panels, which differs from the rim because the flat
  gores carry the lobe bulge; the difference is now measured between every pair of
  match marks and is an error above 3 mm (a 0.5 m dome low on the 8-gore fixture eases
  4.7 mm into one interval; default-size shapes under 1 mm). No pattern changes.
- Drag special shapes in the 3D view: with **Drag special shapes** on (or **Drag in 3D
  view…** in the Special shapes panel), press on a shape and drag it over the envelope; a
  ring previews where its base will sit, and releasing moves it (gore, tape position and
  position across the gore; lean kept) as one undo step.
- Special shapes in the 3D view are drawn in their layer colour; they were drawn with
  their dense mesh edges and looked like black blobs.
- Special shapes in the desktop application: a new **Special shapes** mode adds domes,
  tubes, revolved profiles and imported Blender meshes to a standard envelope, edits
  them with undo, shows their pattern checks, cut pieces and attachment lines, simulates
  them with the preview solver, and exports the build pack and a Blender scene. Shapes
  are placed in a background thread, so editing never waits for them. Unplaceable
  shapes, failed checks, unconverged, failing or stale shape simulations are listed in
  Validation / Warnings. The 3D / Simulation and History shortcuts move to Ctrl+5 and
  Ctrl+6.
- Project files are now format version 2 (ADR-0020): they store the special shapes.
  Version 1 files open unchanged (no shapes); older releases cannot open version 2 files.
- Placing a special shape is 2-2.5x faster (the footprint search samples 241 instead of
  801 points before bisecting); footprints and cut outlines change by less than 0.5 µm.
  On the special-shape validation page the dome study's inflated heights move by at
  most 3.6 µm and its lowest factor of safety by at most 0.24 % (90.34 to 90.56); every
  check still passes.
- Faster preview solves (ADR-0019): the solver's element kernel (membrane strain,
  tension-field stress, internal and pressure forces, nodal sums) runs as one compiled
  loop when the optional `fast` extra (Numba) is installed: 3-4x faster (fixture envelope
  at 1600 mm 10.2 s to 3.3 s, a dome sub-model 3.7 s to 0.9 s). Without it, precomputed
  operators make it 1.1-1.4x faster. Results change only by round-off (largest node
  difference 0.34 µm, iteration counts within a few percent); no benchmark moved. The
  application stays responsive while a solve runs.
- Smoother editing in the desktop application: every panel redraws at most once per
  edit, panels in other workflow modes wait until they are shown, the meridian spline and
  the panel rows are computed once per edit, and rigging lines are drawn as one 3D actor
  per kind. With the 3D view on, an edit takes 25-35 ms instead of 160 ms, undo 20-25 ms
  instead of 100 ms, a mode switch about 30 ms instead of 110 ms and opening a project
  30-40 ms instead of 280 ms. The window appears before the 3D renderer has loaded.
- Free-form special shapes from a mesh (ADR-0018, `FreeformShape`,
  `envelopelab.features.freeform`): import a closed shape modelled in Blender (OBJ, STL
  or PLY), place it on the envelope, and EnvelopeLab clips it at the envelope (the cut
  edge is the footprint), cuts it into panels along half-planes through its axis and
  flattens each panel. Footprint and seam edges keep their exact lengths and the
  interior strain is reported. The same attachment lines, match marks, build-pack
  export, Blender scene and as-cut sub-model as the other shapes. New rows in
  `validation/special-shape-primitives.md`. No existing numerical result changes.
- Blender mesh exchange (ADR-0017, `envelopelab.io.blender`, `envelopelab.features.scene`):
  export the envelope, each special shape as designed and each solved skin as one OBJ
  scene with named objects, written Y up so Blender's default OBJ import shows it upright
  in metres (an unconverged solve is named `..._UNCONVERGED`). STL export, and reading
  OBJ, STL and PLY shapes back with Blender's default axes.
- Build-pack export (ADR-0016, `envelopelab.export`): cutting patterns of the envelope
  rows and of every special shape's pieces, plus marking sheets for the envelope panels
  each shape crosses (footprint line, numbered match marks, feed hole). One DXF per
  sheet in mm, one `pattern.pdf` at 1:1 on roll-width pages (60 in by default; wide
  sheets are split into strips), and `index.json` with pieces, cut counts, fabrics,
  finished sizes and sewn edge pairs. Generated calibration lines and headers. The output
  QA of AGENTS.md §6.6 (`envelopelab.export.qa.check_pack`) now runs in
  `scripts/verify.py`. The Reality Check PDF writes its page size with two decimals; its
  content is unchanged.
- Special-shape primitives: a third shape, `Revolved`, spins any profile you give as
  points (spline or straight segments) about the feature's axis: noses, bulbs, onions,
  balls, flared horns. It closes in an apex or a flat tip disc, has the same attachment
  lines, match marks, cutting pattern, checks and sub-model as the dome and the tube, and
  a single straight segment is developed exactly. A profile that flares outward at its
  base now drops straight down the axis to the envelope. New rows in
  `validation/special-shape-primitives.md`. No existing numerical result changes.
- Special-shape primitives (ADR-0015, `envelopelab.features.primitives`): place a dome
  (blister, lobe, ear) or a tube (horn, nose, mast, leaned or not) on a standard-gore
  design by gore, tape position and lean. EnvelopeLab derives the footprint, its run
  across every envelope panel in that panel's pattern coordinates, numbered match marks
  on the envelope and on the skin, and the skin's cutting pattern: exact developments
  for tube panels, and classic gores laid out with true-length seams for domes. It also
  checks rim length, seam pairs and flattening distortion. `primitive_appendage` builds a
  sub-model whose skin rests in the cut pieces (new builder skin mode `designed`, on the
  true envelope surface), so the preview solver and CalculiX show how the sewn shape
  holds under pressure. Python API only for now (no app or design file yet).
  New generated page `validation/special-shape-primitives.md`. No existing numerical
  result changes.
- Gore loft (ADR-0014): the bulge of each gore between its load tapes is now a design
  input, the lobe-radius ratio k = ρ/r along the gore (stations as fractions of the tape
  length, interpolated). Set it in the standard-gore editor's **Gore loft** table, as one
  ratio in the new-design wizard, or as a `loft` block in shape files. Flat patterns, the
  mass estimate, volume, gross lift, lift margin, the volume lock, the 3D lobes and the
  simulation's sewn panels all follow it. Design schema version 3 (`gores.loft`; v2 files
  migrate to no loft). Designs without a loft are unchanged (k = 1, the small-bulge gore):
  no existing numerical result changes. New analytic benchmarks for the lofted volume and
  area (`validation/analytic-geometry.md`).
- Main window: workflow modes (Shape, Patterns, Rigging, 3D / Simulation, History; Ctrl+1
  to Ctrl+5) replace the nine dock panels. The Design Tree / Properties sidebar and the
  Validation / Warnings strip stay visible in every mode, and mode tabs show ● and [STALE].
  The window now resizes down to under 1280 × 800 px (it could not shrink below
  2137 × 1036 px with a project open). The layout is remembered between sessions, and
  **View ▸ Save layout / Load saved layout / Reset layout** were added (ADR-0013).
- Shape files (`envelopelab.shape` v1, ADR-0012): a normalized gore table (radius against
  tape length, fractions of the gore length) plus the three held values that fix a design,
  with explicit units. `envelopelab.project.shape_family` solves any three held values
  (e.g. the mouth diameter) for the gore length and cut stations and makes a standard-gore
  design. The app has a new **New design ▸ From shape file** tab. Fixture
  `tests/fixtures/smalley_90k` (Balloon Builders Journal 90K table with its source
  spreadsheet) and a generated page `validation/shape-families.md`. No existing numerical
  result changes. Against its spreadsheet, the Smalley table's integrated volume
  coefficient is 0.15 % higher (0.12605 vs 0.12586), so holding its 92,000 ft³ gives gores
  0.05 % shorter (90.035 ft vs 90.081 ft).
- New-design wizard: **Save as my defaults** / **Reset to built-in defaults** (stored in the
  application settings). **File ▸ New from template…** starts a new design as a copy of a
  saved project's design state (`ProjectSession.from_template`,
  `envelopelab.project.templates.state_from_template`).
- 2D pattern view: pieces are stacked vertically as sewn up a gore (scoop, rows from the
  mouth up, parachute on top) in their own full-height column right of the 3D view.
- 3D view: the design surface is solid, coloured by each row's fabric with alternate gores
  shaded, and draws the vertical (load-tape) and horizontal (row) seams, so individual
  gores and panels are visible (`envelopelab.project.gore_design.display_surface`).
- Panel layout from the mouth up: a mouth row in its own fabric (Nomex by default in the
  wizard, configurable height), N body rows (nylon), and the parachute as the top panel.
  Panel rows carry an optional design-level material zone (`gores.panel_rows[].zone`,
  ADR-0011); the pattern view's row zone still overrides it.
- Parachute crown ring (rim of the crown opening) and centre ring (apex, where the
  panels now end): circumference, limit hoop force, factor of safety and mass.
- Optional scoop below the mouth over consecutive gores (depth, flare, fabric zone):
  flat panels that match the mouth row, mass, burner-frame clearance warning.
- Parachute, red line, flying wires and turning vents are part of the design (design
  schema v2, ADR-0010; v1 documents migrate on load, their hash checked first).
  `envelopelab.rigging` computes the seated parachute and its flat panels, shroud and
  centralising line lengths, the shroud lines' limit tension, the red-line pull to open the
  parachute, the red-line route and length, flying-wire and crow's-foot geometry and limit
  tensions, and turning-vent thrust, torque, air and heat loss; every factor-of-safety
  failure, unreachable opening and inconsistent placement is a Validation error. Benchmarks
  against hand calculations: `validation/rigging-benchmarks.md`. Guides: `user/rigging.md`,
  `theory/rigging.md`.
- New designs get a default parachute (one shroud line per load tape), red line and flying
  wires to a four-point burner frame; generic line and cable strengths are `assumed`.
- **Changed result:** the live lift margin now subtracts the parachute and rigging mass
  (parachute fabric, tapes and thread, lines, wires, crow's-foot legs, vent control lines).
  Designs without rigging (all migrated v1 designs) are unchanged; for a new 2000 m^3,
  12-gore design from the wizard (generic 65 g/m^2 fabric) the margin drops by 6.2 kg
  (of which 1.8 kg are the default crown and centre rings).
- Turning vents marked `simulate_open` are left open (`open_seams`) in the preview and
  CalculiX models; other vents are simulated closed, as before.
- Desktop application: Rigging panel (add/remove, lengths, loads, factors of safety, mass),
  Parachute / Rigging / Turning vents in the Design Tree and Properties (with units), a
  parachute and rigging layer in the 3D view, and the rigging mass in the live outputs.
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
