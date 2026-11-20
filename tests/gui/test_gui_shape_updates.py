"""A special shape stays on screen while it is placed again after an edit."""

from __future__ import annotations

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from envelopelab_app import shapes_service
from envelopelab_app.main_window import MainWindow


def test_the_shape_is_drawn_while_it_is_placed_again(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    service = gore_window.controller.shapes
    panel.add_shape("dome")
    assert service.wait(120_000)
    before = panel.placement_data().shapes[0]
    assert len(before.triangles)
    spec = panel.spec()
    assert spec is not None
    panel.set_value(("height",), spec.height * 1.3)  # type: ignore[union-attr]
    # The new placement is being computed: the old shape is drawn meanwhile.
    assert service.result(spec.name) is None
    assert service.updating(spec.name)
    during = panel.placement_data().shapes[0]
    assert len(during.triangles) and during.points is before.points
    assert "updating" in panel.status.text()
    assert service.wait(120_000)
    after = panel.placement_data().shapes[0]
    assert not service.updating(spec.name)
    assert after.points is not before.points
    # Taller: its points reach further from its base point.
    reach_before = np.linalg.norm(before.points - before.base3d, axis=1).max()
    reach_after = np.linalg.norm(after.points - after.base3d, axis=1).max()
    assert reach_after > reach_before * 1.1


def test_the_envelope_surface_is_built_once_for_edits_of_a_shape(
    gore_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    build = shapes_service.envelope_surface  # type: ignore[attr-defined]

    def counted(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return build(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(shapes_service, "envelope_surface", counted)
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    service = gore_window.controller.shapes
    panel.add_shape("dome")
    assert service.wait(120_000)
    built = len(calls)
    spec = panel.spec()
    assert spec is not None
    for factor in (1.1, 1.2):
        panel.set_value(("height",), spec.height * factor)  # type: ignore[union-attr]
        assert service.wait(120_000)
    assert len(calls) == built  # the shape edits reused the envelope surface
    result = service.result(spec.name)
    assert result is not None and result.design is not None


def test_an_edit_is_previewed_at_once_and_placed_when_the_edits_pause(
    gore_window: MainWindow, qtbot: QtBot
) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    service = gore_window.controller.shapes
    panel.add_shape("dome")
    assert service.wait(120_000)
    service.settle_ms = 60_000  # a pause long enough that only the preview runs
    spec = panel.spec()
    assert spec is not None
    before = panel.placement_data().shapes[0]
    panel.set_value(("height",), spec.height * 1.3)  # type: ignore[union-attr]
    assert service.busy and service.result(spec.name) is None

    def previewed() -> None:
        shown = service.shown(spec.name)
        assert shown is not None and shown.design is not None and shown.design.preview

    qtbot.waitUntil(previewed, timeout=10_000)
    # Drawn from the preview, taller; the checks and pieces still wait for the placement.
    during = panel.placement_data().shapes[0]
    reach = np.linalg.norm(during.points - during.base3d, axis=1).max()
    assert reach > np.linalg.norm(before.points - before.base3d, axis=1).max() * 1.1
    assert service.result(spec.name) is None
    assert "updating" in panel.status.text()
    # The pause ends (wait starts the placement at once): the full design replaces it.
    assert service.wait(120_000)
    result = service.result(spec.name)
    assert result is not None and result.design is not None and not result.design.preview
    shown = service.shown(spec.name)
    assert shown is result
