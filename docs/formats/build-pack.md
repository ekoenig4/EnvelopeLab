# Build pack

A build pack is a directory written by `envelopelab.export.build_pack.export_build_pack`
(or `write_pack`). It holds everything needed to cut and mark the cloth at 1:1. From
format 3 (`envelopelab-build-pack/3`, ADR-0037) its top level is laid out as a shop
works, with every file named after the design (`<slug>` = the design name in lower
case, words joined by hyphens), and the machine-readable files are in `cad/`.

**1:1 templates** (`envelopelab.export.templates`), at the top level: **one PDF per piece,
one page each** (ADR-0038):

| File | Content |
|---|---|
| `<slug>-panel-<R>.pdf` | Envelope row `R`, clean, cut once per gore |
| `<slug>-panel-<R>-gore-<g>.pdf` | The panel `R` of gore `g` when a shape is sewn on it or a feed hole is cut in it: the same panel with that panel's footprint lines, side ticks, numbered match marks and feed holes (every shape's marks on that panel), *mark only* (ADR-0039) |
| `<slug>-parachute-panel.pdf`, `<slug>-parachute-centre.pdf` | The parachute radial panel and centre panel |
| `<slug>-<shape>-<piece>.pdf` | Every skin piece of every special shape (e.g. `<slug>-eye-G1.pdf`, `<slug>-horn-TIP.pdf`) |

The page is the piece's cut outline plus 20 mm, so the **whole piece is on one page,
never split**: upright when its height fits the roll (the row height across the bolt, the
gore width along the roll), turned a quarter when only its width fits; a piece larger
than the roll both ways stays whole and the page says `LARGER THAN THE … MM ROLL BOTH
WAYS` in red. A page shows the cut line (solid black), the sewn line (dotted grey),
feature marks (red), the finished widths and height (blue), the panel letter, cut count,
fabric and finished size, the warp (UP) arrow, a legend, the sheet header (as in the DXF)
and two calibration lines, across and along the page, inside the piece. Each page's
stream starts with `%PAGE <sheet> 1 1 <turn> <marking sheets>`; each calibration line is
preceded by `%CAL L T` (across) or `%CALV L T` (along), and its label (`must measure L mm
at 1:1, ticks every T mm`, `along: …`) is generated from the same values.

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
| `<slug>-00-BUILD-PACK-INDEX.pdf` | A3 landscape, three sheets (`envelopelab.export.shop`): the key dimensions in metric and English, the features (special shapes with their gores, rows, pieces and feed holes; turning vents; scoop; parachute; red line; flying wires), the shop limits (bolt width, cutting table, largest cut piece, with a warning when a piece exceeds them), the printing rules; the index of every file, grouped (START HERE, LAYOUT & PLANNING, PANEL TEMPLATES, APPENDAGES, TOP & BOTTOM / CAD) and tagged `REF`, `1:1` or `CAD`; the build order, each step naming its sheet; the airworthiness note and the provenance |
| `<slug>-3d.html` | The 3D view (below), one self-contained page |
| `<slug>-<shape>-3d.html` | Per special shape: the shape as designed and, when simulated, as inflated with every metric (factor of safety, deviation, resultants, wrinkling, displacement) and that simulation's banner; "Not simulated" otherwise |
| `<slug>-assembly-envelope.pdf`, `<slug>-assembly-<shape>.pdf` | Picture assembly instructions (`envelopelab.export.assembly`), A3, numbered frames drawn from the pieces: parts and counts, marking, one gore bottom-up, joining gores, mouth and crown, parachute, where each shape goes, rigging, inspection; per shape: parts, marking, side seams, tip, feed holes, rim to the marked line with the numbered marks, finished |
| `<slug>-spec-summary.pdf` | A4 landscape: key measurements in metric and English (volume, height, width, gore length, mouth, parachute hole and overlap, parachute, lines, red line, gross lift, lift margin), the configuration, the rigging factors of safety, the safety notice and every value tagged `assumed` |
| `<slug>-build-log.pdf` | A3 landscape sign-off sheets (item, spec, done by, date, checked): panel cutting, one per special shape, the turning vents, parachute / rigging / final |
| `<slug>-layout-diagram.html` | The gore x row grid (face = gore 1), every cell in its fabric zone's colour, every feature located (special shapes, feed holes, turning vents, scoop), with a key (`envelopelab.export.planning`) |
| `<slug>-panel-map.html`, `.csv` | The same grid as a table: what each panel of each gore carries (`EYE`, `EYE HOLE`, `VENT`, `SCOOP`, …), else its zone in capitals; CSV header `row\gore,1,2,…`, top row first |
| `<slug>-gore-layout.pdf` | A3: every gore developed (rows stacked, finished outlines) side by side with the footprint lines and feed holes in red and the vents in orange, then one page per gore with each row's bottom width; scale drawings only |
| `<slug>-panel-dimensions.html`, `.csv` | Every panel, top row first: `panel, width_bottom_mm, width_top_mm, height_mm, cut_width_bottom_mm, cut_width_top_mm, cut_height_mm, across_bolt_mm, along_table_mm, bolt_spare_mm, table_spare_mm, cut, fabric` (the shorter cut side lies across the bolt; a negative spare means the piece does not fit); the HTML adds the fabric totals |
| `<slug>-panel-loft.html`, `.csv` | `panel, width@0%_mm … width@100%_mm`: finished width at 0, 25, 50, 75 and 100 % of the height |
| `<slug>-sewing-schedule.html` | Seam specifications (seam, type, allowance, stitch), the webbing / tape schedule (length with 10 % waste, per gore, shape rims and feed holes), the assembly sequence (the build order) and every sewn seam pair in order with both edge lengths, ease and a check box |
| `<slug>-<shape>.pdf` | Per special shape (`envelopelab.export.appendages`): kind, placement, envelope panels, rim length, the skin cut list (piece, cut, finished size, surface area, sheet), every match mark (number, skin piece, envelope gore and row, position on the panel), the feed holes and the shape's design checks (`FAILS` / `WARNING`) |
| `<slug>-<shape>-build.pdf` | Per special shape: the build procedure generated from its data (print and check, cut the skin, mark the envelope, feed holes, sew the skin, tape the footprint, sew the rim with its ease, inspect), each step naming its sheet, with blank notes lines |
| `<slug>-turning-vents.pdf`, `<slug>-vent-panels.pdf` | When the design has turning vents: each vent's seam, gores, rows, direction, opening, slot, open area, thrust and torque, air and heat loss, control line, the net torque and side force; and every panel that carries a vent |
| `<slug>-parachute.pdf` | Parachute hole, seal overlap, diameter, panels, fabric, crown pressure, line lengths (metric and English), red-line pull, red line, and the lines-and-rings table with factors of safety |
| `<slug>-scoop.pdf` | The scoop, the flying wires (each wire's length and limit tension), the wires and crow's-foot legs with factors of safety |
| `<slug>-panels.dxf` (+ `<slug>-panels-dxf-preview.png`) | The full 2D development in mm (`envelopelab.export.cad`): every gore with its rows stacked as sewn (`CUT`, `SEW`), the special shapes' footprint lines and feed holes on the gores that carry them (`FEATURE`), gore numbers and row letters (`LABEL`) |
| `<slug>-panel-templates.dxf` (+ `-preview.png`) | One of each envelope panel on a grid, `CUT` and `SEW`, labelled with its letter and cut count |
| `<slug>-appendage-patterns.dxf` (+ `-preview.png`) | Every special-shape skin piece and the parachute panels on a grid, with their match marks (`MARKS`) |

CSV files with more than one table separate them by a blank line and a `# title` row.
PDF documents are A4 portrait, Helvetica (Latin-1 text: `>=` for ≥, `!` for ▲).

### <slug>-3d.html

One HTML page with its own small WebGL renderer: no library, no network, nothing fetched
(the QA checks it). The scene is embedded as JSON in
`<script id="scene" type="application/json">` (format `envelopelab-viewer/1`):

| Key | Content |
|---|---|
| `meshes[]` | `key`, `name`, `group` (Design, Result, Rigging), `role` (`design`, `result`, `other`), `smooth` (smooth shading; false for the basket), `note` (e.g. `preview`, `stale: …`, `NOT CONVERGED: …`), `visible`, `color` (RGB), `triangles` (count), `positions` (base64 little-endian float32, m, 3 vertices per triangle), optional `base` (uint8 RGB per vertex: the fabric colours), `colorings` |
| `meshes[].colorings` | Per field key (`fos_warp`, `deviation`, …): `rgb` (uint8 RGB per vertex) and `legend` (`title`, `entries`: colour and label, lowest first) |
| `lines[]` | `key`, `name`, `group`, `role`, `visible`, `color`, `vertices`, `positions` (segment end points, float32, m) |
| `labels[]` | `text` (gore numbers `G1`…) and `at` (m) |
| `colorings` | Field key to its title (the *Colour by* list) |
| `initial` | Colouring shown first ("" for layer colours) |
| `status` | `kind` (`ok`, `info`, `stale`, `fail`, `error`), `symbol`, `title`, `message`: the banner |

The page opens in the **realistic look**: every part in its fabric colours (the
inflated envelope coloured by its zones' fabrics), smooth shading under a sun, sky and
ground light with a soft highlight, a sky-and-ground background, and a basket box under
the burner frame when the design has flying wires (display only, 1.3 x 1.3 x 1.1 m,
assumed). The analysis colourings (factor of safety, deviation, resultants, …) are in the
*Colour by* list. Every colour is computed by EnvelopeLab and stored; the page only draws. A stale or
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
    {"file": "sample-panel-A.pdf", "description": "panel A, cut 20",
     "pages": [{"sheet": "envelope-row-A", "band": 1, "bands": 1, "turned": false,
                "markings": []}, "…"]}
  ],
  "documents": [
    {"file": "sample-00-BUILD-PACK-INDEX.pdf", "kind": "index", "description": "…"},
    {"file": "sample-3d.html", "kind": "viewer", "description": "interactive 3D model …"}
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
label says; every piece is on one page of its own file, never split, listed with its
sheet, with one side no longer than the roll or the red larger-than-the-roll note
(formats 1 and 2: every `pattern.pdf` page is as wide as the roll); every sheet is drawn
exactly once (a marking sheet over its row's panel); every header matches the index and the drawn `SEW` outline; every
document opens (PDFs have pages, HTML pages load nothing from outside themselves, combined
DXFs are in mm, previews are PNG images), the
panel dimensions list every envelope panel with the index's cut count and fabric, and the
3D view loads nothing from outside the page and holds a scene
with a surface and a status banner; and
every sewn edge pair differs by its planned ease within its tolerance.
`scripts/check_build_pack.py` exports a generic sample pack and checks it;
`scripts/verify.py` runs it.
