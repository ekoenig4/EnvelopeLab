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


def test_a_scaled_scene_keeps_every_object_and_state_without_analysis_colours() -> None:
    from envelopelab.export.viewer import Coloring, Legend, SceneLines, scale_scene

    scene = design_scene(DESIGN, shapes=SHAPES)
    preview = _result(scene, "envelope", "envelopelab-preview")
    preview.face_rgb = np.array([[10, 20, 30]], dtype=np.uint8)
    preview.colorings["fos_warp"] = Coloring(
        "fos_warp", "FoS", np.zeros((1, 3), dtype=np.uint8), "face", Legend("FoS")
    )
    sim = _result(scene, "shape:ear", "calculix")
    sim.note = "NOT CONVERGED: values are not final"
    scene.meshes += [preview, sim]
    scene.lines.append(
        SceneLines("ov", "overlay", "Design", [np.ones((2, 3))], obj="overlay:o", state="design")
    )
    scene.statuses["envelopelab-preview"] = SceneStatus("ok", "Current and converged.")
    scene.statuses["calculix"] = SceneStatus("fail", "Not converged.", "residual 1e-2")
    scene.state = "envelopelab-preview"
    before = scene_data(scene)
    model = scale_scene(scene, 0.05, "1:20")
    data = scene_data(model)
    # The same objects, parts and Shape choices as the full-size view (the 3D tab's).
    assert data["objects"] == before["objects"]
    assert [(m["key"], m["object"], m["state"]) for m in data["meshes"]] == [
        (m["key"], m["object"], m["state"]) for m in before["meshes"]
    ]
    assert [(ln["key"], ln["state"]) for ln in data["lines"]] == [
        (ln["key"], ln["state"]) for ln in before["lines"]
    ]
    assert data["states"] == before["states"] and data["state"] == "envelopelab-preview"
    # Lengths scale; nothing else is touched.
    for full, small in zip(scene.meshes, model.meshes, strict=True):
        np.testing.assert_allclose(small.points, np.asarray(full.points) * 0.05)
    np.testing.assert_allclose(model.labels[0][1], np.asarray(scene.labels[0][1]) * 0.05)
    np.testing.assert_allclose(model.lines[-1].polylines[0], 0.05)
    assert preview.colorings and np.asarray(scene.meshes[0].points).max() > 1.0
    # Loads and FoS do not scale: no analysis colouring; the fabric colours stay.
    assert data["colorings"] == {} and all(m["colorings"] == {} for m in data["meshes"])
    assert next(m for m in data["meshes"] if m["state"] == "envelopelab-preview")["base"]
    # Each state's banner says it is the full-size run scaled, and never hides a failure.
    assert data["statuses"]["design"]["title"] == "Scale model 1:20."
    ok = data["statuses"]["envelopelab-preview"]
    assert ok["kind"] == "info" and ok["title"] == "Scale model 1:20: Inflated (preview)."
    assert "n/a for a scale model" in ok["message"]
    bad = data["statuses"]["calculix"]
    assert bad["kind"] == "fail" and "Not converged. residual 1e-2" in bad["message"]
    assert next(m for m in data["meshes"] if m["state"] == "calculix")["note"].startswith(
        "NOT CONVERGED"
    )


def test_a_scene_cannot_be_scaled_up() -> None:
    import pytest

    from envelopelab.export.viewer import scale_scene

    with pytest.raises(ValueError, match="scale factor"):
        scale_scene(design_scene(DESIGN), 2.0, "2:1")
