r"""Element kernel of the preview solver, in NumPy and (optionally) compiled.

Every iteration of dynamic relaxation evaluates, for each constant-strain triangle,

.. math::
    F = \sum_a \mathbf{x}_a \otimes \nabla N_a, \qquad
    E = \tfrac12 (F^T F - I), \qquad
    S = \mathbb{C} : E \ \text{(tension-field modified)}, \qquad
    \mathbf{f}^{int}_a = A_0\, F S \nabla N_a

(:mod:`envelopelab.solvers.membrane` documents each step and the tension-field model),
the consistent pressure load on its corners

.. math:: \mathbf{f}^{p}_a = \frac{2 p_a + p_b + p_c}{12}\,
          (\mathbf{x}_b - \mathbf{x}_a) \times (\mathbf{x}_c - \mathbf{x}_a),

and sums both onto the nodes. On meshes of a few thousand triangles the vectorized NumPy
evaluation spends most of its time in per-call overhead rather than arithmetic. When
Numba is installed (the optional ``fast`` extra, ADR-0019), :func:`element_forces` runs
the same arithmetic as one compiled loop over the triangles; otherwise, or with
``ENVELOPELAB_NO_JIT=1``, it calls the NumPy functions. Both paths give the same results
to round-off (tested), so the choice changes run time only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from envelopelab.solvers.membrane import (
    FloatArray,
    IntArray,
    RestGeometry,
    deformation_gradient,
    green_strain,
    internal_forces,
    tension_field,
)

numba: Any
try:  # Optional accelerator (extra "fast").
    import numba

    HAVE_NUMBA = True
except ImportError:  # pragma: no cover - exercised where numba is missing
    numba = None
    HAVE_NUMBA = False


def jit_enabled() -> bool:
    """True when the compiled kernel is available and not disabled by the environment."""
    return HAVE_NUMBA and not os.environ.get("ENVELOPELAB_NO_JIT")


@dataclass
class ElementForces:
    """Per-triangle results of one evaluation and their nodal sums (SI units).

    Attributes
    ----------
    xe : ndarray, shape (m, 3, 3)
        Corner positions, m.
    f : ndarray, shape (m, 3, 2)
        Deformation gradient, dimensionless.
    strain : ndarray, shape (m, 2, 2)
        Green-Lagrange strain, dimensionless.
    stress : ndarray, shape (m, 2, 2)
        PK2 stress resultants, N/m.
    state : ndarray of int8, shape (m,)
        ``TAUT``, ``WRINKLED`` or ``SLACK``.
    trial_minor : ndarray, shape (m,)
        Minor principal trial stress, N/m.
    f_int : ndarray, shape (m, 3, 3)
        Internal force on each corner, N.
    f_p : ndarray, shape (m, 3, 3)
        Pressure force on each corner, N.
    residual : ndarray, shape (n, 3)
        Sum over the corners of ``f_p - f_int`` per node, N.
    external : ndarray, shape (n, 3)
        Sum over the corners of ``f_p`` per node, N.
    """

    xe: FloatArray
    f: FloatArray
    strain: FloatArray
    stress: FloatArray
    state: npt.NDArray[np.int8]
    trial_minor: FloatArray
    f_int: FloatArray
    f_p: FloatArray
    residual: FloatArray
    external: FloatArray


def pressure_corner_forces(xe: FloatArray, p: FloatArray) -> FloatArray:
    r"""Consistent pressure loads on the corners of linear triangles (module docstring), N.

    Parameters
    ----------
    xe : ndarray, shape (m, 3, 3)
        Corner positions, m.
    p : ndarray, shape (m, 3)
        Net pressure at the corners, Pa.

    Returns
    -------
    ndarray, shape (m, 3, 3)
        Force on each corner, N.
    """
    a = xe[:, 1] - xe[:, 0]
    b = xe[:, 2] - xe[:, 0]
    normal = np.empty_like(a)
    normal[:, 0] = a[:, 1] * b[:, 2] - a[:, 2] * b[:, 1]
    normal[:, 1] = a[:, 2] * b[:, 0] - a[:, 0] * b[:, 2]
    normal[:, 2] = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
    normal *= 0.5
    weights = (p + p.sum(axis=1, keepdims=True)) / 12.0
    out: FloatArray = weights[:, :, None] * normal[:, None, :]
    return out


def element_forces_numpy(
    x: FloatArray,
    tri: IntArray,
    rest: RestGeometry,
    stiffness: FloatArray,
    compliance: FloatArray,
    slack_stiffness_ratio: float,
    enabled: bool,
    p: FloatArray,
    scatter: Any,
) -> ElementForces:
    """Reference NumPy evaluation (see :func:`element_forces`)."""
    xe = x[tri]
    f = deformation_gradient(xe, rest.grad_n)
    strain = green_strain(f)
    stress, state, trial_minor = tension_field(
        strain, stiffness, compliance, slack_stiffness_ratio, enabled
    )
    f_int = internal_forces(f, stress, rest)
    f_p = pressure_corner_forces(xe, p)
    ext = np.asarray(scatter @ f_p.reshape(-1, 3))
    r = ext - np.asarray(scatter @ f_int.reshape(-1, 3))
    return ElementForces(xe, f, strain, stress, state, trial_minor, f_int, f_p, r, ext)


def _element_loop(  # pragma: no cover - compiled by numba; the NumPy path is the reference
    x: Any,
    tri: Any,
    grad: Any,
    area: Any,
    c: Any,
    ci: Any,
    kappa: float,
    enabled: bool,
    p: Any,
    xe: Any,
    f: Any,
    strain: Any,
    stress: Any,
    state: Any,
    minor: Any,
    f_int: Any,
    f_p: Any,
    r_nodes: Any,
    ext_nodes: Any,
) -> None:
    m = tri.shape[0]
    for t in range(m):
        for a in range(3):
            for i in range(3):
                xe[t, a, i] = x[tri[t, a], i]
        for i in range(3):
            for k in range(2):
                f[t, i, k] = (
                    xe[t, 0, i] * grad[t, 0, k]
                    + xe[t, 1, i] * grad[t, 1, k]
                    + xe[t, 2, i] * grad[t, 2, k]
                )
        e00 = 0.5 * ((f[t, 0, 0] ** 2 + f[t, 1, 0] ** 2 + f[t, 2, 0] ** 2) - 1.0)
        e11 = 0.5 * ((f[t, 0, 1] ** 2 + f[t, 1, 1] ** 2 + f[t, 2, 1] ** 2) - 1.0)
        e01 = 0.5 * (f[t, 0, 0] * f[t, 0, 1] + f[t, 1, 0] * f[t, 1, 1] + f[t, 2, 0] * f[t, 2, 1])
        strain[t, 0, 0] = e00
        strain[t, 1, 1] = e11
        strain[t, 0, 1] = e01
        strain[t, 1, 0] = e01
        v0, v1, v2 = e00, e11, 2.0 * e01
        s0 = c[t, 0, 0] * v0 + c[t, 0, 1] * v1 + c[t, 0, 2] * v2
        s1 = c[t, 1, 0] * v0 + c[t, 1, 1] * v1 + c[t, 1, 2] * v2
        s2 = c[t, 2, 0] * v0 + c[t, 2, 1] * v1 + c[t, 2, 2] * v2
        mean = 0.5 * (s0 + s1)
        rad = np.sqrt((0.5 * (s0 - s1)) ** 2 + s2**2)
        minor_s = mean - rad
        minor[t] = minor_s
        o0, o1, o2 = s0, s1, s2
        st = 0
        if enabled and minor_s <= 0.0:
            angle = 0.5 * np.arctan2(2.0 * s2, s0 - s1)
            cs = np.cos(angle)
            sn = np.sin(angle)
            eps_n = cs * cs * v0 + sn * sn * v1 + cs * sn * v2
            if eps_n <= 0.0:
                st = 2
                o0, o1, o2 = kappa * s0, kappa * s1, kappa * s2
            else:
                st = 1
                w0, w1, w2 = cs * cs, sn * sn, cs * sn
                q0 = ci[t, 0, 0] * w0 + ci[t, 0, 1] * w1 + ci[t, 0, 2] * w2
                q1 = ci[t, 1, 0] * w0 + ci[t, 1, 1] * w1 + ci[t, 1, 2] * w2
                q2 = ci[t, 2, 0] * w0 + ci[t, 2, 1] * w1 + ci[t, 2, 2] * w2
                u = eps_n / (w0 * q0 + w1 * q1 + w2 * q2)
                u0, u1, u2 = u * w0, u * w1, u * w2
                o0 = u0 + kappa * (s0 - u0)
                o1 = u1 + kappa * (s1 - u1)
                o2 = u2 + kappa * (s2 - u2)
        state[t] = st
        stress[t, 0, 0] = o0
        stress[t, 1, 1] = o1
        stress[t, 0, 1] = o2
        stress[t, 1, 0] = o2
        for i in range(3):
            q0 = f[t, i, 0] * o0 + f[t, i, 1] * o2
            q1 = f[t, i, 0] * o2 + f[t, i, 1] * o1
            for a in range(3):
                f_int[t, a, i] = q0 * (grad[t, a, 0] * area[t]) + q1 * (grad[t, a, 1] * area[t])
        ax = xe[t, 1, 0] - xe[t, 0, 0]
        ay = xe[t, 1, 1] - xe[t, 0, 1]
        az = xe[t, 1, 2] - xe[t, 0, 2]
        bx = xe[t, 2, 0] - xe[t, 0, 0]
        by = xe[t, 2, 1] - xe[t, 0, 1]
        bz = xe[t, 2, 2] - xe[t, 0, 2]
        nx = 0.5 * (ay * bz - az * by)
        ny = 0.5 * (az * bx - ax * bz)
        nz = 0.5 * (ax * by - ay * bx)
        psum = p[t, 0] + p[t, 1] + p[t, 2]
        for a in range(3):
            w = (p[t, a] + psum) / 12.0
            f_p[t, a, 0] = w * nx
            f_p[t, a, 1] = w * ny
            f_p[t, a, 2] = w * nz
            node = tri[t, a]
            for i in range(3):
                ext_nodes[node, i] += f_p[t, a, i]
                r_nodes[node, i] += f_p[t, a, i] - f_int[t, a, i]


_compiled: Any = None


def _kernel() -> Any:
    global _compiled
    if _compiled is None:
        assert numba is not None
        _compiled = numba.njit(cache=True, nogil=True)(_element_loop)
    return _compiled


def element_forces(
    x: FloatArray,
    tri: IntArray,
    rest: RestGeometry,
    stiffness: FloatArray,
    compliance: FloatArray,
    slack_stiffness_ratio: float,
    enabled: bool,
    p: FloatArray,
    scatter: Any,
    use_jit: bool | None = None,
) -> ElementForces:
    r"""Membrane and pressure forces of every triangle and their nodal sums.

    Parameters
    ----------
    x : ndarray, shape (n, 3)
        Node positions, m.
    tri : ndarray of int, shape (m, 3)
        Triangles.
    rest : RestGeometry
        Rest shape-function gradients (1/m) and areas (m^2).
    stiffness, compliance : ndarray, shape (m, 3, 3)
        Plane-stress resultant matrix (N/m) and its inverse (m/N).
    slack_stiffness_ratio : float
        :math:`\kappa`, dimensionless.
    enabled : bool
        Apply the tension-field modification.
    p : ndarray, shape (m, 3)
        Net pressure at every corner, Pa.
    scatter : scipy.sparse matrix, shape (n, 3m)
        Corner-to-node sum (used by the NumPy path).
    use_jit : bool, optional
        Force (True) or avoid (False) the compiled kernel; default :func:`jit_enabled`.

    Returns
    -------
    ElementForces
        Per-triangle results and nodal sums.
    """
    jit = jit_enabled() if use_jit is None else (use_jit and HAVE_NUMBA)
    if not jit:
        return element_forces_numpy(
            x, tri, rest, stiffness, compliance, slack_stiffness_ratio, enabled, p, scatter
        )
    m, n = len(tri), len(x)
    out = ElementForces(
        np.empty((m, 3, 3)),
        np.empty((m, 3, 2)),
        np.empty((m, 2, 2)),
        np.empty((m, 2, 2)),
        np.empty(m, dtype=np.int8),
        np.empty(m),
        np.empty((m, 3, 3)),
        np.empty((m, 3, 3)),
        np.zeros((n, 3)),
        np.zeros((n, 3)),
    )
    _kernel()(
        np.ascontiguousarray(x, dtype=np.float64),
        np.ascontiguousarray(tri, dtype=np.int64),
        rest.grad_n,
        rest.area,
        stiffness,
        compliance,
        float(slack_stiffness_ratio),
        bool(enabled),
        np.ascontiguousarray(p, dtype=np.float64),
        out.xe,
        out.f,
        out.strain,
        out.stress,
        out.state,
        out.trial_minor,
        out.f_int,
        out.f_p,
        out.residual,
        out.external,
    )
    return out
