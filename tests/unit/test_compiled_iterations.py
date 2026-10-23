"""The compiled dynamic-relaxation iterations follow the Python reference loop (ADR-0028).

The compiled loop only changes speed: forces, external forces and fictitious masses agree
with the NumPy reference to round-off, short runs follow the same trajectory, and the
stopping rules (limit, progress, cancellation) behave the same.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pytest

import envelopelab.solvers.dynamic_relaxation as dr
from envelopelab.materials.membrane import MaterialValue, MembraneMaterial, TapeMaterial
from envelopelab.solvers.dynamic_relaxation import CancellationToken, SolverProgress, solve
from envelopelab.solvers.kernels import HAVE_NUMBA
from envelopelab.solvers.model import (
    AMBIENT,
    MAIN_CHAMBER,
    CableSet,
    DistributedLoad,
    LineLoad,
    NodeConstraint,
    OperatingConditions,
    PointLoad,
    PressureChamber,
    PressureClosure,
    SolverModel,
    SolverSettings,
    SymmetryPlane,
)
from envelopelab.validation.meshes import cylinder, sheet, sphere

pytestmark = pytest.mark.skipif(not HAVE_NUMBA, reason="the compiled loop needs numba")

ISO = MembraneMaterial.isotropic("iso", 1.0e5, 0.3, areal_mass=0.05)
TAPE = TapeMaterial(
    "tape",
    MaterialValue(1.0e5, "N", "assumed"),
    MaterialValue(5000.0, "N", "assumed"),
    MaterialValue(0.02, "kg/m", "assumed"),
)
# A hydrostatic gradient with self weight: corner pressures vary with height.
HOT = OperatingConditions(1.2, 0.95, self_weight=True)


def _octant() -> SolverModel:
    mesh = sphere(2.0, 6, octant=True)
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], tuple(np.eye(3)[k]))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    cond = OperatingConditions(1.2, 1.2, uniform_pressure=1000.0, self_weight=False)
    return SolverModel.uniform(
        mesh.positions, mesh.triangles, mesh.rest_uv, ISO, cond, symmetry=planes
    )


def _cable_sheet() -> SolverModel:
    """Sheet with a tape along one edge, line, point and distributed loads, self weight."""
    mesh = sheet(1.0, 1.0, 3, 3)
    top = np.array([[i, i + 1] for i in range(12, 15)])
    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        ISO,
        HOT,
        constraints=[NodeConstraint("bottom", mesh.node_sets["bottom"])],
        cables=[CableSet("tape", top, TAPE, np.full(3, 0.95 / 3))],
        line_loads=[LineLoad("pull", top, np.array([0.0, 50.0, 0.0]))],
        point_loads=[PointLoad("weight", np.array([13]), np.array([0.0, 0.0, -5.0]))],
        distributed_loads=[DistributedLoad("coat", np.arange(18), np.array([0.0, 0.0, -2.0]))],
    )


def _closure() -> SolverModel:
    mesh = cylinder(1.0, 1.0, 24, 4)
    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        ISO,
        HOT,
        constraints=[NodeConstraint("bottom", mesh.node_sets["bottom"])],
        closures=[PressureClosure("cap", mesh.node_sets["top"])],
    )


def _chambers() -> SolverModel:
    """Closed sphere, half its wall shared between the envelope and a chamber."""
    mesh = sphere(1.0, 8)
    m = len(mesh.triangles)
    codes = np.tile([MAIN_CHAMBER, AMBIENT], (m, 1))
    codes[: m // 2] = (MAIN_CHAMBER, 0)
    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        ISO,
        HOT,
        constraints=[NodeConstraint("pin", np.array([0, 1, 2]))],
        chambers=[PressureChamber("pod", 30.0, 2.0, 0.0)],
        tri_chambers=codes,
    )


MODELS = {
    "octant": _octant,
    "cable_sheet": _cable_sheet,
    "closure": _closure,
    "chambers": _chambers,
}


def _perturbed(model: SolverModel, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = model.positions * 1.01
    out: np.ndarray = x + rng.normal(scale=2e-3, size=x.shape)
    return out


@pytest.mark.parametrize("name", sorted(MODELS))
@pytest.mark.parametrize("tension_field", [True, False])
def test_compiled_forces_and_masses_match_the_reference(name: str, tension_field: bool) -> None:
    model = MODELS[name]()
    system = dr._System(model, SolverSettings(tension_field=tension_field))
    for seed in range(3):
        x = _perturbed(model, seed)
        r, ext, data = system.forces(x)
        mass = system.masses(x, data)
        r_c, ext_c, mass_c = system.compiled_forces(x)
        scale = float(np.abs(r).max())
        assert np.allclose(r_c, r, rtol=1e-12, atol=1e-12 * scale)
        assert np.allclose(ext_c, ext, rtol=1e-12, atol=1e-12 * float(np.abs(ext).max()))
        assert np.allclose(mass_c, mass, rtol=1e-12)


def _run(
    model: SolverModel, settings: SolverSettings, compiled: bool, **kwargs: Any
) -> dr.SolveResult:
    original = dr.use_compiled_iterations
    dr.use_compiled_iterations = lambda: compiled
    try:
        return solve(model, settings, **kwargs)
    finally:
        dr.use_compiled_iterations = original


@pytest.mark.parametrize("name", sorted(MODELS))
@pytest.mark.parametrize("damping", ["kinetic", "viscous"])
def test_short_runs_follow_the_reference_trajectory(
    name: str, damping: Literal["kinetic", "viscous"]
) -> None:
    model = MODELS[name]()
    settings = SolverSettings(max_iterations=300, damping=damping, viscous_damping=0.1)
    ref = _run(model, settings, compiled=False)
    fast = _run(model, settings, compiled=True)
    assert fast.convergence.status == ref.convergence.status
    assert fast.convergence.iterations == ref.convergence.iterations
    assert fast.convergence.resets == ref.convergence.resets
    span = float(np.ptp(model.positions, axis=0).max())
    assert np.abs(fast.positions - ref.positions).max() < 1e-9 * span
    assert fast.convergence.residual == pytest.approx(ref.convergence.residual, rel=1e-6)


@pytest.mark.parametrize("name", ["octant", "closure"])
def test_both_loops_converge_to_the_same_equilibrium(name: str) -> None:
    model = MODELS[name]()
    ref = _run(model, SolverSettings(), compiled=False)
    fast = _run(model, SolverSettings(), compiled=True)
    assert ref.converged and fast.converged
    span = float(np.ptp(model.positions, axis=0).max())
    # Round-off can change the iteration count; the equilibrium agrees to the tolerance.
    assert np.abs(fast.positions - ref.positions).max() < 1e-5 * span
    assert fast.volume == pytest.approx(ref.volume, rel=1e-6)


def test_limit_progress_and_cancellation_are_unchanged() -> None:
    model = _octant()
    settings = SolverSettings(progress_interval=10, max_iterations=95)
    reports: dict[bool, list[int]] = {}
    for compiled in (False, True):
        seen: list[SolverProgress] = []
        result = _run(model, settings, compiled, progress=seen.append)
        assert result.convergence.status == "max_iterations"
        assert result.convergence.iterations == 95
        assert not result.converged
        reports[compiled] = [p.iteration for p in seen]
        history = [i for i, _ in result.convergence.history]
        assert history == [0, *range(10, 100, 10), 95]
    assert reports[True] == reports[False] == [*range(10, 100, 10), 95]
    for compiled in (False, True):
        token = CancellationToken()
        result = _run(
            model,
            SolverSettings(progress_interval=10),
            compiled,
            progress=lambda p, t=token: t.cancel() if p.iteration >= 30 else None,
            cancel=token,
        )
        assert result.convergence.status == "cancelled"
        assert result.convergence.iterations == 30
