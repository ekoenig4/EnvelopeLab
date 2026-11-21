# ADR-0056: Live link with Blender through an EnvelopeLab add-on

- Status: Proposed
- Date: 2026-11-21
- Extends: ADR-0017 (mesh exchange with Blender), ADR-0018 (free-form mesh shapes)

## Context
Free-form special shapes (ears, curved horns, faces) are modelled in Blender and brought
in as a mesh file (ADR-0017, ADR-0018). The round trip is manual: export, open, model,
export, import, and only then does EnvelopeLab say whether the mesh can be cut (axis
through the top, disc-shaped panels, no folds when flattened). Builders want one
integrated application.

Three ways to integrate Blender were considered:

* **Embed Blender's window in the Qt main window.** Blender has no supported way to run
  inside another application's window. Re-parenting its native window
  (`QWindow.fromWinId`) is fragile and behaves differently on Linux, macOS, Windows and
  WSLg. Rejected.
* **Import Blender as a Python module (`bpy` from PyPI).** It provides Blender's
  modelling operations without its user interface, so the editor would still have to be
  written. Each `bpy` release supports exactly one Python version and the wheel is several
  hundred MB. Rejected for interactive editing; it may be reconsidered for background mesh
  operations.
* **Blender as an optional external program, linked live through an add-on.** Chosen.

## Decision
* **Optional external program.** Blender (GPL-2.0-or-later) is run as a separate process,
  like CalculiX (ADR-0005). It is not linked, imported or distributed, and it is never
  required: without it, every other feature works and the *Edit in Blender* action says
  that Blender was not found and how to set its path.
* **The add-on.** EnvelopeLab ships a Blender extension (`blender_manifest.toml`,
  GPL-3.0-or-later), *EnvelopeLab Link*, in a new top-level `addons/blender/` directory.
  It contains no engineering math: it sends meshes, receives feedback and draws it.
* **Launch.** *Edit in Blender* on a free-form shape starts Blender with the add-on
  enabled and the shape loaded, using ADR-0017's axes (Z up, metres). Blender is found
  through a setting, then `PATH`, then the standard install locations, and its version
  (`blender --version`) is checked against the supported range.
* **Transport.** A loopback TCP connection (`127.0.0.1` only, a port chosen by the
  system), opened with a random per-session token passed in the environment. Messages
  are JSON lines; meshes are carried as binary PLY (Z up, metres), read with the existing
  `envelopelab.io` mesh code. Blender's side polls the connection with
  `bpy.app.timers`, because `bpy` must not be called from another thread.
* **Messages.** `open_shape` (EnvelopeLab to Blender: the mesh, the shape's name, the
  envelope as reference geometry). `mesh_update` (Blender to EnvelopeLab: when the file
  is saved or *Send to EnvelopeLab* is pressed). `feedback` (EnvelopeLab to Blender: the
  seam lines, a per-face flattening-strain attribute and the design checks with their
  severity). `close`.
* **Edits in EnvelopeLab.** A received mesh goes through the ADR-0018 checks unchanged and
  becomes **one undoable edit** (ADR-0050). A mesh that cannot be cut is rejected with the
  same message as an import, which is also shown in Blender; nothing is repaired
  silently. If the shape was changed in EnvelopeLab after it was sent, the user chooses
  which version to keep; nothing is overwritten without asking.
* **Feedback is labelled as design feedback.** Strain colours in Blender show flattening
  strain of the designed surface. Simulated results are not sent to Blender until a later
  ADR defines how their convergence status is shown there.
* **Code layout.** The message format and mesh encoding are pure, typed functions in
  `envelopelab.io.blender_link`. Starting Blender and the socket server live in the
  application (`app/`), since they hold no engineering math. The add-on lives in
  `addons/blender/envelopelab_link/`.

## Implementation plan
1. **Message format and mesh encoding** (`envelopelab.io.blender_link`): message types,
   validation, PLY encoding, the token handshake. Unit and property tests (round trip of
   every message is lossless). No Blender needed.
2. **Add-on**: connect, receive `open_shape`, send `mesh_update`, sidebar panel. Tested
   against a fake EnvelopeLab server in the add-on's own tests, and by a `slow` test that
   runs real Blender with `--background` where it is installed.
3. **Application**: *Edit in Blender* action, Blender path setting, launcher, socket
   server, undoable import and the conflict choice. GUI tests use a fake Blender client.
4. **Feedback in Blender**: seam lines, strain colours, the list of checks.
5. **Install and CI**: `install_env.sh --blender` (and the Windows script) fetch a
   supported Blender; the Linux and WSL CI jobs run the `slow` round-trip test. User
   guide page, `LICENSES.md` row for Blender, AGENTS.md layout entry for `addons/`.

## Consequences
Builders model in Blender and see in Blender, as they model, whether EnvelopeLab can
cut the shape, without exporting and importing by hand. No Python dependency is added.
The supported Blender versions have to be stated and tested, because Blender's Python API
changes between releases. A local network port is opened while a link is active; it
accepts only loopback connections that present the session token. Built-in modelling
(more parametric primitives, cross-section lofts) remains planned separately, so that
common shapes need no Blender at all.
