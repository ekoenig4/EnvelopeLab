# ADR-0059: Lift-chart settings saved with each project (project format 9)

- Status: Accepted
- Date: 2026-11-24

## Context
The build pack's lift charts (`envelopelab.export.lift_chart`) drew fixed curves: four
pressure altitudes, five ambient temperatures and four ISA deviations, with the load
axis sized automatically and a generic, *assumed* 20 K offset between the crown (top)
temperature and the mean gas temperature. Builders fly from different field elevations
and climates. Once an envelope has been flown, they also have a measured top-to-mean
offset. They need to choose the curves and enter the offset, in metric or English units,
and the choice belongs to that envelope.

## Decision
* `DesignState.lift_chart` (`envelopelab.project.lift_chart_settings.LiftChartSettings`)
  holds, in SI: `altitudes` (m, 1 to 4), `ambient_temperatures` (K, 1 to 6),
  `isa_offsets` (K, 1 to 6), `max_load` (kg, or null for automatic),
  `lowest_top_temperature` (K) and `top_to_mean` (a `TaggedValue` in K with its source
  tag). Values are validated with a reason for each refusal and stored sorted.
* The defaults are the curves drawn before this ADR. They are not written to the file
  (`state.lift_chart` appears only when the settings differ), so existing projects keep
  their content and fingerprints.
* Project format **9**. Versions 1 to 8 read with the default settings.
* A new optional input group `lift_chart` feeds only the `export` artifact. Changing the
  settings makes the build pack stale, never the patterns or simulations.
* Editing is one undoable step (`edits.set_lift_chart`, `ProjectSession.edit_lift_chart`).
  Every other state edit keeps the settings.
* The application's *Design ▸ Lift charts…* dialog (also reachable from the export
  dialog) converts between the builder's units and SI at the boundary. It offers metric
  (m, °C, kg) and English (ft, °F, lb) entry and can preview the charts before export.

## Consequences
* Projects written by this release cannot be opened by older releases (format 9).
* The top-to-mean offset keeps its source tag through the file, the dialog and the
  charts, so a measured value is shown as *measured*, and the default as *assumed*.
* Curve counts are capped (4 altitudes for the 2 x 2 temperature page, 6 curves for six
  distinguishable colours). A builder who needs more makes a second pack with other
  settings.
