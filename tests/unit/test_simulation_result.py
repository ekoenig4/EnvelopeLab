"""Unit tests: normalised simulation results and run manifests."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from envelopelab.materials.membrane import MembraneMaterial
from envelopelab.solvers.dynamic_relaxation import ModelEvaluator, solve
from envelopelab.solvers.manifest import RunManifest, manifest_for
from envelopelab.solvers.membrane import trial_principal, uniaxial_stiffness
from envelopelab.solvers.model import (
    NodeConstraint,
    OperatingConditions,
    SolverModel,
    SolverSettings,
    SymmetryPlane,
)
from envelopelab.solvers.simulation import SimulationResult, from_preview, principal_resultants
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


def test_from_preview_carries_the_required_fields(
    octant: tuple[SolverModel, SimulationResult],
) -> None:
    model, res = octant
    assert res.converged and res.status == "converged"
    assert res.n_nodes == model.n_nodes and res.n_elements == model.n_triangles
    assert res.stress.shape == (model.n_triangles, 3, 3)
    assert res.residual_history and res.iteration_history
    assert res.elapsed > 0.0 and res.solver == "envelopelab-preview"
    assert res.manifest.mesh["nodes"] == model.n_nodes
    assert set(res.summary()) >= {"height_m", "volume_m3", "max_tape_tension_n", "status"}
    # Without a mouth constraint the datum is the lowest node: the octant's full height.
    assert res.height == pytest.approx(float(np.ptp(res.positions[:, 2])))


def test_principal_resultants_of_a_known_tensor() -> None:
    x = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    stress = np.array([[[3.0, 1.0, 0.0], [1.0, 3.0, 0.0], [0.0, 0.0, 0.0]]])
    out = principal_resultants(stress, np.array([[0, 1, 2]]), x)
    assert out[0] == pytest.approx([4.0, 2.0])


def test_manifest_round_trip_fingerprint_and_differences(
    octant: tuple[SolverModel, SimulationResult], tmp_path: Path
) -> None:
    model, res = octant
    manifest = res.manifest
    zone = model.zone_names[0]
    assert manifest.materials[zone]["stiffness_warp"]["source"] == "assumed"
    path = manifest.save(tmp_path / "run.json")
    loaded = RunManifest.load(path)
    assert loaded.fingerprint() == manifest.fingerprint()
    other = manifest_for(model, "calculix", solver_version="2.21", solver_settings={"a": 1})
    assert {"solver", "solver_version", "solver_settings"} <= set(manifest.differences(other))
    # Timestamps and platform do not change the fingerprint.
    later = dataclasses.replace(manifest, created="2000-01-01T00:00:00+00:00")
    assert later.fingerprint() == manifest.fingerprint()
    data = json.loads(path.read_text())
    data["random_seed"] = 7
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fingerprint"):
        RunManifest.load(path)


def test_trial_principal_and_uniaxial_stiffness() -> None:
    c = np.array([[[1e5, 3e4, 0.0], [3e4, 1e5, 0.0], [0.0, 0.0, 3.5e4]]])
    strain = np.array([[[0.02, 0.0], [0.0, -0.01]]])
    s1, s2, direction, eps_n = trial_principal(strain, c)
    assert s1[0] == pytest.approx(1e5 * 0.02 - 3e4 * 0.01)
    assert s2[0] == pytest.approx(3e4 * 0.02 - 1e5 * 0.01)
    assert abs(direction[0, 0]) == pytest.approx(1.0) and eps_n[0] == pytest.approx(0.02)
    e_n = uniaxial_stiffness(direction, np.linalg.inv(c))
    assert e_n[0] == pytest.approx(1e5 - 3e4**2 / 1e5)  # E (1 - nu^2) for this matrix


def test_model_evaluator_matches_the_preview_equilibrium(
    octant: tuple[SolverModel, SimulationResult],
) -> None:
    model, res = octant
    ev = ModelEvaluator(model, SolverSettings())
    assert ev.volume(res.positions) == pytest.approx(res.volume, rel=1e-9)
    f, e = ev.deformation(res.positions)
    assert f.shape == (model.n_triangles, 3, 2) and e.shape == (model.n_triangles, 2, 2)
    resultant = ev.pressure_resultant(res.positions)
    # Octant of a pressurised sphere: equal pressure resultant along each axis.
    assert resultant == pytest.approx(np.full(3, resultant[0]), rel=1e-2)


def test_fixed_mouth_is_the_height_datum() -> None:
    x = np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [0.3, 0.3, 4.0]])
    mesh_tri = np.array([[0, 1, 3], [1, 2, 3], [2, 0, 3]])
    model = SolverModel.uniform(
        x,
        mesh_tri,
        np.zeros((3, 3, 2)) + np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
        MembraneMaterial.isotropic("iso", 1e5),
        OperatingConditions(1.2, 1.2, self_weight=False),
        constraints=[NodeConstraint("mouth", np.array([0, 1, 2]))],
    )
    res = SimulationResult(
        solver="test",
        solver_version="0",
        status="converged",
        converged=True,
        positions=x,
        initial_positions=x,
        triangles=mesh_tri,
        stress=np.zeros((3, 3, 3)),
        principal=np.zeros((3, 2)),
        tape_tensions={},
        tape_edges={},
        reactions={},
        nodal_reactions=np.zeros_like(x),
        volume=0.0,
        lift=0.0,
        residual_history=[],
        iteration_history=[],
        residual_measure="-",
        elapsed=0.0,
        mouth_nodes=model.constraints[0].nodes,
        manifest=manifest_for(model, "test", solver_version="0"),
    )
    assert res.height == pytest.approx(3.0)
    centre = x[:3].mean(axis=0)
    assert res.max_width == pytest.approx(2.0 * np.hypot(*(x[1, :2] - centre[:2])))
