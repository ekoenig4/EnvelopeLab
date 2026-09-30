# Your first design

This walkthrough creates a standard-gore envelope in the desktop application, checks its
live outputs and saves it as a project.

!!! danger "A design aid, not a certification"
    EnvelopeLab is not certified engineering software. The builder is responsible for
    airworthiness. Red items in the **Validation / Warnings** panel, results marked
    **NOT CONVERGED** or **STALE**, and factor-of-safety failures must be resolved before
    you rely on a design.

## Install and start

See [Installation](installation.md) (on Linux: `bash scripts/install_env.sh`), then:

```bash
envelopelab                          # or: python -m envelopelab_app [project.elproj]
```

Start with `envelopelab --no-3d` on a computer without OpenGL; every panel still works,
and the 3D panel lists its layers without drawing them.

## Create the design

1. **File ▸ New design…** opens the wizard. On the **Standard gore** tab enter:
    * target **volume**, **height** (mouth to top opening) and **maximum diameter**;
    * the number of **gores N**;
    * the **mouth row fabric** (default Nomex, next to the burner; or no separate mouth
      row) and its **height** along the tape (0: the same as each body row);
    * the number of **body panel rows** above the mouth row (nylon by default);
    * mouth and top-opening diameters as fractions of the width;
    * the body and parachute fabric, seam allowance and the internal and ambient
      temperatures.

   The envelope is then, from the mouth up: the mouth row (zone `mouth`), the body rows
   (zone `body`) and, as the top panel, the parachute over the crown opening with its
   crown ring and centre ring ([parachute and rigging](rigging.md)).
2. Press **OK**. The wizard finds a profile with exactly that height and width whose
   volume is the target (within 0.1 %). When the volume cannot be reached with that height
   and width, the wizard says which volumes can.

The other tabs create a **special shape from an imported mesh** (OBJ, STL or PLY in m; the
design references the mesh, panels are added later) and **design from measurements**
(planned, not available yet).

## Read the live outputs

The central **gore editor** shows the meridian profile, its control points, the panel rows
and the **Live outputs**, recomputed after every edit:

| Output | Meaning |
|---|---|
| Meridian (tape) length | Length of a load tape from mouth to top, m |
| Height, maximum diameter | Of the surface of revolution through the tapes, m |
| Fabric area, volume | m², m³ |
| Gross lift | \( L = V(\rho_{amb} - \rho_{int}) g \) at the design's temperatures and pressure |
| Estimated envelope mass | Cut panel area × fabric areal mass + tapes + thread, kg |
| Lift margin | \( L/g \) minus envelope mass and payload, kg (red when negative) |
| Material sources | Source tags of every material value in the estimate |

Tape and thread masses are generic `assumed` values; fabric areal mass comes from the
fabric library with its source tag (see [theory](../theory/design-editing.md)).

## Save

**File ▸ Save** writes a project file (`*.elproj`, [format](../formats/project-file.md)).
Panel titles show **●** while there are unsaved changes in what they display. While there
are unsaved changes an autosave file is written every few minutes (**File ▸
Preferences**); after a crash the next start offers to recover it. **File ▸ Open Recent**
lists the last ten projects.

Next: [editing designs](editing-designs.md) and [running simulations](running-simulations.md).
