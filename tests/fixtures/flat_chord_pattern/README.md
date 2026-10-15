# Synthetic flat-chord pattern set (regression fixture)

**Synthetic test data.** `make_fixture.py` makes everything here from an analytic shape.
It is not a real or licensed design, and passing these tests says nothing about
airworthiness.

* `shape.yaml` is a version-2 shape file (`docs/formats/shape-file.md`):
  * a 16-gore, 10-row horizontal-cut envelope with flat-chord gores;
  * a Nomex skirt;
  * measured seam bows, and a 2 % crest loft for variants;
  * a 300 mm seal overlap, 16 parachute gores and two turning vents.

  The generated block is the tape profile through 11 row corners on
  \(r = R\cos\theta(1 + 0.08\sin\theta)\), \(z = 1.05R\sin\theta\) (\(R\) = 8.5 m),
  straight between corners. Its "measured" bows come from a 2.5 % crest loft, so they are
  not the file's own 2 % `loft.crest`. The two sides of every seam differ by 0.8 mm, as in
  hand-drawn patterns.
* `special.yaml` `extends` it with zones, two panel zones (`badge` on row C of gores 16
  and 1, `doubler` on row G of gore 5) and one shape of each kind:
  * a dome with a centred feed hole;
  * a tube leaning 30°;
  * a mesh blister (`shapes/blister.obj`, made by `make_fixture.py`) with two extra
    feed holes.

`tests/regression/test_flat_chord_pattern.py` checks that the generated files are current
and that the designs are complete and consistent.

The shapes' design checks report the flat-panel attachment ease: 3–6 mm per match-mark
interval, above the 3 mm sewn-edge default, so they are **errors**. The blister and the
dome also flatten with warnings. These findings come from the shapes as drawn and are
asserted as they are.
