"""The inflated balloon is drawn like the designed one (panel colours, seams) and the 3D
view's Show choice switches between them."""

from __future__ import annotations

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from envelopelab.assembly.spec import parse_instance_id
from envelopelab_app.main_window import MainWindow

RESULT = "envelopelab-preview"


def test_show_inflated_needs_a_run(gore_window: MainWindow) -> None:
    view = gore_window.view3d
    view.refresh()
    assert not view.set_show("inflated")
    assert view.show_choice.currentData() == "designed"
    assert "run a simulation" in view.info.text()
    assert view.set_show("both") and view.layers["design"].visible


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

    # Results open coloured by a safety field (failures shown at once); Layer colour,
    # once chosen, stays chosen when the field list is filled again.
    assert view.field_choice.currentData() is not None
    view.field_choice.setCurrentIndex(view.field_choice.findData(None))
    view.field_choice.activated.emit(view.field_choice.currentIndex())
    assert view.field_choice.currentData() is None
    view.refresh()
    assert view.field_choice.currentData() is None and view.part_field(RESULT) is None

    # Show: designed, inflated, both.
    assert view.set_show("designed")
    assert view.layers["design"].visible and not view.layers[RESULT].visible
    assert view.set_show("inflated")
    assert view.layers[RESULT].visible and not view.layers["design"].visible
    assert not view.layers["rest"].visible  # the starting mesh would cover the comparison
    view.refresh()  # kept when the view is rebuilt
    assert view.layers[RESULT].visible and not view.layers["design"].visible
    assert view.set_show("both")
    assert view.layers["design"].visible and view.layers[RESULT].visible
