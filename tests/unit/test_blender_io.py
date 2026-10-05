"""Blender mesh exchange: OBJ axes, scenes of the envelope and its shapes."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from envelopelab.features.primitives import (
    Dome,
    Placement,
    Tube,
    _to_host_frame,
    design_primitive,
)
from envelopelab.features.scene import (
    designed_object,
    envelope_object,
    export_scene,
    simulated_object,
    to_envelope_frame,
)
from envelopelab.io.blender import (
    MeshObject,
    from_obj_axes,
    read_shape_mesh,
    to_obj_axes,
    write_obj_scene,
    write_stl_object,
)
from envelopelab.io.reference_mesh import read_mesh
from envelopelab.validation.primitives import SPHERE_RADIUS, sphere_envelope

SPHERE = sphere_envelope()
EQUATOR = 0.35 * math.pi * SPHERE_RADIUS
TETRA = MeshObject(
    "tetra",
    np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]]),
    np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]),
)


def test_obj_axes_are_blender_y_up() -> None:
    up = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
    assert to_obj_axes(up) == pytest.approx(np.array([[0.0, 1.0, 0.0], [0.0, 0.0, -1.0]]))
    pts = np.random.default_rng(1).normal(size=(10, 3))
    assert from_obj_axes(to_obj_axes(pts)) == pytest.approx(pts)


def test_obj_scene_round_trip_through_a_blender_style_file(tmp_path: Path) -> None:
    other = MeshObject("second one", TETRA.vertices + 5.0, TETRA.triangles)
    path = write_obj_scene(tmp_path / "scene.obj", [TETRA, other])
    text = path.read_text(encoding="utf-8")
    assert "o tetra" in text and "o second_one" in text
    raw = read_mesh(path)
    assert len(raw.vertices) == 8 and len(raw.triangles) == 8
    back = read_shape_mesh(path)  # OBJ: y up by default
    assert back.vertices[:4] == pytest.approx(TETRA.vertices)
    assert back.triangles[4:] == pytest.approx(TETRA.triangles + 4)
    zup = write_obj_scene(tmp_path / "z.obj", [TETRA], up="Z")
    assert read_shape_mesh(zup, up="Z").vertices == pytest.approx(TETRA.vertices)


def test_stl_is_z_up_and_scaled_on_read(tmp_path: Path) -> None:
    path = write_stl_object(tmp_path / "t.stl", TETRA)
    back = read_shape_mesh(path, scale=0.001)
    assert back.vertices.max(axis=0) == pytest.approx([0.001, 0.002, 0.003], rel=1e-6)


def test_envelope_and_designed_objects_sit_where_they_should() -> None:
    env = envelope_object(SPHERE, rings=40, per_gore=4)
    assert np.abs(SPHERE.signed_distance(env.vertices)).max() < 1e-3
    assert len(env.triangles) == 2 * 39 * 4 * SPHERE.gore_count
    dome = design_primitive(Dome("ear", Placement(3, EQUATOR), 0.8, 0.6), SPHERE)
    obj = designed_object(dome)
    assert obj.name == "ear designed"
    assert SPHERE.signed_distance(obj.vertices).max() == pytest.approx(0.6, abs=2e-3)
    tube = design_primitive(Tube("horn", Placement(5, EQUATOR), 0.5, 0.2, 1.0), SPHERE)
    t_obj = designed_object(tube)
    # The tip disc closes the tube: its centre is a vertex on the axis at the tip.
    tip = tube.base_point + tube.axis * 1.0
    assert np.linalg.norm(t_obj.vertices - tip, axis=1).min() < 1e-9
    edges = np.sort(
        np.concatenate(
            [t_obj.triangles[:, [0, 1]], t_obj.triangles[:, [1, 2]], t_obj.triangles[:, [2, 0]]]
        ),
        axis=1,
    )
    _, count = np.unique(edges, axis=0, return_counts=True)
    assert int((count == 1).sum()) == 4 * 16  # only the footprint ring is open


def test_simulated_skin_goes_back_onto_the_envelope(tmp_path: Path) -> None:
    dome = design_primitive(Dome("ear", Placement(3, EQUATOR), 0.8, 0.6), SPHERE)
    pts = dome.footprint_points[::40]
    assert to_envelope_frame(dome, _to_host_frame(dome, pts)) == pytest.approx(pts)
    skin = np.array([[0, 1, 2]])
    model = SimpleNamespace(triangles=np.array([[0, 1, 2], [2, 1, 3]]))
    appendage: Any = SimpleNamespace(model=model, skin_triangles=np.array([1]))
    result: Any = SimpleNamespace(
        positions=_to_host_frame(dome, np.vstack([pts[:3], dome.base_point])), converged=False
    )
    obj = simulated_object(dome, appendage, result)
    assert obj.name == "ear simulated UNCONVERGED"
    assert obj.triangles.tolist() == [[1, 0, 2]]
    assert np.abs(SPHERE.signed_distance(obj.vertices[:2])).max() < 1e-6
    _ = skin
    path = export_scene(tmp_path / "s.obj", SPHERE, [dome], [(dome, appendage, result)])
    names = [ln[2:] for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("o ")]
    assert names == ["envelope", "ear_designed", "ear_simulated_UNCONVERGED"]
