"""Where a special shape's panels meet at the crown, set in the Special shapes mode's Panel
layout section (ADR-0049)."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from envelopelab_app.main_window import MainWindow


def test_the_crown_box_sets_the_seam_angles_and_moves_the_cap(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    assert gore_window.controller.shapes.wait(120_000)
    spec = panel.spec()
    assert spec is not None
    # As at the rim until an own crown layout is chosen.
    assert not panel.crown_own.isChecked() and not panel.crown_turn.isEnabled()
    assert panel.cap_shift.isEnabled()  # a dome with its automatic cap
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
    panel.cap_shift.setValue(40.0)
    panel.cap_direction.setValue(90.0)
    spec = panel.spec()
    assert spec is not None and (spec.cap_shift, spec.cap_direction_deg) == (0.04, 90.0)
    assert gore_window.controller.shapes.wait(120_000)
    result = gore_window.controller.shapes.result(spec.name)
    assert result is not None and result.design is not None, result
    assert not [c for c in result.design.checks if c.severity == "error"]
    # Back to the rim's layout in one step.
    panel.crown_own.setChecked(False)
    spec = panel.spec()
    assert spec is not None and spec.crown_seam_offset_deg is None
    assert spec.crown_panel_widths == []
