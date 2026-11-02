"""Unit tests: membrane materials and the CST tension-field element."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from envelopelab.materials.membrane import MaterialValue, MembraneMaterial, TapeMaterial
from envelopelab.solvers.membrane import (
    SLACK,
    TAUT,
    WRINKLED,
    FloatArray,
    RestGeometry,
    deformation_gradient,
    element_stiffness_rowsum,
    green_strain,
    internal_forces,
    rest_geometry,
    tension_field,
    wrinkle_direction,
)

TRI_UV = np.array([[[0.0, 0.0], [1.0, 0.0], [0.2, 0.9]]])
X_AXIS = np.array([[1.0, 0.0]])


def _material(e1: float = 1.0e5, e2: float = 0.8e5, g: float = 5.0e3) -> MembraneMaterial:
    v = MaterialValue
    return MembraneMaterial(
        "test",
        v(e1, "N/m", "assumed"),
        v(e2, "N/m", "assumed"),
        v(g, "N/m", "assumed"),
        v(0.3, "-", "assumed"),
        v(0.06, "kg/m^2", "assumed"),
        v(1.5e4, "N/m", "assumed"),
        v(1.4e4, "N/m", "assumed"),
        v(0.8, "-", "assumed"),
        v(393.0, "K", "assumed"),
    )


def _stress(strain: FloatArray, mat: MembraneMaterial, kappa: float = 1e-3) -> tuple[Any, ...]:
    c = np.asarray(mat.plane_stress_matrix()[None].repeat(len(strain), 0), dtype=np.float64)
    inv = np.asarray(np.linalg.inv(c), dtype=np.float64)
    return tension_field(strain, c, inv, kappa, True)


def _inv(c: FloatArray) -> FloatArray:
    return np.asarray(np.linalg.inv(c), dtype=np.float64)


def _strain(e11: float, e22: float, e12: float) -> FloatArray:
    return np.array([[[e11, e12], [e12, e22]]])


def test_material_value_requires_a_source_tag() -> None:
    with pytest.raises(ValueError, match="source"):
        MaterialValue(1.0, "N/m", "guess")  # type: ignore[arg-type]


def test_isotropic_material_matrix() -> None:
    mat = MembraneMaterial.isotropic("iso", 1.0e5, 0.25)
    c = mat.plane_stress_matrix()
    assert c[0, 0] == pytest.approx(1.0e5 / (1 - 0.25**2))
    assert c[0, 1] == pytest.approx(0.25 * c[0, 0])
    assert c[2, 2] == pytest.approx(1.0e5 / 2.5)
    assert all(v["source"] == "assumed" for v in mat.sources().values())


def test_orthotropic_matrix_is_symmetric_and_checks_positive_definiteness() -> None:
    c = _material().plane_stress_matrix()
    assert np.allclose(c, c.T)
    assert np.all(np.linalg.eigvalsh(c) > 0)
    with pytest.raises(ValueError, match="positive-definite"):
        _material(e1=1.0e4, e2=1.0e6)


def test_tape_material_validation() -> None:
    with pytest.raises(ValueError):
        TapeMaterial("t", MaterialValue(0.0, "N", "assumed"), MaterialValue(1.0, "N", "assumed"))


def test_rest_geometry_gradients_and_area() -> None:
    rest = rest_geometry(TRI_UV, X_AXIS)
    assert rest.area[0] == pytest.approx(0.45)
    assert np.allclose(rest.grad_n.sum(axis=1), 0.0)
    # A rigid rotation plus translation gives F^T F = I (zero strain).
    angle = 0.7
    rot = np.array([[np.cos(angle), -np.sin(angle), 0.0], [np.sin(angle), np.cos(angle), 0.0]])
    xe = (TRI_UV[0] @ rot + np.array([1.0, 2.0, 3.0]))[None]
    assert np.allclose(green_strain(deformation_gradient(xe, rest.grad_n)), 0.0, atol=1e-14)


def test_rest_geometry_rejects_clockwise_triangles() -> None:
    with pytest.raises(ValueError, match="clockwise"):
        rest_geometry(TRI_UV[:, ::-1], X_AXIS)


def test_strain_is_expressed_in_grain_axes() -> None:
    xe = np.concatenate([TRI_UV[0] * [1.01, 1.0], np.zeros((3, 1))], axis=1)[None]
    along = green_strain(deformation_gradient(xe, rest_geometry(TRI_UV, X_AXIS).grad_n))
    across = green_strain(
        deformation_gradient(xe, rest_geometry(TRI_UV, np.array([[0.0, 1.0]])).grad_n)
    )
    assert along[0, 0, 0] == pytest.approx(0.01005, rel=1e-9)
    assert across[0, 1, 1] == pytest.approx(0.01005, rel=1e-9)
    assert across[0, 0, 0] == pytest.approx(0.0, abs=1e-14)


def test_tension_field_states() -> None:
    mat = _material()
    _, state, _ = _stress(_strain(0.01, 0.01, 0.0), mat)
    assert state[0] == TAUT
    _, state, _ = _stress(_strain(-0.01, -0.02, 0.0), mat)
    assert state[0] == SLACK
    stress, state, minor = _stress(_strain(0.0, 0.0, 0.005), mat)
    assert state[0] == WRINKLED
    assert minor[0] < 0.0
    principal = np.linalg.eigvalsh(stress[0])
    assert principal[0] >= -1e-3 * principal[1]


def test_tension_field_is_continuous_where_poisson_makes_both_trial_stresses_negative() -> None:
    # Stretched along x (eps_n > 0) but compressed hard along y: both trial principal
    # stresses are negative. The fabric is still stretched along x and must carry tension;
    # an earlier slack test on s1 <= 0 dropped the stress to zero here (solver chatter).
    mat = MembraneMaterial.isotropic("iso", 1.0e5, 0.4)
    stress, state, _ = _stress(_strain(0.001, -0.01, 0.0), mat)
    assert state[0] == WRINKLED
    assert stress[0, 0, 0] == pytest.approx(1.0e5 * 0.001, rel=2e-2)


def test_tension_field_stress_is_continuous_at_the_taut_boundary() -> None:
    mat = _material()
    c = mat.plane_stress_matrix()
    # Uniaxial stress along x: strain C^-1 (N, 0, 0) sits exactly on the boundary s2 = 0.
    e = np.linalg.solve(c, np.array([100.0, 0.0, 0.0]))
    below = _strain(e[0], e[1] - 1e-9, 0.0)
    above = _strain(e[0], e[1] + 1e-9, 0.0)
    s_below, st_below, _ = _stress(below, mat)
    s_above, st_above, _ = _stress(above, mat)
    assert {int(st_below[0]), int(st_above[0])} == {TAUT, WRINKLED}
    assert np.allclose(s_below, s_above, atol=1e-2)


def test_disabled_tension_field_carries_compression() -> None:
    mat = _material()
    c = mat.plane_stress_matrix()[None]
    stress, state, _ = tension_field(_strain(-0.01, 0.0, 0.0), c, _inv(c), 1e-3, False)
    assert state[0] == TAUT
    assert stress[0, 0, 0] < 0.0


def _relaxed_energy(e: FloatArray, c: FloatArray) -> FloatArray:
    """Relaxed energy density (kappa = 0): W taut, max_n E_n eps_n^2 / 2 wrinkled (by a
    fine scan), 0 slack; ``e`` Voigt (engineering shear), shape (k, 3)."""
    s = e @ c.T
    s_min = 0.5 * (s[:, 0] + s[:, 1]) - np.hypot(0.5 * (s[:, 0] - s[:, 1]), s[:, 2])
    theta = np.linspace(0.0, np.pi, 200_001)[:-1]
    w = np.stack([np.cos(theta) ** 2, np.sin(theta) ** 2, np.cos(theta) * np.sin(theta)], 1)
    e_n = 1.0 / np.einsum("ti,ij,tj->t", w, np.linalg.inv(c), w)
    eps = e @ w.T
    uni = 0.5 * (e_n[None] * np.where(eps > 0.0, eps, 0.0) ** 2).max(axis=1)
    return np.where(s_min > 0.0, 0.5 * np.einsum("ki,ki->k", e, s), uni)


def _batch(e: FloatArray) -> FloatArray:
    out = np.zeros((len(e), 2, 2))
    out[:, 0, 0], out[:, 1, 1] = e[:, 0], e[:, 1]
    out[:, 0, 1] = out[:, 1, 0] = 0.5 * e[:, 2]
    return out


def test_wrinkled_stress_is_the_gradient_of_the_relaxed_energy() -> None:
    """Orthotropic fabric with a soft shear: the wrinkled stress is dW*/dE (Pipkin), which
    the trial-stress wrinkle direction is not; that mismatch kept the solver cycling."""
    c = _material(1.08e5, 0.86e5, 5.0e3).plane_stress_matrix()
    rng = np.random.default_rng(7)
    e = 0.01 * rng.normal(size=(300, 3))
    k = len(e)
    stress, state, _ = tension_field(_batch(e), np.broadcast_to(c, (k, 3, 3)).copy(),
                                     np.broadcast_to(_inv(c), (k, 3, 3)).copy(), 0.0)  # fmt: skip
    wr = state == WRINKLED
    assert wr.sum() > 50
    s = np.stack([stress[:, 0, 0], stress[:, 1, 1], stress[:, 0, 1]], axis=1)[wr]
    h = 1e-7
    numeric = np.zeros_like(s)
    for j in range(3):
        d = np.zeros(3)
        d[j] = h
        numeric[:, j] = (_relaxed_energy(e[wr] + d, c) - _relaxed_energy(e[wr] - d, c)) / (2 * h)
    scale = np.abs(s).max(axis=1, keepdims=True)
    assert np.abs(numeric - s).max() <= 2e-4 * scale.max()  # scan resolution 1e-5 rad


def test_wrinkle_direction_maximises_the_uniaxial_energy() -> None:
    c = _material(1.08e5, 0.86e5, 5.0e3).plane_stress_matrix()
    ci = _inv(c)
    rng = np.random.default_rng(8)
    e = 0.01 * rng.normal(size=(400, 3))
    e_max = 0.5 * (e[:, 0] + e[:, 1]) + np.hypot(0.5 * (e[:, 0] - e[:, 1]), 0.5 * e[:, 2])
    e = e[e_max > 0.0]
    k = len(e)
    s = e @ c.T
    angle = 0.5 * np.arctan2(2.0 * s[:, 2], s[:, 0] - s[:, 1])
    trial = np.column_stack([np.cos(angle), np.sin(angle)])
    cs, sn, eps = wrinkle_direction(e, np.broadcast_to(ci, (k, 3, 3)).copy(), trial)
    assert np.allclose(cs * cs + sn * sn, 1.0, rtol=1e-12)
    w = np.stack([cs * cs, sn * sn, cs * sn], axis=1)
    found = 0.5 * eps**2 / np.einsum("ki,ij,kj->k", w, ci, w)
    assert np.allclose(eps, np.einsum("ki,ki->k", w, e), rtol=1e-12)
    scan = _relaxed_energy(e, c)  # >= the true maximum minus the scan resolution
    s_min = 0.5 * (s[:, 0] + s[:, 1]) - np.hypot(0.5 * (s[:, 0] - s[:, 1]), s[:, 2])
    wr = s_min <= 0.0
    assert np.all(found[wr] >= scan[wr] * (1.0 - 1e-9))


def test_isotropic_wrinkle_direction_is_the_trial_stress_direction() -> None:
    mat = MembraneMaterial.isotropic("iso", 1.0e5, 0.3)
    c = mat.plane_stress_matrix()
    rng = np.random.default_rng(9)
    e = 0.01 * rng.normal(size=(500, 3))
    k = len(e)
    stress, state, _ = tension_field(_batch(e), np.broadcast_to(c, (k, 3, 3)).copy(),
                                     np.broadcast_to(_inv(c), (k, 3, 3)).copy(), 0.0)  # fmt: skip
    wr = state == WRINKLED
    s = e[wr] @ c.T
    angle = 0.5 * np.arctan2(2.0 * s[:, 2], s[:, 0] - s[:, 1])
    n = np.stack([np.cos(angle), np.sin(angle)], axis=1)
    eps_n = np.einsum("ki,kij,kj->k", n, _batch(e[wr]), n)
    expected = (1.0e5 * eps_n)[:, None, None] * np.einsum("ki,kj->kij", n, n)
    assert np.abs(stress[wr] - expected).max() <= 1e-10 * np.abs(expected).max()


def test_orthotropic_stress_is_continuous_at_the_slack_boundary() -> None:
    mat = _material(1.08e5, 0.86e5, 5.0e3)
    # Largest principal strain just above and just below zero (along the bisector).
    for sign in (1.0, -1.0):
        stress, state, _ = _stress(_strain(sign * 1e-9, -0.01, 0.0), mat, kappa=0.0)
        assert state[0] == (WRINKLED if sign > 0 else SLACK)
        assert np.abs(stress).max() <= 1.08e5 * 1e-9 * 1.01  # E_n eps_n -> 0 with eps_n


def _energy(xe: FloatArray, rest: RestGeometry, c: FloatArray) -> float:
    e = green_strain(deformation_gradient(xe, rest.grad_n))[0]
    v = np.array([e[0, 0], e[1, 1], 2 * e[0, 1]])
    return float(0.5 * rest.area[0] * v @ c @ v)


def test_internal_forces_are_the_energy_gradient() -> None:
    mat = _material()
    c = mat.plane_stress_matrix()
    rest = rest_geometry(TRI_UV, np.array([[0.6, 0.8]]))
    rng = np.random.default_rng(1)
    xe = np.concatenate([TRI_UV[0], np.zeros((3, 1))], axis=1)[None]
    xe = xe + 0.01 * rng.normal(size=xe.shape)
    f = deformation_gradient(xe, rest.grad_n)
    e = green_strain(f)
    stress, state, _ = tension_field(e, c[None], _inv(c)[None], 1e-3, False)
    force = internal_forces(f, stress, rest)[0]
    h = 1e-7
    numeric = np.zeros((3, 3))
    for a in range(3):
        for i in range(3):
            xp, xm = xe.copy(), xe.copy()
            xp[0, a, i] += h
            xm[0, a, i] -= h
            numeric[a, i] = (_energy(xp, rest, c) - _energy(xm, rest, c)) / (2 * h)
    assert np.allclose(force, numeric, rtol=1e-5, atol=1e-6)
    assert np.allclose(force.sum(axis=0), 0.0, atol=1e-9)


def test_stiffness_rowsum_bounds_the_numerical_tangent() -> None:
    mat = _material()
    c = mat.plane_stress_matrix()[None]
    rest = rest_geometry(TRI_UV, X_AXIS)
    xe = np.concatenate([TRI_UV[0] * 1.02, np.zeros((3, 1))], axis=1)[None]

    def forces(x: FloatArray) -> FloatArray:
        f = deformation_gradient(x, rest.grad_n)
        s, _, _ = tension_field(green_strain(f), c, _inv(c), 1e-3, False)
        out: FloatArray = internal_forces(f, s, rest)[0].ravel()
        return out

    h = 1e-7
    k = np.zeros((9, 9))
    for j in range(9):
        xp = xe.copy()
        xp.reshape(-1)[j] += h
        k[:, j] = (forces(xp) - forces(xe)) / h
    f = deformation_gradient(xe, rest.grad_n)
    s, _, _ = tension_field(green_strain(f), c, _inv(c), 1e-3, False)
    bound = element_stiffness_rowsum(f, s, c, rest.grad_n, rest.area)[0]
    rows = np.abs(k).sum(axis=1).reshape(3, 3).max(axis=1)
    assert np.all(bound >= rows * (1 - 1e-6))
