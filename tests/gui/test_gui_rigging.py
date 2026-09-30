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
