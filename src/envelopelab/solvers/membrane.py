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
Fabric carries no compression. With trial stress :math:`S^\ast = \mathbb{C}:E`, principal
values :math:`s_1 \ge s_2` and major direction :math:`n`, the mixed criterion
[Kang-Im]_ classifies each triangle as

* **taut** if :math:`s_2 > 0`: :math:`S = S^\ast`;
* **slack** if :math:`\varepsilon_n = n^\mathsf{T} E n \le 0` (no stretch along
  :math:`n`):
  :math:`S = \kappa S^\ast`;
* **wrinkled** otherwise: uniaxial tension along :math:`n`,

  .. math::
      S = E_n \varepsilon_n\, n \otimes n + \kappa (S^\ast - E_n \varepsilon_n\, n\otimes n),
      \qquad E_n = \left(v^\mathsf{T} \mathbb{C}^{-1} v\right)^{-1},\;
      v = (n_1^2, n_2^2, n_1 n_2)

  where :math:`E_n` is the uniaxial stiffness along :math:`n` with free lateral
  contraction.

:math:`\kappa` (``slack_stiffness_ratio``, default :math:`10^{-3}`) keeps a small
compressive stiffness so that slack regions have no zero-energy modes. The residual
compression is at most :math:`\kappa |s_2^\ast|` and is reported with the results.

Assumptions: small strain (< ~10 %), linear elastic fabric, constant strain per triangle,
wrinkle direction taken from the trial stress (exact for isotropic material, approximate
for strongly orthotropic fabric), no bending stiffness.

References
----------
.. [Kang-Im] S. Kang and S. Im, "Finite element analysis of wrinkling membranes",
   J. Appl. Mech. 64 (1997) 263-269.
.. [Bonet-Wood] J. Bonet and R. D. Wood, *Nonlinear Continuum Mechanics for Finite
   Element Analysis*, 2nd ed., Cambridge University Press (2008), ch. 6 and 9.
.. [Miller-Hedgepeth] R. K. Miller and J. M. Hedgepeth, "An algorithm for finite element
   analysis of partly wrinkled membranes", AIAA J. 20 (1982) 1761-1763.
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
    eps_n = c * c * e[:, 0] + sn * sn * e[:, 1] + c * sn * e[:, 2]
    # Slack only when the fabric is not stretched along n. A test on s1 <= 0 would make
    # the stress jump from E_n eps_n n n to zero where Poisson coupling gives s1 <= 0 with
    # eps_n > 0; with this criterion the stress is continuous across both state changes.
    slack = (s2 <= 0.0) & (eps_n <= 0.0)
    wrinkled = (s2 <= 0.0) & ~slack
    state[wrinkled] = WRINKLED
    state[slack] = SLACK
    out = s.copy()
    out[slack] *= slack_stiffness_ratio
    if np.any(wrinkled):
        v = np.stack([c * c, sn * sn, c * sn], axis=1)[wrinkled]
        e_n = 1.0 / np.einsum("mi,mij,mj->m", v, compliance[wrinkled], v)
        uni = (e_n * eps_n[wrinkled])[:, None] * v
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
