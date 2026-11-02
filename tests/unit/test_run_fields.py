"""Unit tests: per-triangle factor of safety and the result fields of a stored run."""

from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab.materials.membrane import MembraneMaterial
from envelopelab.project.run_fields import FIELD_LABELS, missing_fields, run_fields
from envelopelab.solvers.dynamic_relaxation import SolveResult, solve
from envelopelab.solvers.model import OperatingConditions, SolverModel, SymmetryPlane
from envelopelab.solvers.results import factors_of_safety, triangle_factors_of_safety
from envelopelab.validation.meshes import sphere

STRENGTH = 10_000.0  # N/m (assumed test value)
PRESSURE = 1000.0  # Pa (assumed test value)
RADIUS = 2.0  # m


def _model() -> SolverModel:
    mesh = sphere(RADIUS, 8, octant=True)
    fabric = MembraneMaterial.isotropic("fabric", 1.0e5, 0.3, areal_mass=0.0, strength=STRENGTH)
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], tuple(np.eye(3)[k]))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        fabric,
        OperatingConditions(1.2, 1.2, uniform_pressure=PRESSURE, self_weight=False),
        symmetry=planes,
    )


@pytest.fixture(scope="module")
def solved() -> tuple[SolverModel, SolveResult]:
    model = _model()
    return model, solve(model)


def _arrays(result: SolveResult, model: SolverModel) -> dict[str, np.ndarray]:
    return {
        "positions": result.positions,
        "initial_positions": result.initial_positions,
        "triangles": model.triangles,
        "principal": result.principal,
        "fabric_resultants": result.fabric_resultants,
        "wrinkle_state": result.state.astype(np.int8),
    }


def test_triangle_fos_minimum_equals_the_zone_factor(
    solved: tuple[SolverModel, SolveResult],
) -> None:
    model, result = solved
    fos = triangle_factors_of_safety(model, result.fabric_resultants)
    assert fos.shape == (len(model.triangles), 2)
    zone = {r.name: r.fos for r in factors_of_safety(model, result) if r.kind == "zone"}
    assert math.isclose(float(fos[:, 0].min()), zone["fabric (warp)"], rel_tol=1e-12)
    assert math.isclose(float(fos[:, 1].min()), zone["fabric (weft)"], rel_tol=1e-12)


def test_triangle_fos_of_a_pressurized_sphere_matches_hand_calculation(
    solved: tuple[SolverModel, SolveResult],
) -> None:
    # Sphere: N = p r / 2 in every direction, so FoS = N_ult / (p r / 2) = 10.
    model, result = solved
    assert result.convergence.converged
    fos = triangle_factors_of_safety(model, result.fabric_resultants)
    expected = STRENGTH / (PRESSURE * RADIUS / 2.0)
    assert np.median(fos) == pytest.approx(expected, rel=0.02)


def test_unloaded_or_compressed_directions_have_infinite_fos() -> None:
    model = _model()
    m = len(model.triangles)
    demand = np.zeros((m, 3))
    demand[0, 0] = 2000.0  # warp tension in triangle 0
    demand[1, 1] = -500.0  # weft compression in triangle 1
    fos = triangle_factors_of_safety(model, demand)
    assert fos[0, 0] == pytest.approx(STRENGTH / 2000.0)
    assert np.isinf(fos[1, 1]) and np.isinf(fos[2]).all()


def test_triangle_fos_rejects_mismatched_resultants() -> None:
    model = _model()
    with pytest.raises(ValueError, match="do not match"):
        triangle_factors_of_safety(model, np.zeros((len(model.triangles) + 1, 3)))


def test_run_fields_of_a_current_preview_run(solved: tuple[SolverModel, SolveResult]) -> None:
    model, result = solved
    arrays = _arrays(result, model)
    fields = run_fields(arrays, model)
    assert list(fields) == list(FIELD_LABELS)  # every field, in display order
    assert fields["displacement"].location == "node"
    assert len(fields["displacement"].values) == len(model.positions)
    for key in ("fos_warp", "n1", "n_weft", "wrinkle_state"):
        assert len(fields[key].values) == len(model.triangles)
    assert fields["n1"].unit == "N/m" and fields["fos_warp"].unit == "-"
    assert missing_fields(arrays, model) == {}


def test_fos_is_left_out_without_a_matching_model_or_resultants(
    solved: tuple[SolverModel, SolveResult],
) -> None:
    model, result = solved
    arrays = _arrays(result, model)
    assert "fos_warp" not in run_fields(arrays)  # stale run: no model given
    why = missing_fields(arrays)
    assert "current run" in why["fos_warp"]
    calculix = {k: v for k, v in arrays.items() if k not in ("fabric_resultants", "wrinkle_state")}
    fields = run_fields(calculix, model)
    assert "fos_warp" not in fields and "n_warp" not in fields and "n1" in fields
    assert "CalculiX" in missing_fields(calculix, model, "calculix")["fos_weft"]
    assert "run it again" in missing_fields(calculix, model, "envelopelab-preview")["n_warp"]


def test_run_fields_of_positions_only() -> None:
    model = _model()
    arrays = {"positions": model.positions, "triangles": model.triangles}
    assert run_fields(arrays, model) == {}
    assert set(missing_fields(arrays, model)) == set(FIELD_LABELS)
