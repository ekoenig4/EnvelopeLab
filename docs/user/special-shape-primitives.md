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

!!! note "Python API for now"
    Primitives are available from Python (`envelopelab.features.primitives`). They are
    not yet in the desktop application or in the design file.

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

## Limitations

* Revolved shapes are symmetric about their axis. Shapes that are not (ears, curved
  horns, faces) need the mesh import, which is planned next.
* The envelope is the surface of revolution through the load tapes. The lobe bulge
  between tapes is not included when placing the footprint, and marks across a lofted
  gore are placed in proportion to its flat width.
* Seam allowances, stitching and tape widths are not part of the simulation model.
