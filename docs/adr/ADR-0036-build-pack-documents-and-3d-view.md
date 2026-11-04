# ADR-0036: Build pack format 2: documents and a self-contained 3D view

- Status: Accepted
- Date: 2026-11-03

## Context
A build pack (ADR-0016, format `envelopelab-build-pack/1`) held the cutting sheets
(DXF, `pattern.pdf`) and `index.json`. A builder also needs to know what to cut in what
quantity, the order of the seams, the rigging lengths and loads, the design's size, lift
and masses, which values are only *assumed*, and what the balloon looks like inflated,
including its factor of safety, without running EnvelopeLab. The 3D page must open
offline and must not hide a stale, unconverged or preview-only result (AGENTS.md §1).
Ready-made WebGL libraries (three.js, MIT) would work but add about 600 kB to every pack
and a dependency with a runtime role.

## Decision
- The index becomes format `envelopelab-build-pack/2`: two new keys, `provenance`
  (app version, git commit, design hash, time, project) and `documents` (file, kind,
  description). A pack exported without documents has both empty.
- Documents (`envelopelab.export.documents`): cover and index, spec summary, cut list,
  rigging sheet and sewing schedule, as PDF (the existing minimal writer,
  `envelopelab.report.pdf`) and CSV or JSON, generated from the same sheets, seam pairs
  and outputs as the rest of the pack.
- The 3D view (`envelopelab.export.viewer`) is one HTML page with its own small WebGL
  renderer (no library, no network). The scene is embedded as JSON with base64 arrays.
  Every colour is computed by EnvelopeLab with the application's colour rules and stored
  per triangle or point, so the page computes nothing. The banner is the application's
  banner; stale and unconverged results carry no colouring.
- The output QA (`envelopelab.export.qa`) checks the documents: they are listed, the
  PDFs open, the cut list agrees with every sheet header, and the 3D page loads nothing
  from outside itself.
- **File ▸ Export build pack…** chooses the folder, the roll width and the documents.

## Consequences
- Readers of format 1 that ignore unknown keys read format 2 packs unchanged; the QA
  reads both.
- No new dependency. The renderer is small (orbit, pan, zoom, flat shading, lines,
  labels) and has to be maintained with the pack format; a test checks its banner
  colours against the application's theme.
- The 3D page shows the run chosen in the application's 3D view at export time; a pack
  exported from a script shows the design and its rigging only.
- Nesting (marker layouts) and printed tape-marking templates are not part of this
  format and would extend it.
