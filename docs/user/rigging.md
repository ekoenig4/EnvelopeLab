# Parachute, rings, red line, flying wires, turning vents and scoop

Besides its gores, every standard-gore design has a parachute (the top panel, with a
crown ring at the rim of the opening and a centre ring at its apex), a red line and flying
wires. New designs get defaults for all of them; turning vents and a scoop are optional. All defaults
are generic starting values — review every one, and replace the `assumed` line and cable
strengths with datasheet or measured values before building.

The models behind the numbers are described in [theory](../theory/rigging.md).

## The Rigging panel

The **Rigging** mode (**View ▸ Rigging**, Ctrl+3) shows one card per element, in the same
look as the other windows:

* The **toolbar** keeps the key figures in view: the rigging mass, the **lowest factor of
  safety** of the assessed lines against the requirement, and the limit load factor (with
  its source tag), plus a chip saying whether the requirement is met.
* The **banner** states the worst problem first:

  | Banner | When |
  |---|---|
  | ▲ **Rigging fails a check.** | a factor of safety below the requirement, or another error; the first two are named with their values |
  | i **Rigging not complete.** | the parachute, flying wires or red line is not yet added |
  | ✓ **Rigging checked.** | every assessed line meets the requirement; what is *not* assessed is listed |
  | ✕ **Rigging not evaluated.** | the outputs could not be computed (the reason is given) |

* Each **card** has its own status chip (▲ *Fails*, ✓ *Meets FoS*, i *Not assessed*), an
  **Add** button while the element is missing (with what is missing without it) and a
  **Remove** button once it is there. Turning vents keep **Add turning-vent pair** to add
  more, and **Remove all**. Every change is one undo step.
* A card lists its values and a **lines table**: count, length (Ø for a ring's diameter),
  limit load (hoop force for a ring), strength with its source tag, factor of safety and
  mass.

What each card shows:

* **Parachute**: diameter and panel count, hole diameter, seal overlap, fabric length and
  area, the finished radial and centre panels, crown pressure, the static load on the
  shroud lines, the red-line pull for a *seal open* and a *fully open* parachute (▲ *NOT
  REACHABLE* when it cannot open), and the shroud and centralising lines, **crown ring**
  and **centre ring** in its table.
* **Flying wires**: wires and tapes per wire, suspended and limit weight, each wire's
  length, and the wires and the load-tape legs of the crow's feet in its table.
* **Red line**: total length (route plus spare), the confluence height and where it ends.
* **Turning vents**: per vent its seam and direction, slot length and open area, thrust,
  torque, air and heat loss fully open; the net torque and side force; the control lines in
  its table.
* **Scoop**: gores covered, fabric zone, slant length, bottom radius, panel widths and
  mass (wind load not assessed).

A factor of safety below the requirement says **▲ … FAILS (required …)** in its row, in
the fail colour, turns its card's chip and the toolbar chip to ▲, is named in the banner
and is listed as an error in **Validation / Warnings**. Values that are not assessed (the
red line's pull force, the centralising lines' load, the scoop's wind load) say so. The
parachute and rigging mass appears in the editor's live outputs and is subtracted from the
lift margin.

## Parachute overlap and centre panel

The **Parachute** card at the top of the Rigging panel sets two things directly:

* **Overlap with the envelope (m)**: how far the parachute reaches past the top hole onto
  the envelope, measured along the fabric (`gores.seal_overlap`). Internal pressure presses
  this band against the envelope to seal it. A wider overlap makes the parachute and its
  radial panels larger and moves the shroud-line attachment down with the edge. The overlap
  must be less than the hole radius.
* **Centre panel diameter (m)**: the parachute is cut as one radial panel per shroud line,
  each a trapezoid from the edge to this circle, plus one circular centre panel that joins
  them. New parachutes get a quarter of the hole diameter. Leave it empty for radial panels
  that run to the centre ring (narrow wedges). It must be larger than the centre ring and
  smaller than the hole.

The pattern view shows the radial panel (`PARACHUTE xN`) on top of the gore rows and the
centre panel (`PARACHUTE CENTRE x1`) above it. The tree lists both finished sizes; the
radial panels' top edges and the centre panel's edge are checked to be the same length.

Parachutes from designs saved before the centre panel existed have none; type a diameter
to add one.

**Export build pack…** (Shapes panel) writes the parachute with the envelope rows:
`parachute-panel.dxf`, cut once per radial panel, and `parachute-centre.dxf`, cut once.
The pack's output QA checks that the radial panels' tops match the centre panel's edge
([build pack format](../formats/build-pack.md)). A parachute whose pattern cannot be made
(see Validation) stops the export.

## Placing the elements

Select **Parachute**, **Rigging (red line, flying wires)** or **Turning vents** in the
Design Tree and edit the fields in **Properties** (SI values):

| Element | Field | Meaning |
|---|---|---|
| Parachute | `panel_count` | radial panels, one shroud and one centralising line each; should divide the gore count |
| | `billow` | cap rise over the hole, as a fraction of the hole diameter |
| | `shroud_attachment` | m along the load tape below the parachute edge |
| | `centralizing_depth` | m below the crown opening where the centralising lines meet |
| | `crown_ring`, `centre_ring` | ring class, linear mass (kg/m), strength (N) and required factor of safety; remove to model none |
| | `centre_ring_diameter` | m; without a centre panel the parachute panels end at the centre ring |
| | `centre_panel_diameter` | m; a flat circular centre panel that the radial panels (then trapezoids) are sewn to; empty: none (wedges) |
| Red line | `guide_seam` | load tape (1..N) the line is led down |
| | `spare_length` | m of extra line below the basket attachment |
| Flying wires | `count` | wires; the gore count must be a multiple |
| | `frame_points`, `frame_radius`, `frame_drop`, `frame_azimuth_deg` | burner-frame attachment points |
| | `crows_foot_drop` | m below the mouth where each wire's load tapes meet |
| Turning vent | `seam`, `rows` | the seam left open and the consecutive rows it spans |
| | `direction` | rotation it gives, seen from above |
| | `opening_width` | gap width when pulled fully open, m |
| | `simulate_open` | leave the seam open in the preview / CalculiX model |
| Scoop | `first_gore`, `gore_count` | the consecutive gores it hangs from (all gores: a skirt) |
| | `height`, `flare_deg` | depth below the mouth (m) and outward angle from the vertical |
| | `zone` | fabric zone; default the mouth row's (Nomex) |

The parachute is sized by the gores' crown opening (`gores.parachute_hole_diameter` and
`gores.seal_overlap`). The rigging load case (`rigging.load_factor`,
`rigging.required_safety_factor`) applies to every line, wire and load tape; the flying
wires carry `operating.payload_mass` (basket, burner, fuel and occupants), so set it — with
a payload of 0 the wires are not load-checked and a warning says so.

Use **Add turning-vent pair** for two opposite vents that turn the balloon the same way;
one vent alone, or two turning opposite ways, give a warning.

## Panel rows and fabrics

Each panel row can name its material zone (`gores.panel_rows[].zone`, e.g. `mouth` for
the Nomex row next to the burner); a zone set on the row in the 2D pattern view overrides
it, and rows without one use the first zone (`body`). The Design Tree lists every row
with its zone and fabric, and the parachute as the top panel.

## Designs from earlier versions

Designs saved before schema version 2 open with their crown-line name kept and the
parachute, red line and flying wires undefined; the Validation panel lists each one as
missing until you add it.
