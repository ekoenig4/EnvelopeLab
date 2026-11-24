"""The inflated balloon is drawn like the designed one (panel colours, seams) and the 3D
view's Show choice switches between them."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from envelopelab.assembly.spec import parse_instance_id
from envelopelab_app.main_window import MainWindow

RESULT = "envelopelab-preview"


def test_an_inflated_shape_needs_a_run(gore_window: MainWindow) -> None:
    view = gore_window.view3d
    view.refresh()
    assert view.state() == "design" and view.layers["design"].visible
    assert not view.set_state("envelopelab-preview")
    assert not view.set_state("calculix")
    assert view.state() == "design"
    assert "run that solver first" in view.info.text()
    # The Objects list: the envelope, ticked.
    item = view.object_item("envelope")
    assert item is not None and item.text(0) == "Envelope"
    assert item.checkState(0) == Qt.CheckState.Checked
    view.set_object_visible("envelope", False)
    assert not view.layers["design"].visible
    view.set_object_visible("envelope", True)
    assert view.layers["design"].visible


@pytest.mark.slow
def test_the_inflated_envelope_is_drawn_like_the_design(
    qtbot: QtBot, gore_window: MainWindow
) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    failures: list[str] = []
    w.simulation.failed.connect(failures.append)
    w.runs.run_preview.click()
    qtbot.waitUntil(lambda: len(session.project.runs) == 1 or bool(failures), timeout=600_000)
    assert not failures, failures
    qtbot.waitUntil(lambda: not w.simulation.running, timeout=60_000)
    view = w.view3d
    view.refresh()
    result = view.layers[RESULT]
    assert not result.stale

    # Panel colours per triangle, from the panel each triangle was cut from.
    assert result.face_colors is not None and len(result.face_colors) == len(result.faces)
    cache = w.controller.model_cache
    assert cache is not None and cache.built.build.mesh is not None
    mesh = cache.built.build.mesh
    panels = [parse_instance_id(i) for i in mesh.instance_ids]
    tri = {(p[1], p[2]): k for k, p in enumerate(panels) if p is not None}
    row = session.design.gores.panel_rows[1].letter  # type: ignore[union-attr]
    first = int(np.flatnonzero(mesh.tri_instance == tri[(row, 1)])[0])
    second = int(np.flatnonzero(mesh.tri_instance == tri[(row, 2)])[0])
    # Every second gore is darker, as on the design surface.
    assert result.face_colors[second].sum() < result.face_colors[first].sum()
    design = view.layers["design"]
    assert design.face_colors is not None
    assert {tuple(c) for c in result.face_colors[[first, second]]} <= {
        tuple(c) for c in design.face_colors
    }
    # The seams are drawn on the inflated shape too.
    assert result.polylines["vertical_seams"] and result.polylines["horizontal_seams"]
    segment = result.polylines["vertical_seams"][0]
    assert segment.shape == (2, 3)

    # Results open in Layer colour (panel colours); a field, once chosen, stays chosen
    # when the field list is filled again.
    assert view.field_choice.currentData() is None and view.part_field(RESULT) is None
    view.field_choice.setCurrentIndex(view.field_choice.findData("fos_warp"))
    view.field_choice.activated.emit(view.field_choice.currentIndex())
    view.refresh()
    assert view.field_choice.currentData() == "fos_warp"
    assert view.part_field(RESULT) is not None
    view.field_choice.setCurrentIndex(view.field_choice.findData(None))
    view.field_choice.activated.emit(view.field_choice.currentIndex())
    view.refresh()
    assert view.field_choice.currentData() is None and view.part_field(RESULT) is None

    # Shape: designed or inflated by the preview run; no CalculiX run yet.
    assert view.set_state("design")
    assert view.layers["design"].visible and not view.layers[RESULT].visible
    assert view.set_state(RESULT)
    assert view.layers[RESULT].visible and not view.layers["design"].visible
    assert not view.layers["rest"].visible  # the starting mesh is off unless ticked
    view.refresh()  # kept when the view is rebuilt
    assert view.state() == RESULT and view.layers[RESULT].visible
    assert not view.set_state("calculix") and view.state() == RESULT
    # Ticking the rest mesh shows it with either Shape; unticking the envelope hides it.
    view.set_object_visible("rest", True)
    assert view.layers["rest"].visible
    view.set_object_visible("envelope", False)
    assert not view.layers[RESULT].visible and not view.layers["design"].visible


@pytest.mark.slow
def test_a_reopened_run_keeps_its_panel_colours_and_rest_mesh(
    qtbot: QtBot, gore_window: MainWindow
) -> None:
    """The solver model is not rebuilt when a project is reopened: the run's own result
    file carries what the view needs (its panels, seams and as-sewn shape)."""
    w = gore_window
    session = w.controller.session
    assert session is not None
    failures: list[str] = []
    w.simulation.failed.connect(failures.append)
    w.runs.run_preview.click()
    qtbot.waitUntil(lambda: len(session.project.runs) == 1 or bool(failures), timeout=600_000)
    assert not failures, failures
    qtbot.waitUntil(lambda: not w.simulation.running, timeout=60_000)
    view = w.view3d
    view.refresh()
    before = view.layers[RESULT].face_colors
    assert before is not None
    fos_before = view.part_fields[RESULT]["fos_warp"].values
    state_before = view.run_state()
    assert state_before is not None
    w.controller.model_cache = None  # as after reopening the project
    view.refresh()
    # The factors of safety (and the zones below the limit) come from the run itself.
    fos = view.part_fields[RESULT].get("fos_warp")
    assert fos is not None and np.array_equal(fos.values, fos_before)
    state = view.run_state()
    assert state is not None and state.failing_zones == state_before.failing_zones
    assert state.min_fos == state_before.min_fos
    # A solved part is drawn in panel colours only with Layer colour chosen: with a
    # field chosen it shows the field, or its plain colour when it cannot give it.
    assert view.shows_panel_colours(RESULT, field_chosen=False)
    assert not view.shows_panel_colours(RESULT, field_chosen=True)
    result = view.layers[RESULT]
    assert result.face_colors is not None and np.array_equal(result.face_colors, before)
    assert result.polylines["vertical_seams"] and result.polylines["horizontal_seams"]
    assert "rest" in view.layers and len(view.layers["rest"].faces) == len(result.faces)
    view.set_object_visible("rest", True)
    assert view.layers["rest"].visible


def test_the_designed_envelope_keeps_its_panel_colours_with_a_field_chosen(
    gore_window: MainWindow,
) -> None:
    view = gore_window.view3d
    view.refresh()
    assert view.layers["design"].face_colors is not None
    assert view.shows_panel_colours("design", field_chosen=True)
    assert view.shows_panel_colours("design", field_chosen=False)


@pytest.mark.slow
def test_a_project_opens_on_its_most_up_to_date_shape(
    qtbot: QtBot, gore_window: MainWindow
) -> None:
    """Opening a project shows CalculiX's inflated shape, else the preview's, else the
    design: the first whose latest run is current and converged, in Layer colour."""
    w = gore_window
    session = w.controller.session
    assert session is not None
    failures: list[str] = []
    w.simulation.failed.connect(failures.append)
    w.runs.run_preview.click()
    qtbot.waitUntil(lambda: len(session.project.runs) == 1 or bool(failures), timeout=600_000)
    assert not failures, failures
    qtbot.waitUntil(lambda: not w.simulation.running, timeout=60_000)
    view = w.view3d
    view.field_choice.setCurrentIndex(view.field_choice.findData("fos_warp"))
    view.field_choice.activated.emit(view.field_choice.currentIndex())
    view.set_state("design")

    view.reopened()  # as when the project is opened again
    view.refresh()
    assert view.state() == RESULT and view.layers[RESULT].visible
    assert view.field_choice.currentData() is None  # Layer colour

    preview = view.layers[RESULT]
    view.layers["calculix"] = replace(preview, key="calculix", kind="calculix")
    assert view.opening_state() == "calculix"
    view.layers["calculix"] = replace(preview, key="calculix", kind="calculix", converged=False)
    assert view.opening_state() == RESULT  # an unconverged run is never the default
    view.layers["calculix"] = replace(preview, key="calculix", kind="calculix", stale=True)
    assert view.opening_state() == RESULT
    view.layers[RESULT] = replace(preview, stale=True)
    assert view.opening_state() == "design"
