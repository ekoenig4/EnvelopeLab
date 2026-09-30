# TODO and open work

A running list of parked and planned work, with what is already known, so it can be
picked up later. Items are grouped by area and ordered by priority within each group.
Numbers quoted here were measured as stated; none of them is a verified result.

## 1. Solver convergence on fine meshes (parked, highest priority)

**Problem.** The preview (dynamic-relaxation) solver converges on coarse meshes but not
on fine ones for lofted designs. On a real 20-gore, 17-row build pack with 2 % loft
(about 2 600 m³; the pack itself is not in the repository):

| Mesh | Nodes | Result |
|---|---|---|
| 800 mm | 5 460 | converged, 10 605 iterations, residual 9.3e-7 |
| 400 mm | 12 200 | **not converged** at the 200 000-iteration limit, residual 6.4e-3 |

CalculiX did not converge on either mesh (800 mm: relative out-of-balance 0.228 after
23 min, even when warm-started from the converged preview).

**Diagnosis so far.**

* It is not slow convergence. The median residual falls steadily for about 25 000
  iterations and then plateaus at 1e-3 to 1e-2, while triangles keep switching between
  taut and wrinkled (tens to about 130 per 500 iterations).
* Warm-starting the 400 mm solve from the converged 800 mm shape does not help: both
  starts are level by 25 000 iterations.
* It is not the slack horizontal tapes (92 % slack, 8 % of the residual) and not a twist
  of the envelope (0.006° rotation). 87 % of the residual is on the taut vertical load
  tapes, 99 % of it tangential (around the circumference), concentrated on the vertical
  seams of the widest row. Its sign varies from seam to seam: the 20 gores' lobes drift
  between near-equal shapes and break the 20-fold symmetry.
* Holding every vertical seam in its meridian plane (`SymmetryPlane` per seam) makes the
  400 mm solve converge in 8 274 iterations (residual 9.1e-7, about 3 min). Height,
  width and volume agree with the 800 mm unconstrained result within 1 mm and 0.05 %.
  But the constraint is not free: evaluated in the unconstrained model, the constrained
  shape is out of balance by 12.8 % (400 mm, largest nodal force 3.0 N) and 19.5 %
  (800 mm, 12.9 N). In the converged unconstrained 800 mm result the seams sit only
  0.17 mm (median; 1.2 mm max) off their planes, so the forces come from tape tension
  on sub-millimetre offsets. They shrink with refinement, which suggests a mesh
  artefact: every gore uses the same non-mirror-symmetric triangulation.

**Parked experiment: mirror-symmetric meshing.** `wip/mirror-symmetric-meshing.patch`
(apply with `git apply docs/dev/wip/mirror-symmetric-meshing.patch`):

* `graded_fractions` averages its fractions with their mirror image, so edge nodes are
  symmetric;
* an edge crossing a panel's mirror line gets a node on it (on both sides of its seam);
* a panel whose prescribed boundary is mirror-symmetric is meshed as its left half and
  reflected, with the mirror line discretised like a seam edge.

Status: implemented, the fast test suite passes, and the triangulations are exactly
symmetric (0 mismatch) with all mesh checks passing. **Not validated.** The only BARD
run used an earlier version that also over-refined the centre line (16 160 nodes), so
it cannot be compared: it reached a median residual of 1.7e-4 at 30 000 iterations with
no state changes, where the old meshes plateaued. The current version still meshes
denser (14 500 against 12 200 nodes at 400 mm), and the symmetric spacing also changes
non-mirrored meshes (12 920 nodes at 400 mm).

**Next steps.**

1. Fair comparison: unconstrained 400 mm-class solves on (A) the mirror-symmetric mesh
   and (B) the old meshing at the same node count. Symmetry is the fix only if A
   converges and B does not.
2. If it is the fix: find why the mirror mesh is denser, then run the §6.4 benchmarks
   with before and after values, update golden files and validation pages, and commit as
   `physics(solvers)`.
3. If not: offer the seam-plane constraint as a documented option (it excludes wrinkle
   patterns that differ from gore to gore), or look at the tension-field law and masses.
   Fictitious masses use the taut stiffness even for wrinkled triangles, which keep only
   0.1 % of it.
4. Get CalculiX to converge (it sees the same weakly held modes), for the cross-solver
   check.

The instrumented probe used for the diagnosis is in `wip/dr-probe-script.patch` (it
applies as `scripts/wip/dr_probe.py`; usage in its docstring; `--sym` adds the seam
planes).

## 2. Verification

* Mesh-convergence study: three refinements with a Richardson estimate of volume,
  height, width and the largest stress (AGENTS.md §6.3), on a fixture design and as a
  tool builders can run on their own design.
* Preview against CalculiX within 5 % on the same mesh.
* A *verified* run state in the app (converged + mesh-converged + cross-solver agreement)
  beside *converged*.

## 3. Solver physics

* Flying wires to a burner frame with the payload, instead of a mouth fixed in place.
* The parachute as a membrane with centering and confluence lines, the seal overlap and
  its weight. Today it is an unmeshed cap, and its weight is not applied.
* Measured or datasheet membrane stiffness, strength and seam efficiency, and tape
  stiffness (all generic `assumed` values now).
* Internal temperature stratification (hotter crown) and altitude cases.
* Factor of safety against fabric and tape strength in the results, highlighted where
  it fails; tape and line loads.

## 4. App

* Use `start_from_run` in the GUI. Today only CalculiX warm-starts, and only from a
  preview on the same mesh. A converged run on another mesh could seed the solve,
  recorded in the run manifest.
* Show the saved residual history of a run (a plot in the Simulation Runs panel).
* 2D pattern view: row labels and "MANUAL OVERRIDE" flags overlap when zoomed out.
* 2D pattern view: the dashed cut line is drawn from the generated row, not from a
  manual override's own offset.
* Manual outlines must use the editable layout (right side up, left side down, straight
  top and bottom). Imported panels with curved horizontal seams need the centre-line
  split, which shows 1 mm "top/bottom" edges. A general polygon override would be
  cleaner.
* Parachute pieces in the pattern view are read-only (no outline editing, notches or
  grain).
* Import of vector PDF patterns (today only DXF build packs), with detection of cut,
  sew and turning-vent lines.

## 5. Tooling

* The pre-commit hooks call `python` from `PATH`, so a commit fails outside the
  activated virtualenv; they could use the project's environment explicitly.
