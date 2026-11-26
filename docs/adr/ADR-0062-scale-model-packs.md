# ADR-0062: Scale-model build packs on paper sheets

- Status: Accepted
- Date: 2026-11-26

## Context
Builders make 1:n scale models of an envelope to check the shape and the sewing sequence
before cutting cloth, and want to print the model's patterns at home on standard paper
(US Letter 8.5 x 11 in, A4, …). The full-size build pack prints each piece on a roll
page as long as the piece (ADR-0038, ADR-0042), which a desktop printer cannot take, and
the design schema's `scale_variants` (factor and overrides) was never wired to an output.
A model needs: every pattern length divided by n, a seam allowance that can still be
handled at model size, each piece whole on one sheet of the chosen paper, and a way to
find the largest scale at which every piece fits.

## Decision
* New module `envelopelab.export.scale_model`: `ScaleModel` (denominator n, paper,
  printer margin, seam allowance at model size or None to scale the design's allowance),
  the standard `PAPER_SIZES`, `scale_sheet` / `scale_pack` (every length of every sheet
  and the planned seam ease times k = 1/n), `paper_fit` (turn and portrait/landscape
  orientation that fit a piece in the printable area) and `fit_scale` (largest
  whole-number 1:n at which every piece fits).
* The model is made by **scaling the flat sheets**, after the full-size patterns are
  built, not by scaling the design: the model is geometrically similar to the patterns
  that will be sewn, and no design field (tapes, rigging, shapes, overlays) needs a
  scaling rule.
* `export_build_pack(..., scale_model=…)` writes the scaled sheets: the same DXFs (mm)
  and one template PDF per piece, each page **one sheet of the paper**, portrait or
  landscape, with the piece centred and the header, legend and calibration lines laid out
  in the printable area. Every sheet notes `SCALE MODEL 1:n - not a full-size pattern`
  and the page footer the scale, paper and "print at 100 %". A piece larger than the
  printable area stays whole on a page grown to hold it, and says so in red (never
  hidden, as for the roll).
* A scale-model pack has **no documents**: they describe the full-size envelope (loads,
  rigging, lift). Asking for both is an error.
* `index.json` gains `scale_model` (`null` for a full-size pack): scale, denominator,
  factor, paper name and size, margin and allowance (mm). Template page records of a
  model carry `page_width_mm`, `page_height_mm` and `fits_paper` instead of the roll
  sizes. The pack format stays `envelopelab-build-pack/4`: the key is additive and older
  readers ignore it. The QA checks every model page is one sheet of the paper (either
  way up) or carries the red note, and states the scale.
* GUI: **File ▸ Export build pack…** has a *Scale model* group (scale 1:n, *Fit to
  paper*, paper, margin, fixed or scaled allowance) with a live line saying whether every
  piece fits. The settings are remembered between exports (application settings, not
  the project).

## Consequences
* A model shows the shape of the patterns only. Lift scales with k³ and skin mass with
  k², and stresses do not scale; the dialog, the pages and the theory page say so.
* `scale_variants` in the design schema is still unused; a later change may store a
  model's settings in the project and use its overrides.
* Full-size packs are unchanged except for the `scale_model: null` index key and, on
  pieces under 0.4 m tall or wide, the blue dimension lines' inset (now proportional to
  the piece instead of a fixed 40 / 60 mm, so it stays on small pieces).
