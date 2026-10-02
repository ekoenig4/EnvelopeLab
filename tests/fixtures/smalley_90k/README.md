# Smalley 90K shape file (regression fixture)

`source/Smalley_90K.xlsx` is the builder's gore-layout spreadsheet, stored unmodified. It is
the Balloon Builders Journal method (Issues 1 and 22): a 51-station normalized
natural-shape table scaled by the gore length \( L = (V/0.12586)^{1/3} \), with 20 gores and
a 1 in seam allowance. `shape.yaml` is the same design as an `envelopelab.shape` file
(`docs/formats/shape-file.md`). It holds the nominal volume (92,000 ft³) and the mouth and
vent stations, and lets the program solve the rest.

`tests/regression/test_shape_fixtures.py` reads the spreadsheet with the standard library.
It checks that every table value, label and input in `shape.yaml` matches it, and that the
solved design reproduces all 51 sewn and cut half-gore widths within 0.1 %.
`docs/validation/shape-families.md` lists the comparisons.

Two interpretations to note:

* **Seam allowance.** The spreadsheet's cut half gore is the sewn half gore + 2 × 1 in, so
  the file stores `seam_allowance: 2 in`, the cut allowance per gore edge.
* **Volume.** The integrated volume coefficient of the table is 0.12605, against the
  published 0.12586 (0.15 %), so holding 92,000 ft³ gives L = 90.04 ft instead of
  90.08 ft. Hold `gore_length: 90.081 ft` to cut exactly the spreadsheet's gores.

This is test data, not a reference design, and passing these tests says nothing about its
airworthiness.
