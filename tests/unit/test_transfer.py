"""Transfer of a solved shape between two meshes of one build pack."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from envelopelab.assembly.transfer import SolvedShape, transfer_positions
from envelopelab.project.session import ProjectSession
from envelopelab.project.simulation import BuiltModel, build_solver_model

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


@pytest.fixture(scope="module")
def meshes(tmp_path_factory: pytest.TempPathFactory) -> tuple[BuiltModel, BuiltModel]:
    s = ProjectSession.open(FIXTURE)
    tmp = tmp_path_factory.mktemp("transfer")
    coarse = build_solver_model(s.design, s.patterns, tmp / "c", 1600.0)
    fine = build_solver_model(s.design, s.patterns, tmp / "f", 600.0)
    return coarse, fine


def test_transfer_onto_the_same_mesh_is_exact(meshes: tuple[BuiltModel, BuiltModel]) -> None:
    coarse, _ = meshes
    mesh = coarse.build.rest_model.mesh  # type: ignore[union-attr]
    x = coarse.model.positions + np.random.default_rng(0).normal(
        0.0, 0.1, coarse.model.positions.shape
    )
    shape = SolvedShape.from_mesh(mesh, x)
    assert np.allclose(transfer_positions(shape, mesh), x, atol=1e-9)


def test_coarse_shape_is_interpolated_onto_a_finer_mesh(
    meshes: tuple[BuiltModel, BuiltModel],
) -> None:
    coarse, fine = meshes
    c_mesh = coarse.build.rest_model.mesh  # type: ignore[union-attr]
    f_mesh = fine.build.rest_model.mesh  # type: ignore[union-attr]
    assert f_mesh.n_nodes > 2 * c_mesh.n_nodes
    mapped = transfer_positions(SolvedShape.from_mesh(c_mesh, coarse.model.positions), f_mesh)
    # Both starting shapes lie on the same surface of revolution: the transferred points
    # are chords of it, off by the sagitta of a 1.6 m element at most.
    size = float(np.ptp(fine.model.positions, axis=0).max())
    error = np.linalg.norm(mapped - fine.model.positions, axis=1)
    assert error.max() < 0.02 * size
    assert np.median(error) < 0.005 * size
    # The mouth ring maps onto the mouth ring (it is held fixed by the solver).
    mouth = np.unique(f_mesh.openings["mouth"])
    z_mouth = coarse.model.positions[np.unique(c_mesh.openings["mouth"]), 2].mean()
    assert np.allclose(mapped[mouth, 2], z_mouth, atol=1e-6)


def test_transfer_refuses_another_build_pack(meshes: tuple[BuiltModel, BuiltModel]) -> None:
    coarse, fine = meshes
    c_mesh = coarse.build.rest_model.mesh  # type: ignore[union-attr]
    shape = SolvedShape.from_mesh(c_mesh, coarse.model.positions)
    renamed = SolvedShape(
        shape.triangles,
        shape.rest_uv,
        shape.tri_instance,
        ["x"] * len(shape.instance_ids),
        shape.positions,
    )
    with pytest.raises(ValueError, match="another build pack"):
        transfer_positions(renamed, fine.build.rest_model.mesh)  # type: ignore[union-attr]


def test_saved_run_arrays_seed_another_mesh(meshes: tuple[BuiltModel, BuiltModel]) -> None:
    from envelopelab.project.simulation import start_from_run

    coarse, fine = meshes
    c_mesh = coarse.build.rest_model.mesh  # type: ignore[union-attr]
    arrays = {
        "positions": coarse.model.positions,
        "triangles": coarse.model.triangles,
        "rest_uv": c_mesh.rest_uv,
        "tri_instance": c_mesh.tri_instance,
        "instance_ids": np.asarray(c_mesh.instance_ids, dtype=np.str_),
    }
    same = start_from_run(arrays, coarse)
    assert same is not None and np.array_equal(same, coarse.model.positions)
    other = start_from_run(arrays, fine)
    assert other is not None and other.shape == fine.model.positions.shape
    size = float(np.ptp(fine.model.positions, axis=0).max())
    assert np.linalg.norm(other - fine.model.positions, axis=1).max() < 0.02 * size
    old = {k: arrays[k] for k in ("positions", "triangles")}  # a run saved before the flat data
    assert start_from_run(old, fine) is None
