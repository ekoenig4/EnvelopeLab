# ADR-0063: Scale models carry every document; custom print sizes

- Status: Accepted
- Date: 2026-11-26
- Supersedes: the "no documents" and paper-size parts of ADR-0062

## Context
ADR-0062 wrote a scale model's patterns only, by scaling the finished full-size sheets.
Builders want the model pack to carry the same instructions as the full-size pack: the
build-pack index and build order, spec summary, layout and planning, sewing schedule,
build log, picture assembly instructions, appendage procedures, parachute and scoop
sheets, combined DXFs and 3D views, all at model size. They also print on paper sizes
other than the standard ones, or on a roll or strip limited only in width, and want to
see the model's volume while they choose the scale.

## Decision
* **Scale the inputs, not the sheets.** `envelopelab.export.scale_model.scale_inputs`
  scales the design (`scale_design`: meridian, rows and seam bows, openings, tape widths,
  seam allowances, rigging and parachute lengths, scoop, vent openings), the row
  annotations (`scale_patterns`), the overlays (`scale_overlay`) and the special shapes:
  each shape's primitive is scaled (`scale_primitive`) and designed again on the scaled
  envelope with its design inputs scaled (`scale_primitive_design`). `PrimitiveDesign`
  now records those inputs (`DesignInputs`: seam allowance, feed holes, check tolerance,
  feed-hole clearance). Every sheet and document is then made by the same code as the
  full-size pack, so the pack is consistent with itself.
* Envelope and parachute sheets from the scaled design equal the scaled full-size sheets
  to rounding. A shape's skin is flattened again at model size: each piece agrees with the
  scaled full-size piece within 0.1 % in area and in the length of every sewn edge (a
  test), though it may lie turned slightly differently in the plane.
* **Every document but the lift charts.** Lift does not scale with the patterns; asking
  for the lift charts with a scale model is an error. Values that do not scale
  geometrically (weights, loads, strengths, factors of safety, lift and margin, vent flow
  and thrust, crown pressure) are printed `n/a (scale model)`; the spec summary says why.
  Pattern checks (geometry) keep their results, at model size. The documents' "bolt" and
  "table" are the paper's printable area. The 3D views are drawn from the scaled design
  and shapes with a *Scale model 1:n* banner, never from a full-size solver run.
* **Print size.** `PaperSize.height` may be `None`: a print size limited only in width
  (a roll or strip), each page exactly that wide and as long as its piece (at least
  180 mm, for the calibration line along it). `PaperSize.custom(width, height=None)`
  builds a custom size. `index.json` `scale_model.paper_height_mm` is `null` for such a
  size; the QA then checks only the page width.
* **Dialog.** The *Scale model* group offers the standard papers, *Custom width x
  height* and *Maximum width only*; the seam allowance is set at model size by default
  (5 mm) or the design's, scaled; a *Model* line shows the model's volume
  (\(k^3 V\)), height and widest diameter (`model_summary`).

## Consequences
* Model packs are as complete as full-size ones, minus the lift charts. Small values are
  printed with more precision (lengths under 10 mm to 0.1 mm, under a foot to 0.1 in,
  volumes under 100 m³ to three significant figures); full-size documents change only
  where a value is that small.
* The pack format stays `envelopelab-build-pack/4`; `paper_height_mm` may now be null.
* `scale_pack` and `scale_seam_pair` (ADR-0062) are removed; `scale_sheet` remains for
  fitting the paper.
