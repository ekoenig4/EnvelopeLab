# ADR-0009: Design schema v2 — parachute, red line, flying wires and turning vents

- Status: Accepted
- Date: 2026-09-30

## Context
Design schema v1 held the rigging as names only (`red_line: str`, `flying_wires: [str]`,
`parachute_confluence_centering: str`); the parachute was only a hole diameter and a seal
overlap, and turning vents could not be placed. Builders need the parachute panels, the
shroud and centralising lines, the red-line route, the flying wires to the basket and
optional turning vents as part of the design, with lengths, loads, factors of safety and
masses, and the build pack must be able to leave a vent's seam open.

## Decision
* `schema_version` 2 adds `parachute: ParachuteSpec | null` and
  `turning_vents: [TurningVentSpec]`, and replaces `rigging` with `RiggingSpec` v2:
  `crown_line`, `load_factor` and `required_safety_factor` (tagged values), and
  `red_line: RedLineSpec | null`, `flying_wires: FlyingWireSpec | null`. Line and cable
  classes (`LineSpec`) carry strength and linear mass as `TaggedValue`s with a
  `datasheet | measured | assumed` source tag.
* Migration v1 → v2 keeps the crown-line name, drops the red-line and flying-wire names and
  the confluence-centering text (they cannot become placements), leaves the parachute, red
  line and flying wires undefined (reported as missing) and sets the documented load-case
  defaults (limit load factor 1.4, 14 CFR 31.23; factor of safety 5, 14 CFR 31.25(b); both
  `assumed`).
* A v1 document's content hash is checked against its content as written, before
  migration; the migrated document gets a new hash. `DesignDocument` validation migrates
  older payloads, so v1 data still validates.
* New designs from the templates get a default parachute, red line and flying wires
  (`envelopelab.rigging.defaults`).
* Two new input groups, `parachute` (read by patterns) and `turning_vents` (read by export),
  and `vent_openings` (vents simulated open; read by assembly) join the dependency graph.

## Consequences
Project files keep format version 1: they hold the design unchanged and migrate it on load.
Opening a v1 design and saving it writes v2; the dropped rigging names are lost (they were
free text). The lift margin of designs with rigging now subtracts the parachute and rigging
mass. The envelope simulation still closes the crown with an unmeshed cap; a meshed
parachute with shroud-line cables would need a further decision.
