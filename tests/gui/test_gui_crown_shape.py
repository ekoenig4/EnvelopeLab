"""Shaping a special shape's crown cap in the Panel layout (ADR-0054)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from envelopelab_app.main_window import MainWindow


def _placed(window: MainWindow) -> None:
    assert window.controller.shapes.wait(120_000)


def test_every_cap_shape_can_be_chosen_and_is_drawn(
    gore_window: MainWindow, tmp_path: Path
) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    assert panel.cap_kind.isEnabled() and panel.cap_kind.currentData() is None
    circle = panel.meeting_pad.cap
    assert circle is not None and np.ptp(np.hypot(circle[:, 0], circle[:, 1])) < 1e-9
    for index in range(panel.cap_kind.count()):
        if panel.cap_kind.itemData(index) in ("footprint", "ellipse", "polygon"):
            panel.cap_kind.setCurrentIndex(index)
            panel.cap_kind.activated.emit(index)
            _placed(gore_window)
            spec = panel.spec()
            assert spec is not None and spec.crown_shape is not None
            assert spec.crown_shape.kind == panel.cap_kind.itemData(index)
            result = gore_window.controller.shapes.result(spec.name)
            assert result is not None and result.design is not None, result
            assert not [
                c.name for c in result.design.checks if c.severity == "error" and not c.passed
            ]
            assert panel.meeting_pad.cap is not None
    # The polygon: its corners in the table, a corner added and moved.
    spec = panel.spec()
    assert spec is not None and spec.crown_shape is not None and spec.crown_shape.kind == "polygon"
    assert panel.cap_points.rowCount() == 4 and not panel.cap_points_row.isHidden()
    assert panel.add_cap_point()
    spec = panel.spec()
    assert spec is not None and len(spec.crown_shape.points) == 5  # type: ignore[union-attr]
    panel.cap_points.item(0, 0).setText("60")  # type: ignore[union-attr]
    spec = panel.spec()
    assert spec is not None and spec.crown_shape.points[0][0] == 0.06  # type: ignore[union-attr]
    # An ellipse sized and turned.
    panel.set_crown_shape({"kind": "ellipse", "width": 0.2, "length": 0.12})
    panel.cap_turn.setValue(30.0)
    gore_window.controller.flush_live()
    spec = panel.spec()
    assert spec is not None and spec.crown_shape.turn_deg == 30.0  # type: ignore[union-attr]
    # An imported outline.
    svg = tmp_path / "leaf.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M 0 10 Q 20 -10 40 10 Q 20 30 0 10 Z"/>'
        "</svg>"
    )
    assert panel.import_cap_outline(svg)
    _placed(gore_window)
    spec = panel.spec()
    assert spec is not None and spec.crown_shape is not None
    assert spec.crown_shape.kind == "outline" and spec.crown_shape.source == "leaf.svg"
    assert panel.cap_source.text() == "leaf.svg"
    result = gore_window.controller.shapes.result(spec.name)
    assert result is not None and result.design is not None, result
    # Back to a circle.
    panel.cap_kind.setCurrentIndex(0)
    panel.cap_kind.activated.emit(0)
    spec = panel.spec()
    assert spec is not None and spec.crown_shape is None
