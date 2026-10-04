"""Headless GUI tests of the Special shapes mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from envelopelab.export.qa import check_pack
from envelopelab.io.blender import MeshObject, write_obj_scene
from envelopelab.validation.primitives import ellipsoid_mesh
from envelopelab_app.main_window import MainWindow
from envelopelab_app.panels.shapes import ShapesPanel


def _placed(window: MainWindow) -> ShapesPanel:
    assert window.controller.shapes.wait(120_000)
    return window.shapes


def _messages(window: MainWindow) -> list[str]:
    window.validation.refresh()
    return window.validation.messages()


def test_special_shapes_mode_exists(gore_window: MainWindow) -> None:
    labels = [gore_window.mode_tabs.tabText(i) for i in range(gore_window.mode_tabs.count())]
    assert any(label.startswith("Special shapes") for label in labels)
    gore_window.show_panel("shapes")
    assert gore_window.panel_visible("shapes")


def test_add_dome_is_placed_in_the_background(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    assert panel.add_shape("dome") == "Dome"
    session = gore_window.controller.session
    assert session is not None and [s.name for s in session.state.shapes] == ["Dome"]
    panel = _placed(gore_window)
    assert "placed" in panel.status.text()
    assert panel.pieces.topLevelItemCount() == 16
    assert panel.attachment.topLevelItemCount() >= 1
    assert panel.checks.topLevelItemCount() >= 1
    assert len(panel.preview.pieces) == 16
    assert not any("shape Dome" in m and "[ERROR]" in m for m in _messages(gore_window))
    assert gore_window.controller.artifact_status("shapes") == "current"
    assert "shape:Dome" in gore_window.view3d.labels()


def test_edit_and_undo_shape_parameters(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("tube")
    _placed(gore_window)
    pieces = panel.pieces.topLevelItemCount()
    panel.fields[("panels",)].setValue(6)
    _placed(gore_window)
    assert panel.pieces.topLevelItemCount() == pieces + 2  # 4 -> 6 panels, tip disc kept
    gore_window.undo()
    _placed(gore_window)
    assert panel.pieces.topLevelItemCount() == pieces
    assert panel.fields[("panels",)].value() == 4


def test_shape_that_does_not_fit_is_an_error(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    assert panel.set_value(("base_radius",), 6.0)
    _placed(gore_window)
    assert "CANNOT BE PLACED" in panel.status.text()
    assert any("[ERROR] shape Dome cannot be placed" in m for m in _messages(gore_window))
    assert not panel.simulate_button.isEnabled()
    assert panel.export_pack(Path("unused")) is None  # never leaves a shape out silently


def test_export_build_pack_passes_qa(gore_window: MainWindow, tmp_path: Path) -> None:
    gore_window.show_panel("shapes")
    gore_window.shapes.add_shape("dome")
    panel = _placed(gore_window)
    index = panel.export_pack(tmp_path / "pack")
    assert index is not None
    data = json.loads(index.read_text(encoding="utf-8"))
    assert any(s["piece"].startswith("Dome-G1") for s in data["sheets"])
    assert check_pack(tmp_path / "pack") == []


def test_import_mesh_and_export_to_blender(gore_window: MainWindow, tmp_path: Path) -> None:
    gore_window.show_panel("shapes")
    mesh = ellipsoid_mesh(0.25, 0.2, 0.3, -0.05, rings=10, segments=16)
    path = write_obj_scene(
        tmp_path / "blob.obj", [MeshObject("blob", mesh.vertices, mesh.triangles)]
    )
    panel = gore_window.shapes
    assert panel.import_mesh(path) == "blob"
    _placed(gore_window)
    placed = panel.placed("blob")
    assert placed is not None, panel.status.text()
    # Flattening a near-sphere into 12 panels distorts it; that is shown, never hidden.
    warnings = [c for c in placed.checks if c.severity == "warning"]
    if warnings:
        assert "need attention" in panel.status.text()
        assert any("[WARNING] shape blob" in m for m in _messages(gore_window))
    out = panel.export_blender(tmp_path / "scene.obj")
    assert out is not None
    names = [
        line.split(maxsplit=1)[1] for line in out.read_text().splitlines() if line.startswith("o ")
    ]
    assert any(n.startswith("blob") for n in names) and len(names) >= 2


def test_bad_mesh_file_is_reported(gore_window: MainWindow, tmp_path: Path) -> None:
    rejected: list[str] = []
    gore_window.controller.editRejected.connect(rejected.append)
    bad = tmp_path / "bad.obj"
    bad.write_text("not a mesh\n", encoding="utf-8")
    assert gore_window.shapes.import_mesh(bad) is None
    assert rejected


@pytest.mark.slow
def test_simulate_shape_shows_result_and_goes_stale(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    panel.set_value(("feed_hole_radius",), 0.07)
    _placed(gore_window)
    panel.mesh_spin.setValue(80.0)
    assert panel.simulate_selected()
    assert gore_window.controller.shape_simulator.wait(600_000)
    text = panel.sim_status.text()
    assert text.startswith("Preview solver"), text
    assert panel.sim_tree.topLevelItemCount() > 5
    assert gore_window.controller.shapes.simulation_status("Dome") == "current"
    assert "shape-sim:Dome" in gore_window.view3d.labels()
    panel.set_value(("height",), 0.25)
    _placed(gore_window)
    assert gore_window.controller.shapes.simulation_status("Dome") == "stale"
    assert "STALE" in panel.sim_status.text()
    assert any("simulation is STALE" in m for m in _messages(gore_window))


def test_removing_every_shape_leaves_nothing_stale(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    assert gore_window.controller.artifact_status("shapes") == "current"
    panel.remove_selected()
    _placed(gore_window)
    assert gore_window.controller.artifact_status("shapes") == "not built"
    assert not any("special shapes is stale" in m for m in _messages(gore_window))


def test_refused_rename_restores_the_name(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    panel.add_shape("dome")
    assert panel.selected == "Dome 2"
    panel.name_edit.setText("Dome")
    panel.name_edit.editingFinished.emit()
    assert panel.selected == "Dome 2"
    assert panel.name_edit.text() == "Dome 2"
    panel.name_edit.setText("Ear")
    panel.name_edit.editingFinished.emit()
    assert panel.selected == "Ear"
    assert [s.name for s in panel.specs()] == ["Dome", "Ear"]
