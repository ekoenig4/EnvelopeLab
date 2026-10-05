# Adding special shapes to a standard envelope

Start from a standard-gore design, add domes (blisters, lobes, ears), tubes (horns,
masts) and revolved shapes of any profile (noses, bulbs, onions, balls) on top of it, and
EnvelopeLab works out:

* where each shape meets the envelope (the **footprint**), as a line to mark on every
  envelope panel it crosses, in that panel's own pattern coordinates;
* numbered **match marks** on that line and on the shape's rim, so the skin goes on
  in the right place;
* the **cutting pattern** of the shape: finished and cut outlines of every gore or panel,
  and a tip disc for a tube;
* **checks** on that pattern;
* a **simulation model** whose skin is sewn from exactly those cut pieces, so you can see
  how the shape holds under pressure before cutting cloth.

!!! danger "Design aid only"
    EnvelopeLab is not certified engineering software. Preview results are not verified,
    and a result that did not converge is not a prediction. The builder is responsible
    for airworthiness.

The shapes are part of the project: they are saved in the project file, undone and redone
with the rest of the design, and kept in snapshots and versions. Use them in the desktop
application ([below](#in-the-desktop-application)) or from Python (sections 1 to 5).

## In the desktop application

Open a standard-gore project and choose the **Special shapes** mode (**View ▸ Special
shapes**, or its tab).

1. **Add shape** ▸ **Dome**, **Tube** or **Revolved profile** adds a shape sized from your
   envelope on gore 1, about halfway up the tape. **Import mesh (OBJ/STL/PLY)…** adds a
   free-form shape modelled in Blender (metres, Y up for OBJ as Blender exports it; Z up
   for STL and PLY). The mesh is stored in the project, so the file is no longer needed.
2. Edit the shape in the **Parameters** form: placement (gore, tape position from the
   mouth in m, position across the gore, lean and lean direction in degrees), sizes in m,
   number of skin gores or panels, match marks per piece, seam allowance, an optional
   feed hole in the envelope, and the skin fabric (by default the fabric of the envelope
   row the shape sits on). A revolved shape's profile is edited in its table (radius and
   height in m, base first, axis last). Every change is one undo step.
3. The shape is placed in the background while you keep editing; the list says
   **being placed…** until it is done (usually under a second). The right-hand side then
   shows the **pattern checks**, a drawing of the **cut pieces** (finished line solid, cut
   line dashed, the rim sewn to the envelope in red) with their sizes and areas, and the
   **attachment lines** on each envelope panel. The **3D View** shows the shape on the
   envelope.
4. To move a shape by hand, press **Drag in 3D view…** (or tick **Drag special shapes**
   in the 3D View). Press the left mouse button on a shape and drag it over the
   envelope: a magenta ring shows where its base will sit, and the 3D View's info line
   gives the gore, the tape position from the mouth and the position across the gore.
   Release to place it there; the shape is placed again in the background and the move
   is one undo step (**Edit ▸ Undo** moves it back). The lean set in the form is kept.
   Pressing anywhere else still turns the view. The ring is an approximate preview (a
   circle of the base radius, without the lean); the real footprint, pattern and checks
   come when the shape is placed.
5. **Simulate shape (preview solver)** solves the shape's sub-model (choose the mesh
   size; finer is slower) in the background. **Cancel** stops it. The result lists the
   convergence status, iterations, final residual, mesh size, heights above the envelope
   as designed and inflated, chamber pressure, wrinkled fraction, rim tape tension and
   the factor of safety of each region. It is drawn in the 3D View as a separate layer.
6. **Export build pack…** writes the envelope rows and every shape's pieces and marking
   sheets (DXF, PDF and `index.json`, section 4). **Export to Blender (OBJ)…** writes the
   envelope, every shape and every current shape simulation (section 5).

Nothing is hidden. A shape that cannot be placed (for example a base too large for the
local curvature), a failed check, a simulation that did NOT converge, a factor of safety
below 5, and a simulation that is **STALE** because the shape or the envelope changed
after it ran are shown in red in the panel and listed in **Validation / Warnings**.
Selecting such a warning opens the shape. The build pack is not written while a shape
is being placed or cannot be placed, so a pack never leaves a shape out without saying
so. Shape simulations are kept until the project is closed; they are not saved in the
project file.

## 1. Place a shape

```python
from envelopelab.features.primitives import (
    Dome,
    Tube,
    Placement,
    EnvelopeSurface,
    design_primitive,
)

surface = EnvelopeSurface.from_design(design)  # your standard-gore design

ear = Dome(
    "ear",
    Placement(gore=3, tape_position=12.0),  # gore 3, 12 m up the tape from the mouth
    base_radius=1.0,
    height=1.2,  # m
    gores=16,  # skin gores
)
horn = Tube(
    "horn",
    Placement(
        gore=6,
        tape_position=10.0,
        across=0.5,  # on the load tape of gores 6/7
        lean_deg=30,
        lean_toward_deg=0,
    ),  # leaning 30° towards the crown
    base_radius=0.8,
    tip_radius=0.3,
    length=2.5,  # m
    panels=4,
)
d = design_primitive(ear, surface, seam_allowance=0.0125, feed_hole_radius=0.3)
```

**Any profile.** A `Revolved` shape spins a profile you give as `(rho, zeta)` points
about its axis. `rho` is the distance from the axis and `zeta` the height above the base
circle, both in metres, from the base circle (`zeta` = 0) to the tip. End on the axis
(`rho` = 0) for a point, or anywhere else for a flat tip disc:

```python
from envelopelab.features.primitives import Revolved

onion = Revolved(
    "onion",
    Placement(gore=9, tape_position=11.0),
    profile=((0.4, 0.0), (0.9, 0.5), (0.8, 1.0), (0.3, 1.5), (0.0, 1.9)),
    gores=12,
)
```

The points are joined by a smooth curve (`smooth=False` for straight segments). A single
straight segment is a frustum and is unrolled exactly like a tube.

**Placement.** Gores are numbered from 1. `across` is the fraction of the gore width from
its centreline (−0.5 and +0.5 are the load tapes either side). `tape_position` is measured
along the load tape from the mouth, in metres. The lean tilts the shape's axis away from
the envelope normal: `lean_toward_deg` 0 leans it up towards the crown, 90 towards the
next gore and 180 down towards the mouth.

**Shapes from Blender.** Model anything else (an ear, a curved horn, a face) in Blender
and bring it in as a `FreeformShape`:

* model it in metres around the origin, with **Z out of the envelope** (the shape's
  axis), **X up the balloon** towards the crown, and the origin where the axis meets the
  envelope;
* make it a closed surface and **sink its base a little below Z = 0**, as you would for a
  boolean union with the balloon. EnvelopeLab cuts away everything inside the envelope,
  and the cut edge becomes the footprint;
* the axis must leave the shape through its top. The panels are cut along half-planes
  through the axis, like gores, and meet there;
* export it with **File ▸ Export ▸ Wavefront (.obj)** using the default settings (or STL).

```python
from envelopelab.features.primitives import FreeformShape
from envelopelab.io.blender import read_shape_mesh

ear = FreeformShape(
    "ear",
    Placement(gore=4, tape_position=13.0, lean_deg=15),
    read_shape_mesh("ear.obj"),  # Blender's default OBJ axes, metres
    panels=12,
)
d = design_primitive(ear, surface, feed_hole_radius=0.3)
```

Each panel is flattened so that its footprint edge and both seam edges keep their exact
lengths. Then both sides of every seam match and the rim matches the footprint. The
flattening strain of a curved panel goes into its interior, and the *area distortion*
and *edge strain* checks report it: use more panels until they pass.

## 2. Read the result

```python
for c in d.checks:
    print(c.severity, c.name, c.value, c.message)

for line in d.attachment:  # footprint on each host panel
    print(line.gore, line.row, line.points)  # m, panel pattern coordinates

for m in d.marks:  # match marks
    print(m.number, m.gore, m.row, m.host_xy, m.piece, m.piece_xy)

for p in d.pieces:  # cutting pattern
    print(p.label, p.size, p.cut_count)  # finished width, height (m)
    p.finished, p.cut  # outlines, m

summary = d.as_dict()  # JSON-ready, units in the keys
```

Panel pattern coordinates are the same as the 2D pattern view: `x` across the panel from
the gore centreline, `y` up from the finished bottom seam line of the row. Mark 1 is at
the top of the shape (towards the crown) and the numbers run round it. Every mark has a
partner on a skin piece's rim edge (`piece`, `piece_xy`).

**What the checks mean**

* *rim length*, *skin seam match*: the skin's rim must equal the footprint, and the two
  sides of every skin seam must be the same length (within 3 mm). Tube panels are exact
  developments, and dome gores are laid out so both sides of each seam have the seam's
  true length.
* *attachment ease*: the skin's rim is sewn to the line marked on the **flat** envelope
  panels, which is a little longer or shorter than the rim (the flat gore includes the
  bulge of the lobe). The difference is worked in between match marks; the check gives
  the largest difference between two neighbouring marks and the total. Above 3 mm it is
  an error: add match marks (*marks per piece*), use more envelope gores, or a smaller
  shape. Small shapes on most envelopes ease well under 1 mm.
* *area distortion*: a dome's gores cannot be flattened without changing their area.
  Above 1 % the check warns. Use more gores: the distortion drops about four times when
  you double them (3.7 % at 8, 0.9 % at 16, 0.2 % at 32 gores for a hemisphere).
* *host panels*: the gores and rows the footprint crosses. Mark it on all of them.
* *feed hole inside footprint*: the hole cut in the envelope to inflate the shape must
  lie inside the footprint.

A shape is rejected if it does not fit: a base too large for the local envelope
curvature, a lean that brings the skin back onto the envelope, or a footprint that would
reach the mouth or the crown.

## 3. See how it holds its shape

```python
from envelopelab.features.builder import build_appendage
from envelopelab.features.metrics import appendage_metrics
from envelopelab.features.primitives import primitive_appendage
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions
from envelopelab.solvers.simulation import from_preview

spec = primitive_appendage(d, mesh_size=0.2, load_tape=tape, rim_tape=tape, hem_tape=tape)
cond = OperatingConditions.hot_air(373.15, mouth_height=0.0, self_weight=False)
am = build_appendage(spec, cond, {"host": envelope_fabric, "skin": skin_fabric})
result = from_preview(am.model, solve(am.model))
metrics = appendage_metrics(am, result)
print(result.status, metrics.projected_height, spec.intended["projected_height_m"])
print(metrics.fos, metrics.skin_wrinkled_fraction)
```

The skin is sewn from the cut pieces exactly as patterned, and the shape is filled
through its feed hole. The result shows:

* **projected height** against the designed height: how well the sewn shape keeps the
  shape you designed;
* **factors of safety** of the skin, the envelope under the shape and around it;
* **wrinkled skin**: where the cloth carries tension in one direction only. At envelope
  pressures any pattern that differs from the designed shape by more than about 0.01 %
  shows some, so read it as an indicator that depends on the mesh, not as a count of
  visible wrinkles;
* the load in the envelope's tapes near the shape.

Check `result.converged` before reading anything. A result that did not converge is not
a prediction. The same model can be verified with CalculiX (`calculix_adapter.run_calculix`)
or run through the [Reality Check report](reality-check-report.md) workflow.

## 4. Export the cutting patterns

```python
from envelopelab.export.build_pack import export_build_pack
from envelopelab.export.qa import check_pack

export_build_pack(
    design,
    [d],  # the envelope and its placed shapes
    "build-pack/",
    skin_fabric={"ear": "ripstop red"},  # per shape, or one name for all
    roll_width=60 * 0.0254,  # m (60 in roll)
)
assert check_pack("build-pack/") == []  # the output QA, from the files alone
```

The pack contains:

* one DXF per piece, in millimetres: the envelope's row panels (cut once per gore) and
  every gore, panel and tip disc of each shape;
* a **marking sheet** for each envelope panel a shape crosses: the panel with the
  footprint line, the numbered match marks and the feed hole drawn where they go. Mark
  them on the cut panels before sewing the envelope;
* `pattern.pdf`: every sheet at 1:1 on pages as wide as your fabric roll. A sheet wider
  than the roll is split into numbered strips;
* `index.json`: every file with its piece, cut count, fabric, finished size, and which
  edges are sewn together.

Before cutting, **measure the calibration line** on every printed or plotted sheet. It
must measure what its label says (for example 500 mm with ticks every 100 mm). If it
doesn't, the sheet was scaled when it was printed. The layers and the index are described in
[Build pack](../formats/build-pack.md).

## 5. Look at it in Blender

```python
from envelopelab.features.scene import export_scene

export_scene(
    "balloon.obj",
    surface,
    designs=[d],  # shapes as designed
    solved=[(d, am, result)],  # and as simulated (from step 3)
)
```

In Blender use **File ▸ Import ▸ Wavefront (.obj)** with the default settings. The file is
written with Y up, which is what Blender's importer expects, so the balloon stands
upright, in metres. Each part is a separate object: `envelope`, `<name>_designed` and
`<name>_simulated`. A simulation that did not converge is named
`<name>_simulated_UNCONVERGED`: it is not a prediction. For STL use
`envelopelab.io.blender.write_stl_object`; STL files are written Z up, Blender's STL
default.

## Limitations

* Revolved shapes are symmetric about their axis. Use a Blender mesh for anything
  else.
* A free-form shape's axis must leave the mesh through its top, and each panel must be
  a single piece. A strongly curved horn may need a leaned placement, or more panels.
* A free-form shape rests in its flattened panels exactly as the mesh describes it. Use
  a mesh fine enough to follow the curved surface (the solver does not correct a coarse
  mesh's flat facets).
* The envelope is the surface of revolution through the load tapes. The lobe bulge
  between tapes is not included when placing the footprint, and marks across a lofted
  gore are placed in proportion to its flat width.
* Seam allowances, stitching and tape widths are not part of the simulation model.
* In the desktop application, shape simulations use the preview solver with assumed
  stiffness values and are not saved with the project; run them again after reopening.
