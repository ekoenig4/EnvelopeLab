"""Properties panel: typed editors, clearing, adding and removing sections and entries."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from envelopelab.project.session import ProjectSession
from envelopelab_app.main_window import MainWindow


def _session(window: MainWindow) -> ProjectSession:
    session = window.controller.session
    assert session is not None
    return session


def test_optional_sections_can_be_added_and_removed(gore_window: MainWindow) -> None:
    w, props = gore_window, gore_window.properties
    session = _session(w)
    session.set_design_value(("parachute",), None)
    w.controller.select("parachute")
    assert ("add", ("parachute",)) in props.buttons
    props.buttons[("add", ("parachute",))].click()
    assert session.design.parachute is not None
    # A section inside it: remove the centre ring, then add it back.
    assert session.design.parachute.centre_ring is not None
    props.remove_entry(("parachute", "centre_ring"))
    assert session.design.parachute.centre_ring is None
    assert ("add", ("parachute", "centre_ring")) in props.buttons
    props.buttons[("add", ("parachute", "centre_ring"))].click()
    assert session.design.parachute.centre_ring is not None
    # Optional numbers clear and can be typed again from empty; a centre ring needs its
    # diameter, so the clear is refused until the ring is removed.
    props.buttons[("clear", ("parachute", "centre_ring_diameter"))].click()
    assert session.design.parachute.centre_ring_diameter is not None
    props.remove_entry(("parachute", "centre_ring"))
    props.buttons[("clear", ("parachute", "centre_ring_diameter"))].click()
    assert session.design.parachute.centre_ring_diameter is None
    props.set_field(("parachute", "centre_ring_diameter"), "0.08")
    assert session.design.parachute.centre_ring_diameter == 0.08
    props.buttons[("remove", ("parachute",))].click()
    assert session.design.parachute is None


def test_typed_editors_for_choices_and_yes_no(gore_window: MainWindow) -> None:
    w, props = gore_window, gore_window.properties
    session = _session(w)
    w.rigging.buttons["add_vents"].click()
    w.controller.select("turning_vents")
    assert isinstance(props.editors[("turning_vents", 0, "simulate_open")], QCheckBox)
    assert isinstance(props.editors[("turning_vents", 0, "direction")], QComboBox)
    props.set_field(("turning_vents", 0, "simulate_open"), "true")
    props.set_field(("turning_vents", 0, "direction"), "clockwise")
    vent = session.design.turning_vents[0]
    assert vent.simulate_open and vent.direction == "clockwise"
    props.set_field(("turning_vents", 0, "rows"), "C, D")
    assert session.design.turning_vents[0].rows == ["C", "D"]


def test_single_list_entries_are_added_and_removed(gore_window: MainWindow) -> None:
    w, props = gore_window, gore_window.properties
    session = _session(w)
    w.rigging.buttons["add_vents"].click()
    w.controller.select("turning_vents")
    props.buttons[("add", ("turning_vents", 2))].click()
    names = [v.name for v in session.design.turning_vents]
    assert len(names) == 3 and len(set(names)) == 3
    props.buttons[("remove", ("turning_vents", 0))].click()
    assert [v.name for v in session.design.turning_vents] == names[1:]
    # Seam types, features, scale variants and panel zones: add one, remove it again.
    for section, path in (
        ("seam_types", ("seam_types",)),
        ("features", ("features",)),
        ("scale_variants", ("scale_variants",)),
        ("gores", ("gores", "panel_zones")),
    ):
        w.controller.select(section)
        before = session.design_value(path)
        props.add_entry((*path, len(before)))
        after = session.design_value(path)
        assert len(after) == len(before) + 1, section
        props.remove_entry((*path, len(before)))
        assert session.design_value(path) == before


def test_lists_of_numbers_and_name_maps_are_parsed(gore_window: MainWindow) -> None:
    w, props = gore_window, gore_window.properties
    session = _session(w)
    w.controller.select("gores")
    props.add_entry(("gores", "panel_zones", 0))
    w.controller.select("gores")
    props.set_field(("gores", "panel_zones", 0, "gores"), "2, 3")
    assert session.design.gores is not None
    assert session.design.gores.panel_zones[0].gores == [2, 3]
    w.controller.select("scale_variants")
    props.add_entry(("scale_variants", 0))
    props.set_field(("scale_variants", 0, "fixed_size_overrides"), "mouth_diameter=0.3")
    assert session.design.scale_variants[0].fixed_size_overrides == {"mouth_diameter": 0.3}
    props.set_field(("scale_variants", 0, "fixed_size_overrides"), "mouth_diameter")
    assert session.design.scale_variants[0].fixed_size_overrides == {"mouth_diameter": 0.3}


def test_owned_fields_are_read_only_and_flying_wire_count_is_not(
    gore_window: MainWindow,
) -> None:
    w, props = gore_window, gore_window.properties
    session = _session(w)
    w.controller.select("gores")
    assert not any(p[:2] == ("gores", "meridian_profile_control_points") for p in props.editors)
    assert not any(p[:2] == ("gores", "panel_rows") for p in props.editors)
    count = props.editors[("gores", "count")]
    assert isinstance(count, QLineEdit) and count.isReadOnly() and not count.isEnabled()
    assert ("remove", ("gores",)) not in props.buttons
    w.rigging.buttons["add_flying_wires"].click()
    w.controller.select("rigging")
    wires = props.editors[("rigging", "flying_wires", "count")]
    assert isinstance(wires, QLineEdit) and not wires.isReadOnly()
    props.set_field(("rigging", "flying_wires", "count"), "4")
    assert session.design.rigging.flying_wires is not None
    assert session.design.rigging.flying_wires.count == 4


def test_a_refused_value_changes_nothing(gore_window: MainWindow) -> None:
    w, props = gore_window, gore_window.properties
    session = _session(w)
    w.controller.select("operating")
    before = session.design
    props.set_field(("operating", "ambient_pressure"), "-5")
    assert session.design == before
