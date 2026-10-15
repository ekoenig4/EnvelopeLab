# ADR-0024: Parachute centre panel (design schema version 6)

- Status: Accepted
- Date: 2026-10-14

## Context
The parachute was cut as N radial wedges running from its edge to the apex, or to the
centre ring when there is one. A wedge that narrows to a point (or to a 50 mm ring) is
not how builders make parachutes: the radial panels are trapezoids, and a round piece of
fabric at the centre joins them. Builders also need to see and set the overlap between
the parachute and the envelope round the top hole. That overlap was already in the design
(`gores.seal_overlap`) but only showed in the Properties panel of the gores.

## Decision
* `ParachuteSpec.centre_panel_diameter` (m, optional) is the diameter of a flat circular
  centre panel. The radial panels end at the circle of that diameter on the seated
  parachute, so they are trapezoids, and the centre panel closes it. The centre panel is
  larger than the centre ring and smaller than the parachute hole. None keeps the earlier
  construction, with radial panels running to the centre ring or the apex.
* The centre panel is cut flat, a circle of that diameter plus the seam allowance. Its
  edge \(\pi D_c\) matches the radial panels' top edges (\(2\pi r_c\) in the small-bulge
  width model), and a mismatch over 3 mm is an error. The cap's rise inside the seam is
  not in the pattern. The crown pressure and the shroud-line load keep the full cap rise,
  which is conservative.
* New parachutes (`default_parachute`) get a centre panel of a quarter of the hole
  diameter. This is a generic starting value for the builder to review.
* The Rigging panel edits the overlap and the centre-panel diameter directly. The pattern
  view draws the centre panel above the radial panel, and the 3D view draws its seam.
* The design document becomes schema version 6. Version-5 documents migrate unchanged:
  their parachutes have no centre panel, so their patterns and results are as before.

## Consequences
* Parachute patterns match the usual construction, and the radial and centre panels are
  checked to sew together.
* Shape files accept `centre_panel_diameter` under `rigging.parachute` (a length with a
  unit).
* The parachute fabric area and mass include the centre panel. For the same seated shape
  they differ from the wedge construction only by the flat disc against the spherical cap
  inside the seam (below 1 % for the default billow).
* Older EnvelopeLab versions cannot read version-6 documents.
