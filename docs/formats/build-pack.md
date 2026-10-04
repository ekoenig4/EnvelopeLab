# Build pack

A build pack is a directory written by `envelopelab.export.build_pack.export_build_pack`
(or `write_pack`). It holds everything needed to cut and mark the cloth at 1:1.

| File | Content |
|---|---|
| `envelope-row-<R>.dxf` | Envelope row panel `R`, cut once per gore |
| `<shape>-G<k>.dxf`, `<shape>-P<k>.dxf` | Skin gore or panel `k` of a special shape |
| `<shape>-TIP.dxf` | Flat tip disc of a tube or revolved shape |
| `<shape>-mark-G<g>-<R>.dxf` | Marking sheet: envelope panel (gore `g`, row `R`) with the shape's footprint line, match marks and feed hole |
| `pattern.pdf` | Every sheet at 1:1 on pages as wide as the fabric roll; a sheet wider than the roll is split into numbered strips |
| `index.json` | The index (below); it lists every other file |

## DXF sheets

Units are millimetres (`$INSUNITS` = 4, `$MEASUREMENT` = 1). Pattern coordinates: `x`
across the piece, `y` up the piece (up the tape for envelope panels, from the rim
towards the tip for skin pieces).

| Layer | Content |
|---|---|
| `CUT` | Cut outline, with the seam allowance |
| `SEW` | Finished (sewn-line) outline |
| `EDGE_<NAME>` | Each finished edge on its own: `RIM`, `LEFT`, `RIGHT`, `TOP` (skin), `LEFT`, `RIGHT`, `BOTTOM`, `TOP` (envelope panels) |
| `MARKS` | Match marks (crosses) and their numbers |
| `ATTACH` | Footprint line of a shape (marking sheets) |
| `HOLE` | Feed hole (marking sheets) |
| `GRAIN` | Warp direction arrow |
| `LABEL` | Header: `piece \| kind \| cut N \| fabric F \| finished W x H mm`, and a note |
| `CAL` | Calibration line with ticks and its label `must measure L mm at 1:1, ticks every T mm` |

The header and the calibration label are generated from the values that draw the
geometry. The PDF draws the same content and puts a calibration line at the left of
every page, preceded by a `%CAL L T` comment in the page's content stream.

## index.json

```json
{
  "format": "envelopelab-build-pack/1",
  "title": "design name",
  "units": "mm",
  "roll_width_mm": 1524.0,
  "pdf": "pattern.pdf",
  "sheets": [
    {"file": "ear-G1.dxf", "piece": "ear-G1", "kind": "skin piece", "cut_count": 1,
     "fabric": "ripstop red", "finished_width_mm": 392.1, "finished_height_mm": 1855.0,
     "pdf_pages": 1}
  ],
  "seam_pairs": [
    {"a": [{"file": "ear-G1.dxf", "edge": "right"}],
     "b": [{"file": "ear-G2.dxf", "edge": "left"}],
     "tolerance_mm": 3.0}
  ]
}
```

`kind` is `envelope panel`, `skin piece` or `marking` (cut count 0). A seam pair lists the
finished edges sewn together, with lengths summed on each side (all of a tube's panel
tops against its tip disc, for example).

## Output QA

`envelopelab.export.qa.check_pack` checks a pack from its files alone (AGENTS.md §6.6):
the index and the directory list the same files; every DXF is in mm; every calibration
line, in every DXF and on every PDF page, measures what its label says; every PDF page is
as wide as the roll; every header matches the index and the drawn `SEW` outline; and
every sewn edge pair matches within its tolerance. `scripts/check_build_pack.py` exports
a generic sample pack and checks it; `scripts/verify.py` runs it.
