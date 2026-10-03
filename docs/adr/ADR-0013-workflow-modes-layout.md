# ADR-0013: Workflow modes and splitters instead of dock widgets

- Status: Accepted
- Date: 2026-10-03

## Context
ADR-0007 chose PySide6 with dock widgets for the main window. The window grew to a central
gore editor plus nine docks shown at once. Their minimum sizes add up: with a project open,
the window could not be made smaller than 2137 × 1036 px, so on common screens panels were
clipped and resizing did not work. The layout was not saved, and there was no way to reset a
broken arrangement. Most panels belong to one stage of the work (shape, patterns, rigging,
simulation, history), so showing all of them at once added clutter without helping.

We considered: keeping the docks with saved and preset layouts; a sidebar with a tabbed
centre (VS Code style); the Qt Advanced Docking System (`PySide6-QtAds`, LGPL-2.1); and a
different GUI stack.

## Decision
* The main window shows one **workflow mode** at a time (Shape, Patterns, Rigging,
  3D / Simulation, History), chosen with a tab bar or Ctrl+1 to Ctrl+5. Each mode is a page
  of a `QStackedWidget` holding one or two panels.
* The Design Tree / Properties **sidebar** and the **Validation / Warnings strip** are
  visible in every mode. Only the sidebar can be collapsed, so the layout can never hide
  safety warnings (AGENTS.md §1).
* Areas are divided by named `QSplitter`s instead of `QDockWidget`s. Tall forms are put in
  scroll areas so they do not set the window's minimum size.
* Each panel lives in exactly one mode. The PyVista interactor is not moved between parents,
  because reparenting a native OpenGL widget is unreliable on some platforms.
* Mode tabs repeat the panels' ● (unsaved) and [STALE] indicators.
* The layout (mode, splitter states, window geometry) is stored in `QSettings` under
  `layout/last` on close and restored at start; **View ▸ Save layout / Load saved layout**
  use `layout/saved`; **View ▸ Reset layout** applies built-in default sizes. A stored
  layout carries a version and is ignored when the splitter structure changes.

This supersedes the dock-widget part of ADR-0007; the rest of ADR-0007 still applies.

## Consequences
No new dependency. With the fixture project open, the minimum window size fell from
2137 × 1036 px to under 1280 × 800 px. Panels cannot be torn off into floating windows
or arranged freely. If that is needed later, the Qt Advanced Docking System is the
candidate, and it would need a new ADR. Seeing the 3D view and the gore editor side by side
needs a mode switch, because the 3D view lives only in the 3D / Simulation mode.
