"""Warm-started CalculiX passes: frozen tension-field states, hysteresis, law consistency.

The classification tests need no ``ccx``; the solves are skipped without it.
"""

from __future__ import annotations

import numpy as np
import pytest

from calculix_adapter import CalculixInstallation, CalculixSettings, run_calculix
from calculix_adapter.analysis import _Problem
from envelopelab.materials.membrane import MembraneMaterial
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.membrane import SLACK, TAUT, WRINKLED
from envelopelab.solvers.model import (
    OperatingConditions,
    SolverModel,
    SolverSettings,
    SymmetryPlane,
)
from envelopelab.validation.meshes import sphere

NU = 0.3  # Poisson ratio of the test fabric


def octant_model(divisions: int = 4) -> SolverModel:
    """Pressurised octant of a 2 m sphere with its three symmetry planes."""
    mesh = sphere(2.0, divisions, octant=True)
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], (float(k == 0), float(k == 1), float(k == 2)))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        MembraneMaterial.isotropic("isotropic test", 1.0e5, NU),
        OperatingConditions(1.2, 1.2, uniform_pressure=1000.0, self_weight=False),
        symmetry=planes,
        name="octant sphere",
    )


def strain_with_minor(problem: _Problem, ratio: float) -> np.ndarray:
    """The same strain in every element, with minor trial resultant ``ratio`` times the
    major one (isotropic material, principal axes on the fabric axes)."""
    e1 = 1e-3
    e2 = -e1 * (NU - ratio) / (1.0 - ratio * NU)
    strain = np.zeros((problem.m, 2, 2))
    strain[:, 0, 0], strain[:, 1, 1] = e1, e2
    return strain


@pytest.fixture
def problem() -> _Problem:
    return _Problem(octant_model(2), CalculixSettings(state_band=1e-3))


def test_the_plain_test_releases_any_compression(problem: _Problem) -> None:
    state, _ = problem.classify(strain_with_minor(problem, -0.5e-3))
    assert np.all(state == WRINKLED)
    state, _ = problem.classify(strain_with_minor(problem, 0.5e-3))
    assert np.all(state == TAUT)


def test_inside_the_band_an_element_keeps_its_state(problem: _Problem) -> None:
    inside = strain_with_minor(problem, -0.5e-3)
    taut = np.full(problem.m, TAUT, dtype=np.int8)
    wrinkled = np.full(problem.m, WRINKLED, dtype=np.int8)
    assert np.all(problem.classify(inside, taut)[0] == TAUT)
    assert np.all(problem.classify(inside, wrinkled)[0] == WRINKLED)
    slightly_taut = strain_with_minor(problem, 0.5e-3)
    assert np.all(problem.classify(slightly_taut, wrinkled)[0] == WRINKLED)


def test_outside_the_band_the_state_follows_the_law(problem: _Problem) -> None:
    taut = np.full(problem.m, TAUT, dtype=np.int8)
    wrinkled = np.full(problem.m, WRINKLED, dtype=np.int8)
    assert np.all(problem.classify(strain_with_minor(problem, -2e-3), taut)[0] == WRINKLED)
    assert np.all(problem.classify(strain_with_minor(problem, 2e-3), wrinkled)[0] == TAUT)
    # Compressed both ways: slack, whatever the previous state.
    squeezed = np.zeros((problem.m, 2, 2))
    squeezed[:, 0, 0] = squeezed[:, 1, 1] = -1e-3
    assert np.all(problem.classify(squeezed, wrinkled)[0] == SLACK)


def test_the_law_is_the_frozen_material_at_a_consistent_state() -> None:
    problem = _Problem(octant_model(6), CalculixSettings())
    rng = np.random.default_rng(3)
    # Stretched sideways and squashed vertically, with noise: taut, wrinkled and slack.
    x = problem.X * np.array([1.01, 1.01, 0.98]) + rng.normal(0.0, 5e-3, problem.X.shape)
    _, strain = problem.ev.deformation(x)
    state, direction = problem.classify(strain)
    assert np.any(state != TAUT)  # the perturbation wrinkles some elements
    material = problem.materials(state, direction, problem.settings.slack_stiffness_ratio)
    np.testing.assert_allclose(
        problem.law_stress(x), problem.exact_stress(x, material), rtol=1e-9, atol=1e-9
    )


def test_a_cold_start_does_not_use_the_frozen_scheme(ccx: CalculixInstallation) -> None:
    model = octant_model()
    frozen = run_calculix(model, CalculixSettings(freeze_states=True))
    plain = run_calculix(model, CalculixSettings(freeze_states=False))
    np.testing.assert_array_equal(frozen.positions, plain.positions)
    assert not any("law consistency" in r.stage for r in frozen.iteration_history)


def test_a_warm_start_from_equilibrium_settles_in_one_pass(ccx: CalculixInstallation) -> None:
    model = octant_model()
    preview = solve(model, SolverSettings(slack_stiffness_ratio=1e-3))
    assert preview.converged
    result = run_calculix(model, CalculixSettings(), start_positions=preview.positions)
    assert result.converged, [f.message for f in result.findings]
    passes = [r for r in result.iteration_history if r.stage == "pass: relative out-of-balance"]
    law = [r for r in result.iteration_history if "law consistency" in r.stage]
    assert len(passes) == 1
    assert law and law[-1].residual <= CalculixSettings().stress_tolerance
    assert float(np.abs(result.positions - preview.positions).max()) < 1e-3
