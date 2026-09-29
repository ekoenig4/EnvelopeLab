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

The `features:` section of `build-pack.yaml` describes the two eye pods and the two
antennae for `envelopelab.features` (placement, rim, match points, feed holes, pressure,
construction steps, intended values from the pack's documents); `reference:` names the
reference mesh `reference/alien-reference.obj` and the concept page whose title carries
the volume notation. The mesh is generated from `pack/alien-balloon-3d.html` by
`make_reference_mesh.py` (the page's own lathe profile and eye bulges). They are used by
`tests/regression/test_feature_regressions.py` and `docs/validation/special-shape-fixtures.md`.

Figures measured from the pack's DXF (not the task text): skin offset 224 mm (mean),
rim ease 1.241 m = 5.35 % over 16 match points (77.6 mm per segment). The DXF antenna
cone sector has two equal side seams (2.27 m), so it does not produce the 35 deg lean the
instructions describe; the Reality Check reports this.
