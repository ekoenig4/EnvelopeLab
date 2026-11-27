# ADR-0065: A scale model's 3D views are the 3D view's, scaled

- Status: Accepted
- Date: 2026-11-27
- Supersedes: the 3D-view clause of ADR-0063 ("The 3D views are drawn from the scaled
  design and shapes with a *Scale model 1:n* banner, never from a full-size solver run")

## Context
ADR-0064 made the full-size pack's 3D page show what the application's 3D view shows:
every object (envelope, special shapes, overlays, rigging) in every Shape state
(Designed, Inflated (preview), Inflated (CalculiX)). A scale model's page was still drawn
from the scaled design alone (ADR-0063): it had no inflated shapes and no overlays, so
builders of a model could not see what the model should look like inflated. The page
also left out parts the 3D view draws: the seams of inflated parts, the envelope's panel
details and the symmetry axes.

## Decision
* A scale model's 3D page and per-shape pages are the full-size pages the application
  builds from its 3D view, with every position (meshes, lines, labels) multiplied by the
  model's factor \( k = 1/n \) (`envelopelab.export.viewer.scale_scene`). The objects,
  rows and Shape states are unchanged.
* Every analysis colouring (factors of safety, resultants, wrinkling, displacement,
  deviation) is dropped: loads and stresses do not scale with the patterns (ADR-0062).
  The fabric colours stay.
* Each inflated Shape's banner says *Scale model 1:n: Inflated (...)*, that the shape is
  the full-size run's scaled and that loads, stresses and factors of safety are n/a,
  and quotes the full-size run's status. A stale, unconverged or failing run keeps its
  banner kind and part notes: a scaled result never hides a problem.
* Without a 3D view (a pack from a script), the page is drawn from the scaled design, as
  before.
* The page also gets, from the 3D view, the seams of inflated parts, the panel details
  (envelope, designed) and the symmetry axes (an object of their own, every state).

## Consequences
* The model's page matches the application's 3D tab part for part.
* The inflated shape of a model is the full-size run's, scaled. A real model of other
  fabric, at much lower pressure, may inflate differently; the banner says the shape is
  scaled from the full-size run.
* No format change: viewer format 2 already carries objects and states.
