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


# --------------------------------------------------------------------------------------
# Compiled dynamic-relaxation iterations
# --------------------------------------------------------------------------------------

#: Return codes of the compiled iterations (:func:`relax_kernel`).
RELAX_REPORT, RELAX_CONVERGED, RELAX_DIVERGED, RELAX_LIMIT = 0, 2, 3, 4


def _gas_pressure(params: Any, code: int, z: float) -> float:  # pragma: no cover - compiled
    """Differential pressure of gas ``code`` (row of ``params``) at height ``z``, Pa:
    ``p0 + gradient * (z - z_ref)``, clamped at zero height for the open envelope."""
    p0 = float(params[code, 0])
    gradient = float(params[code, 1])
    height = z - float(params[code, 2])
    if params[code, 3] > 0.5 and height < 0.0:
        height = 0.0
    return p0 + gradient * height


def _forces_into(  # pragma: no cover - compiled by numba; the NumPy path is the reference
    x: Any,
    tri: Any,
    grad: Any,
    area: Any,
    c: Any,
    ci: Any,
    kappa: float,
    enabled: bool,
    tri_gas: Any,
    gas: Any,
    fixed: Any,
    cable_edges: Any,
    cable_l0: Any,
    cable_ea: Any,
    cl_edges: Any,
    cl_edge_ptr: Any,
    cl_nodes: Any,
    cl_node_ptr: Any,
    cl_gas: Any,
    p: Any,
    xe: Any,
    f: Any,
    strain: Any,
    stress: Any,
    state: Any,
    minor: Any,
    f_int: Any,
    f_p: Any,
    r: Any,
    ext: Any,
) -> None:
    """Residual ``r`` and external force ``ext`` (n, 3) at ``x``: the same terms as
    ``_System.forces`` (elements and pressure, fixed weight and dead loads, tapes,
    closure caps)."""
    n = x.shape[0]
    m = tri.shape[0]
    # Corner pressures: gas inside (side 0) minus gas outside (side 1).
    for t in range(m):
        for a in range(3):
            z = x[tri[t, a], 2]
            p[t, a] = _gas_pressure(gas, tri_gas[t, 0], z) - _gas_pressure(gas, tri_gas[t, 1], z)
    for i in range(n):
        for k in range(3):
            r[i, k] = 0.0
            ext[i, k] = 0.0
    _element_loop_nb(
        x,
        tri,
        grad,
        area,
        c,
        ci,
        kappa,
        enabled,
        p,
        xe,
        f,
        strain,
        stress,
        state,
        minor,
        f_int,
        f_p,
        r,
        ext,
    )
    for i in range(n):
        for k in range(3):
            r[i, k] += fixed[i, k]
            ext[i, k] += fixed[i, k]
    for e in range(cable_edges.shape[0]):
        a = cable_edges[e, 0]
        b = cable_edges[e, 1]
        dx = x[b, 0] - x[a, 0]
        dy = x[b, 1] - x[a, 1]
        dz = x[b, 2] - x[a, 2]
        length = np.sqrt(dx * dx + dy * dy + dz * dz)
        strain_c = length / cable_l0[e] - 1.0
        tension = cable_ea[e] * strain_c if strain_c > 0.0 else 0.0
        scale = tension / (length if length > 1e-300 else 1e-300)
        r[a, 0] += scale * dx
        r[a, 1] += scale * dy
        r[a, 2] += scale * dz
        r[b, 0] -= scale * dx
        r[b, 1] -= scale * dy
        r[b, 2] -= scale * dz
    for q in range(cl_gas.shape[0]):
        n0, n1 = cl_node_ptr[q], cl_node_ptr[q + 1]
        cx = cy = cz = 0.0
        for j in range(n0, n1):
            cx += x[cl_nodes[j], 0]
            cy += x[cl_nodes[j], 1]
            cz += x[cl_nodes[j], 2]
        count = n1 - n0
        cx /= count
        cy /= count
        cz /= count
        tx = ty = tz = 0.0
        trib_total = 0.0
        e0, e1 = cl_edge_ptr[q], cl_edge_ptr[q + 1]
        for j in range(e0, e1):
            a = cl_edges[j, 0]
            b = cl_edges[j, 1]
            ax = x[b, 0] - cx
            ay = x[b, 1] - cy
            az = x[b, 2] - cz
            bx = x[a, 0] - cx
            by = x[a, 1] - cy
            bz = x[a, 2] - cz
            nx = 0.5 * (ay * bz - az * by)
            ny = 0.5 * (az * bx - ax * bz)
            nz = 0.5 * (ax * by - ay * bx)
            zc = (cz + x[a, 2] + x[b, 2]) / 3.0
            pc = _gas_pressure(gas, cl_gas[q], zc)
            tx += pc * nx
            ty += pc * ny
            tz += pc * nz
            ex = x[b, 0] - x[a, 0]
            ey = x[b, 1] - x[a, 1]
            ez = x[b, 2] - x[a, 2]
            trib_total += np.sqrt(ex * ex + ey * ey + ez * ez)
        if trib_total <= 0.0:
            continue
        for j in range(e0, e1):
            a = cl_edges[j, 0]
            b = cl_edges[j, 1]
            ex = x[b, 0] - x[a, 0]
            ey = x[b, 1] - x[a, 1]
            ez = x[b, 2] - x[a, 2]
            share = 0.5 * np.sqrt(ex * ex + ey * ey + ez * ez) / trib_total
            for node in (a, b):
                r[node, 0] += share * tx
                r[node, 1] += share * ty
                r[node, 2] += share * tz
                ext[node, 0] += share * tx
                ext[node, 1] += share * ty
                ext[node, 2] += share * tz


def _project_into(r: Any, constrained: Any, proj: Any, out: Any) -> None:  # pragma: no cover
    """``out`` = ``r`` with the constrained components removed."""
    for i in range(r.shape[0]):
        for k in range(3):
            out[i, k] = r[i, k]
    for j in range(constrained.shape[0]):
        node = constrained[j]
        r0, r1, r2 = r[node, 0], r[node, 1], r[node, 2]
        for k in range(3):
            out[node, k] = proj[j, k, 0] * r0 + proj[j, k, 1] * r1 + proj[j, k, 2] * r2


def _masses_into(  # pragma: no cover - compiled by numba; _System.masses is the reference
    tri: Any,
    grad: Any,
    area: Any,
    c: Any,
    f: Any,
    stress: Any,
    xe: Any,
    p: Any,
    x: Any,
    cable_edges: Any,
    cable_l0: Any,
    cable_ea: Any,
    mass_factor: float,
    mass: Any,
) -> None:
    """Gershgorin fictitious masses at the current state, as ``_System.masses``: CST
    material and geometric row sums
    (:func:`~envelopelab.solvers.membrane.element_stiffness_rowsum`), the pressure term
    ``max|p| * perimeter / 6``, and the tapes' ``2 sqrt(3) (EA/L0 + T/L)``."""
    n = mass.shape[0]
    m = tri.shape[0]
    for i in range(n):
        mass[i] = 0.0
    b = np.empty((3, 3, 3))  # corner, voigt, xyz
    gn = np.empty(3)
    for t in range(m):
        for a in range(3):
            g0 = grad[t, a, 0]
            g1 = grad[t, a, 1]
            gn[a] = np.sqrt(g0 * g0 + g1 * g1)
            for i in range(3):
                b[a, 0, i] = g0 * f[t, i, 0]
                b[a, 1, i] = g1 * f[t, i, 1]
                b[a, 2, i] = g1 * f[t, i, 0] + g0 * f[t, i, 1]
        s00 = stress[t, 0, 0]
        s11 = stress[t, 1, 1]
        s01 = stress[t, 0, 1]
        mean = 0.5 * (s00 + s11)
        rad = np.sqrt((0.5 * (s00 - s11)) ** 2 + s01 * s01)
        s_abs = max(abs(mean + rad), abs(mean - rad))
        gsum = gn[0] + gn[1] + gn[2]
        perimeter = 0.0
        p_max = 0.0
        for a in range(3):
            q = (a + 1) % 3
            dx = xe[t, q, 0] - xe[t, a, 0]
            dy = xe[t, q, 1] - xe[t, a, 1]
            dz = xe[t, q, 2] - xe[t, a, 2]
            perimeter += np.sqrt(dx * dx + dy * dy + dz * dz)
            if abs(p[t, a]) > p_max:
                p_max = abs(p[t, a])
        pressure_term = p_max * perimeter / 6.0
        for a in range(3):
            best = 0.0
            for i in range(3):
                row = 0.0
                for bb in range(3):
                    for j in range(3):
                        kij = 0.0
                        for v in range(3):
                            cbv = 0.0
                            for w in range(3):
                                cbv += c[t, v, w] * b[bb, w, j]
                            kij += b[a, v, i] * cbv
                        row += abs(kij)
                if row > best:
                    best = row
            mass[tri[t, a]] += area[t] * (best + gn[a] * gsum * s_abs) + pressure_term
    for e in range(cable_edges.shape[0]):
        a = cable_edges[e, 0]
        bnode = cable_edges[e, 1]
        dx = x[bnode, 0] - x[a, 0]
        dy = x[bnode, 1] - x[a, 1]
        dz = x[bnode, 2] - x[a, 2]
        length = np.sqrt(dx * dx + dy * dy + dz * dz)
        strain_c = length / cable_l0[e] - 1.0
        tension = cable_ea[e] * strain_c if strain_c > 0.0 else 0.0
        kc = 2.0 * np.sqrt(3.0) * (cable_ea[e] / cable_l0[e] + tension / length)
        mass[a] += kc
        mass[bnode] += kc
    k_max = 0.0
    for i in range(n):
        if mass[i] > k_max:
            k_max = mass[i]
    floor = 1e-9 * k_max if k_max > 0.0 else 1.0
    for i in range(n):
        mass[i] = mass_factor * 0.5 * (mass[i] if mass[i] > floor else floor)


def _relax_loop(  # pragma: no cover - compiled by numba; the Python loop is the reference
    x: Any,
    v: Any,
    v_prev: Any,
    r_free: Any,
    mass: Any,
    scalars: Any,
    first: int,
    last: int,
    report_every: int,
    tolerance: float,
    kinetic: bool,
    viscous: float,
    tri: Any,
    grad: Any,
    area: Any,
    c: Any,
    ci: Any,
    kappa: float,
    enabled: bool,
    tri_gas: Any,
    gas: Any,
    fixed: Any,
    cable_edges: Any,
    cable_l0: Any,
    cable_ea: Any,
    cl_edges: Any,
    cl_edge_ptr: Any,
    cl_nodes: Any,
    cl_node_ptr: Any,
    cl_gas: Any,
    constrained: Any,
    proj: Any,
    mass_factor: float,
) -> tuple[int, int]:
    """Iterations ``first``..``last`` of ``solve`` (same order of operations).

    ``scalars`` holds ``[ke_prev, fresh, ke, residual, resets]``; it, ``x``, ``v``,
    ``v_prev``, ``r_free`` and ``mass`` are updated in place. Returns ``(code, iteration)``:
    a progress report is due, the solve converged or diverged, or ``last`` was reached.
    """
    n = x.shape[0]
    m = tri.shape[0]
    p = np.empty((m, 3))
    xe = np.empty((m, 3, 3))
    f = np.empty((m, 3, 2))
    strain = np.empty((m, 2, 2))
    stress = np.empty((m, 2, 2))
    state = np.empty(m, dtype=np.int8)
    minor = np.empty(m)
    f_int = np.empty((m, 3, 3))
    f_p = np.empty((m, 3, 3))
    r = np.empty((n, 3))
    ext = np.empty((n, 3))
    ke_prev = scalars[0]
    fresh = scalars[1] > 0.5
    ke = scalars[2]
    residual = scalars[3]
    for it in range(first, last + 1):
        ke = 0.0
        for i in range(n):
            for k in range(3):
                accel = r_free[i, k] / mass[i]
                if kinetic:
                    v[i, k] = 0.5 * accel if fresh else v[i, k] + accel
                else:
                    v[i, k] = ((1.0 - 0.5 * viscous) * v[i, k] + accel) / (1.0 + 0.5 * viscous)
                ke += mass[i] * v[i, k] * v[i, k]
        ke *= 0.5
        fresh = False
        reset = kinetic and ke < ke_prev
        if reset:
            # Back to the kinetic-energy peak, at rest, with masses for that state.
            for i in range(n):
                for k in range(3):
                    x[i, k] -= 0.5 * v_prev[i, k]
                    v[i, k] = 0.0
                    v_prev[i, k] = 0.0
            ke_prev = 0.0
            fresh = True
            scalars[4] += 1.0
        else:
            for i in range(n):
                for k in range(3):
                    x[i, k] += v[i, k]
                    v_prev[i, k] = v[i, k]
            ke_prev = ke
        _forces_into(
            x,
            tri,
            grad,
            area,
            c,
            ci,
            kappa,
            enabled,
            tri_gas,
            gas,
            fixed,
            cable_edges,
            cable_l0,
            cable_ea,
            cl_edges,
            cl_edge_ptr,
            cl_nodes,
            cl_node_ptr,
            cl_gas,
            p,
            xe,
            f,
            strain,
            stress,
            state,
            minor,
            f_int,
            f_p,
            r,
            ext,
        )
        if reset:
            _masses_into(
                tri,
                grad,
                area,
                c,
                f,
                stress,
                xe,
                p,
                x,
                cable_edges,
                cable_l0,
                cable_ea,
                mass_factor,
                mass,
            )
        _project_into(r, constrained, proj, r_free)
        norm_r = 0.0
        norm_e = 0.0
        for i in range(n):
            for k in range(3):
                norm_r += r_free[i, k] * r_free[i, k]
                norm_e += ext[i, k] * ext[i, k]
        norm_r = np.sqrt(norm_r)
        norm_e = np.sqrt(norm_e)
        residual = norm_r / norm_e if norm_e > 0.0 else norm_r
        scalars[0] = ke_prev
        scalars[1] = 1.0 if fresh else 0.0
        scalars[2] = ke
        scalars[3] = residual
        if not np.isfinite(residual) or residual > 1e8:
            return RELAX_DIVERGED, it
        if residual < tolerance:
            return RELAX_CONVERGED, it
        if it % report_every == 0:
            return RELAX_REPORT, it
    return RELAX_LIMIT, last


_compiled_relax: Any = None
_element_loop_nb: Any = None


def relax_kernel() -> Any:
    """The compiled iteration loop (:func:`_relax_loop`), compiled on first use."""
    global _compiled_relax, _element_loop_nb
    if _compiled_relax is None:
        assert numba is not None
        jit = numba.njit(cache=True, nogil=True)
        _element_loop_nb = _kernel()
        globals()["_gas_pressure"] = jit(_gas_pressure)
        globals()["_forces_into"] = jit(_forces_into)
        globals()["_project_into"] = jit(_project_into)
        globals()["_masses_into"] = jit(_masses_into)
        _compiled_relax = jit(_relax_loop)
    return _compiled_relax


def compiled_forces_and_masses(
    x: FloatArray,
    tri: IntArray,
    rest: RestGeometry,
    stiffness: FloatArray,
    compliance: FloatArray,
    slack_stiffness_ratio: float,
    enabled: bool,
    inputs: dict[str, Any],
    mass_factor: float,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Residual and external force (N, (n, 3)) and fictitious masses ((n,)) at ``x`` with
    the compiled functions of the iteration loop (for comparison with the reference
    ``_System.forces`` and ``_System.masses``; ``inputs`` from ``_System.compiled_inputs``).
    """
    relax_kernel()
    n, m = len(x), len(tri)
    p = np.empty((m, 3))
    xe = np.empty((m, 3, 3))
    f = np.empty((m, 3, 2))
    strain = np.empty((m, 2, 2))
    stress = np.empty((m, 2, 2))
    state = np.empty(m, dtype=np.int8)
    minor = np.empty(m)
    f_int = np.empty((m, 3, 3))
    f_p = np.empty((m, 3, 3))
    r = np.empty((n, 3))
    ext = np.empty((n, 3))
    mass = np.empty(n)
    xc = np.ascontiguousarray(x, dtype=np.float64)
    _forces_into(
        xc,
        tri,
        rest.grad_n,
        rest.area,
        stiffness,
        compliance,
        float(slack_stiffness_ratio),
        bool(enabled),
        inputs["tri_gas"],
        inputs["gas"],
        inputs["fixed"],
        inputs["cable_edges"],
        inputs["cable_l0"],
        inputs["cable_ea"],
        inputs["cl_edges"],
        inputs["cl_edge_ptr"],
        inputs["cl_nodes"],
        inputs["cl_node_ptr"],
        inputs["cl_gas"],
        p,
        xe,
        f,
        strain,
        stress,
        state,
        minor,
        f_int,
        f_p,
        r,
        ext,
    )
    _masses_into(
        tri,
        rest.grad_n,
        rest.area,
        stiffness,
        f,
        stress,
        xe,
        p,
        xc,
        inputs["cable_edges"],
        inputs["cable_l0"],
        inputs["cable_ea"],
        float(mass_factor),
        mass,
    )
    return r, ext, mass
