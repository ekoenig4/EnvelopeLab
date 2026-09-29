"""Unit tests: preview-solver post-processing (fields, force balance, FoS, export)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.materials.membrane import MaterialValue, MembraneMaterial, TapeMaterial
from envelopelab.solvers.dynamic_relaxation import SolveResult, solve
from envelopelab.solvers.model import (
    CableSet,
    OperatingConditions,
    SeamLine,
    SolverModel,
    SolverSettings,
    SymmetryPlane,
)
from envelopelab.solvers.results import (
    factors_of_safety,
    force_balance,
    result_fields,
    save_result,
    summary_markdown,
    wrinkle_zones,
    write_obj,
)
from envelopelab.validation.meshes import sphere

STRENGTH = 10_000.0  # N/m


def _model() -> SolverModel:
    mesh = sphere(2.0, 8, octant=True)
    fabric = MembraneMaterial.isotropic(
        "fabric", 1.0e5, 0.3, areal_mass=0.0, strength=STRENGTH, seam_efficiency=0.5
    )
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], tuple(np.eye(3)[k]))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    # The equator (z = 0 plane) nodes in order of angle carry a tape and a seam.
    ring = mesh.node_sets["z0"]
    ring = ring[np.argsort(np.arctan2(mesh.positions[ring, 1], mesh.positions[ring, 0]))]
    edges = np.column_stack([ring[:-1], ring[1:]])
    tape = TapeMaterial(
        "tape", MaterialValue(1.0e5, "N", "assumed"), MaterialValue(2000.0, "N", "datasheet")
    )
    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        fabric,
        OperatingConditions(1.2, 1.2, uniform_pressure=1000.0, self_weight=False),
        symmetry=planes,
        cables=[CableSet("equator tape", edges, tape)],
        seams=[SeamLine("equator seam", edges)],
    )


@pytest.fixture(scope="module")
def solved() -> tuple[SolverModel, SolveResult]:
    model = _model()
    return model, solve(model)


def test_fields_have_units_and_one_value_per_location(
    solved: tuple[SolverModel, SolveResult],
) -> None:
    model, result = solved
    fields = result_fields(model, result)
    assert fields["displacement"].unit == "m"
    assert fields["n1"].unit == "N/m"
    assert fields["tape_tension"].unit == "N"
    assert len(fields["displacement"].values) == model.n_nodes
    assert len(fields["n1"].values) == model.n_triangles
    assert len(fields["tape_tension"].values) == len(model.cables[0].edges)
    assert fields["n1"].range[1] >= fields["n2"].range[1]
    assert set(np.unique(fields["wrinkle_state"].values)) <= {0.0, 1.0, 2.0}
    assert len(wrinkle_zones(result)) == int(np.sum(result.state != 0))


def test_force_balance_passes_for_a_converged_solve(
    solved: tuple[SolverModel, SolveResult],
) -> None:
    _, result = solved
    balance = force_balance(result)
    assert balance.passed
    assert balance.imbalance < 1e-4
    items = [row.item for row in balance.rows]
    assert "pressure on membrane" in items
    assert any(item.startswith("reaction") for item in items)


def test_factors_of_safety_for_zone_seam_and_tape(solved: tuple[SolverModel, SolveResult]) -> None:
    model, result = solved
    rows = {(r.kind, r.name): r for r in factors_of_safety(model, result, required=2.0)}
    pr2 = 1000.0 * 2.0 / 2.0
    warp = rows[("zone", "fabric (warp)")]
    assert warp.unit == "N/m"
    # The demand is the worst element; faceting scatters elements a few % about p r / 2.
    assert warp.fos == pytest.approx(STRENGTH / result.fabric_resultants[:, 0].max())
    assert warp.demand == pytest.approx(pr2, rel=0.1)
    assert warp.passed
    seam = rows[("seam", "equator seam")]
    assert seam.capacity == pytest.approx(0.5 * STRENGTH)
    assert seam.demand == pytest.approx(pr2, rel=0.1)
    tape = rows[("tape", "equator tape")]
    assert tape.unit == "N" and tape.source == "datasheet"
    assert tape.demand > 0.0
    strict = factors_of_safety(model, result, required={"zone": 100.0})
    assert any(r.status == "FAIL" for r in strict if r.kind == "zone")


def test_unconverged_results_never_pass() -> None:
    model = _model()
    result = solve(model, SolverSettings(max_iterations=3))
    assert all(r.status == "not converged" for r in factors_of_safety(model, result))
    assert not force_balance(result).passed
    assert "NOT CONVERGED" in summary_markdown(model, result)


def test_obj_and_json_export(tmp_path: Path, solved: tuple[SolverModel, SolveResult]) -> None:
    model, result = solved
    obj = write_obj(tmp_path / "shape.obj", result.positions, model.triangles)
    text = obj.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("v ") for line in text) == model.n_nodes
    assert sum(line.startswith("f ") for line in text) == model.n_triangles
    data = json.loads(save_result(model, result, tmp_path / "result.json").read_text("utf-8"))
    assert data["converged"] is True
    assert data["units"]["stress_resultants"] == "N/m"
    assert data["fields"]["n1"]["unit"] == "N/m"
    assert data["metadata"]["convergence"]["status"] == "converged"
    assert all(row["fos"] is None or math.isfinite(row["fos"]) for row in data["factors_of_safety"])


def test_summary_lists_balance_fos_and_warnings(solved: tuple[SolverModel, SolveResult]) -> None:
    model, result = solved
    text = summary_markdown(model, result)
    assert "**Status: CONVERGED**" in text
    assert "## Force balance (N)" in text
    assert "## Factors of safety" in text
