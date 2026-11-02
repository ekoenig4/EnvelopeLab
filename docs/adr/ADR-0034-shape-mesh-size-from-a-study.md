# ADR-0034: Automatic shape element size: footprint length / 40, 100 to 300 mm

- Status: Accepted
- Date: 2026-11-02
- Supersedes: the automatic element size of ADR-0030 and ADR-0031 (footprint length / 100,
  60 to 300 mm, assumed with no study)

## Context
ADR-0030 chose the element size of a shape solved with the envelope as footprint length
/ 100, between 60 and 300 mm, and noted that no study had fixed it. Once the shapes of the
Smalley 90K alien design converge (ADR-0033), a study is possible. Solved as the
application does (preview solver, the design's own mesh shapes):

| shape | element size | nodes | solve | height | largest rim-tape tension |
|---|---|---|---|---|---|
| antenna | 150 mm | 900 | 24 s | 3.263 m | 53.8 N |
| antenna | 120 mm | 1,392 | 51 s | 3.260 m | 53.1 N |
| antenna | 90 mm | 2,319 | 96 s | 3.258 m | 51.6 N |
| antenna | 60 mm (old rule) | 5,073 | 333 s | 3.254 m | 47.7 N |
| eye pod | 400 mm | 2,684 | 9 s | 1.180 m | 162.9 N |
| eye pod | 300 mm | 4,377 | 23 s | 1.178 m | 177.2 N |
| eye pod | 229 mm (old rule) | 7,126 | 70 s | 1.176 m | 180.2 N |
| eye pod | 160 mm | 13,871 | 139 s | 1.178 m | 189.1 N |

(4-core Linux container, one shape at a time.) The shape is settled within 0.3 % at the
coarser sizes; the peak tape tension is a local value that keeps changing with the mesh.

## Decision
* The automatic element size is footprint length / 40, between 100 and 300 mm (all
  assumed, set from this study). The upper limit stays at 300 mm: at 400 mm the eye pod's
  largest rim-tape tension was 10 % below the 229 mm value, at 300 mm 2 %.
* Every shape result carries a `peak_values_mesh_dependent` warning: peak tape tensions,
  peak fabric resultants and the factors of safety from them depend on the element size;
  the builder solves with a finer chosen size, or compares two, before relying on them.

## Consequences
* On the alien design the antennae are solved at 100 mm instead of 60 mm and the eye pods
  at 300 mm instead of 229 mm, several times faster, with the shape unchanged within
  0.3 %.
* Peak values from an automatic run are explicitly provisional; local refinement at the rim
  and cap (instead of a finer mesh everywhere) is the follow-up for factor-of-safety work.
* The element size is not part of a shape result's key, so results kept from earlier runs
  stay current until the shape or the envelope changes.
