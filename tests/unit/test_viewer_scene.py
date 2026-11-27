"""The build pack's 3D view data: objects and Shape states, as in the application."""

from __future__ import annotations

import numpy as np

from envelopelab.export.viewer import (
    Scene,
    SceneMesh,
    SceneStatus,
    design_scene,
    scene_data,
)
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    Tube,
    design_primitive,
)
from envelopelab.project.gore_design import standard_gore_design

DESIGN = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
SURFACE = EnvelopeSurface.from_design(DESIGN)
SHAPES = [
    design_primitive(Dome("ear", Placement(3, 12.0, across=0.5), 1.0, 1.2, gores=8), SURFACE),
    design_primitive(Tube("horn", Placement(7, 10.0), 0.8, 0.3, 2.0), SURFACE),
]


def _result(scene: Scene, obj: str, state: str) -> SceneMesh:
    tri = np.array([[0, 1, 2]])
    pts = np.eye(3)
    return SceneMesh(f"{obj}@{state}", obj, "Result", pts, tri, role="result", obj=obj, state=state)


def test_design_scene_draws_every_special_shape_as_an_object() -> None:
    scene = design_scene(DESIGN, shapes=SHAPES)
    data = scene_data(scene)
    assert data["objects"] == [
        {"key": "envelope", "label": "Envelope", "group": ""},
        {"key": "shape:ear", "label": "ear", "group": "Special shapes"},
        {"key": "shape:horn", "label": "horn", "group": "Special shapes"},
    ]
    ear = [m for m in data["meshes"] if m["object"] == "shape:ear"]
    assert len(ear) == 1 and ear[0]["state"] == "design" and ear[0]["triangles"] > 0
    assert any(ln["object"] == "shape:ear" for ln in data["lines"])  # its seams and rim
    # Only the design to show: the page offers Designed alone and opens on it.
    assert data["states"] == [["design", "Designed"]] and data["state"] == "design"


def test_states_follow_the_application_order_and_opening() -> None:
    scene = design_scene(DESIGN, shapes=SHAPES)
    scene.meshes.append(_result(scene, "envelope", "envelopelab-preview"))
    data = scene_data(scene)
    assert [k for k, _t in data["states"]] == ["design", "envelopelab-preview"]
    assert data["state"] == "envelopelab-preview"  # the best result there is
    scene.meshes.append(_result(scene, "envelope", "calculix"))
    scene.meshes.append(_result(scene, "shape:ear", "calculix"))
    scene.statuses["calculix"] = SceneStatus("ok", "CalculiX run converged.")
    data = scene_data(scene)
    assert [t for _k, t in data["states"]] == [
        "Designed",
        "Inflated (preview)",
        "Inflated (CalculiX)",
    ]
    assert data["state"] == "calculix"  # CalculiX > preview > design
    assert data["statuses"]["calculix"]["title"] == "CalculiX run converged."
    scene.state = "design"  # the caller's choice (the state the app's view shows) wins
    assert scene_data(scene)["state"] == "design"


def test_rigging_is_drawn_in_every_state() -> None:
    from envelopelab.project.gore_design import gore_outputs
    from envelopelab.project.model import PatternSet

    rigging = gore_outputs(DESIGN, PatternSet()).rigging
    data = scene_data(design_scene(DESIGN, rigging))
    rig = [x for x in [*data["meshes"], *data["lines"]] if x["object"] == "rigging"]
    assert rig and all(x["state"] is None for x in rig)
    assert {"key": "rigging", "label": "Rigging", "group": ""} in data["objects"]


def test_a_field_on_the_design_is_listed_as_its_field() -> None:
    from envelopelab.export.viewer import Coloring, Legend

    scene = design_scene(DESIGN)
    design = scene.meshes[0]
    rgb = np.zeros((len(design.triangles), 3), dtype=np.uint8)
    design.colorings["deviation@calculix"] = Coloring(
        "deviation", "Deviation", rgb, "face", Legend("Deviation")
    )
    assert scene.coloring_titles() == {"deviation": "Deviation"}
