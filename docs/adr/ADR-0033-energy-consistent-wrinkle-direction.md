# ADR-0033: The wrinkle direction maximises the uniaxial energy (relaxed energy)

- Status: Accepted
- Date: 2026-11-02
- Changes the tension-field law of ADR-0004 (preview solver) and the state
  classification of ADR-0005 / ADR-0027 (CalculiX adapter).

## Context
Special shapes on a full-size envelope (the Smalley 90K design with two eye pods and two
antennae, solved as in ADR-0031) did not converge at the automatic element size: the eye
pod at 232 mm (8,002 nodes) and the antenna at 60 mm (3,053 nodes) both stopped at a
relative residual of about 0.3 after 200,000 iterations. The residual sat on the wrinkled
caps; the shape had stopped moving (< 0.4 mm per 20,000 iterations), but the kinetic
damping reset every ~18 iterations. The same antenna with an isotropic fabric converged in
11,072 iterations.

The tension-field law took the wrinkle direction from the trial stress (mixed criterion,
Kang and Im). That is exact for isotropic fabric, but for orthotropic fabric (the generic
ripstop: warp 108 kN/m, weft 86 kN/m, shear 5 kN/m) the resulting stress is not the
gradient of any energy. Dynamic relaxation with kinetic damping relies on a potential; with
a non-conservative law it can cycle. Newton variants stalled for the same reason
(docs/dev/solver-trial.md).

## Decision
* A wrinkled triangle carries uniaxial tension \( E_n \varepsilon_n\, n \otimes n \)
  (+ the residual \( \kappa \)) along the direction \( n \) that maximises the uniaxial
  energy \( \tfrac12 E_n \varepsilon_n^2 \). That maximum is the relaxed energy of Pipkin
  and Steigmann and the stress is its gradient. A triangle is slack when no direction is
  stretched (largest principal strain \( \le 0 \)). Taut is unchanged (\( s_2 > 0 \)).
* The direction is found per triangle by
  `envelopelab.solvers.membrane.wrinkle_direction`: the best of the trial-stress direction,
  the major strain direction and 4 scanned angles, then Newton steps on
  \( \ln(\varepsilon_n^2 / q) \) with exact rational rotations (no trigonometric calls).
  The compiled kernel repeats the same arithmetic; the CalculiX adapter classifies states
  and freezes directions with `wrinkle_principal`, so both solvers keep the same law.

## Consequences
* For isotropic fabric results are unchanged (stress equal to 7.5e-14). For orthotropic
  fabric the equilibrium changes slightly: Smalley 90K at 800 mm volume -0.025 %, maximum
  tape tension +0.004 %; generic envelope at 600 mm volume -0.07 %, mean tape tension
  -11 %, 99th-percentile fabric N1 +8 % (docs/validation/).
* Shapes that never converged now converge: eye pod 232 mm in 14,956 iterations, antenna
  60 mm in 15,762 (preview). Envelopes need about 10 % fewer iterations.
* Each wrinkled triangle costs more per iteration (the direction search): about 1.5x per
  iteration on the 32 %-wrinkled eye pod and 2x on the 80 %-wrinkled Smalley envelope. A
  warm start from the previous iteration's direction would remove most of it and is a
  possible follow-up.
* The search constants are repeated in `kernels.py`, so changing them invalidates Numba's
  on-disk cache; a test keeps them equal to the NumPy law's.
