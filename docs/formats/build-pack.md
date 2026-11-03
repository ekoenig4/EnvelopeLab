# Build pack

A build pack is a directory written by `envelopelab.export.build_pack.export_build_pack`
(or `write_pack`). It holds everything needed to cut and mark the cloth at 1:1. From
format 3 (`envelopelab-build-pack/3`, ADR-0037) its top level is laid out as a shop
works, with every file named after the design (`<slug>` = the design name in lower
case, words joined by hyphens), and the machine-readable files are in `cad/`.

**1:1 templates** (`envelopelab.export.templates`), at the top level:

| File | Content |
|---|---|
| `<slug>-panels-<R1>-<R2>.pdf` | Envelope rows without shape markings, two to a file (an odd one out joins the file before it: `-panels-O-P-Q.pdf`), one panel per page |
| `<slug>-panel-<R>.pdf` | A row that carries a shape's markings, on its own sheet: the panel with every gore's footprint lines, match marks, side ticks and feed holes drawn over it, each labelled `<shape> - GORE <g>` |
| `<slug>-panels-grouped.pdf` | Every paired file in one |
| `<slug>-parachute-patterns.pdf` | Parachute radial panel and centre panel |
| `<slug>-<shape>-patterns.pdf` | A special shape's skin pieces, one per page |

Every page is one piece at 1:1, as large as the piece plus 20 mm, with **one side no
longer than the roll**: upright when its height fits the roll (the row height across the
bolt, the gore width along the roll), turned a quarter when only its width fits, and
split into numbered bands across the roll when neither does. A page shows the cut line
(solid black), the sewn line (dotted grey), feature marks (red), the finished widths and
height (blue), the panel letter, cut count, fabric and finished size, the warp (UP)
arrow, a legend, the sheet header (as in the DXF) and two calibration lines, across and
along the page, all inside the piece. Each page's stream starts with
`%PAGE <sheet> <band> <bands> <turn> <marking sheets>`; each calibration line is preceded
by `%CAL L T` (across) or `%CALV L T` (along), and its label (`must measure L mm at 1:1,
ticks every T mm`, `along: …`) is generated from the same values.

**`cad/`**:

| File | Content |
|---|---|
| `cad/envelope-row-<R>.dxf` | Envelope row panel `R`, cut once per gore |
| `cad/parachute-panel.dxf` | Parachute radial panel, cut once per radial panel; bottom = the parachute edge |
| `cad/parachute-centre.dxf` | Parachute centre panel (a circle), cut once; only when the parachute has one |
| `cad/<shape>-G<k>.dxf`, `cad/<shape>-P<k>.dxf` | Skin gore or panel `k` of a special shape |
| `cad/<shape>-TIP.dxf` | Flat tip disc of a tube or revolved shape |
| `cad/<shape>-mark-G<g>-<R>.dxf` | Marking sheet: envelope panel (gore `g`, row `R`) with the shape's footprint line, match marks and feed hole |
| `cad/index.json` | The index (below); it lists every other file of the pack |

Formats 1 and 2 had the DXFs and `index.json` at the top and `pattern.pdf` (every sheet
on pages exactly as wide as the roll) instead of the templates; the QA still reads them.

A pack can also hold **documents** (since format 2), chosen when it is exported
(**File ▸ Export build pack…**, or `PackExtras` in
`envelopelab.export.build_pack.export_build_pack`); a pack with none has empty
`documents` and `provenance` keys.

| File | Content |
|---|---|
| `00-cover.pdf` | Cover and index: provenance (app version, git commit, design hash, time), the safety notice, every value tagged `assumed`, the structural result in one line, and every file of the pack with what it is |
| `3d-view.html` | The 3D view (below), one self-contained page |
| `spec-summary.pdf`, `spec-summary.json` | Size and lift (height, diameter, tape length, volume, area, operating conditions, gross lift, payload, lift margin), mass budget, materials per zone with source tags, rigging factors of safety |
| `cut-list.pdf`, `cut-list.csv` | Every sheet (file, piece, kind, cut count, fabric, finished size, finished and cut areas of one piece and of all), fabric totals, tape lengths per class and thread |
| `rigging.pdf`, `rigging.csv` | Every line and ring: element, count, length each (rings: diameter), total, limit load, strength and its source, factor of safety, required, check (`ok`, `FAILS`, `not assessed`), mass; the red-line pull |
| `sewing-schedule.pdf`, `sewing-schedule.csv` | Every seam pair in assembly order (gore seams, row seams, parachute, shape skin seams, shape rims to the envelope), how often it is sewn, both edge lengths, the planned ease, a *Done* box |

CSV files with more than one table separate them by a blank line and a `# title` row.
PDF documents are A4 portrait, Helvetica (Latin-1 text: `>=` for ≥, `!` for ▲).

### 3d-view.html

One HTML page with its own small WebGL renderer: no library, no network, nothing fetched
(the QA checks it). The scene is embedded as JSON in
`<script id="scene" type="application/json">` (format `envelopelab-viewer/1`):

| Key | Content |
|---|---|
| `meshes[]` | `key`, `name`, `group` (Design, Result, Rigging), `role` (`design`, `result`, `other`), `note` (e.g. `preview`, `stale: …`, `NOT CONVERGED: …`), `visible`, `color` (RGB), `triangles` (count), `positions` (base64 little-endian float32, m, 3 vertices per triangle), optional `base` (uint8 RGB per vertex), `colorings` |
| `meshes[].colorings` | Per field key (`fos_warp`, `deviation`, …): `rgb` (uint8 RGB per vertex) and `legend` (`title`, `entries`: colour and label, lowest first) |
| `lines[]` | `key`, `name`, `group`, `role`, `visible`, `color`, `vertices`, `positions` (segment end points, float32, m) |
| `labels[]` | `text` (gore numbers `G1`…) and `at` (m) |
| `colorings` | Field key to its title (the *Colour by* list) |
| `initial` | Colouring shown first ("" for layer colours) |
| `status` | `kind` (`ok`, `info`, `stale`, `fail`, `error`), `symbol`, `title`, `message`: the banner |

Every colour is computed by EnvelopeLab and stored; the page only draws. A stale or
unconverged result has no colourings and its `note` says why.

## DXF sheets

Units are millimetres (`$INSUNITS` = 4, `$MEASUREMENT` = 1). Pattern coordinates: `x`
across the piece, `y` up the piece (up the tape for envelope panels, from the rim
towards the tip for skin pieces).

| Layer | Content |
|---|---|
| `CUT` | Cut outline, with the seam allowance |
| `SEW` | Finished (sewn-line) outline |
| `EDGE_<NAME>` | Each finished edge on its own: `RIM`, `LEFT`, `RIGHT`, `TOP` (skin), `LEFT`, `RIGHT`, `BOTTOM`, `TOP` (envelope and parachute radial panels), `RIM` (parachute centre panel) |
| `MARKS` | Match marks (crosses) and their numbers; on a marking sheet each number names the skin piece that carries it, e.g. `55 (P15)` |
| `ATTACH` | Footprint line of a shape (marking sheets); in seam pairs the k-th line of a sheet is edge `attach<k>` |
| `ATTACH_SIDE` | Short ticks every 150 mm on the side of the footprint line the shape covers |
| `HOLE` | Feed hole, finished size (marking sheets) |
| `HOLE_CUT` | Feed hole as cut: the finished radius less the hem, by default a double fold over the design's hole tape (twice its width) |
| `NOTES` | Sewing directions placed on the piece: the feed-hole sizes and hem; on a skin piece what each edge is sewn to (`RIM: sew to the envelope, marks a-b`, `sew to P4 (its left side)`, `TOP: sew to the tip disc`, `APEX of …`) |
| `GRAIN` | Warp direction arrow |
| `LABEL` | Header: `piece \| kind \| cut N \| fabric F \| finished W x H mm` (the first `LABEL` text, which the QA reads), then notes: on a marking sheet how to sew the shape there, or that the panel lies under it; on a skin piece where its rim marks lie on the envelope; on an envelope row which gores of that row carry a shape's marking sheet or feed hole |
| `CAL` | Calibration line with ticks and its label `must measure L mm at 1:1, ticks every T mm` |

The header and the calibration label are generated from the values that draw the
geometry. The PDF draws the same content and puts a calibration line at the left of
every page, preceded by a `%CAL L T` comment in the page's content stream.

## index.json

```json
{
  "format": "envelopelab-build-pack/3",
  "title": "design name",
  "units": "mm",
  "roll_width_mm": 1524.0,
  "provenance": {"app_version": "0.1.0", "git_commit": "2753321…", "design_hash": "…",
                 "created": "2026-11-03T20:56:43+00:00", "project": "balloon.elproj"},
  "templates": [
    {"file": "sample-panels-A-B.pdf", "description": "panels A, B",
     "pages": [{"sheet": "envelope-row-A", "band": 1, "bands": 1, "turned": false,
                "markings": []}, "…"]}
  ],
  "documents": [
    {"file": "00-cover.pdf", "kind": "cover", "description": "Cover and index: …"},
    {"file": "3d-view.html", "kind": "viewer", "description": "3D view of …"}
  ],
  "sheets": [
    {"file": "cad/ear-G1.dxf", "piece": "ear-G1", "kind": "skin piece", "cut_count": 1,
     "fabric": "ripstop red", "finished_width_mm": 392.1, "finished_height_mm": 1855.0}
  ],
  "seam_pairs": [
    {"a": [{"file": "cad/ear-G1.dxf", "edge": "right"}],
     "b": [{"file": "cad/ear-G2.dxf", "edge": "left"}],
     "tolerance_mm": 3.0, "ease_mm": 0.0},
    {"a": [{"file": "cad/ear-G1.dxf", "edge": "rim"}, "…"],
     "b": [{"file": "cad/ear-mark-G3-D.dxf", "edge": "attach1"}],
     "tolerance_mm": 3.0, "ease_mm": -5.677}
  ]
}
```

`kind` is `envelope panel`, `parachute panel`, `skin piece` or `marking` (cut count 0). A
seam pair lists the finished edges sewn together, with lengths summed on each side (all
of a tube's panel tops against its tip disc, or the `top` of the parachute radial panel
once per radial panel against the centre panel's `rim`, for example). `ease_mm` is the planned length of side `a`
minus side `b`: 0 for edges cut to the same length, and for a shape's rim against the
footprint lines on its marking sheets the attachment ease worked in between match
marks (checked per mark interval when the shape is designed).

## Output QA

`envelopelab.export.qa.check_pack` checks a pack from its files alone (AGENTS.md §6.6):
the index and the directory list the same files; every DXF is in mm; every calibration
line, in every DXF and on every template page (across and along), measures what its
label says; every template page is listed with its sheet and has one side no longer than
the roll (formats 1 and 2: every `pattern.pdf` page is as wide as the roll); every sheet
is drawn on a template page (a marking sheet over its row's panel); every header matches the index and the drawn `SEW` outline; every
document opens (PDFs have pages), the cut list lists every sheet with the index's cut
count and fabric, and the 3D view loads nothing from outside the page and holds a scene
with a surface and a status banner; and
every sewn edge pair differs by its planned ease within its tolerance.
`scripts/check_build_pack.py` exports a generic sample pack and checks it;
`scripts/verify.py` runs it.
