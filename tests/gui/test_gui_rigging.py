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


def test_patterns_are_stacked_vertically_in_their_own_column(gore_window: MainWindow) -> None:
    _add_all(gore_window)
    gore_window.rigging.buttons["add_scoop"].click()
    gore_window.patterns.regenerate()
    offsets = gore_window.patterns.view.offsets
    letters = list(offsets)
    assert letters == ["A", "B", "C", "D"]
    # Scene y grows downward: each row above the previous one, all centred on x = 0.
    ys = [offsets[k].y() for k in letters]
    assert ys == sorted(ys, reverse=True) and all(offsets[k].x() == 0.0 for k in letters)
    top = gore_window.patterns.parachute_item
    bottom = gore_window.patterns.scoop_item
    assert top is not None and bottom is not None
    # Polygon extents (the item bounding rects include the cosmetic pen width).
    top_rect = top.mapToScene(top.polygon()).boundingRect()
    bottom_rect = bottom.mapToScene(bottom.polygon()).boundingRect()
    assert top_rect.bottom() < offsets["D"].y()  # parachute above row D
    assert bottom_rect.top() > offsets["A"].y()  # scoop below row A
    # The pattern view has its own mode, apart from the 3D view.
    assert gore_window.panel_modes["patterns"] == "patterns"
    assert gore_window.panel_modes["view3d"] != "patterns"


def test_3d_design_layer_shows_gores_rows_and_seams(gore_window: MainWindow) -> None:
    layer = gore_window.view3d.layers["design"]
    assert "8 gores x 4 panel rows" in layer.label
    assert layer.face_colors is not None and len(layer.face_colors) == len(layer.faces)
    assert len(layer.polylines["vertical_seams"]) == 8
    assert len(layer.polylines["horizontal_seams"]) == 5  # mouth, 3 row seams, top
    # Neighbouring gores are shaded differently.
    assert len({tuple(c) for c in layer.face_colors}) >= 2


def test_wizard_defaults_can_be_saved_and_reset(window: MainWindow) -> None:
    from envelopelab_app.settings import WizardDefaults, load_wizard_defaults
    from envelopelab_app.wizard import NewDesignWizard

    wizard = NewDesignWizard(window.controller.fabrics, window, window.settings)
    assert wizard.gores.value() == WizardDefaults().gores
    wizard.gores.setValue(16)
    wizard.volume.setValue(3000.0)
    wizard.mouth_height.setValue(1.5)
    wizard.store_defaults()
    assert load_wizard_defaults(window.settings).gores == 16
    again = NewDesignWizard(window.controller.fabrics, window, window.settings)
    assert again.gores.value() == 16 and again.volume.value() == 3000.0
    assert again.mouth_height.value() == 1.5
    again.restore_builtin_defaults()
    assert again.gores.value() == WizardDefaults().gores
    assert load_wizard_defaults(window.settings) == WizardDefaults()


def test_new_from_template_opens_an_unsaved_copy(window: MainWindow, tmp_path: object) -> None:
    from pathlib import Path

    from .gui_support import GORE_PROJECT

    session = window.new_from_template(GORE_PROJECT, "copy of the fixture")
    assert session is not None and session.path is None
    assert session.design.meta.name == "copy of the fixture"
    assert window.controller.session is session
    assert window.template_action.text() == "New from &template…"
    assert window.new_from_template(Path(str(tmp_path)) / "missing.elproj", "x") is None
