"""Unit tests: dynamic-relaxation solver (small analytic cases)."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from envelopelab.materials.membrane import MaterialValue, MembraneMaterial, TapeMaterial
from envelopelab.solvers.dynamic_relaxation import (
    UNITS,
    CancellationToken,
    SolverJob,
    SolverProgress,
    solve,
)
from envelopelab.solvers.model import (
    CableSet,
    DistributedLoad,
    LineLoad,
    ModelError,
    NodeConstraint,
    OperatingConditions,
    PointLoad,
    PressureClosure,
    SolverModel,
    SolverSettings,
    SymmetryPlane,
    edge_rest_lengths,
)
from envelopelab.validation.meshes import cylinder, sheet, sphere

ISO = MembraneMaterial.isotropic("iso", 1.0e5, 0.3, areal_mass=0.05)
NO_GRAVITY = OperatingConditions(1.2, 1.2, uniform_pressure=1000.0, self_weight=False)


def _octant(divisions: int = 6, conditions: OperatingConditions = NO_GRAVITY) -> SolverModel:
    mesh = sphere(2.0, divisions, octant=True)
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], tuple(np.eye(3)[k]))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        ISO,
        conditions,
        symmetry=planes,
    )


def _tape(ea: float = 1.0e5, mass: float = 0.0) -> TapeMaterial:
    return TapeMaterial(
        "tape",
        MaterialValue(ea, "N", "assumed"),
        MaterialValue(5000.0, "N", "assumed"),
        MaterialValue(mass, "kg/m", "assumed"),
    )


def _cable_model(point_force: float = 0.0, elements: int = 20) -> SolverModel:
    x = np.linspace(0.0, 4.0, elements + 1)
    positions = np.column_stack([x, np.zeros_like(x), -0.01 * np.sin(np.pi * x / 4.0)])
    edges = np.column_stack([np.arange(elements), np.arange(1, elements + 1)])
    loads = (
        [PointLoad("weight", np.array([elements // 2]), np.array([0.0, 0.0, -point_force]))]
        if point_force
        else []
    )
    return SolverModel(
        positions,
        np.zeros((0, 3), dtype=np.int64),
        np.zeros((0, 3, 2)),
        np.zeros((0, 2)),
        np.zeros(0, dtype=np.int64),
        [],
        {},
        OperatingConditions(1.2, 1.2, self_weight=True),
        cables=[CableSet("cable", edges, _tape(mass=0.5), np.full(elements, 4.4 / elements))],
        constraints=[
            NodeConstraint("left", np.array([0])),
            NodeConstraint("right", np.array([elements])),
        ],
        point_loads=loads,
    )


def test_octant_sphere_converges_to_p_r_over_2() -> None:
    result = solve(_octant(10))
    assert result.converged, result.convergence
    assert result.convergence.residual < 1e-6
    r = float(np.linalg.norm(result.positions, axis=1).mean())
    assert result.principal.mean() == pytest.approx(1000.0 * r / 2.0, rel=0.02)
    assert not result.errors
    # Symmetry reactions balance the pressure resultant on the octant.
    total = result.loads.pressure + sum(result.loads.reactions.values())
    assert np.linalg.norm(total) < 5e-3 * np.linalg.norm(result.loads.pressure)


def test_result_metadata_has_units_sources_and_reproducibility_data() -> None:
    result = solve(_octant(4))
    meta = result.metadata
    for key in (
        "convergence",
        "mesh",
        "load_case",
        "materials",
        "units",
        "git_commit",
        "dependencies",
        "model_content_hash",
        "random_seed",
        "settings",
    ):
        assert key in meta
    assert meta["units"] == UNITS
    assert meta["materials"]["fabric"]["stiffness_warp"]["source"] == "assumed"
    assert meta["mesh"]["triangles"] == len(_octant(4).triangles)
    assert meta["convergence"]["converged"] is True
    assert meta["convergence"]["run_time_s"] > 0.0


def test_iteration_limit_is_reported_as_not_converged() -> None:
    result = solve(_octant(), SolverSettings(max_iterations=5))
    assert not result.converged
    assert result.convergence.status == "max_iterations"
    assert [w.code for w in result.errors] == ["not_converged"]
    assert "NOT CONVERGED" in result.metadata["status"]


def test_progress_callback_and_cancellation() -> None:
    token = CancellationToken()
    seen: list[SolverProgress] = []

    def progress(p: SolverProgress) -> None:
        seen.append(p)
        if len(seen) == 2:
            token.cancel()

    settings = SolverSettings(tolerance=1e-15, progress_interval=10, max_iterations=100_000)
    result = solve(_octant(), settings, progress=progress, cancel=token)
    assert result.convergence.status == "cancelled"
    assert not result.converged
    assert result.errors and result.errors[0].code == "not_converged"
    assert [p.iteration for p in seen[:2]] == [10, 20]
    assert all(0.0 <= p.fraction <= 1.0 for p in seen)


def test_solver_job_runs_in_background_and_can_be_cancelled() -> None:
    started = threading.Event()
    settings = SolverSettings(tolerance=1e-15, progress_interval=5, max_iterations=10**7)
    job = SolverJob(_octant(8), settings, progress=lambda p: started.set()).start()
    assert started.wait(30.0)
    assert not job.done()
    job.cancel()
    result = job.result(timeout=30.0)
    assert job.done()
    assert result.convergence.status == "cancelled"


def test_solver_job_reraises_errors() -> None:
    model = _octant(2)
    model.rest_uv = model.rest_uv[:, ::-1]  # clockwise rest triangles
    with pytest.raises(ValueError, match="clockwise"):
        SolverJob(model).start().result(timeout=30.0)


def test_time_limit_stops_the_solve() -> None:
    settings = SolverSettings(tolerance=1e-15, progress_interval=1, time_limit=1e-9)
    result = solve(_octant(), settings)
    assert result.convergence.status == "time_limit"


def test_warm_start_needs_fewer_iterations() -> None:
    cold = solve(_octant(8))
    warmer = OperatingConditions(1.2, 1.2, uniform_pressure=1100.0, self_weight=False)
    restart = solve(_octant(8, warmer), initial_positions=cold.positions)
    fresh = solve(_octant(8, warmer))
    assert restart.converged and fresh.converged
    assert restart.convergence.iterations < fresh.convergence.iterations
    assert np.allclose(restart.positions, fresh.positions, atol=1e-4)
    # Displacements are always measured from the model's initial (as-sewn) positions,
    # not from the warm-start shape.
    assert np.allclose(restart.initial_positions, fresh.initial_positions)
    assert np.allclose(restart.displacements, fresh.displacements, atol=1e-4)


def test_viscous_damping_converges_to_the_same_shape() -> None:
    kinetic = solve(_octant(4))
    viscous = solve(_octant(4), SolverSettings(damping="viscous", viscous_damping=0.1))
    assert viscous.converged
    assert np.allclose(viscous.positions, kinetic.positions, atol=1e-4)


def test_orthotropic_grain_direction_controls_stiffness() -> None:
    mat = MembraneMaterial(
        "ortho",
        MaterialValue(1.0e5, "N/m", "assumed"),
        MaterialValue(0.5e5, "N/m", "assumed"),
        MaterialValue(1.0e4, "N/m", "assumed"),
        MaterialValue(0.0, "-", "assumed"),
        MaterialValue(0.0, "kg/m^2", "assumed"),
        MaterialValue(1.0e4, "N/m", "assumed"),
        MaterialValue(1.0e4, "N/m", "assumed"),
        MaterialValue(1.0, "-", "assumed"),
        MaterialValue(400.0, "K", "assumed"),
    )
    mesh = sheet(1.0, 1.0, 4, 4)
    stretched = mesh.positions.copy()
    stretched[:, 0] *= 1.001
    left, right = mesh.node_sets["left"], mesh.node_sets["right"]
    forces = []
    for grain in ((1.0, 0.0), (0.0, 1.0)):
        model = SolverModel.uniform(
            mesh.positions,
            mesh.triangles,
            mesh.rest_uv,
            mat,
            OperatingConditions(1.2, 1.2, self_weight=False),
            grain=grain,
            constraints=[
                NodeConstraint("left", left, stretched[left], (True, False, True)),
                NodeConstraint("right", right, stretched[right], (True, False, True)),
            ],
            symmetry=[SymmetryPlane("y0", np.array([0]), (0.0, 1.0, 0.0))],
        )
        result = solve(model)
        assert result.converged
        forces.append(result.loads.reactions["right"][0])
    assert forces[0] / forces[1] == pytest.approx(2.0, rel=1e-3)
    assert forces[0] == pytest.approx(1.0e5 * 1.0e-3 * (1 + 0.5e-3), rel=1e-3)


def test_cable_point_load_and_self_weight_balance() -> None:
    result = solve(_cable_model(point_force=100.0))
    assert result.converged
    weight = 0.5 * 4.4 * 9.80665
    vertical = result.loads.reactions["left"][2] + result.loads.reactions["right"][2]
    assert vertical == pytest.approx(100.0 + weight, rel=1e-5)
    assert result.loads.point_loads["weight"][2] == pytest.approx(-100.0)
    assert result.loads.tape_weight[2] == pytest.approx(-weight)
    assert np.all(result.tape_tensions["cable"] > 0.0)


def test_line_and_distributed_loads_are_applied() -> None:
    mesh = sheet(1.0, 1.0, 3, 3)
    top_edges = np.array([[i, i + 1] for i in range(12, 15)])
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        ISO,
        OperatingConditions(1.2, 1.2, self_weight=False),
        constraints=[NodeConstraint("bottom", mesh.node_sets["bottom"])],
        line_loads=[LineLoad("pull", top_edges, np.array([0.0, 50.0, 0.0]))],
        distributed_loads=[DistributedLoad("coat", np.arange(18), np.array([0.0, 0.0, -2.0]))],
    )
    result = solve(model, SolverSettings(tension_field=False))
    assert result.loads.line_loads["pull"] == pytest.approx([0.0, 50.0, 0.0])
    assert result.loads.distributed_loads["coat"] == pytest.approx([0.0, 0.0, -2.0])


def test_closure_transfers_cap_pressure_and_closes_the_volume() -> None:
    mesh = cylinder(1.0, 1.0, 24, 4)
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        ISO,
        NO_GRAVITY,
        constraints=[NodeConstraint("bottom", mesh.node_sets["bottom"])],
        closures=[PressureClosure("cap", mesh.node_sets["top"])],
    )
    result = solve(model)
    assert result.converged
    cap_area = 0.5 * 24 * np.sin(2 * np.pi / 24)  # regular 24-gon, r = 1 m
    assert result.loads.closures["cap"][2] == pytest.approx(1000.0 * cap_area, rel=0.02)
    assert result.volume == pytest.approx(cap_area * 1.0, rel=0.03)


def test_unconstrained_and_temperature_findings() -> None:
    fabric = MembraneMaterial.isotropic("f", 1.0e5, max_service_temperature=373.15)
    mesh = sphere(1.0, 2, octant=True)
    hot = OperatingConditions(
        1.2, 0.9, self_weight=False, internal_temperature=400.0, uniform_pressure=10.0
    )
    model = SolverModel.uniform(mesh.positions, mesh.triangles, mesh.rest_uv, fabric, hot)
    result = solve(model, SolverSettings(max_iterations=10))
    codes = {w.code for w in result.errors}
    assert {"unconstrained", "temperature_exceedance", "not_converged"} <= codes


def test_model_validation_errors() -> None:
    mesh = sphere(1.0, 2, octant=True)
    with pytest.raises(ModelError, match="no material"):
        SolverModel(
            mesh.positions,
            mesh.triangles,
            mesh.rest_uv,
            np.tile([1.0, 0.0], (len(mesh.triangles), 1)),
            np.zeros(len(mesh.triangles), dtype=np.int64),
            ["a"],
            {},
            NO_GRAVITY,
        )
    with pytest.raises(ModelError, match="out of range"):
        SolverModel.uniform(
            mesh.positions,
            mesh.triangles,
            mesh.rest_uv,
            ISO,
            NO_GRAVITY,
            constraints=[NodeConstraint("bad", np.array([10_000]))],
        )
    with pytest.raises(ModelError):
        SolverSettings(mass_factor=0.1)


def test_edge_rest_lengths_average_both_sides() -> None:
    mesh = sheet(1.0, 1.0, 2, 2)
    lengths = edge_rest_lengths(np.array([[0, 1], [4, 3]]), mesh.triangles, mesh.rest_uv)
    assert lengths == pytest.approx([0.5, 0.5])
    with pytest.raises(ModelError):
        edge_rest_lengths(np.array([[0, 8]]), mesh.triangles, mesh.rest_uv)


def test_hot_air_conditions_use_isa_and_record_sources() -> None:
    cond = OperatingConditions.hot_air(373.15, altitude=0.0, mouth_height=1.0)
    assert cond.pressure_gradient == pytest.approx(2.736, rel=1e-3)
    assert cond.pressure(0.5) == 0.0
    assert cond.pressure(11.0) == pytest.approx(27.36, rel=1e-3)
    assert cond.as_dict()["source"] == "datasheet"
