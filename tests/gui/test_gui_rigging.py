"""Headless GUI tests of the parachute, red line, flying wires and turning vents."""

from __future__ import annotations

from envelopelab_app.main_window import MainWindow


def _messages(window: MainWindow) -> list[str]:
    window.validation.refresh()
    return window.validation.messages()


def _add_all(window: MainWindow) -> None:
    panel = window.rigging
    for key in ("add_parachute", "add_red_line", "add_flying_wires"):
        panel.buttons[key].click()


def test_migrated_design_reports_missing_rigging(gore_window: MainWindow) -> None:
    messages = _messages(gore_window)
    assert any("no parachute is defined" in m for m in messages)
    assert any("no flying wires are defined" in m for m in messages)
    assert any("no red line is defined" in m for m in messages)
    assert gore_window.rigging.buttons["add_parachute"].isEnabled()


def test_add_rigging_shows_lengths_and_is_undoable(gore_window: MainWindow) -> None:
    session = gore_window.controller.session
    assert session is not None
    _add_all(gore_window)
    design = session.design
    assert design.parachute is not None and design.rigging.flying_wires is not None
    texts = gore_window.rigging.texts()
    assert {"Parachute", "Red line", "Flying wires"} <= set(texts)
    assert texts["Red line"].endswith(" m")
    assert not any("no parachute" in m for m in _messages(gore_window))
    rigging_mass = gore_window.gore_editor.outputs["rigging_mass"].text()
    assert rigging_mass.endswith("kg") and rigging_mass != "0.0 kg"
    assert "rigging" in gore_window.view3d.labels()
    gore_window.undo()
    assert session.design.rigging.flying_wires is None
    assert gore_window.rigging.buttons["add_flying_wires"].isEnabled()


def test_factor_of_safety_failure_is_shown(gore_window: MainWindow) -> None:
    session = gore_window.controller.session
    assert session is not None
    _add_all(gore_window)
    assert any("payload mass is 0" in m for m in _messages(gore_window))
    gore_window.controller.set_value(("operating", "payload_mass"), 50.0)
    gore_window.controller.set_value(
        ("rigging", "flying_wires", "wire", "strength", "value"), 100.0
    )
    assert any(
        "flying wire: factor of safety" in m and "[ERROR]" in m for m in _messages(gore_window)
    )
    items = gore_window.rigging.find_items("factor of safety")
    assert any("FAILS" in item.text(1) for item in items)


def test_turning_vents_in_tree_and_properties(gore_window: MainWindow) -> None:
    _add_all(gore_window)
    gore_window.rigging.buttons["add_vents"].click()
    session = gore_window.controller.session
    assert session is not None and len(session.design.turning_vents) == 2
    texts = gore_window.rigging.texts()
    assert "Net turning torque" in texts and "turning vent 1" in texts
    gore_window.controller.select("turning_vents")
    props = gore_window.properties
    assert ("turning_vents", 0, "opening_width") in props.editors
    props.set_field(("turning_vents", 0, "opening_width"), "0.05")
    assert session.design.turning_vents[0].opening_width == 0.05
    root = gore_window.design_tree.tree.topLevelItem(0)
    assert root is not None
    titles = [child.text(0) for i in range(root.childCount()) if (child := root.child(i))]
    assert "Parachute" in titles and "Turning vents" in titles
    gore_window.rigging.buttons["remove_vents"].click()
    assert session.design.turning_vents == []


def test_parachute_fields_have_units(gore_window: MainWindow) -> None:
    _add_all(gore_window)
    gore_window.controller.select("parachute")
    props = gore_window.properties
    assert ("parachute", "shroud_attachment") in props.editors
    props.set_field(("parachute", "billow"), "0.2")
    session = gore_window.controller.session
    assert session is not None and session.design.parachute is not None
    assert session.design.parachute.billow == 0.2


def test_parachute_panel_in_the_pattern_view(gore_window: MainWindow) -> None:
    assert gore_window.patterns.parachute_item is None
    _add_all(gore_window)
    gore_window.patterns.regenerate()
    item = gore_window.patterns.parachute_item
    assert item is not None and "PARACHUTE x8" in item.toolTip()


def test_wizard_makes_a_nomex_mouth_row_and_n_nylon_rows(window: MainWindow, qtbot: object) -> None:
    from envelopelab_app.wizard import NO_MOUTH_ROW, NewDesignWizard

    wizard = NewDesignWizard(window.controller.fabrics, window)
    assert wizard.mouth_fabric.currentText() == "nomex"
    assert wizard.fabric.currentText() == "ripstop_nylon"
    wizard.volume.setValue(170.0)
    wizard.target_height.setValue(8.2)
    wizard.target_width.setValue(6.4)
    wizard.gores.setValue(8)
    wizard.rows.setValue(3)
    wizard.mouth_height.setValue(1.0)
    wizard.create_design()
    design = wizard.design
    assert design is not None and design.gores is not None, wizard.error.text()
    assert [r.zone for r in design.gores.panel_rows] == ["mouth", None, None, None]
    assert design.gores.panel_rows[0].finished_height == 1.0
    assert design.zones["mouth"] == "nomex" and design.parachute is not None
    window.new_project(design)
    root = window.design_tree.tree.topLevelItem(0)
    assert root is not None
    labels = [
        root.child(i).child(j).child(k).text(0)  # type: ignore[union-attr]
        for i in range(root.childCount())
        for j in range(root.child(i).childCount())  # type: ignore[union-attr]
        for k in range(root.child(i).child(j).childCount())  # type: ignore[union-attr]
    ]
    assert "Row A: mouth (nomex)" in labels and "Top: parachute" in labels
    texts = window.rigging.find_items("crown ring")
    assert texts and texts[0].text(1).endswith("m diameter")
    wizard.mouth_fabric.setCurrentText(NO_MOUTH_ROW)
    wizard.create_design()
    assert wizard.design is not None and len(wizard.design.gores.panel_rows) == 3  # type: ignore[union-attr]


def test_scoop_can_be_added_and_is_drawn(gore_window: MainWindow) -> None:
    session = gore_window.controller.session
    assert session is not None
    gore_window.rigging.buttons["add_scoop"].click()
    assert session.design.scoop is not None
    assert "Scoop" in gore_window.rigging.texts()
    gore_window.patterns.regenerate()
    item = gore_window.patterns.scoop_item
    assert item is not None and "SCOOP x4" in item.toolTip()
    gore_window.controller.select("scoop")
    gore_window.properties.set_field(("scoop", "height"), "0.8")
    assert session.design.scoop.height == 0.8
    gore_window.rigging.buttons["remove_scoop"].click()
    assert session.design.scoop is None
