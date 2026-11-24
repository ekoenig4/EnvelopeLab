"""Where a special shape's panels meet at the crown, set in the Special shapes mode's Panel
layout section (ADR-0049)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from envelopelab_app.main_window import MainWindow


def _fractions(window: MainWindow) -> None:
    """Show where the panels meet as fractions of the widest radius (balloon
    coordinates); in metres the boxes show offsets in m."""
    window.apply_preferences(replace(window.prefs, position_units="balloon"))


def test_the_crown_box_sets_the_seam_angles_and_moves_the_cap(gore_window: MainWindow) -> None:
    _fractions(gore_window)
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    assert gore_window.controller.shapes.wait(120_000)
    spec = panel.spec()
    assert spec is not None
    # As at the rim until an own crown layout is chosen.
    assert not panel.crown_own.isChecked() and not panel.crown_turn.isEnabled()
    assert panel.meeting_pad.isEnabled()  # a dome with its automatic cap
    panel.crown_own.setChecked(True)
    spec = panel.spec()
    assert spec is not None and spec.crown_seam_offset_deg == spec.seam_offset_deg
    panel.crown_turn.setValue(20.0)
    spec = panel.spec()
    assert spec is not None and spec.crown_seam_offset_deg == 20.0
    buttons = {b.objectName(): b for b in panel.findChildren(QPushButton)}
    buttons["shapeCrownEqual"].click()
    spec = panel.spec()
    assert spec is not None and spec.crown_panel_widths == [1.0] * spec.gores  # type: ignore[union-attr]
    panel.cap_across.setValue(0.1)  # where the panels meet, towards the next gore
    spec = panel.spec()
    assert spec is not None and (spec.cap_across, spec.cap_up, spec.cap_shift) == (0.1, 0.0, 0.0)
    assert gore_window.controller.shapes.wait(120_000)
    result = gore_window.controller.shapes.result(spec.name)
    assert result is not None and result.design is not None, result
    assert not [c for c in result.design.checks if c.severity == "error"]
    # Back to the rim's layout in one step.
    panel.crown_own.setChecked(False)
    spec = panel.spec()
    assert spec is not None and spec.crown_seam_offset_deg is None
    assert spec.crown_panel_widths == []


def test_the_meeting_pad_moves_where_the_panels_meet(gore_window: MainWindow) -> None:
    _fractions(gore_window)
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    assert gore_window.controller.shapes.wait(120_000)
    pad = panel.meeting_pad
    pad.resize(200, 200)
    assert pad.isEnabled() and len(pad.seams) == panel.spec().gores  # type: ignore[union-attr]
    # Click right of the centre, a fifth of the way to the outline: across 0.2, up 0.
    centre, radius = pad._frame()
    click = QPoint(int(centre.x() + 0.2 * radius), int(centre.y()))
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click)
    gore_window.controller.flush_live()
    spec = panel.spec()
    assert spec is not None
    assert spec.cap_across == pytest.approx(0.2, abs=0.01) and spec.cap_up == 0.0
    assert panel.cap_across.value() == pytest.approx(spec.cap_across)
    assert gore_window.controller.shapes.wait(120_000)
    result = gore_window.controller.shapes.result(spec.name)
    assert result is not None and result.design is not None, result
    assert "mm down the skin" in panel.meeting_info.text()
    # Typed values, then back to the tip in one click.
    panel.cap_up.setValue(0.1)
    gore_window.controller.flush_live()
    spec = panel.spec()
    assert spec is not None and spec.cap_up == 0.1
    assert spec.cap_across == pytest.approx(0.2, abs=0.01)
    panel.meeting_centre.click()
    spec = panel.spec()
    assert spec is not None and (spec.cap_across, spec.cap_up, spec.cap_shift) == (0.0, 0.0, 0.0)
    # One drag is one undo step.
    session = gore_window.controller.session
    assert session is not None
    depth = session.stack.index
    for x in (0.1, 0.15, 0.2):
        pad.moved.emit(x, 0.0)
    gore_window.controller.flush_live()
    assert session.stack.index == depth + 1
