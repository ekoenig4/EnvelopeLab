# ADR-0007: Desktop application stack (PySide6, PyVista, pytest-qt)

- Status: Accepted
- Date: 2026-09-29

## Context
EnvelopeLab needs a desktop application in which builders create, inspect and modify
designs without editing JSON, run the preview and CalculiX solvers and inspect results in
2D and 3D. It must be free/open-source (GPL-3.0 project), run on Linux, macOS and Windows,
and be testable headlessly in CI. Engineering math must stay in `envelopelab` (AGENTS.md).

## Decision
* **PySide6** (Qt for Python; LGPL-3.0-only / GPL) for the application: dock widgets,
  undo history views, QGraphicsView for the profile canvas and the 2D pattern editor,
  QThread workers for solves.
* **PyVista** (MIT) with **pyvistaqt** (MIT) on **VTK** (BSD-3-Clause) for the 3D view:
  orbit/zoom, clip-plane section, cell picking, spline widget for profile editing. The 3D
  panel keeps a plain layer list (source, colour, stale and convergence state) and draws it
  only when a renderer is available, so the application also runs without OpenGL.
* **pytest-qt** (MIT, dev only) for GUI tests on Qt's `offscreen` platform; the renderer
  test runs under Xvfb on Linux CI.
* The GUI lives in `app/envelopelab_app` and is a view of `envelopelab.project`
  (sessions, commands, dependency graph, project files), which holds every calculation.
* The GUI is an optional extra (`pip install -e ".[gui]"`), so the library and solvers keep
  working without Qt or VTK.

## Consequences
Wheels for all CI platforms exist; the GUI extra adds ~300 MB (Qt, VTK). Qt's LGPL is
compatible with the GPL-3.0 project. Headless CI covers the application logic and the layer
bookkeeping; pixel output of the 3D view is only checked for being produced (Xvfb test).
