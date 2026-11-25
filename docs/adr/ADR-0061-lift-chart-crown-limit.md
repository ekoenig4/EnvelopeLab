# ADR-0061: Crown temperature limit set per project (project format 11)

- Status: Accepted
- Date: 2026-11-25

## Context
The lift charts take their crown (top) temperature limit from the lowest maximum service
temperature of the design's fabrics in the fabric library, or a generic 120 °C tagged
*assumed* when a fabric is not in it. Builders need to set the limit for a project without
editing the shared fabric library: a manufacturer's operating limit below the fabric
rating, or a datasheet value for a fabric not yet in the library.

## Decision
* `LiftChartSettings.top_limit` (a `TaggedValue` in K, 0 to 300 °C, or null): null
  (default) keeps the limit from the fabrics; a value replaces it for the lift charts only.
  The fabric limit is still computed and kept (`LiftChartInputs.fabric_limit`).
* A limit above the fabrics' service temperature is allowed but flagged as not
  conservative on the form, the charts' status line, the inputs list and the PDF
  (`LiftChartInputs.limit_above_fabric`, `limit_warning`).
* The structural solver's temperature-exceedance check keeps using the fabrics' service
  temperature.
* Project format **11**. Versions 1 to 10 read with the limit from the fabrics; the
  setting is written only when it differs from the default.

## Consequences
* No result changes for projects that do not set a limit.
* Projects written by this release cannot be opened by older releases (format 11).
