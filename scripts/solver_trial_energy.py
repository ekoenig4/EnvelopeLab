r"""Total-potential-energy model of a solver model, for the solver trial (not the app).

Hot-air pressure is conservative, so the inflated shape is a stationary point (a minimum
for a stable envelope) of

.. math::
    \Pi(x) = \sum_T A_0 \bigl[(1-\kappa) W^\ast(E) + \kappa W(E)\bigr]
           + \sum_{tapes} \tfrac12 EA\, L_0 \langle \varepsilon \rangle_+^2
           - \int_V p\, dV - f_{dead} \cdot x,

with :math:`W = \tfrac12 e^\mathsf{T} \mathbb{C} e` (St. Venant-Kirchhoff, Voigt strain
:math:`e`), and :math:`W^\ast` Pipkin's relaxed energy

.. math:: W^\ast(E) = \min_{w \ge 0,\ \theta} W(E + w\, m_\theta \otimes m_\theta)

(:math:`W^\ast = 0` where the largest principal strain is not positive). Its gradient
:math:`S = \mathbb{C}(e + w^\ast v^\ast)` is the uniaxial tension-field stress along the
optimal direction. For isotropic fabric this equals the app's mixed-criterion law; for
orthotropic fabric the app takes the wrinkle direction from the trial stress instead of
the energy minimiser, so the two laws differ slightly (the trial measures by how much).

The pressure is the linear field :math:`p = p_0 + \gamma (z - z_m)` (unclamped), and
:math:`\int_V p\,dV` is evaluated exactly with the divergence theorem over the envelope
triangles and fan caps over the closures. Its exact gradient is the consistent load
:math:`a_T (2p_i + p_j + p_k)/12` the app uses, except at a closure: the fan cap's centre
is the mean of its ring nodes, so the centre's share is split equally between them
(the app distributes the cap's resultant by tributary ring length).

Supported: one gas (the main envelope), closures, tapes, weight, dead loads, fixed
nodes and symmetry planes (through the free-direction basis). Chambers are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp

from envelopelab.solvers.dynamic_relaxation import _System
from envelopelab.solvers.membrane import deformation_gradient, green_strain, internal_forces
from envelopelab.solvers.model import MAIN_CHAMBER, SolverModel, SolverSettings

GRID = 24  # wrinkle directions sampled before refining
GOLDEN_STEPS = 40


@dataclass
class EnergyTerms:
    """Energy (J) and gradient (N, shape (n, 3)) with the membrane state counts."""

    energy: float
    gradient: np.ndarray
    wrinkled: int
    slack: int


def _voigt_dir(theta: np.ndarray) -> np.ndarray:
    """Voigt (engineering shear) vector of m (x) m for angle(s) theta."""
    c, s = np.cos(theta), np.sin(theta)
    return np.stack([c * c, s * s, 2.0 * c * s], axis=-1)


def relaxed_stress(e: np.ndarray, c_mat: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Relaxed energy density W* (J/m^2), its stress S* (Voigt, N/m) and state per row.

    ``e`` is the Voigt Green strain (m, 3), ``c_mat`` the plane-stress matrix (m, 3, 3).
    State: 0 taut, 1 wrinkled, 2 slack.
    """
    s_trial = np.einsum("mij,mj->mi", c_mat, e)
    w_full = 0.5 * np.einsum("mi,mi->m", e, s_trial)

    # Principal values of the trial stress and of the strain (2x2 symmetric).
    def minor_major(a11: np.ndarray, a22: np.ndarray, a12: np.ndarray) -> tuple[np.ndarray, ...]:
        mean = 0.5 * (a11 + a22)
        rad = np.sqrt((0.5 * (a11 - a22)) ** 2 + a12**2)
        return mean - rad, mean + rad

    s_min, _ = minor_major(s_trial[:, 0], s_trial[:, 1], s_trial[:, 2])
    _, e_max = minor_major(e[:, 0], e[:, 1], 0.5 * e[:, 2])
    state = np.zeros(len(e), dtype=np.int8)
    slack = e_max <= 0.0
    wrinkled = (s_min <= 0.0) & ~slack
    state[wrinkled] = 1
    state[slack] = 2
    stress = s_trial.copy()
    energy = w_full.copy()
    stress[slack] = 0.0
    energy[slack] = 0.0
    idx = np.flatnonzero(wrinkled)
    if len(idx):
        ew, sw, cw = e[idx], s_trial[idx], c_mat[idx]

        def gain(theta: np.ndarray) -> np.ndarray:
            v = _voigt_dir(theta)
            q = np.einsum("...i,...i->...", v, sw if theta.ndim == 1 else sw[:, None, :])
            cv = np.einsum("...ij,...j->...i", cw if theta.ndim == 1 else cw[:, None], v)
            k = np.einsum("...i,...i->...", v, cv)
            return np.where(q < 0.0, q * q / k, -1.0)

        grid = np.linspace(0.0, np.pi, GRID, endpoint=False)
        g = gain(np.broadcast_to(grid, (len(idx), GRID)))
        best = grid[np.argmax(g, axis=1)]
        lo, hi = best - np.pi / GRID, best + np.pi / GRID
        ratio = 0.5 * (np.sqrt(5.0) - 1.0)
        a = hi - ratio * (hi - lo)
        b = lo + ratio * (hi - lo)
        ga, gb = gain(a), gain(b)
        for _ in range(GOLDEN_STEPS):
            left = ga > gb
            hi = np.where(left, b, hi)
            lo = np.where(left, lo, a)
            new_a = hi - ratio * (hi - lo)
            new_b = lo + ratio * (hi - lo)
            a, b = np.where(left, new_a, b), np.where(left, a, new_b)
            ga, gb = np.where(left, gain(new_a), gb), np.where(left, ga, gain(new_b))
        theta = 0.5 * (lo + hi)
        v = _voigt_dir(theta)
        q = np.einsum("mi,mi->m", v, sw)
        cv = np.einsum("mij,mj->mi", cw, v)
        k = np.einsum("mi,mi->m", v, cv)
        w = np.maximum(-q / k, 0.0)
        e_el = ew + w[:, None] * v
        s_el = np.einsum("mij,mj->mi", cw, e_el)
        stress[idx] = s_el
        energy[idx] = 0.5 * np.einsum("mi,mi->m", e_el, s_el)
    return energy, stress, state


try:
    from numba import njit
except ImportError:  # pragma: no cover - the trial falls back to NumPy
    njit = None


def _relaxed_scalar(e: np.ndarray, c_mat: np.ndarray, out_w, out_s, out_state) -> None:  # noqa: ANN001
    """Per-triangle relaxed law (compiled when Numba is installed); same steps as
    :func:`relaxed_stress`."""
    ratio = 0.5 * (np.sqrt(5.0) - 1.0)
    for t in range(e.shape[0]):
        e0, e1, e2 = e[t, 0], e[t, 1], e[t, 2]
        c = c_mat[t]
        s0 = c[0, 0] * e0 + c[0, 1] * e1 + c[0, 2] * e2
        s1 = c[1, 0] * e0 + c[1, 1] * e1 + c[1, 2] * e2
        s2 = c[2, 0] * e0 + c[2, 1] * e1 + c[2, 2] * e2
        mean = 0.5 * (s0 + s1)
        s_min = mean - np.sqrt((0.5 * (s0 - s1)) ** 2 + s2 * s2)
        e_max = 0.5 * (e0 + e1) + np.sqrt((0.5 * (e0 - e1)) ** 2 + (0.5 * e2) ** 2)
        if e_max <= 0.0:
            out_state[t] = 2
            out_w[t] = 0.0
            out_s[t, 0] = out_s[t, 1] = out_s[t, 2] = 0.0
            continue
        if s_min > 0.0:
            out_state[t] = 0
            out_w[t] = 0.5 * (e0 * s0 + e1 * s1 + e2 * s2)
            out_s[t, 0], out_s[t, 1], out_s[t, 2] = s0, s1, s2
            continue
        out_state[t] = 1
        best_g = -1.0
        best_th = 0.0
        for k in range(GRID):
            th = np.pi * k / GRID
            cc, ss = np.cos(th), np.sin(th)
            v0, v1, v2 = cc * cc, ss * ss, 2.0 * cc * ss
            q = v0 * s0 + v1 * s1 + v2 * s2
            kk = (
                v0 * (c[0, 0] * v0 + c[0, 1] * v1 + c[0, 2] * v2)
                + v1 * (c[1, 0] * v0 + c[1, 1] * v1 + c[1, 2] * v2)
                + v2 * (c[2, 0] * v0 + c[2, 1] * v1 + c[2, 2] * v2)
            )
            g = q * q / kk if q < 0.0 else -1.0
            if g > best_g:
                best_g, best_th = g, th
        lo = best_th - np.pi / GRID
        hi = best_th + np.pi / GRID
        a = hi - ratio * (hi - lo)
        b = lo + ratio * (hi - lo)
        ga = 0.0
        gb = 0.0
        for side in range(2):
            th = a if side == 0 else b
            cc, ss = np.cos(th), np.sin(th)
            v0, v1, v2 = cc * cc, ss * ss, 2.0 * cc * ss
            q = v0 * s0 + v1 * s1 + v2 * s2
            kk = (
                v0 * (c[0, 0] * v0 + c[0, 1] * v1 + c[0, 2] * v2)
                + v1 * (c[1, 0] * v0 + c[1, 1] * v1 + c[1, 2] * v2)
                + v2 * (c[2, 0] * v0 + c[2, 1] * v1 + c[2, 2] * v2)
            )
            g = q * q / kk if q < 0.0 else -1.0
            if side == 0:
                ga = g
            else:
                gb = g
        for _ in range(GOLDEN_STEPS):
            if ga > gb:
                hi = b
                b, gb = a, ga
                a = hi - ratio * (hi - lo)
                th = a
            else:
                lo = a
                a, ga = b, gb
                b = lo + ratio * (hi - lo)
                th = b
            cc, ss = np.cos(th), np.sin(th)
            v0, v1, v2 = cc * cc, ss * ss, 2.0 * cc * ss
            q = v0 * s0 + v1 * s1 + v2 * s2
            kk = (
                v0 * (c[0, 0] * v0 + c[0, 1] * v1 + c[0, 2] * v2)
                + v1 * (c[1, 0] * v0 + c[1, 1] * v1 + c[1, 2] * v2)
                + v2 * (c[2, 0] * v0 + c[2, 1] * v1 + c[2, 2] * v2)
            )
            g = q * q / kk if q < 0.0 else -1.0
            if th == a:
                ga = g
            else:
                gb = g
        th = 0.5 * (lo + hi)
        cc, ss = np.cos(th), np.sin(th)
        v0, v1, v2 = cc * cc, ss * ss, 2.0 * cc * ss
        q = v0 * s0 + v1 * s1 + v2 * s2
        kk = (
            v0 * (c[0, 0] * v0 + c[0, 1] * v1 + c[0, 2] * v2)
            + v1 * (c[1, 0] * v0 + c[1, 1] * v1 + c[1, 2] * v2)
            + v2 * (c[2, 0] * v0 + c[2, 1] * v1 + c[2, 2] * v2)
        )
        w = -q / kk
        if w < 0.0:
            w = 0.0
        f0, f1, f2 = e0 + w * v0, e1 + w * v1, e2 + w * v2
        r0 = c[0, 0] * f0 + c[0, 1] * f1 + c[0, 2] * f2
        r1 = c[1, 0] * f0 + c[1, 1] * f1 + c[1, 2] * f2
        r2 = c[2, 0] * f0 + c[2, 1] * f1 + c[2, 2] * f2
        out_s[t, 0], out_s[t, 1], out_s[t, 2] = r0, r1, r2
        out_w[t] = 0.5 * (f0 * r0 + f1 * r1 + f2 * r2)


_relaxed_compiled = njit(cache=True)(_relaxed_scalar) if njit is not None else None


def relaxed_stress_fast(
    e: np.ndarray, c_mat: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """:func:`relaxed_stress` through the compiled per-triangle loop (NumPy without Numba)."""
    if _relaxed_compiled is None:
        return relaxed_stress(e, c_mat)
    m = len(e)
    w = np.empty(m)
    s = np.empty((m, 3))
    state = np.empty(m, dtype=np.int8)
    _relaxed_compiled(np.ascontiguousarray(e), np.ascontiguousarray(c_mat), w, s, state)
    return w, s, state


class EnergyModel:
    """Total potential energy and its exact gradient for a :class:`SolverModel`."""

    def __init__(self, model: SolverModel, settings: SolverSettings | None = None) -> None:
        if model.chambers:
            raise ValueError("the energy trial supports the main envelope gas only")
        self.settings = settings or SolverSettings()
        self.system = _System(model, self.settings)
        sysm = self.system
        self.model = model
        self.kappa = self.settings.slack_stiffness_ratio
        cond = model.conditions
        self.gamma = cond.pressure_gradient
        self.p_ref = cond.uniform_pressure - self.gamma * cond.mouth_height
        self.fixed_force = sysm.weight_nodes + sysm.dead
        self.closures = [
            (edges, nodes, code)
            for (_, edges), nodes, code in zip(
                sysm.closures, sysm.closure_nodes, sysm.closure_codes, strict=True
            )
        ]
        for _, _, code in self.closures:
            if code != MAIN_CHAMBER:
                raise ValueError("closures must hold the main envelope gas")

    def pressure(self, z: np.ndarray) -> np.ndarray:
        """Linear differential pressure field, Pa."""
        return self.p_ref + self.gamma * z

    def _pressure_terms(self, xe: np.ndarray) -> tuple[float, np.ndarray]:
        """\\int p dV contribution (J) and corner forces (N) of triangles ``xe`` (k, 3, 3)."""
        a_t = 0.5 * np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0])
        z = xe[:, :, 2]
        centroid = xe.mean(axis=1)
        vol = np.einsum("ki,ki->k", centroid, a_t) / 3.0
        zz = (z * z).sum(axis=1) + z[:, 0] * z[:, 1] + z[:, 1] * z[:, 2] + z[:, 2] * z[:, 0]
        z_moment = a_t[:, 2] * zz / 12.0
        integral = float((self.p_ref * vol + self.gamma * z_moment).sum())
        p = self.pressure(z)
        weights = (p + p.sum(axis=1, keepdims=True)) / 12.0
        return integral, weights[:, :, None] * a_t[:, None, :]

    def evaluate(self, x: np.ndarray) -> EnergyTerms:
        """Energy and gradient at positions ``x`` (n, 3), m."""
        sysm = self.system
        n = sysm.n
        tri = sysm.tri
        xe = x[tri]
        f = deformation_gradient(xe, sysm.rest.grad_n)
        strain = green_strain(f)
        e = np.stack([strain[:, 0, 0], strain[:, 1, 1], 2.0 * strain[:, 0, 1]], axis=1)
        w_star, s_star, state = relaxed_stress_fast(e, sysm.c)
        s_trial = np.einsum("mij,mj->mi", sysm.c, e)
        w_full = 0.5 * np.einsum("mi,mi->m", e, s_trial)
        k = self.kappa
        density = (1.0 - k) * w_star + k * w_full
        s_eff = (1.0 - k) * s_star + k * s_trial
        energy = float((density * sysm.rest.area).sum())
        stress = np.empty((len(tri), 2, 2))
        stress[:, 0, 0] = s_eff[:, 0]
        stress[:, 1, 1] = s_eff[:, 1]
        stress[:, 0, 1] = stress[:, 1, 0] = s_eff[:, 2]
        corner = internal_forces(f, stress, sysm.rest)
        integral, f_p = self._pressure_terms(xe)
        corner = corner - f_p
        grad = np.zeros((n, 3))
        for d in range(3):
            grad[:, d] = np.bincount(tri.ravel(), corner[:, :, d].ravel(), minlength=n)
        # Fan caps over the closures (outward = along the cap's area normals).
        for edges, nodes, _ in self.closures:
            centre = x[nodes].mean(axis=0)
            fan = np.stack(
                [x[edges[:, 1]], x[edges[:, 0]], np.broadcast_to(centre, (len(edges), 3))],
                axis=1,
            )
            cap_int, cap_f = self._pressure_terms(fan)
            integral += cap_int
            for d in range(3):
                grad[:, d] -= np.bincount(edges[:, 1], cap_f[:, 0, d], minlength=n)
                grad[:, d] -= np.bincount(edges[:, 0], cap_f[:, 1, d], minlength=n)
            grad[nodes] -= cap_f[:, 2].sum(axis=0) / len(nodes)
        # Tapes: tension only.
        if len(sysm.cable_edges):
            ce = sysm.cable_edges
            d_vec = x[ce[:, 1]] - x[ce[:, 0]]
            length = np.linalg.norm(d_vec, axis=1)
            eps = np.maximum(length / sysm.cable_l0 - 1.0, 0.0)
            energy += float((0.5 * sysm.cable_ea * sysm.cable_l0 * eps * eps).sum())
            pull = (sysm.cable_ea * eps / np.maximum(length, 1e-300))[:, None] * d_vec
            for d in range(3):
                grad[:, d] += np.bincount(ce[:, 1], pull[:, d], minlength=n)
                grad[:, d] -= np.bincount(ce[:, 0], pull[:, d], minlength=n)
        energy -= integral
        energy -= float((self.fixed_force * x).sum())
        grad -= self.fixed_force
        return EnergyTerms(energy, grad, int((state == 1).sum()), int((state == 2).sum()))

    def external_scale(self, x: np.ndarray) -> float:
        """||F_ext|| of the app's model at ``x`` (normalises the relative residual), N."""
        _, ext, _ = self.system.forces(x)
        return float(np.linalg.norm(ext))


def free_basis(system: _System) -> sp.csr_matrix:
    """Sparse basis (3n x f) of the free directions of every node."""
    n = system.n
    proj = np.broadcast_to(np.eye(3), (n, 3, 3)).copy()
    if len(system.constrained):
        proj[system.constrained] = system.proj
    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    col = 0
    constrained = set(system.constrained.tolist())
    for i in range(n):
        if i not in constrained:
            rows += [3 * i, 3 * i + 1, 3 * i + 2]
            cols += [col, col + 1, col + 2]
            vals += [1.0, 1.0, 1.0]
            col += 3
            continue
        w, vec = np.linalg.eigh(proj[i])
        for j in range(3):
            if w[j] > 0.5:
                rows += [3 * i, 3 * i + 1, 3 * i + 2]
                cols += [col] * 3
                vals += vec[:, j].tolist()
                col += 1
    return sp.csr_matrix((vals, (rows, cols)), shape=(3 * n, col))
