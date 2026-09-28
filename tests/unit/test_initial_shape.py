from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from envelopelab.assembly.initial_shape import (
    closest_points_on_triangles,
    load_obj,
    project_to_reference,
)
from envelopelab.assembly.pipeline import import_build_pack

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore"


def _sphere_obj(path: Path, radius: float, centre_z: float, n: int = 48) -> None:
    lines = []
    for i in range(n + 1):
        phi = math.pi * i / n
        for j in range(2 * n):
            theta = math.pi * j / n
            x = radius * math.sin(phi) * math.cos(theta)
            y = radius * math.sin(phi) * math.sin(theta)
            z = centre_z + radius * math.cos(phi)
            lines.append(f"v {x:.9f} {y:.9f} {z:.9f}")
    for i in range(n):
        for j in range(2 * n):
            a = i * 2 * n + j + 1
            b = i * 2 * n + (j + 1) % (2 * n) + 1
            c = a + 2 * n
            d = b + 2 * n
            lines.append(f"f {a} {b} {d} {c}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_closest_point_matches_brute_force() -> None:
    rng = np.random.default_rng(3)
    a, b, c = rng.normal(size=(3, 1, 3))
    points = rng.normal(scale=2.0, size=(200, 3))
    ours = closest_points_on_triangles(
        points, np.repeat(a, 200, 0), np.repeat(b, 200, 0), np.repeat(c, 200, 0)
    )
    u, v = np.meshgrid(np.linspace(0, 1, 401), np.linspace(0, 1, 401))
    keep = (u + v) <= 1
    samples = a + u[keep, None] * (b - a) + v[keep, None] * (c - a)
    brute = np.min(np.linalg.norm(points[:, None, :] - samples[None], axis=2), axis=1)
    assert np.linalg.norm(ours - points, axis=1) == pytest.approx(brute, abs=5e-3)


def test_load_obj_triangulates_quads(tmp_path: Path) -> None:
    obj = tmp_path / "quad.obj"
    obj.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n", encoding="utf-8")
    vertices, faces = load_obj(obj)
    assert vertices.shape == (4, 3)
    assert faces.tolist() == [[0, 1, 2], [0, 2, 3]]


def test_projection_lands_on_reference(tmp_path: Path) -> None:
    obj = tmp_path / "sphere.obj"
    _sphere_obj(obj, 2.0, 0.0)
    vertices, faces = load_obj(obj)
    points = np.random.default_rng(1).normal(size=(50, 3))
    projected = project_to_reference(points, vertices, faces)
    radius = np.linalg.norm(projected, axis=1)
    assert radius == pytest.approx(np.full(50, 2.0), abs=0.01)


def test_reference_mesh_is_used_only_as_initial_guess(tmp_path: Path) -> None:
    data = yaml.safe_load((FIXTURE / "build-pack.yaml").read_text(encoding="utf-8"))
    data["import"]["sources"] = [{"file": str(FIXTURE / "panels.dxf")}]
    _sphere_obj(tmp_path / "reference.obj", 3.2, 4.2)
    data["assembly"]["initial_shape"] = {
        "method": "reference_mesh",
        "reference_mesh": "reference.obj",
    }
    config = tmp_path / "build-pack.yaml"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = import_build_pack(config)
    assert result.rest_model is not None
    positions = result.rest_model.positions
    distance = np.abs(np.linalg.norm(positions - [0.0, 0.0, 4.2], axis=1) - 3.2)
    assert float(distance.max()) < 0.02
    # The rest geometry (flat panels) is unchanged by the reference.
    assert result.mesh_report is not None and result.mesh_report.passed
    assert any("reference mesh" in w.message for w in result.warnings)
