"""Unit tests: aligning and comparing two simulation results."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from envelopelab.materials.membrane import MembraneMaterial
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions, SolverModel, SymmetryPlane
from envelopelab.solvers.simulation import SimulationResult, from_preview
from envelopelab.validation.comparison import align_nodes, compare_results
from envelopelab.validation.meshes import sphere


@pytest.fixture(scope="module")
def octant() -> tuple[SolverModel, SimulationResult]:
    mesh = sphere(2.0, 6, octant=True)
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], tuple(np.eye(3)[k]))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        MembraneMaterial.isotropic("iso", 1e5, 0.3),
        OperatingConditions(1.2, 1.2, uniform_pressure=1000.0, self_weight=False),
        symmetry=planes,
    )
    return model, from_preview(model, solve(model))


def test_comparing_a_result_with_itself_flags_nothing(
    octant: tuple[SolverModel, SimulationResult],
) -> None:
    _, res = octant
    comparison = compare_results(res, res)
    assert comparison.passed and not comparison.flagged
    assert comparison.row("volume").difference == 0.0
    assert "| volume |" in comparison.to_markdown()


def test_comparison_flags_differences_and_unconverged_results(
    octant: tuple[SolverModel, SimulationResult],
) -> None:
    _, res = octant
    scaled = dataclasses.replace(
        res,
        positions=res.positions * 1.1,
        volume=res.volume * 1.1**3,
        solver="other",
        converged=False,
    )
    comparison = compare_results(res, scaled)
    assert comparison.row("volume").flagged  # 1.1^3 - 1 = 33 %
    assert comparison.row("height").difference == pytest.approx(0.1)
    assert not comparison.row("mean tape tension").flagged  # no tapes: 0 vs 0
    assert not comparison.passed
    assert any("NOT valid" in note for note in comparison.notes)


def test_nearest_node_alignment_on_a_permuted_mesh(
    octant: tuple[SolverModel, SimulationResult],
) -> None:
    _, res = octant
    order = np.random.default_rng(3).permutation(res.n_nodes)
    permuted = dataclasses.replace(
        res,
        positions=res.positions[order],
        initial_positions=res.initial_positions[order],
    )
    mapping, distance, identical = align_nodes(res, permuted)
    assert not identical and distance == pytest.approx(0.0, abs=1e-12)
    assert np.array_equal(mapping, order)
