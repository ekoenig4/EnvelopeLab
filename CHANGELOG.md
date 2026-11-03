# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
- Added: special-shape simulations have the envelope's colour maps in the 3D view. Each
  solved shape is in the *Run* list (*Dome (inflated)*) with factor of safety warp/weft,
  principal and warp/weft resultants, wrinkling, displacement and the deviation from its
  designed skin; the banner and run details describe it. Shape runs now store their skin's
  results (`skin_*` arrays, optional: earlier runs have none and must be run again). The
  per-triangle factor uses warp and weft as for the envelope; the shape summary's skin
  factor stays the conservative min(N_ult) / N1 bound (never higher, tested). No existing
  result changes.
- Added: *Deviation from design* heat map: where the solved envelope lies outside (red) or
  inside (blue) the designed shape, in mm, measured along the design's outward normal at
  the run's nodes (`envelopelab.project.deviation`). In the 3D view it colours the design
  surface (a new *Colour by* field); in the Patterns view *Overlay: Deviation from design*
  maps it onto the flat panels (each point shows the gore that deviates most). Current,
  converged runs only. On the standard-gore fixture's preview: -239 mm (inside, near the
  mouth, where the shape check reports compression) to +121 mm. No existing result
  changes. Diverging colours are the project's own ramp (no new dependency).
- Changed: patterns are regenerated automatically after every edit and when a project
  opens (Preferences, *Regenerate patterns after every edit*, now on by default; it costs
  under 1 ms per edit on the fixtures). Settings saved by an earlier version take the new
  default once (preferences version 2); turning it off is kept. When regeneration fails,
  the Patterns banner says why instead of only "stale". Patterns and cut files are
  unchanged.
- Changed: the 3D view's layer list, legend and *Run* list use short layer names
  (*Design surface*, *Preview result*, *Dome (inflated)*, ...), with the full description
  as the tooltip. A stale or unconverged layer still says so on its row (*◷ stale*,
  *✕ not converged*; plain words in the scene legend), and the stale banner no longer
  repeats the run id (it is in the run details). Display only.
- Changed: the envelope panels a special shape is sewn on (its footprint sew line, match
  marks and feed holes) moved from the Patterns view to the Special shapes window, in a
  new *Envelope panels* tab shown with the selected shape (opens zoomed on the marked
  area; double click for the whole panels). The Patterns view now shows only the base
  envelope, and its *Show special shapes* option is gone. Display only: the build pack's
  marking sheets are unchanged.
- Changed: the Validation / Warnings strip uses the shared design: count chips per
  severity (✕ errors, ▲ warnings, i notes, or ✓ no problems), the severity's symbol and
  colour on every finding, and a *Show* menu filtering errors, warnings and notes (the
  counts always include every finding). Display only.
- Changed: the 2D pattern view uses the shared design: its state (current, not
  generated, STALE) is the shared status banner with a *Regenerate patterns* button on it
  when needed, and the *Selected row* form is drawn as a card. Display only.
- Changed: the standard-gore editor uses the shared design: the key figures (volume,
  height, maximum diameter, gross lift) and a lift-margin chip in its title bar, a status
  banner stating the worst design problem (errors, compression under load, negative lift
  margin), the side column's boxes as cards, and the theme's status colours in place of
  hard-coded reds. Display only.
- Changed: the Simulation Runs panel uses the shared design: an action toolbar (*Run
  Preview* as the main action), the CalculiX version as a status chip or a banner saying
  why it is disabled, a status chip per run (current, stale, FoS fail, not converged), a
  solver colour swatch, a *Min FoS* column (lowest fabric factor of safety of a current
  converged preview run, FAIL below 5) and an empty-state message. Display only.
- Changed: the 3D view is reorganised (approved mockup): a toolbar chooses the run, the
  field to colour by and the display mode (shaded, with mesh edges, wireframe), with a
  screenshot button; a status banner across the view states the run's state worst first
  (not converged, stale, factor of safety or temperature limit exceeded, current but not
  verified with CalculiX, verified) and cannot be dismissed; tools sit on a rail left of
  the view, an orientation cube in its corner, the camera buttons below it; the side
  panel shows the layers with colour swatches, a *Run details* card (solver, status,
  iterations, residual, mesh, load case, run time, volume, material sources) and the
  *Probe* read-out. A shared theme (`envelopelab_app.theme`: colours, status banner and
  chip) is applied to the whole application, for the other windows to follow.
- Added: colour a run by fabric factor of safety (warp or weft), principal, warp and weft
  resultants, wrinkle state or displacement. Factors below the required factor (5,
  assumed) are always orange and labelled FAIL. Fields a run cannot give are listed but
  disabled with the reason. Preview runs now store their warp/weft resultants
  (`fabric_resultants`, ADR-0035); existing results are unchanged, older runs and
  CalculiX runs cannot be coloured by factor of safety.
- Fixed: the *attachment ease* check failed on most special shapes (on the Smalley 90K
  alien design 6.5 mm per match-mark interval on the antennae and 20.5 mm on the eye pods,
  against a 3 mm limit) although the rim and the marked line differed by only 0.5 % and
  0.12 % in total: the envelope marks sat at the same angles as the rim marks, so the
  difference bunched into a few intervals. The envelope marks now divide the marked line
  in the rim marks' proportions and the ease is spread evenly (1.2 mm and 2.5 mm at most
  there; the marks move round the shape by at most 1.5°). Marking sheets change
  accordingly; match marks carry `host_phi_deg`.
- Changed: special shapes solved with the envelope use an element size of footprint
  length / 40 (100 to 300 mm) instead of / 100 (60 to 300 mm), set from a mesh study on the
  Smalley 90K alien design (ADR-0034): its four shapes solve in 105 s instead of 374 s
  (four threads), with shape heights within 0.15 % of the 60/229 mm results (antenna
  3.258 against 3.254 m, eye pod 1.178 against 1.176 m). Peak values still change with the
  mesh, so every shape result now carries a `peak_values_mesh_dependent` warning.
- Changed (physics): wrinkled fabric now carries its tension along the direction that
  maximises the uniaxial energy (Pipkin–Steigmann relaxed energy), instead of the major
  direction of the trial stress, and is slack only when no direction is stretched. For
  isotropic fabric nothing changes; for orthotropic fabric the law is now the gradient of
  an energy, so the preview solver no longer cycles on wrinkled caps: special shapes that
  never converged at their automatic element size now do (Smalley 90K eye pod at 232 mm in
  14,956 iterations, antenna at 60 mm in 15,762; before, both stopped at a residual of
  about 0.3 after 200,000). Results move slightly: Smalley 90K at 800 mm volume −0.025 %,
  maximum tape tension +0.004 %; the generic validation envelope at 600 mm volume −0.07 %,
  mean tape tension −11 %, 99th-percentile fabric tension +8 % (ADR-0033).
- Changed: a run's special shapes are solved in parallel threads (one per shape, leaving
  one processor for the window; at most two for CalculiX), each reported as soon as it is
  ready.
- Changed: special shapes from meshes are placed about 7 times faster (the alien design's
  four shapes: 31 s to 4 s; an eye pod 10.2 s to 1.3 s). Mesh cuts split only the
  triangles they cross and find every crossing in one vectorised bisection, the
  flattening uses the closed-form 2D rotation and pre-built sparse matrices, and the
  conformal start is solved directly. Patterns are unchanged (largest difference
  0.000001 mm). The app shows each shape as soon as it is placed, and an edit made while
  shapes are being placed no longer waits for the out-of-date ones to finish.
- Changed: the Special shapes screen is reorganised so it is no longer squeezed. It uses
  the whole window (design tree and properties folded away, warnings strip compact but
  always shown, both restored in the other modes) and has three columns: the shape list
  with its buttons; the editor in tabs (*Placement & size*, *Profile* for revolved shapes,
  *Feed holes & cap*, *Simulation*); and the results in tabs (*Cut pieces*, *Checks*,
  *Attachment*). The cut-piece drawing lays the pieces out in rows to fill its area,
  names each one, zooms with the mouse wheel, pans by dragging and fits on a double
  click. Stored window layouts from earlier versions are reset once (layout version 2).
  Display only; no pattern or result changes.
- Changed: special shapes whose gores or panels met in a point (domes, revolved profiles
  ending on the axis, pointed tubes, mesh shapes) now have their tops sewn round a
  **cap**, a round piece of measurable diameter, as points are made in practice
  (ADR-0032). Each shape's *Cap diameter* (project field `cap_diameter`) is automatic by
  default: every piece's top at least 100 mm wide, d = M x 100 mm / pi (637 mm for 20
  panels, 509 mm for 16), at most half the base diameter; 0 brings the pieces to a point.
  Existing projects get automatic caps when opened. Results change: a capped dome or
  revolved shape stops where it is as wide as the cap (designed height
  h sqrt(1 - (r_c/a)^2), e.g. 0.600 to 0.585 m for the special-shape fixture's dome) and
  gains a `-TIP` piece; a mesh shape keeps its designed surface and gains a cap piece
  cut from its top, so its panels lose that area. The flat cap flattens the inflated top
  (a free-form test shape stood 14 mm, 1.2 %, lower than designed) and the preview solver
  converges more slowly, or not at all for some large caps, round its edge. The tip
  disc's sheet ticks where every seam meets it and names each piece between its ticks.
- Fixed: a mesh shape's panel was split the wrong way round when its boundary loop
  started part-way along the rim (the rim's direction was tested before the loop was
  turned to start at the rim).
- Added: special shapes check that every feed hole is clear of the seams of the envelope
  panel it is cut in, by the hole tape's width plus the seam allowance (*feed hole clear
  of seams*, an error when too close), and **Move feed holes clear of seams** moves the
  extra holes that are too close the least distance, inside their panels and footprints
  (one undo step). Shapes are placed again when the seam allowance or the tapes change.
- Added: *Show special shapes* in the 2D pattern view (on by default) adds every envelope
  panel a special shape is sewn on, gore by gore, with the footprint line and its
  shape-side ticks, the match marks naming their skin pieces and the feed holes at cut and
  finished size; each row lists the gores it carries shapes on. Display only.
- Added: build packs say where and how special shapes are sewn on. Marking sheets draw
  each feed hole at its cut and finished size with the hem (double fold over the hole
  tape by default), tick the side of the footprint line the shape covers, name the skin
  piece beside every match number and say when a panel lies under a shape; skin pieces
  say what each edge is sewn to (rim with its mark numbers, neighbouring pieces, tip disc
  or apex); envelope row sheets list the gores that carry a marking sheet or feed hole.
- Added: **Run Preview** and **Run CalculiX** also solve every placed special shape that
  has a feed hole, after the envelope, with the same solver and load case (each shape's
  own sub-model, element size footprint length / 100 between 60 and 300 mm, assumed;
  CalculiX from a preview of the same sub-model). The 3D view shows them as sewn and
  inflated (ADR-0031). *Simulate shape* still solves one shape with a chosen size.
- Changed: project format version 3 keeps the latest simulation of every special shape
  (summary, factor of safety, provenance, the envelope run it was solved with and the
  solved skin) with the project, so it is shown again, current or STALE, after reopening
  (ADR-0030). Version 1 and 2 files open unchanged; older releases cannot open version 3
  files.
- Changed: the 3D view draws special shapes as sewn instead of as a plain pink surface:
  every gore or panel in the skin fabric's colour (every second one darker), with the
  seams between the pieces and the rim drawn as lines. A shape simulation is drawn the
  same way as *as sewn and inflated*, and the designed shape is hidden while that result
  is current (tick it to compare). Display only; no pattern or result changes.
- Fixed: special-shape simulations put rim nodes on the straight segment between two
  footprint nodes where a load tape or row seam crossed the footprint, up to 10 mm inside
  a curved footprint, and moved a skin seam's end along the rim by up to 0.3 mesh sizes
  where a tape crossed next to it. The cut skin was strained there before any pressure
  (up to 21 % on a 9 m teardrop pod) and the solver reported false stress peaks. Every
  rim node now lies on the designed footprint and seam ends stay put (a tape crossing
  next to one meets the rim there). That pod (20 panels, 0.25 m mesh, preview solver,
  not verified): lowest skin FoS 2.6 → 67.6, converged in 147 000 iterations instead
  of 404 000, height 1.298 → 1.305 m (designed 1.300 m). The validation study on
  `special-shape-primitives` is unchanged within its tolerances (only one mesh lost 3
  of 1435 nodes). Imported build-pack pods are unaffected.
- Fixed: the parachute's red-line kinematic limit (*max travel*) was the last path sample before the travel stopped increasing, so the refined full-open pull could exceed it (by 1.9 µm in the case found). The limit is now the refined peak of the path (+3.2 µm in that case).
- Changed: the 2D pattern view puts the pieces side by side on shelves that fill the view
  (*Layout: Side by side*, the new default), re-arranged when the view is resized,
  instead of one tall column with empty space on both sides. In a wide window the pieces
  draw 2.6 times larger for the 4-row test envelope and 4.1 times for a 12-row full-size
  one. *Layout: Assembled gore* keeps the stacked view. Display only; the cut files are
  unchanged.
- Added: in the 3D view, *Face seam* / *Face gore* look straight at seam or gore *k*,
  *Zoom to layer* fits the view to the selected layer, and *Save view* keeps named
  viewpoints per project file between sessions.
- Added: viewpoint controls in the 3D view. *Front*, *Back*, *Side*, *Top*, *Into mouth*
  and *Isometric* views fit the whole scene, *◀ Gore* and *Gore ▶* turn the view one gore
  about the envelope axis, and *Orthographic* switches to a parallel projection. Each has
  a key (1, 3, 7 with Ctrl for the opposite side, 0, Home, 4/6, 5) that works over the 3D
  view itself, where VTK's own keys used to take them (its 3 turned on stereo rendering).
- Fixed: the 3D view slowed the whole window down, especially on software OpenGL (WSLg,
  Mesa llvmpipe). The render widget redrew 5 times a second even when nothing changed
  (about 0.1 s a frame for a large window there). The scene was also rebuilt with one
  render per added actor, and the rest mesh drew every tape as its own actor (473 actors
  on the 2600 m³ full-size fixture). The timer is off, a rebuild renders once, and the
  tapes are one actor (12 actors). Measured under Xvfb with llvmpipe on that fixture:
  switching to the Simulate tab 22.0 → 0.5 s, a run arriving 24.2 → 0.3 s, and no
  stalls at all while idle with the 3D view shown.
- Added: *Fit profile to simulated shape* takes the stretch out by default (*Take out the
  stretch (cut the flight shape)*). It cuts the inflated shape at the current tape length,
  with the mouth and top opening kept, so repeated fits no longer lengthen the tapes by
  the stretch: +0.39 % (tape-line tapes) or +0.67 % (gore-edge tapes) per cycle on the
  full-size fixture with plain adoption. The shape itself still drifts, taller and
  narrower by about 50 mm per cycle after ten cycles there; see
  `docs/theory/profile-matching.md`. Untick the box for the previous behaviour.
- Fixed: the window froze around runs of large designs. Building the solver model scanned
  the whole mesh once per tape: 88 s on the 2600 m³ full-size fixture at 800 mm, in a
  worker thread that held the interpreter lock and could not be stopped, so *Stop*
  waited up to a minute. Each edge length is now looked up in one table per mesh: 3.5 s,
  results bit-identical. The gore editor's solved-shape panel re-read every run's tape
  line on every refresh, including when a run started or ended (0.5 s each on that
  fixture). It now keeps them until the run, the design or the target changes, and it
  measures deviations with a k-d tree (16 ms instead of 4.4 s for 3000 points, same
  values). Headless measurement on that fixture: the longest freeze is 0.15 s, against
  81 s (Stop) and about 1 s (Start, run finished) before.
- Added: vertical load tapes can be cut to the design's tape line (`tapes.vertical_length:
  tape_line`) instead of to the gore edge they are sewn to (`fabric_edge`, the default and
  the behaviour until now). The simulation then models the tapes at the tape length, with
  the longer gore edge eased onto them, so the tapes carry the vertical load. Full-size
  fixture (2600 m³, 20 gores), 800 mm mesh: the bottom and top tapes carry 327 and 321 N
  against 205 and 76 N, and the height error falls from +507 to +483 mm. The solve takes
  29.6k iterations (38 s) instead of 17.0k (21 s). The middle rows' tapes still carry
  37–60 N of about 450 N, because the fabric there is not cut longer than the tape.
  Design schema version 8; earlier designs migrate as `fabric_edge`, and their results are
  unchanged.
- Added: *Fit profile to simulated shape* in the gore editor replaces the drawn profile
  with the simulated tape line in one click. It uses the latest current, converged run
  (CalculiX or preview). Without one, it runs the preview first. An unconverged run
  never changes the profile. *Adopt solved shape* (and the fit) now also work on a
  *Segments* profile, which becomes a spline in the same undoable edit.
- Faster preview solves: with the `fast` extra (Numba) the whole dynamic-relaxation
  iteration now runs compiled, not just the element forces. Generic 8-gore fixture:
  800 mm mesh 24.2 → 6.1 s, 1600 mm 2.9 → 0.7 s. Results agree with the Python loop to
  round-off: equilibrium positions within 0.21 µm, volume identical, iteration counts
  within a few percent (39,829 against 37,620 at 800 mm). No benchmark or golden value
  moved.
- Known limitation: on a snapped profile (spans at zero hoop stress) kinetic damping is
  sensitive to round-off. The same preview can converge or run to its iteration limit
  on either loop. Viscous damping (`damping="viscous"`, 0.05) converges it reliably
  (71k iterations on the fixture).
- Fixed: the progress bar of preview and CalculiX runs stayed near the start until the
  very end. It now follows the best residual so far and the share of the iteration
  limit, so it never moves backwards and fills by the time the run ends, converged or
  stopped at its limit. CalculiX moves during each `ccx` job. The text gives the
  elapsed time, the time to the iteration limit, and *about N s left* once the residual
  is clearly falling (or a warning that it may not converge in time).
- Added: the gore editor checks the profile under load while it is edited (membrane
  statics, milliseconds). Spans that would need hoop or meridional compression, which
  fabric cannot carry and which therefore do not keep their shape, are drawn red, live
  while dragging. *Show natural shape* draws the zero-hoop-stress shape for comparison.
  *Snap to a shape that holds* limits the curvature of the red spans only. Generic
  fixture, converged previews at 800 mm: drawn, 23 % of the tape fails the check, the
  lowest quarter collapses inward by 62 mm, largest deviation 103 mm; snapped, no
  compression, no collapse, largest deviation 48 mm. The snapped preview needs 211k
  iterations, above the default limit of 200k.
- CalculiX runs converge. A CalculiX run now always starts from a preview equilibrium of
  the same mesh. Without a current one it solves the preview first and keeps it as a
  run. From that start the tension-field states and wrinkle directions stay frozen until
  the passes settle, and are then checked against the tension-field law (new acceptance
  criterion, within 0.2 %). Generic 8-gore fixture, 800 mm mesh: before, 60 passes in
  147 s (cold) or 129 s (warm), not converged; now 1 pass in 4.4 s after an 18 s
  preview, converged, with height and volume equal to the preview's. Validation envelope
  (`docs/validation/preview-vs-calculix.md`): CalculiX 30–35 % faster (35.1 → 23.5 s on
  the finest level). Its results are unchanged within 1e-7 relative; preview values on
  that page moved by up to 5e-8 relative from earlier solver commits now regenerated.
  Cold starts are unchanged.
- The gore editor draws the solved tape line of the latest preview and CalculiX run over
  the profile, with its deviation from the intended profile (largest and RMS distance,
  height and diameter change). Stale and unconverged runs are drawn dotted and flagged.
  *Compensate towards intended profile* changes the cut so the inflated tapes land on
  the drawn profile, one step per solve. The intended profile is kept in the project
  file as `profile_target`. On the generic fixture the deviation fell 103 → 47 → 32 → 21
  → 16 mm in four preview steps. *Adopt solved shape* makes the drawn profile the solved
  line. Both need a current, converged run. New run result arrays carry the gore count.
- Added: *Set profile from file…* in the gore editor takes a shape file's or project's
  profile into the open design (points, interpolation, segments). The rows are refitted,
  the locks applied, and the edit can be undone. *Use as profile* does the same from a
  reference profile, fitted with a spline within 2 mm.
- Added: reference profiles in the gore editor. Another envelope's outline, from a
  shape file or project, or a snapshot of the current profile, is drawn dashed over the
  design. Each can be shown or hidden, renamed and shifted vertically, and the table
  shows its largest distance from the current profile. References are saved in the
  project file (`references`) and change nothing in the design.
- Fixed: with the mouth or top-hole diameter locked, the opening's control point could
  be dragged sideways on the canvas and stayed drawn there although the design had not
  changed. It now keeps the locked radius during the drag. Its radius cell is read-only,
  deleting it is refused, and the canvas redraws whenever the locks undo an edit.
- Added: the profile canvas also marks the mouth, the top (parachute) hole and the
  seated parachute edge with their diameters, and the live outputs list them.
- Added: the profile canvas marks every row seam with a tick and each row's letter, and
  highlights the row selected in the table. A dashed line marks the equator (the widest
  point, with its diameter); the live outputs give its height above the mouth and its
  position along the tape.
- Added: segment profiles. *Profile between points* gains *Segments*: every span between
  control points is a line, a circular arc (bulge) or part of a smooth curve, and each
  joint is a corner or smooth (G1). Smooth joints that cannot be met are listed as kinks.
  Converting a spline or straight-segment profile keeps its exact shape. Design schema
  version 7 (ADR-0025); older designs are unchanged.
- Added: editing many profile points at once in the gore editor. Points are selected on
  the canvas (click, Ctrl+click or box) or in the table. A drag moves the selection, and
  a soft radius with a falloff makes the neighbours follow. Also *Scale*, *Rotate*,
  *Straighten* (a straight section), *Smooth*, and a curvature comb.
- Added: *Simplify* replaces the profile's control points with as few as keep it within
  a tolerance (mm). It uses Ramer-Douglas-Peucker for straight segments and greedy
  insertion for splines, keeps the mouth and top points, and refuses when no profile
  with fewer points meets the tolerance.
- Added: build packs include the parachute: `parachute-panel.dxf` (the radial panel, cut
  once per radial panel) and `parachute-centre.dxf` (the centre circle, cut once), with
  their radial seams and centre seam checked by the output QA. A parachute whose pattern
  cannot be made stops the export with the reason.
- Added: the parachute can have a flat circular centre panel
  (`parachute.centre_panel_diameter`). Its radial panels are then trapezoids sewn to the
  circle, instead of wedges that run to the centre ring. The pattern view, the 3D view and
  the Rigging panel show it, and new parachutes get one a quarter of the hole diameter
  across. Design schema version 6 (ADR-0024); older designs keep their wedges, so their
  results do not change.
- Added: the parachute's overlap with the envelope and its centre-panel diameter are set
  in a **Parachute** box in the Rigging panel.
- Added: *Fixed mouth diameter* and *Fixed top (parachute) hole diameter* constraint
  locks in the gore editor; profile edits keep the locked end radii, and a typed target
  solves the design to it, keeping the other locks.
- Fixed: in a Wayland session (WSLg under Windows 11, many Linux desktops) Qt chose its
  Wayland platform, where the 3D view's render window crashes the application.
  EnvelopeLab now selects Qt's X11 platform (`xcb`) when an X server is present, unless
  `QT_QPA_PLATFORM` is set.
- A crash log (`~/.local/state/envelopelab/crash.log` on Linux and WSL) records the
  versions and display settings of each start, and the Python stack of a crash or an
  unhandled error. `envelopelab --diagnose` prints them with the OpenGL renderer.
- CI also runs on Windows with WSL 2 Ubuntu 24.04: the Linux install script, the full
  verification, and the 3D renderer and launcher under Xvfb.
- Crest-loft taper stations can follow a row seam (*Follows seam* in the gore editor,
  `bottom of <row>` in shape files). They stay on the seam when rows are resized,
  renamed or split. Design schema version 5 (ADR-0023); version-4 designs open unchanged.
- The 3D view shows the gore design as edited:
  - flat-chord gores with their crest raised by the crest loft or by the offset the
    measured seam bows imply (`crest_offsets_from_bows`), seams bowing outward;
  - panel zones in their fabric's colour and outlined;
  - the pattern view's tape paths and feature locations;
  - the feed holes of special shapes, with the shapes moved onto the drawn surface.
  Display only: designs, volumes and results are unchanged.
- Fixed: a set `ENVELOPELAB_CCX` that did not work stopped the search for CalculiX, so a
  working `ccx` on PATH was ignored, and nothing said why. EnvelopeLab now tries the
  preference, `ENVELOPELAB_CCX` and PATH in turn. Quoted paths, `%VARIABLES%` and folders
  are accepted. The Runs panel shows where it looked and why each place failed, and so
  does `python -m calculix_adapter`.
- CalculiX on Windows: step-by-step instructions (Windows zip from the CalculiX site, or
  conda-forge), a *Browse…* button for the CalculiX executable in Preferences, and
  detection of the Windows executable names `ccx_static.exe` and `ccx_dynamic.exe` (and
  `ccx_2.23`) on PATH.
- Windows install script: `scripts\install_env.cmd` (or `install_env.ps1`) finds or
  installs Python, creates the virtualenv, installs EnvelopeLab and checks that it starts;
  it works where PowerShell blocks scripts, and can add a desktop shortcut.
- Every part of a design can be changed in the GUI. Zones can be renamed (every reference
  follows), and *Add zone* and *Remove zone* refuse duplicates and zones in use. Rows can
  be renamed in the gore editor, and a row's zone is set in one place (gore editor or
  pattern view). Single notches, tape paths and feature locations can be removed. Extra
  feed holes of special shapes are edited in a table. Locks take a typed target value. A
  test fails when a new design field has no editor. Findings now report panel zones with
  an undefined zone.
- The Properties panel builds its editors from the design schema. Yes/no fields get a
  check box, fields with fixed choices a drop-down list, and optional values a *Clear*
  button. Optional sections (parachute rings, red line, flying wires, scoop) can be
  added and removed. Turning vents, seam types, features, scale variants and panel zones
  can be added and removed one by one. Fields owned by the gore editor or the Materials
  panel are read-only. Fixed: the flying-wire count could not be edited; control points
  and row letters could be edited there without the locks. Scale variants appear in the
  design tree.
- Fixed: changing the gore construction, the profile interpolation, the crest loft or
  the panel zones did not mark the patterns, meshes and results built from the design as
  stale. Designs that do not use them keep their fingerprints.
- The gore editor edits flat-chord gores: construction (lobe or flat chord), profile
  between points (spline or straight segments), the crest loft (fraction and taper
  stations), measured seam bows per row in mm, *Freeze as measured bows*, *Use crest
  loft* and *Straight seams*. The new-design wizard can start a flat-chord or
  straight-segment design.
- Fixed: splitting a row with measured seam bows was refused, and merging two such rows
  kept the lower row's top bow instead of the upper row's. Split rows keep their zone,
  and row letters go on past Z (AA, AB, …).
- Fixed: editing a design whose profile has straight tape segments
  (`profile_interpolation: linear`) used a spline for the locks, the row refit and the
  editor's curve, so a locked volume was held on the wrong profile (6.2 % off for a
  six-point test profile). Only linear-profile designs change. New edit
  `set_profile_interpolation` switches a design between spline and straight segments.
- Example shape files `tests/fixtures/flat_chord_pattern/` (synthetic): a 16-gore,
  10-row flat-chord pattern set and a special-shape file that `extends` it. The
  shape-family validation page now also checks the flat-chord fixture's design.
- Shape files can carry special shapes (`special_shapes`), placed by gore and row; a
  position `above` the bottom seam is measured up the panel centreline, as on the cut
  panel. **New design ▸ From shape file** puts them in the new project.
- A special shape can have several feed holes anywhere inside its footprint
  (`feed_holes`). Each is checked, cut in the sub-model and drawn on the build pack,
  including on a panel that only has a hole.
- Special shapes on flat-chord gores map to the cut panels exactly (straight sides, bowed
  seams), on the marking sheets too. Lobe-gore results are unchanged.
- Shape files, format version 2 (ADR-0022): a shape file now describes a whole pattern
  set, and **New design ▸ From shape file** builds all of it into the design.
  - Version-1 files load unchanged.
  - New optional sections:
    - a profile known only from the mouth to the top opening (`profile.span: cut`);
    - straight tape segments between stations (`interpolation: linear`);
    - flat-chord gores with measured seam bows or a crest loft;
    - named panel rows with zones;
    - single-panel zones;
    - the parachute seal overlap and crown ring;
    - rigging (parachute, red line, flying wires, scoop, turning vents) merged over the
      defaults;
    - `extends`, a file built on another one.
  - When a file gives its own rows and zones, the tab uses them instead of its row-count
    and fabric choices.
- Flat-chord gores (design schema version 4, ADR-0021). A new gore construction cuts
  every row as a flat tape-to-tape trapezoid with straight sides, and lofts the gore
  lengthwise: its horizontal seams bow outward as parabolas, given per row (measured) or
  from a crest loft (crest offset as a fraction of the radius with a taper).
  - Profiles can use straight tape segments between control points.
  - Single panels can get their own material zone (appliques, doublers).
  - Row letters may have up to 8 characters.
  - Version-3 designs open unchanged; their results are bit-identical.
  - The design volume of a flat-chord gore is that of the flat-gore polygon.
- The `gui` extra excludes PySide6 6.12: that release drops a reference to `None` on
  every Qt call that returns nothing, so on Python 3.11 the application (and the test
  suite) aborted with "Fatal Python error: none_dealloc" after a while.
- Special shapes: new *attachment ease* check. The skin rim is sewn to the footprint
  line marked on the flat envelope panels, which differs from the rim because the flat
  gores carry the lobe bulge; the difference is now measured between every pair of
  match marks and is an error above 3 mm (a 0.5 m dome low on the 8-gore fixture eases
  4.7 mm into one interval; default-size shapes under 1 mm). No pattern changes.
- Build packs list each shape's rim and its marked footprint lines as a sewn pair with
  the planned ease (`ease_mm`), and the output QA checks the files against it.
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
- `scripts/install_env.sh` now installs the OpenMP runtime the Gmsh wheel needs
  (`libgomp1` on Debian/Ubuntu) and checks that Gmsh loads. Fixes "build pack import
  failed: libgomp.so.1: cannot open shared object file" on minimal installs such as WSL
  Ubuntu 24.04.
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
