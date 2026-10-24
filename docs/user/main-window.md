# The main window

The window shows one **workflow mode** at a time. The mode tabs sit above the workspace;
the menu **View** lists the same modes with shortcuts:

| Mode | Shortcut | Shows |
|---|---|---|
| **Shape** | Ctrl+1 | The gore editor: meridian profile, control points, panel rows, constraint locks and live outputs |
| **Patterns** | Ctrl+2 | The 2D pattern view beside the **Materials** panel (fabric library and material zones) |
| **Rigging** | Ctrl+3 | The **Rigging** panel: parachute, red line, flying wires, turning vents, scoop |
| **Special shapes** | Ctrl+4 | The **Special Shapes** panel: domes, tubes, revolved and mesh shapes on the envelope, their cutting patterns and simulations ([guide](special-shape-primitives.md#in-the-desktop-application)) |
| **3D / Simulation** | Ctrl+5 | The 3D view above the **Simulation Runs** table |
| **History** | Ctrl+6 | Undo history, snapshots, versions and provenance |

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

## Moving around the 3D view

Drag with the left mouse button to orbit, the right button or the wheel to zoom, and the
middle button (or Shift and the left button) to pan. The row of buttons under the 3D
options places the camera exactly:

| Button | Key | View |
|---|---|---|
| **Front** / **Back** | 1 / Ctrl+1 | From the front or back, mouth down |
| **Side** / **Other side** | 3 / Ctrl+3 | From either side, mouth down |
| **Top** / **Into mouth** | 7 / Ctrl+7 | Down onto the crown, or up into the mouth |
| **Isometric** | 0 | Three-quarter view from above |
| **Fit** | Home | The whole scene, keeping the current direction |
| **◀ Gore** / **Gore ▶** | 4 / 6 | Turn the view one gore (360° / gore count) about the envelope axis |
| **Orthographic** | 5 | Parallel projection on or off: no perspective, so profiles and lengths compare directly |

A second row places the camera on a part of the envelope and keeps viewpoints:

* **Face seam** / **Face gore** with the number beside them: look straight at vertical
  seam *k*, or at the centre of gore *k*, mouth down, with it running up the middle of
  the view. Seams and gores are numbered as in the Rigging panel (gore *k* lies between
  seams *k − 1* and *k*).
* **Zoom to layer**: fit the view to the layer selected in the layer list (the design
  surface, a run's result, the rest mesh, …), keeping the viewing direction.
* **Views**: *Save view* remembers the current viewpoint and projection under a name.
  Choose it in the list to go back there, or *Delete view* to forget it. Saved views
  belong to the project file and are kept between sessions (in the application settings,
  not in the project).

The number keys follow the numeric-keypad views of common 3D programs, and they work on
the number row too. They act when the 3D view or its panel has the keyboard focus (click
the view first). Stepping by gores keeps a seam or a gore centre in the same place on the
screen, so the gores can be checked one by one. The chosen view stays when the scene
changes, for example when a run finishes.

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
