# Alien build pack (regression fixture only)

`pack/` is a complete special-shape build pack (20 gores x 17 rows, 25 mm seam allowance,
3,988 mm mouth, 5,000 mm parachute opening with 360 mm seal overlap), stored unmodified as
**test data**. `build-pack.yaml` maps its DXF layers and labels and describes how its
pieces are sewn; every design-specific value lives there, never in `src/`.

It is used only to check that a real pack imports, audits and assembles without
source-code special cases (`tests/regression/test_pattern_import_fixtures.py`,
`docs/validation/pattern-import-fixtures.md`). It is not a reference design, and passing
these tests says nothing about its airworthiness. Its eye-pod layout (a separate skin sewn
onto envelope panels over feed holes) is one example of an appendage, not a general
assumption.
