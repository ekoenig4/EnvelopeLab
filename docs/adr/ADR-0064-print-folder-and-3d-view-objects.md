# ADR-0064: Print folder (pack format 5) and the 3D view's objects and Shape states

- Status: Accepted
- Date: 2026-11-27

## Context
A build pack's 1:1 templates lay at its top level among the documents (PDF, HTML, CSV,
DXF), so builders had to pick out the files to send to the printer by name. Separately,
the pack's 3D page did not show the special shapes when a run was shown (the designed
shapes were hidden under the result, and shapes not solved with the run were not drawn),
and its layer list did not work like the application's 3D view, where a *Shape* choice
(Designed, Inflated (preview), Inflated (CalculiX)) says what every object is drawn as
and an *Objects* list turns the envelope, each special shape, each overlay and the
rigging on and off.

## Decision
* **Pack format 5** (`envelopelab-build-pack/5`): every template PDF is written in
  `print/` (`envelopelab.export.templates.PRINT_DIR`), and `print/` holds nothing else.
  A template's name in the code and in `index.json` (`templates[].file`) is its path in
  the pack (`print/<slug>-panel-A.pdf`), so the documents that name a template name its
  path. The build-pack index lists `print/` first under *START HERE*. The QA checks every
  template is in `print/` and `print/` holds only templates. Formats 1 to 4 are still
  read by the QA; format 4's roll-frame rule for the page width applies to format 5.
* **Viewer format 2** (`envelopelab-viewer/2`): every mesh and line has an `object`
  (`envelope`, `shape:<name>`, `overlay:<name>`, `rigging`) and a `state` (`design`,
  `envelopelab-preview`, `calculix`, or null for every state). The scene lists its
  `objects`, its `states`, the state it opens on and each state's banner. The page shows
  a *Shape* select and an *Objects* list with the application's rule: each ticked object
  is drawn as its parts of the chosen state, else as designed (its row says so); with
  the deviation chosen, its designed parts too. A field drawn on the design for one state
  is keyed `<field>@<state>`.
* The application exports every state the 3D view has, each with its fields on a shared
  scale per field and state and its run's banner, and opens the page on the Shape the
  view shows. Without a view (scripts, scale models) the page offers *Designed* with
  the envelope, every special shape (`design_scene(shapes=...)`) and the rigging.

## Consequences
* Packs written by this release have their templates in `print/`; tools that looked for
  them at the top level need the new path (the index gives it).
* The 3D page is larger by the parts of every state (preview and CalculiX both, when
  both exist).
* Per-shape 3D pages keep their own scenes, now also tagged with objects and states.
