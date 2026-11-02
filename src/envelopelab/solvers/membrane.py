r"""Constant-strain triangle (CST) membrane with an orthotropic law and a tension field.

All functions are vectorised over ``m`` triangles. Rest coordinates are the flat (as-cut)
panel coordinates rotated into the fabric axes (1 = warp along the grain arrow, 2 = weft),
so strains and second Piola-Kirchhoff (PK2) stresses are expressed in fabric axes.

Kinematics
----------
With rest corner coordinates :math:`X_a \in \mathbb{R}^2` and current positions
:math:`x_a \in \mathbb{R}^3`,

.. math::
    F = [x_1 - x_0,\; x_2 - x_0]\,[X_1 - X_0,\; X_2 - X_0]^{-1}
      = \sum_a x_a \otimes \nabla N_a, \qquad
    E = \tfrac12 (F^\mathsf{T} F - I)

(Green-Lagrange strain, exact for large rotations). The St. Venant-Kirchhoff law
:math:`S = \mathbb{C} : E` gives PK2 stress resultants (N/m); nodal internal forces are

.. math:: f_a = A_0\, F S\, \nabla N_a

and the true (Cauchy) stress resultant is :math:`\sigma = J^{-1} F S F^\mathsf{T}` with
:math:`J = A / A_0`.

Tension field (wrinkling)
-------------------------
Fabric carries no compression. With trial stress :math:`S^\ast = \mathbb{C}:E` and its
principal values :math:`s_1 \ge s_2`, each triangle is

* **taut** if :math:`s_2 > 0`: :math:`S = S^\ast`;
* **slack** if no direction is stretched (largest principal strain
  :math:`\varepsilon_{max} \le 0`): :math:`S = \kappa S^\ast`;
* **wrinkled** otherwise: uniaxial tension along :math:`n`,

  .. math::
      S = E_n \varepsilon_n\, n \otimes n + \kappa (S^\ast - E_n \varepsilon_n\, n\otimes n),
      \qquad E_n = \left(v^\mathsf{T} \mathbb{C}^{-1} v\right)^{-1},\;
      v = (n_1^2, n_2^2, n_1 n_2)

  where :math:`E_n` is the uniaxial stiffness along :math:`n` with free lateral
  contraction and :math:`n` maximises the uniaxial energy
  :math:`\tfrac12 E_n \varepsilon_n^2` (:func:`wrinkle_direction`). That maximum is the
  relaxed energy :math:`W^\ast` [Pipkin]_, [Steigmann]_ and the stress is its gradient,
  so the law derives from an energy for any orthotropic fabric. For isotropic fabric the
  maximiser is the major trial-stress direction: the mixed criterion of [Kang-Im]_.

:math:`\kappa` (``slack_stiffness_ratio``, default :math:`10^{-3}`) keeps a small
compressive stiffness so that slack regions have no zero-energy modes. The residual
compression is at most :math:`\kappa |s_2^\ast|` and is reported with the results.

Assumptions: small strain (< ~10 %), linear elastic fabric, constant strain per triangle,
no bending stiffness.

References
----------
.. [Kang-Im] S. Kang and S. Im, "Finite element analysis of wrinkling membranes",
   J. Appl. Mech. 64 (1997) 263-269.
.. [Bonet-Wood] J. Bonet and R. D. Wood, *Nonlinear Continuum Mechanics for Finite
   Element Analysis*, 2nd ed., Cambridge University Press (2008), ch. 6 and 9.
.. [Miller-Hedgepeth] R. K. Miller and J. M. Hedgepeth, "An algorithm for finite element
   analysis of partly wrinkled membranes", AIAA J. 20 (1982) 1761-1763.
.. [Pipkin] A. C. Pipkin, "The relaxed energy density for isotropic elastic membranes",
   IMA J. Appl. Math. 36 (1986) 85-99.
.. [Steigmann] D. J. Steigmann, "Tension-field theory", Proc. R. Soc. Lond. A 429 (1990)
   141-173.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

#: Triangle states returned by :func:`tension_field`.
TAUT, WRINKLED, SLACK = 0, 1, 2
STATE_NAMES = {TAUT: "taut", WRINKLED: "wrinkled", SLACK: "slack"}


@dataclass(frozen=True)
class RestGeometry:
    """Per-triangle rest data in fabric axes.

    Attributes
    ----------
    grad_n : ndarray, shape (m, 3, 2)
        Shape-function gradients :math:`\\nabla N_a` in fabric axes, 1/m.
    area : ndarray, shape (m,)
        Rest (flat) area, m^2.
    """

    grad_n: FloatArray
    area: FloatArray


def rest_geometry(rest_uv: FloatArray, grain: FloatArray) -> RestGeometry:
    """Shape-function gradients and areas of the flat rest triangles in fabric axes.

    Parameters
    ----------
    rest_uv : ndarray, shape (m, 3, 2)
        Flat rest corner coordinates, m (counter-clockwise).
    grain : ndarray, shape (m, 2)
        Warp direction in the same flat frame (normalised here), dimensionless.

    Returns
    -------
    RestGeometry
        Gradients (1/m) and rest areas (m^2).

    Raises
    ------
    ValueError
        If a triangle is degenerate or clockwise, or a grain vector is zero.
    """
    g = np.asarray(grain, dtype=np.float64)
    norm = np.linalg.norm(g, axis=1)
    if np.any(~np.isfinite(norm)) or np.any(norm < 1e-12):
        raise ValueError("every triangle needs a finite, non-zero grain direction")
    g = g / norm[:, None]
    # Rows of the rotation are the warp and weft (warp rotated +90 deg) unit vectors.
    rot = np.stack([g, np.column_stack([-g[:, 1], g[:, 0]])], axis=1)
    xm = np.einsum("mij,maj->mai", rot, rest_uv)
    dm = np.stack([xm[:, 1] - xm[:, 0], xm[:, 2] - xm[:, 0]], axis=2)
    det = dm[:, 0, 0] * dm[:, 1, 1] - dm[:, 0, 1] * dm[:, 1, 0]
    if np.any(det <= 1e-14):
        bad = int(np.argmin(det))
        raise ValueError(f"rest triangle {bad} is degenerate or clockwise (2A = {det[bad]:.3g})")
    inv = np.empty_like(dm)
    inv[:, 0, 0] = dm[:, 1, 1] / det
    inv[:, 0, 1] = -dm[:, 0, 1] / det
    inv[:, 1, 0] = -dm[:, 1, 0] / det
    inv[:, 1, 1] = dm[:, 0, 0] / det
    grad = np.empty((len(det), 3, 2))
    grad[:, 1] = inv[:, 0]
    grad[:, 2] = inv[:, 1]
    grad[:, 0] = -(inv[:, 0] + inv[:, 1])
    return RestGeometry(grad_n=grad, area=0.5 * det)


def deformation_gradient(xe: FloatArray, grad_n: FloatArray) -> FloatArray:
    """Deformation gradient of each triangle.

    Parameters
    ----------
    xe : ndarray, shape (m, 3, 3)
        Current corner positions, m.
    grad_n : ndarray, shape (m, 3, 2)
        Rest shape-function gradients, 1/m.

    Returns
    -------
    ndarray, shape (m, 3, 2)
        :math:`F`, dimensionless.
    """
    # Explicit sums: much faster than einsum for these tiny inner dimensions.
    g = grad_n
    return (
        xe[:, 0, :, None] * g[:, 0, None, :]
        + xe[:, 1, :, None] * g[:, 1, None, :]
        + xe[:, 2, :, None] * g[:, 2, None, :]
    )


def green_strain(f: FloatArray) -> FloatArray:
    """Green-Lagrange membrane strain :math:`E = (F^T F - I)/2`, shape (m, 2, 2)."""
    f0, f1 = f[:, :, 0], f[:, :, 1]
    out = np.empty((len(f), 2, 2))
    out[:, 0, 0] = 0.5 * ((f0 * f0).sum(axis=1) - 1.0)
    out[:, 1, 1] = 0.5 * ((f1 * f1).sum(axis=1) - 1.0)
    out[:, 0, 1] = out[:, 1, 0] = 0.5 * (f0 * f1).sum(axis=1)
    return out


def _sym_eig(s11: FloatArray, s22: FloatArray, s12: FloatArray) -> tuple[FloatArray, ...]:
    """Principal values (s1 >= s2) and unit major direction of symmetric 2x2 tensors."""
    mean = 0.5 * (s11 + s22)
    rad = np.sqrt((0.5 * (s11 - s22)) ** 2 + s12**2)
    s1 = mean + rad
    s2 = mean - rad
    angle = 0.5 * np.arctan2(2.0 * s12, s11 - s22)
    return s1, s2, np.cos(angle), np.sin(angle)


def trial_principal(
    strain: FloatArray, stiffness: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Principal trial stress and the stretch along its major direction.

    Parameters
    ----------
    strain : ndarray, shape (m, 2, 2)
        Green-Lagrange strain in fabric axes, dimensionless.
    stiffness : ndarray, shape (m, 3, 3)
        Plane-stress resultant matrix, N/m.

    Returns
    -------
    s1, s2 : ndarray, shape (m,)
        Major and minor principal trial PK2 resultants :math:`\\mathbb{C}:E`, N/m.
    direction : ndarray, shape (m, 2)
        Unit major direction :math:`n` in fabric axes (the wrinkle direction).
    eps_n : ndarray, shape (m,)
        :math:`n^T E n`, dimensionless.
    """
    e = np.stack([strain[:, 0, 0], strain[:, 1, 1], 2.0 * strain[:, 0, 1]], axis=1)
    s = (
        stiffness[:, :, 0] * e[:, 0, None]
        + stiffness[:, :, 1] * e[:, 1, None]
        + stiffness[:, :, 2] * e[:, 2, None]
    )
    s1, s2, c, sn = _sym_eig(s[:, 0], s[:, 1], s[:, 2])
    eps_n = c * c * e[:, 0] + sn * sn * e[:, 1] + c * sn * e[:, 2]
    return s1, s2, np.column_stack([c, sn]), eps_n


#: Angles scanned for the wrinkle direction before Newton refinement, and Newton steps.
WRINKLE_SCAN = 4
WRINKLE_NEWTON_STEPS = 8
#: Newton stops once its step is below this, rad.
WRINKLE_ANGLE_TOLERANCE = 1e-12
_SCAN_C2 = np.cos(2.0 * np.arange(WRINKLE_SCAN) * np.pi / WRINKLE_SCAN)
_SCAN_S2 = np.sin(2.0 * np.arange(WRINKLE_SCAN) * np.pi / WRINKLE_SCAN)


def _eps_q(
    c2: FloatArray, s2: FloatArray, e0: FloatArray, e1: FloatArray, e2: FloatArray, d: FloatArray
) -> tuple[FloatArray, FloatArray]:
    r""":math:`\varepsilon_n` and :math:`q = v^T \mathbb{C}^{-1} v` for a direction given by
    :math:`\cos 2\theta, \sin 2\theta` (``d`` is the compliance, shape (k, 3, 3))."""
    w0, w1, w2 = 0.5 * (1.0 + c2), 0.5 * (1.0 - c2), 0.5 * s2  # (c^2, s^2, cs)
    eps = w0 * e0 + w1 * e1 + w2 * e2
    dw0 = d[:, 0, 0] * w0 + d[:, 0, 1] * w1 + d[:, 0, 2] * w2
    dw1 = d[:, 1, 0] * w0 + d[:, 1, 1] * w1 + d[:, 1, 2] * w2
    dw2 = d[:, 2, 0] * w0 + d[:, 2, 1] * w1 + d[:, 2, 2] * w2
    return eps, w0 * dw0 + w1 * dw1 + w2 * dw2


def _uniaxial_energy_terms(
    c2: FloatArray, s2: FloatArray, e0: FloatArray, e1: FloatArray, e2: FloatArray, d: FloatArray
) -> tuple[FloatArray, ...]:
    r""":math:`\varepsilon_n`, :math:`q` and their first and second derivatives in
    :math:`\theta`, for the direction :math:`(\cos 2\theta, \sin 2\theta)` = ``(c2, s2)``."""
    w0, w1, w2 = 0.5 * (1.0 + c2), 0.5 * (1.0 - c2), 0.5 * s2
    p0, p1, p2 = -s2, s2, c2  # dw/dtheta
    r0, r1, r2 = -2.0 * c2, 2.0 * c2, -2.0 * s2  # d2w/dtheta2
    eps = w0 * e0 + w1 * e1 + w2 * e2
    deps = p0 * e0 + p1 * e1 + p2 * e2
    ddeps = r0 * e0 + r1 * e1 + r2 * e2
    dw0 = d[:, 0, 0] * w0 + d[:, 0, 1] * w1 + d[:, 0, 2] * w2
    dw1 = d[:, 1, 0] * w0 + d[:, 1, 1] * w1 + d[:, 1, 2] * w2
    dw2 = d[:, 2, 0] * w0 + d[:, 2, 1] * w1 + d[:, 2, 2] * w2
    dp0 = d[:, 0, 0] * p0 + d[:, 0, 1] * p1 + d[:, 0, 2] * p2
    dp1 = d[:, 1, 0] * p0 + d[:, 1, 1] * p1 + d[:, 1, 2] * p2
    dp2 = d[:, 2, 0] * p0 + d[:, 2, 1] * p1 + d[:, 2, 2] * p2
    q = w0 * dw0 + w1 * dw1 + w2 * dw2
    dq = 2.0 * (p0 * dw0 + p1 * dw1 + p2 * dw2)
    ddq = 2.0 * (r0 * dw0 + r1 * dw1 + r2 * dw2) + 2.0 * (p0 * dp0 + p1 * dp1 + p2 * dp2)
    return eps, deps, ddeps, q, dq, ddq


def _gain(eps: FloatArray, q: FloatArray) -> FloatArray:
    r"""Uniaxial energy measure :math:`\varepsilon_n^2 / q` (= :math:`E_n \varepsilon_n^2`),
    -1 where the direction is not stretched."""
    out: FloatArray = np.where(eps > 0.0, eps * eps / q, -1.0)
    return out


def wrinkle_direction(
    e: FloatArray, compliance: FloatArray, trial: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray]:
    r"""Tension direction of a wrinkled triangle: the maximiser of the uniaxial energy.

    The relaxed (tension-field) energy of a linear orthotropic membrane is
    :math:`W^\ast(E) = \max_n \tfrac12 E_n \varepsilon_n^2` over directions with
    :math:`\varepsilon_n = n^\mathsf{T} E n > 0` [Pipkin]_, [Steigmann]_, and its stress
    :math:`S = \partial W^\ast / \partial E = E_n \varepsilon_n\, n \otimes n` at the
    maximiser (envelope theorem). For isotropic fabric the maximiser is the major principal
    direction of the trial stress; for orthotropic fabric it is not, and taking the trial
    stress direction gives a stress that is not the gradient of any energy.

    The search maximises :math:`\ln(\varepsilon_n^2 / q)`, :math:`q = v^\mathsf{T}
    \mathbb{C}^{-1} v`, from the best of the trial-stress direction, the major strain
    direction and :data:`WRINKLE_SCAN` evenly spaced angles, by at most
    :data:`WRINKLE_NEWTON_STEPS` Newton steps with analytic derivatives. A step
    :math:`\delta` turns the direction by :math:`\arctan\delta` (an exact rational
    rotation of :math:`(\cos 2\theta, \sin 2\theta)`, so no trigonometric function is
    evaluated); a step that does not raise the energy is halved, at most three times, and
    the search stops for a triangle when its step is below :data:`WRINKLE_ANGLE_TOLERANCE`
    or no halving helps. Every triangle gets the same arithmetic as in the compiled kernel
    (:func:`envelopelab.solvers.kernels._wrinkle_dir_scalar`).

    Parameters
    ----------
    e : ndarray, shape (k, 3)
        Green strain (Voigt, engineering shear), dimensionless; some direction must be
        stretched (largest principal strain > 0).
    compliance : ndarray, shape (k, 3, 3)
        Inverse plane-stress matrix, m/N.
    trial : ndarray, shape (k, 2)
        Unit major direction of the trial stress (fabric axes).

    Returns
    -------
    c, s : ndarray, shape (k,)
        Cosine and sine of the tension direction (fabric axes).
    eps_n : ndarray, shape (k,)
        Stretch along it, dimensionless (> 0).
    """
    e0, e1, e2 = e[:, 0], e[:, 1], e[:, 2]
    d = compliance
    k = len(e0)
    # Directions are unit vectors (cos 2 theta, sin 2 theta): no trigonometric calls.
    ct, st = trial[:, 0], trial[:, 1]
    c2, s2 = ct * ct - st * st, 2.0 * ct * st
    eps, q = _eps_q(c2, s2, e0, e1, e2, d)
    best = _gain(eps, q)
    half = 0.5 * (e0 - e1)
    norm = np.sqrt(half * half + 0.25 * e2 * e2)
    safe = norm > 0.0
    sc2 = np.where(safe, half / np.where(safe, norm, 1.0), 1.0)
    ss2 = np.where(safe, 0.5 * e2 / np.where(safe, norm, 1.0), 0.0)
    eps, q = _eps_q(sc2, ss2, e0, e1, e2, d)
    g = _gain(eps, q)
    better = g > best
    c2, s2, best = np.where(better, sc2, c2), np.where(better, ss2, s2), np.where(better, g, best)
    for j in range(WRINKLE_SCAN):
        eps, q = _eps_q(np.full(k, _SCAN_C2[j]), np.full(k, _SCAN_S2[j]), e0, e1, e2, d)
        g = _gain(eps, q)
        better = g > best
        c2 = np.where(better, _SCAN_C2[j], c2)
        s2 = np.where(better, _SCAN_S2[j], s2)
        best = np.where(better, g, best)
    active = np.arange(k)
    for _ in range(WRINKLE_NEWTON_STEPS):
        if not len(active):
            break
        a = active
        eps, deps, ddeps, q, dq, ddq = _uniaxial_energy_terms(
            c2[a], s2[a], e0[a], e1[a], e2[a], d[a]
        )
        grad = 2.0 * deps / eps - dq / q
        curv = 2.0 * (ddeps * eps - deps * deps) / (eps * eps) - (ddq * q - dq * dq) / (q * q)
        step = np.where(curv < 0.0, -grad / np.where(curv < 0.0, curv, -1.0), 0.05 * grad)
        step = np.clip(step, -0.2, 0.2)
        moving = np.abs(step) > WRINKLE_ANGLE_TOLERANCE
        a, step = a[moving], step[moving]
        pending = np.ones(len(a), dtype=bool)
        for _ in range(4):
            sub = a[pending]
            if not len(sub):
                break
            # Rotate theta by atan(t), t = step: (cos, sin) of twice that, exactly rational.
            t = step[pending]
            den = 1.0 + t * t
            cr, sr = (1.0 - t * t) / den, 2.0 * t / den
            tc2 = c2[sub] * cr - s2[sub] * sr
            ts2 = s2[sub] * cr + c2[sub] * sr
            te, tq = _eps_q(tc2, ts2, e0[sub], e1[sub], e2[sub], d[sub])
            tg = _gain(te, tq)
            ok = tg >= best[sub]
            c2[sub[ok]], s2[sub[ok]], best[sub[ok]] = tc2[ok], ts2[ok], tg[ok]
            still = pending.copy()
            still[pending] = ~ok
            pending = still
            step = 0.5 * step
        active = a[~pending]
    eps, _ = _eps_q(c2, s2, e0, e1, e2, d)
    c = np.sqrt(np.maximum(0.5 * (1.0 + c2), 0.0))
    sn = np.copysign(np.sqrt(np.maximum(0.5 * (1.0 - c2), 0.0)), s2)
    return c, sn, eps


def wrinkle_principal(
    strain: FloatArray, stiffness: FloatArray, compliance: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Principal trial stress, and the tension direction and stretch of the wrinkled law.

    Where some direction is stretched (largest principal strain > 0) the direction is
    :func:`wrinkle_direction`'s and ``eps_n`` its stretch (> 0); elsewhere it is the major
    strain direction and ``eps_n`` the largest principal strain (<= 0). So ``eps_n > 0``
    is exactly the wrinkled side of the wrinkled/slack boundary of :func:`tension_field`,
    for every element (also taut ones, for a solver that releases with a hysteresis band).

    Parameters
    ----------
    strain : ndarray, shape (m, 2, 2)
        Green-Lagrange strain in fabric axes, dimensionless.
    stiffness, compliance : ndarray, shape (m, 3, 3)
        Plane-stress resultant matrix (N/m) and its inverse (m/N).

    Returns
    -------
    s1, s2 : ndarray, shape (m,)
        Major and minor principal trial PK2 resultants, N/m.
    direction : ndarray, shape (m, 2)
        Unit tension direction :math:`n` in fabric axes.
    eps_n : ndarray, shape (m,)
        Stretch along it, dimensionless.
    """
    e = np.stack([strain[:, 0, 0], strain[:, 1, 1], 2.0 * strain[:, 0, 1]], axis=1)
    s = (
        stiffness[:, :, 0] * e[:, 0, None]
        + stiffness[:, :, 1] * e[:, 1, None]
        + stiffness[:, :, 2] * e[:, 2, None]
    )
    s1, s2, c, sn = _sym_eig(s[:, 0], s[:, 1], s[:, 2])
    eps_n, _, ce, se = _sym_eig(e[:, 0], e[:, 1], 0.5 * e[:, 2])
    direction = np.column_stack([ce, se])
    stretched = eps_n > 0.0
    if np.any(stretched):
        trial = np.column_stack([c[stretched], sn[stretched]])
        cw, sw, eps = wrinkle_direction(e[stretched], compliance[stretched], trial)
        direction[stretched] = np.column_stack([cw, sw])
        eps_n = eps_n.copy()
        eps_n[stretched] = eps
    return s1, s2, direction, eps_n


def uniaxial_stiffness(direction: FloatArray, compliance: FloatArray) -> FloatArray:
    """Uniaxial resultant stiffness :math:`E_n = (v^T \\mathbb{C}^{-1} v)^{-1}` along ``direction``.

    Parameters
    ----------
    direction : ndarray, shape (m, 2)
        Unit directions in fabric axes.
    compliance : ndarray, shape (m, 3, 3)
        Inverse plane-stress matrix, m/N.

    Returns
    -------
    ndarray, shape (m,)
        :math:`E_n`, N/m (free lateral contraction).
    """
    c, sn = direction[:, 0], direction[:, 1]
    v = np.stack([c * c, sn * sn, c * sn], axis=1)
    out: FloatArray = 1.0 / np.einsum("mi,mij,mj->m", v, compliance, v)
    return out


def tension_field(
    strain: FloatArray,
    stiffness: FloatArray,
    compliance: FloatArray,
    slack_stiffness_ratio: float,
    enabled: bool = True,
) -> tuple[FloatArray, npt.NDArray[np.int8], FloatArray]:
    """PK2 stress resultants with the no-compression (tension-field) modification.

    Parameters
    ----------
    strain : ndarray, shape (m, 2, 2)
        Green-Lagrange strain in fabric axes, dimensionless.
    stiffness : ndarray, shape (m, 3, 3)
        Plane-stress resultant matrix (Voigt, engineering shear), N/m.
    compliance : ndarray, shape (m, 3, 3)
        Inverse of ``stiffness``, m/N.
    slack_stiffness_ratio : float
        :math:`\\kappa`, fraction of the trial stress kept in the relaxed part,
        dimensionless.
    enabled : bool
        False gives the linear-elastic (compression-carrying) membrane.

    Returns
    -------
    stress : ndarray, shape (m, 2, 2)
        PK2 stress resultants in fabric axes, N/m.
    state : ndarray of int8, shape (m,)
        ``TAUT``, ``WRINKLED`` or ``SLACK``.
    trial_minor : ndarray, shape (m,)
        Minor principal trial stress :math:`s_2^\\ast`, N/m (negative where released).
    """
    e = np.stack([strain[:, 0, 0], strain[:, 1, 1], 2.0 * strain[:, 0, 1]], axis=1)
    s = (
        stiffness[:, :, 0] * e[:, 0, None]
        + stiffness[:, :, 1] * e[:, 1, None]
        + stiffness[:, :, 2] * e[:, 2, None]
    )
    s1, s2, c, sn = _sym_eig(s[:, 0], s[:, 1], s[:, 2])
    state = np.full(len(s), TAUT, dtype=np.int8)
    if not enabled:
        return _tensor(s), state, s2
    # Slack only when no direction is stretched (largest principal strain <= 0): then the
    # relaxed energy is zero. Otherwise the uniaxial energy has a positive maximum, which
    # tends to zero at that boundary, so the stress is continuous across both changes.
    e_max = 0.5 * (e[:, 0] + e[:, 1]) + np.sqrt(
        (0.5 * (e[:, 0] - e[:, 1])) ** 2 + (0.5 * e[:, 2]) ** 2
    )
    slack = (s2 <= 0.0) & (e_max <= 0.0)
    wrinkled = (s2 <= 0.0) & ~slack
    state[wrinkled] = WRINKLED
    state[slack] = SLACK
    out = s.copy()
    out[slack] *= slack_stiffness_ratio
    if np.any(wrinkled):
        trial = np.column_stack([c[wrinkled], sn[wrinkled]])
        cw, sw, eps_n = wrinkle_direction(e[wrinkled], compliance[wrinkled], trial)
        v = np.stack([cw * cw, sw * sw, cw * sw], axis=1)
        e_n = 1.0 / np.einsum("mi,mij,mj->m", v, compliance[wrinkled], v)
        uni = (e_n * eps_n)[:, None] * v
        out[wrinkled] = uni + slack_stiffness_ratio * (s[wrinkled] - uni)
    return _tensor(out), state, s2


def _tensor(voigt: FloatArray) -> FloatArray:
    out = np.empty((len(voigt), 2, 2))
    out[:, 0, 0] = voigt[:, 0]
    out[:, 1, 1] = voigt[:, 1]
    out[:, 0, 1] = out[:, 1, 0] = voigt[:, 2]
    return out


def internal_forces(f: FloatArray, stress: FloatArray, rest: RestGeometry) -> FloatArray:
    """Nodal internal forces :math:`f_a = A_0 F S \\nabla N_a`.

    Parameters
    ----------
    f : ndarray, shape (m, 3, 2)
        Deformation gradient, dimensionless.
    stress : ndarray, shape (m, 2, 2)
        PK2 stress resultants, N/m.
    rest : RestGeometry
        Rest gradients (1/m) and areas (m^2).

    Returns
    -------
    ndarray, shape (m, 3, 3)
        Force on each corner, N (the gradient of the strain energy).
    """
    p0 = f[:, :, 0] * stress[:, None, 0, 0] + f[:, :, 1] * stress[:, None, 1, 0]
    p1 = f[:, :, 0] * stress[:, None, 0, 1] + f[:, :, 1] * stress[:, None, 1, 1]
    g = rest.grad_n * rest.area[:, None, None]
    return p0[:, None, :] * g[:, :, 0, None] + p1[:, None, :] * g[:, :, 1, None]


def cauchy_resultants(f: FloatArray, stress: FloatArray) -> FloatArray:
    """True stress resultants :math:`\\sigma = J^{-1} F S F^T` in 3D, shape (m, 3, 3), N/m.

    :math:`J` is the current-to-rest area ratio, dimensionless.
    """
    n = np.cross(f[:, :, 0], f[:, :, 1])
    j = np.linalg.norm(n, axis=1)
    fs = np.einsum("mij,mjk->mik", f, stress)
    out: FloatArray = np.einsum("mik,mlk->mil", fs, f) / j[:, None, None]
    return out


def element_stiffness_rowsum(
    f: FloatArray, stress: FloatArray, stiffness: FloatArray, grad_n: FloatArray, area: FloatArray
) -> FloatArray:
    """Gershgorin row sums of the CST tangent stiffness, per corner.

    Material part :math:`K^{mat}_{ab} = A_0 B_a^T \\mathbb{C} B_b` and geometric part
    :math:`K^{geo}_{ab} = A_0 (\\nabla N_a^T S \\nabla N_b) I`, bounded by
    :math:`A_0 \\max|s_i|\\, |\\nabla N_a| |\\nabla N_b|`. With the full (taut)
    :math:`\\mathbb{C}` the bound holds for every tension-field state.

    Parameters
    ----------
    f : ndarray, shape (m, 3, 2)
        Deformation gradient.
    stress : ndarray, shape (m, 2, 2)
        PK2 stress resultants, N/m.
    stiffness : ndarray, shape (m, 3, 3)
        Full (taut) constitutive matrix, N/m.
    grad_n : ndarray, shape (m, 3, 2)
        Rest shape-function gradients, 1/m.
    area : ndarray, shape (m,)
        Rest areas, m^2.

    Returns
    -------
    ndarray, shape (m, 3)
        Maximum over x, y, z of the absolute row sum for each corner, N/m.
    """
    g = grad_n
    f0, f1 = f[:, :, 0], f[:, :, 1]
    # B[m, b, voigt, xyz]
    b = np.empty((len(g), 3, 3, 3))
    b[:, :, 0] = g[:, :, 0, None] * f0[:, None, :]
    b[:, :, 1] = g[:, :, 1, None] * f1[:, None, :]
    b[:, :, 2] = g[:, :, 1, None] * f0[:, None, :] + g[:, :, 0, None] * f1[:, None, :]
    cb = np.einsum("mvw,mbwj->mbvj", stiffness, b)
    k = np.einsum("mavi,mbvj->maibj", b, cb)
    rows = np.abs(k).sum(axis=(3, 4))
    s_abs = np.abs(np.linalg.eigvalsh(stress)).max(axis=1)
    gn = np.linalg.norm(g, axis=2)
    geo = gn * gn.sum(axis=1, keepdims=True) * s_abs[:, None]
    out: FloatArray = area[:, None] * (rows.max(axis=2) + geo)
    return out
