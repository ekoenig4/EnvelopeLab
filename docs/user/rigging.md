# Parachute, rings, red line, flying wires, turning vents and scoop

Besides its gores, every standard-gore design has a parachute (the top panel, with a
crown ring at the rim of the opening and a centre ring at its apex), a red line and flying
wires. New designs get defaults for all of them; turning vents and a scoop are optional. All defaults
are generic starting values — review every one, and replace the `assumed` line and cable
strengths with datasheet or measured values before building.

The models behind the numbers are described in [theory](../theory/rigging.md).

## The Rigging panel

The **Rigging** mode (**View ▸ Rigging**, Ctrl+3) has buttons to add or remove each element and
shows what the design gives:

* **Parachute**: diameter, panel count, fabric length and area, the size of one panel,
  crown pressure, the static load on the shroud lines, shroud and centralising line
  lengths, the shroud lines' limit tension and factor of safety, the **crown ring** and
  **centre ring** (diameter, limit hoop force, factor of safety, mass), and the red-line
  pull for a *seal open* and a *fully open* parachute.
* **Red line**: total length (route plus spare), the confluence height and where it ends.
* **Flying wires**: suspended and limit weight, each wire's length, the most loaded wire's
  limit tension and factor of safety, and the same for the load-tape legs of the crow's
  feet.
* **Scoop**: gores covered, fabric zone, slant length, bottom radius, panel widths and
  mass (wind load not assessed).
* **Turning vents**: slot length and open area, thrust, torque, air and heat loss with the
  vent fully open, the control-line length, and the net torque and side force.

A factor of safety below the requirement is red, says **FAILS**, and is listed as an
error in **Validation / Warnings**. Values that are not assessed (the red line's pull force,
the centralising lines' load) say so. The parachute and rigging mass appears in the
editor's live outputs and is subtracted from the lift margin.

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
| | `centre_ring_diameter` | m; the parachute panels end at the centre ring |
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
