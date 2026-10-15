# ADR-0026: Solved-shape ghosts and the profile compensation target

- Status: Accepted
- Date: 2026-10-15

## Context
The drawn meridian profile of a standard-gore design is the intended tape line. The
patterns cut from it inflate to the shape equilibrium gives. On the generic 8-gore
fixture the preview's tape line lies up to 103 mm from the drawn profile (101 mm taller,
84 mm wider). Builders need to see this difference, and need a way to remove it: either
pre-distort the cut so the inflated shape matches the drawing, or make the drawing what
actually flies.

Compensation is an iteration, and every step needs a new solve. After the first step,
the drawn control points are the *cut* line, not the intended line. If the editor took
the drawn profile as the target again, each step would correct towards the previous cut
and drift away from the shape the builder drew.

## Decision
* `envelopelab.project.profile_match` reads the solved tape line of a run from its
  result arrays. The seam nodes are found by their initial azimuth, and the line is
  averaged over the seams at common material stations. The module measures the line's
  deviation and computes *compensated* and *adopted* control points (see
  [theory](../theory/profile-matching.md)). New runs store their `gore_count` in the
  result arrays, so the tapes are found even after the gore count is edited.
* The project file gains an optional `profile_target`: the intended control points,
  their interpolation, the start time and the deviation before each step. It is written
  only while a profile is being compensated. Projects that never compensate are
  unchanged, and the format version stays 2.
* Like the constraint locks, the target is an editor setting outside the design state.
  It does not change the design content hash or the simulation fingerprint, so setting
  it makes nothing stale. It is not in the undo history. The profile edits that go with
  it (compensate, adopt, restore) are ordinary undoable commands.
* Only a current, converged run may drive an update. Height, volume, maximum-diameter,
  mouth-diameter and top-hole-diameter locks refuse an update, because the update changes
  those quantities on purpose. Segment profiles (ADR-0025) refuse it too: lines and arcs
  cannot follow a solved line.

## Consequences
* Releases before this one reject a project saved while it has a target (the project
  model forbids unknown keys). *Restore intended profile* or *Keep cut, clear target*
  removes the key.
* An undo of a compensation step restores the control points but keeps the target and
  its history. This is intended: the target is what the builder wants, whatever cut is
  current.
* Updated profiles gain control points (13 instead of 5 on the fixture at the default
  5 mm fit tolerance). They stay editable as before.
