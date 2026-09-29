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
