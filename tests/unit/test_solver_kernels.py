"""Compiled and NumPy element kernels give the same forces (the JIT only changes speed)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from envelopelab.solvers.kernels import HAVE_NUMBA, element_forces, pressure_corner_forces
from envelopelab.solvers.membrane import SLACK, TAUT, WRINKLED, rest_geometry
from envelopelab.validation.preview_solver import GENERIC_FABRIC

pytestmark = pytest.mark.skipif(not HAVE_NUMBA, reason="the compiled kernel needs numba")


def _case(seed: int, n_tri: int = 400) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    rest_uv = rng.normal(size=(n_tri, 3, 2)) * 0.3
    # Counter-clockwise rest triangles.
    a = rest_uv[:, 1] - rest_uv[:, 0]
    b = rest_uv[:, 2] - rest_uv[:, 0]
    flip = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0] < 0
    rest_uv[flip] = rest_uv[flip][:, [0, 2, 1]]
    tri = np.arange(3 * n_tri).reshape(n_tri, 3)
    # Current shape: rest lifted into 3D, stretched along x and squeezed along y so that
    # taut, wrinkled and slack triangles all occur.
    scale = rng.uniform(0.9, 1.08, size=(n_tri, 1, 2))
    xy = rest_uv * scale
    z = rng.normal(size=(n_tri, 3, 1)) * 0.01
    x = np.concatenate([xy, z], axis=2).reshape(-1, 3)
    p = rng.uniform(-5.0, 50.0, size=(n_tri, 3))
    return x, tri, rest_uv, p


@pytest.mark.parametrize("enabled", [True, False])
def test_compiled_kernel_matches_numpy(enabled: bool) -> None:
    x, tri, rest_uv, p = _case(3)
    rest = rest_geometry(rest_uv, np.tile([1.0, 0.0], (len(tri), 1)))
    c = np.broadcast_to(GENERIC_FABRIC.plane_stress_matrix(), (len(tri), 3, 3)).copy()
    ci = np.asarray(np.linalg.inv(c), dtype=np.float64)
    scatter = csr_matrix(
        (np.ones(tri.size), (tri.ravel(), np.arange(tri.size))), shape=(len(x), tri.size)
    )
    ref = element_forces(x, tri, rest, c, ci, 1e-3, enabled, p, scatter, use_jit=False)
    fast = element_forces(x, tri, rest, c, ci, 1e-3, enabled, p, scatter, use_jit=True)
    if enabled:
        assert {TAUT, WRINKLED, SLACK} <= set(ref.state.tolist())
    assert np.array_equal(ref.state, fast.state)
    for name in ("xe", "f", "strain", "stress", "trial_minor", "f_int", "f_p"):
        a, b = getattr(ref, name), getattr(fast, name)
        scale = max(float(np.abs(a).max()), 1e-300)
        assert np.abs(a - b).max() <= 1e-12 * scale, name
    for name in ("residual", "external"):
        a, b = getattr(ref, name), getattr(fast, name)
        assert np.abs(a - b).max() <= 1e-12 * float(np.abs(a).max()), name


def test_pressure_corner_forces_sum_to_pressure_times_area() -> None:
    xe = np.array([[[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 1.0, 0.0]]])
    f = pressure_corner_forces(xe, np.full((1, 3), 10.0))
    assert f.sum(axis=(0, 1)) == pytest.approx([0.0, 0.0, 10.0 * 1.0])
