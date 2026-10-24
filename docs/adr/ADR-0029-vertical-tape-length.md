# ADR-0029: Vertical load tapes can be cut to the tape line

- Status: Accepted
- Date: 2026-10-23

## Context
A flat gore is drawn with the tape arc length on its axis, so its side edge is longer than
the design's tape line wherever the gore width changes (`docs/theory/gore-geometry.md`).
The solvers gave every tape the length of the fabric edge it is sewn to. On the generic
8-gore fixture that tape is 189 mm (2 %) longer than the meridian, and 4–5 % longer near
the mouth and the top opening. The tapes hung slack: in a converged preview, 76 % of the
vertical tape elements carried no tension, and the fabric carried the vertical load.
The inflated envelope grew 101 mm taller than drawn. Builders who want the load tapes to
carry the load cut them to the tape length and ease the fabric onto them.

## Decision
* `TapeSet.vertical_length` (design schema version 8) is `"fabric_edge"` (default, the
  former model) or `"tape_line"`. Version-7 documents migrate as `"fabric_edge"`, and the
  default does not enter the simulation fingerprint, so existing designs keep their
  results and their runs stay current.
* With `"tape_line"`, `project.simulation.build_solver_model` gives each vertical-gore
  tape edge its length along the gore axis of the flat pattern
  (`solvers.model.tape_line_rest_lengths`). Both solvers use these rest lengths. Each
  row's tape must total the row's finished height within 1 mm. A pattern that is not
  drawn with the tape length along its axis is refused with a build error, never
  modelled with a wrong tape.
* Horizontal tapes, rims and hems are cut as before.

## Consequences
* On the full-size fixture (2600 m³, 20 gores) the bottom and top tapes carry 327 and
  321 N instead of 205 and 76 N at 800 mm, and the preview converges in 29.6k iterations
  instead of 17.0k.
* The middle rows' tapes still carry about a tenth of the load. The fabric there is cut no
  longer than the tape, so it shares the load by stiffness. Lengthwise ease of the cut
  panels is the follow-up.
* Eased fabric is slack along the tape. Just above the mouth it has hardly any pressure
  and, where the profile needs hoop compression, no hoop tension, so it is only weakly
  held. The 8-gore generic fixture, with up to 4.5 % ease there, does not converge at
  800 mm (it does at 1600 mm). Such runs are reported NOT CONVERGED, as every
  unconverged run is.
