# The main window

The window shows one **workflow mode** at a time. The mode tabs sit above the workspace;
the menu **View** lists the same modes with shortcuts:

| Mode | Shortcut | Shows |
|---|---|---|
| **Shape** | Ctrl+1 | The gore editor: meridian profile, control points, panel rows, constraint locks and live outputs |
| **Patterns** | Ctrl+2 | The 2D pattern view beside the **Materials** panel (fabric library and material zones) |
| **Rigging** | Ctrl+3 | The **Rigging** panel: parachute, red line, flying wires, turning vents, scoop |
| **3D / Simulation** | Ctrl+4 | The 3D view above the **Simulation Runs** table |
| **History** | Ctrl+5 | Undo history, snapshots, versions and provenance |

Two areas stay visible in every mode:

* the **sidebar** on the left, with the **Design Tree** above **Properties**. Selecting an
  element in the tree shows its values in Properties, whatever the mode.
* the **Validation / Warnings** strip at the bottom. The layout cannot hide it, so errors,
  factor-of-safety failures and stale or unconverged results stay on screen while you
  work in any mode.

Mode tabs repeat the indicators of the panels they hold: **●** for unsaved changes and
**[STALE]** when a result they show is out of date (for example *Patterns [STALE]* after
changing the seam allowance, until you press **Regenerate patterns**). A stale panel's
title is drawn in red.

## Resizing

Every divider between areas can be dragged. A mode page or form that needs more space
than the window has scrolls instead of growing the window, so the window fits a
1280 × 800 screen, also with large system fonts. Only the
sidebar can be collapsed (drag its divider to the left edge, or **View ▸ Show sidebar**);
the mode page and the warnings strip always keep some space.

## Saving, loading and resetting the layout

* The layout (mode, divider positions, window size and position) is remembered when you
  close the window and restored at the next start.
* **View ▸ Save layout** stores the current mode and divider positions.
  **View ▸ Load saved layout** returns to them (the window keeps its size).
* **View ▸ Reset layout** returns to the default divider positions and the Shape mode.

Layouts are stored in the application settings, not in the project file, so they apply to
every design. A layout stored by an older EnvelopeLab with a different window structure is
ignored and the defaults are used.
