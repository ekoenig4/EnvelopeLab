# ADR-0023: Crest-loft taper stations that follow row seams (design schema version 5)

- Status: Accepted
- Date: 2026-10-14

## Context
A crest loft (ADR-0021) is scaled along the tape by taper stations given as fractions of
the tape length. Builders think of a loft by panel row instead, for example "no loft on
the bottom rows, the full loft from row F up". They had to work out each seam's fraction
from the row heights by hand. The fraction then went stale whenever a row was resized,
split or merged, or when the profile changed the tape length: the loft moved off the
seam it was meant to start at.

## Decision
* A taper point may name a row, `TaperPoint.at_row`: its station is that row's bottom
  seam. The anchor is what counts. The stored `station` mirrors it, and every design
  edit sets it again (`sync_taper_anchors`, called by `ProjectSession.edit`), so the
  document is readable without the rows.
* The station of row `k` is \(\sum_{i<k} h_i / \sum_i h_i\), from the rows' finished
  heights.
* Validation names an unknown row, and checks that the stations are strictly increasing
  in their effective positions.
* When a row is renamed its anchors follow. When a row is merged away its bottom seam
  disappears, and the anchors on it become free stations where the seam was.
* Shape files write such a station as `bottom of <row>` in `loft.crest.taper`. The first
  row's bottom is the mouth, given as 0 or a station name.
* The design document becomes schema version 5. Version-4 documents migrate unchanged:
  every station is a free one.

## Consequences
* A loft defined by rows stays on those rows through every edit and every scaled variant.
* A version-5 design cannot be opened by an older EnvelopeLab (the field is unknown
  there); version-4 files open in this one.
* Designs without anchors give the same seams and results. Their content hash changes
  once, when they are migrated, as with every schema version.
